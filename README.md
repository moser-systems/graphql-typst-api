# graphql-typst

Render [Typst](https://typst.app) PDFs from GraphQL queries, over HTTP.

You describe a document once — a Typst template, the GraphQL query that feeds it, a
JMESPath transform that reshapes the response, and any static defaults — and the
service turns that into an endpoint:

```console
$ curl -H 'X-API-Key: …' -H 'Content-Type: application/json' \
       -d '{"args": {"id": "10"}}' \
       -o invoice.pdf https://pdf.example.com/v1/render/invoice
```

## How a request flows

```
POST /v1/render/invoice {"args": {"id": "10"}}
  │
  ├─ arguments validated against the query's own variable definitions   → 422
  ├─ query executed against the GraphQL endpoint with those variables   → 502 / 504
  ├─ response reshaped by the template's JMESPath transform
  ├─ merged onto the bundle defaults (see Data precedence)
  └─ compiled by Typst with the result as sys.inputs.data               → application/pdf
```

## Quickstart

```console
$ docker run --rm -p 8000:8000 \
    -e GRAPHQL_TYPST_GRAPHQL_URL=http://your-api:8080/graphql \
    ghcr.io/resmo/graphql-typst:latest

$ curl -s localhost:8000/v1/templates | jq
$ curl -s -d '{"args":{"id":"10"}}' -H 'Content-Type: application/json' \
    -o out.pdf localhost:8000/v1/render/invoice
```

The image ships an **example bundle** so it starts with no configuration beyond the
upstream URL. It is a demonstration — placeholder company, logo and IBAN — not a
supported template set. Mount your own:

```console
$ docker run --rm -p 8000:8000 \
    -e GRAPHQL_TYPST_GRAPHQL_URL=http://your-api:8080/graphql \
    -e GRAPHQL_TYPST_BUNDLE_DIR=/srv/bundle \
    -v "$PWD/my-bundle:/srv/bundle:ro" \
    ghcr.io/resmo/graphql-typst:latest
```

Or install from PyPI:

```console
$ pip install graphql-typst
$ graphql-typst check --bundle-dir my-bundle
$ graphql-typst serve
```

The published wheel contains no templates at all — bundles are yours.

## The template bundle

A bundle is one directory, and that directory is also the Typst compilation root, so
templates address their siblings root-absolutely (`#import "/lib/page.typ"`,
`image("/assets/logo.png")`).

```
my-bundle/
├── templates.yaml     # the only entry point
├── defaults.yaml      # optional global defaults
├── templates/         # one .typ entry document per template
├── lib/               # shared .typ imported by templates
├── queries/           # .graphql
├── transforms/        # .jmespath
├── defaults/          # .json / .yaml, per template
├── assets/            # images
└── fonts/             # optional, picked up automatically
```

```yaml
# templates.yaml
version: 1
defaults: defaults.yaml                    # optional, merged under everything

templates:
  - name: invoice                          # also the URL path segment
    description: Swiss QR invoice
    template: templates/invoice.typ
    query: queries/invoice.graphql
    transform: transforms/invoice.jmespath # optional; omitted = raw GraphQL data
    defaults: defaults/invoice.json        # optional
    args: [id]                             # optional cross-check, see below
    operation_name: InvoiceById            # required only if the query has >1 operation
    filename: "invoice-{id}.pdf"           # optional, default "{name}.pdf"
```

Everything is validated at startup, and **every** problem is reported at once, so a
broken bundle takes one pass to fix rather than one restart per typo:

```console
$ graphql-typst check --bundle-dir my-bundle
invalid template bundle (2 problem(s)):
  1. template 'invoice'.query: file not found (queries/invoice.graphql)
  2. template 'letter'.args ['ref'] does not match the query's variables ['id']
```

### Arguments are GraphQL variables

The query declares them; the config does not:

```graphql
query InvoiceById($id: ID!) {
  invoiceById(id: $id) { ... }
}
```

Names, types and required-ness are read straight from those variable definitions, so
there is one source of truth and it is the one the server actually enforces. The
optional `args:` list in `templates.yaml` is an assertion checked at load time, not a
second declaration. Request arguments are passed as GraphQL `variables` — never
interpolated into the query text.

An argument that is declared but not supplied is *omitted* rather than sent as `null`,
so the query's own default applies. Strings are coerced only where the declared type
makes that unambiguous (`Int`, `Float`, `Boolean`), which is what lets
`--arg id=10` work.

### Writing a template

The document data arrives as one JSON string in `sys.inputs`:

```typst
#let data = json(bytes(sys.inputs.data))
= #data.title
```

Templates may import from [Typst Universe](https://typst.app/universe)
(`#import "@preview/payqr-swiss:0.4.1": swiss-qr-bill`). Those packages are downloaded
on first use, so the container image bakes them in at build time with
`graphql-typst warm-cache` — at runtime it needs no network for rendering.

### Data precedence

```
global defaults  <  template defaults  <  transform output
```

with one rule that matters: **`null` values in the transform output are dropped before
merging.** A JMESPath multi-select hash returns `{"amount": null}` for any field the
response omitted, and merging that would erase the very default the bundle supplies
for that case. Dropping it means "upstream did not return this" falls back to the
default, which is what a defaults file is for.

Lists are exempt, contents included. `deep_merge` replaces a list wholesale, so no
default can ever show through one — and a GraphQL record inside a list legitimately
carries `"vatRate": null` that the template then reads.

## API

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/healthz` | open | Liveness. 200 whenever the process is up. |
| `GET` | `/readyz` | open | Readiness. 503 until the bundle, renderer and upstream session are all up. Issues no upstream query. |
| `GET` | `/v1/templates` | key | Templates and the arguments each accepts. |
| `POST` | `/v1/render/{name}` | key | Renders to `application/pdf`. |
| `GET` | `/metrics` | key | Prometheus text, when `metrics_enabled`. |
| `GET` | `/docs`, `/openapi.json` | open | Toggle with `docs_enabled`. |

```http
POST /v1/render/invoice?disposition=inline
X-API-Key: …
Content-Type: application/json

{"args": {"id": "10"}, "filename": "custom.pdf"}
```

Responses carry `Content-Disposition` in both the ASCII and RFC 5987 forms (German
templates produce umlauts), `Cache-Control: no-store`, `X-Request-ID` and
`X-Render-Duration-Ms`.

Errors are `{"error": {"code", "message", "request_id", "details"}}`:

| Status | `code` | When |
| --- | --- | --- |
| 401 | `unauthorized` | Missing or wrong API key. |
| 404 | `template_not_found` | Unknown template; `details.available` lists them. |
| 422 | `invalid_request` | Malformed body. |
| 422 | `invalid_arguments` | `details.missing` / `unknown` / `accepted`. |
| 502 | `upstream_graphql_error` | The endpoint answered with `errors`. |
| 502 | `upstream_transport_error` | Could not reach or read from the endpoint. |
| 502 | `empty_upstream_result` | The transform produced no document data. |
| 503 | `render_busy` | No render capacity within the queue timeout. |
| 504 | `upstream_timeout` | The endpoint timed out. |
| 500 | `render_failed` | Typst refused to compile. |

GraphQL `errors[].message` and `path` are always returned — they describe the caller's
own request, and hiding them makes a 502 undebuggable — but `extensions` is stripped,
because servers put stack traces there. Typst diagnostics quote template source and are
returned only when `debug_errors` is on. Both are always logged in full against the
request id.

## Configuration

Environment variables, prefix `GRAPHQL_TYPST_`, also read from `.env`.

| Setting | Default | Notes |
| --- | --- | --- |
| `BUNDLE_DIR` | *required* | Template bundle directory. |
| `GRAPHQL_URL` | *required to serve* | Upstream endpoint. `check` and `warm-cache` work without it. |
| `GRAPHQL_AUTH_HEADER_NAME` | `Authorization` | |
| `GRAPHQL_AUTH_HEADER_VALUE` | — | Full value, e.g. `Bearer xyz`. |
| `GRAPHQL_EXTRA_HEADERS` | `{}` | JSON object. |
| `GRAPHQL_TIMEOUT_S` / `GRAPHQL_EXECUTE_TIMEOUT_S` | `30` | |
| `GRAPHQL_VERIFY_SSL` | `true` | |
| `GRAPHQL_POOL_SIZE` | `20` | Upstream connection limit. |
| `GRAPHQL_RETRY_EXECUTE` | `true` | Retry transport faults with backoff — never a query the server rejected. Costs a few seconds before a hard failure surfaces as 502; set `false` to fail fast. |
| `API_KEY` | — | Unset means the API is open. |
| `API_KEY_HEADER` | `X-API-Key` | |
| `RENDER_CONCURRENCY` | CPU count (min 2) | Concurrent compiles. |
| `COMPILER_POOL_SIZE` | = concurrency | Compilers cached per template. |
| `RENDER_QUEUE_TIMEOUT_S` | `10` | Then 503 `render_busy`. |
| `MAX_ARGS_BYTES` | `65536` | |
| `TYPST_PACKAGE_CACHE_PATH` | — | Where `@preview` packages live. |
| `TYPST_PACKAGE_PATH` | — | Local `@local` packages. |
| `IGNORE_SYSTEM_FONTS` / `FONT_PATHS` | `false` / `[]` | |
| `PDF_STANDARDS` | `[]` | e.g. `["a-3b"]` for archival PDF/A. |
| `PDF_TIMESTAMP` | — | Fix it for byte-reproducible output. |
| `HOST` / `PORT` / `WORKERS` | `0.0.0.0` / `8000` / `1` | |
| `ROOT_PATH` | — | Behind a proxy prefix. |
| `DOCS_ENABLED` | `true` | |
| `CORS_ALLOW_ORIGINS` | `[]` | |
| `REQUEST_ID_HEADER` | `X-Request-ID` | |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `json` or `console`. |
| `ACCESS_LOG` | `true` | |
| `DEBUG_ERRORS` | `false` | Return Typst diagnostics to clients. |
| `METRICS_ENABLED` | `false` | Needs the `metrics` extra. |

## CLI

```console
graphql-typst serve [--host] [--port] [--workers] [--reload]
graphql-typst render <name> [--arg k=v]... [--args-json '{…}'] [-o out.pdf | -]
graphql-typst check [--bundle-dir DIR]        # exit 1 and list every problem
graphql-typst warm-cache [--bundle-dir DIR]   # pull @preview packages
graphql-typst version
```

`render` goes through the same service as the HTTP route, so the CLI never diverges
from production behaviour.

## Deployment notes

**Sizing.** Typst releases the GIL while compiling, so renders genuinely run in
parallel. `RENDER_CONCURRENCY` caps how many at once; beyond that, callers queue for
`RENDER_QUEUE_TIMEOUT_S` and then get a 503 with `Retry-After` rather than joining an
unbounded backlog. Budget roughly 150–300 ms of CPU per render.

**No hard timeout on a compile, deliberately.** A Python thread cannot be killed, so
abandoning a running compile would return 504 while leaking its concurrency slot
permanently — after N runaway compiles the service would deadlock. Templates are
operator-supplied and trusted; an infinite loop in a `.typ` is a deploy-time bug like
an infinite loop in application code. If untrusted templates ever become a
requirement, move the compile behind a `ProcessPoolExecutor`, where a hard kill is
possible.

**Probes.** Point liveness at `/healthz` and readiness at `/readyz`. Both stay open
when an API key is configured, so probes need no secret. `/readyz` deliberately does
not query upstream — probes run every few seconds and would become a self-inflicted
load test.

**Hardening.** The image runs as UID 10001 and works with `read_only: true`,
`cap_drop: ALL` and `no-new-privileges` (see `docker-compose.yml`). Mount bundles
read-only.

## Development

```console
$ make install     # uv sync --all-extras
$ make check       # lint, typecheck, tests, bundle validation
$ make run         # serve the example bundle with reload
$ make test-all    # also the tests that download @preview packages
```

The test suite is hermetic: its fixture template imports no `@preview` package and
selects no font, so a real Typst compile — including a 16-way concurrency check — runs
offline in every CI job. The GraphQL layer is doubled with a real `gql.Client` over a
local schema rather than a mock, because variable binding is exactly where the bugs
are.

## License

MIT
