"""Domain exceptions and their HTTP mapping.

Every error the service raises deliberately carries the HTTP status and the stable
machine-readable ``code`` that the client sees, so the mapping lives in one place
instead of being scattered across route handlers.
"""

from __future__ import annotations

from typing import Any


class GraphQLTypstError(Exception):
    """Base class for every error this service raises on purpose."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(GraphQLTypstError):
    """A setting needed for this operation is missing or unusable."""

    status_code = 500
    code = "configuration_error"


class BundleConfigError(GraphQLTypstError):
    """The template bundle is invalid.

    Raised only at startup (or from ``graphql-typst check``); never in a request path,
    because a bundle is validated once and then held immutable.
    """

    status_code = 500
    code = "bundle_config_error"

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        body = "\n".join(f"  {i}. {p}" for i, p in enumerate(problems, start=1))
        super().__init__(
            f"invalid template bundle ({len(problems)} problem(s)):\n{body}",
            {"problems": self.problems},
        )


class TemplateNotFoundError(GraphQLTypstError):
    status_code = 404
    code = "template_not_found"

    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__(f"unknown template {name!r}", {"available": available})
        self.name = name


class InvalidArgumentsError(GraphQLTypstError):
    status_code = 422
    code = "invalid_arguments"

    def __init__(
        self,
        message: str,
        *,
        missing: list[str] | None = None,
        unknown: list[str] | None = None,
        accepted: list[str] | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if missing:
            details["missing"] = missing
        if unknown:
            details["unknown"] = unknown
        if accepted is not None:
            details["accepted"] = accepted
        super().__init__(message, details)


class UpstreamError(GraphQLTypstError):
    """Anything that went wrong between this service and the GraphQL endpoint."""

    status_code = 502
    code = "upstream_error"


class UpstreamGraphQLError(UpstreamError):
    """The GraphQL server answered, but with ``errors``."""

    status_code = 502
    code = "upstream_graphql_error"

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        # ``extensions`` is stripped deliberately: servers routinely put stack traces
        # and internal identifiers there. ``message`` and ``path`` describe the
        # caller's own request, so hiding those would make a 502 undebuggable.
        safe = [
            {k: v for k, v in (err or {}).items() if k in ("message", "path")} for err in errors
        ]
        first = safe[0].get("message") if safe else None
        super().__init__(
            (
                f"GraphQL endpoint returned errors: {first}"
                if first
                else "GraphQL endpoint returned errors"
            ),
            {"errors": safe},
        )
        self.errors = safe


class UpstreamTransportError(UpstreamError):
    status_code = 502
    code = "upstream_transport_error"

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message, {"status": status} if status is not None else None)
        self.status = status


class UpstreamTimeoutError(UpstreamError):
    status_code = 504
    code = "upstream_timeout"


class EmptyResultError(GraphQLTypstError):
    """The transform produced nothing usable to feed the template."""

    status_code = 502
    code = "empty_upstream_result"

    def __init__(self, template: str, received_keys: list[str]) -> None:
        super().__init__(
            f"transform for template {template!r} produced no document data",
            {"received_keys": received_keys},
        )


class RenderBusyError(GraphQLTypstError):
    status_code = 503
    code = "render_busy"

    def __init__(self, timeout_s: float) -> None:
        super().__init__(
            f"no render capacity available within {timeout_s:g}s",
            {"timeout_s": timeout_s},
        )


class RenderFailedError(GraphQLTypstError):
    """Typst refused to compile the document.

    The typst diagnostics quote template source, so they are only exposed to the
    client when ``debug_errors`` is on. They are always logged in full.
    """

    status_code = 500
    code = "render_failed"

    def __init__(
        self,
        template: str,
        typst_message: str,
        hints: list[str] | None = None,
        trace: list[str] | None = None,
    ) -> None:
        super().__init__(f"failed to compile template {template!r}")
        self.template = template
        self.typst_message = typst_message
        self.hints = hints or []
        self.trace = trace or []

    def debug_details(self) -> dict[str, Any]:
        return {"message": self.typst_message, "hints": self.hints, "trace": self.trace}


class UnauthorizedError(GraphQLTypstError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "missing or invalid API key") -> None:
        super().__init__(message)
