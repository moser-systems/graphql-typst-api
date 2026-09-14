# syntax=docker/dockerfile:1.9
#
# Base is Debian slim, not Alpine: PyPI publishes no musllinux wheel for `typst`,
# so a musl base would compile the whole Rust Typst compiler from source. Not
# distroless either: the image needs fonts from apt, fontconfig for Typst's system
# font discovery, and a shell for the healthcheck.
ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------- build stage
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, from the lockfile only, so this layer survives source edits.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --no-editable

COPY pyproject.toml uv.lock README.md /app/
COPY src/ /app/src/
# --no-editable matters: uv installs the project editable by default, which would
# leave the copied venv pointing at a /app/src that the runtime stage does not have.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# -------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# fonts-liberation owns LiberationSans-Regular.ttf, the family the example
# templates ask for, and fonts-dejavu-core covers their declared fallback;
# fontconfig is how Typst discovers both.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      fontconfig \
      fonts-dejavu-core \
      fonts-liberation \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

COPY --from=builder /app/.venv /app/.venv
COPY examples/bundle /opt/graphql-typst/examples/bundle

# The container runs with a read-only root filesystem, so point the caches that
# libraries expect to write at a writable tmpfs instead of a non-existent home.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    GRAPHQL_TYPST_BUNDLE_DIR=/opt/graphql-typst/examples/bundle \
    GRAPHQL_TYPST_TYPST_PACKAGE_CACHE_PATH=/opt/graphql-typst/typst-packages \
    GRAPHQL_TYPST_HOST=0.0.0.0 \
    GRAPHQL_TYPST_PORT=8000 \
    GRAPHQL_TYPST_LOG_FORMAT=json

# Bake the @preview packages into the image by compiling every template, which
# also pulls their transitive dependencies. A hardcoded download list would miss
# those. Fails the build if a package cannot be fetched, so the runtime never
# needs network for rendering.
RUN mkdir -p /opt/graphql-typst/typst-packages \
 && graphql-typst warm-cache \
 && chmod -R a+rX /opt/graphql-typst /app/.venv

# Numeric UID so the image works unchanged under a restricted PodSecurity policy.
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

ENTRYPOINT ["graphql-typst"]
CMD ["serve"]
