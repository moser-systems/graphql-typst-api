"""HTTP routes."""

from __future__ import annotations

import json
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from graphql_typst_api import __version__
from graphql_typst_api.deps import ServiceDep, SettingsDep, require_api_key
from graphql_typst_api.errors import InvalidArgumentsError
from graphql_typst_api.models import (
    ArgInfo,
    ErrorResponse,
    HealthResponse,
    ReadyResponse,
    RenderRequest,
    TemplateInfo,
    TemplateListResponse,
)

meta_router = APIRouter(tags=["meta"])
v1_router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])

_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
    404: {"model": ErrorResponse, "description": "Unknown template"},
    422: {"model": ErrorResponse, "description": "Invalid arguments"},
    502: {"model": ErrorResponse, "description": "Upstream GraphQL failure"},
    503: {"model": ErrorResponse, "description": "No render capacity"},
    504: {"model": ErrorResponse, "description": "Upstream timeout"},
}


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """Build a header carrying both the ASCII and the RFC 5987 filename forms.

    German templates routinely produce umlauts, which a bare ``filename=`` cannot
    express portably.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    quoted = ascii_name.replace('"', "")
    disposition = "inline" if inline else "attachment"
    return f"{disposition}; filename=\"{quoted}\"; filename*=UTF-8''{quote(filename)}"


@meta_router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    return HealthResponse(version=__version__)


@meta_router.get(
    "/readyz",
    response_model=ReadyResponse,
    summary="Readiness probe",
    responses={503: {"model": ReadyResponse, "description": "Not ready to serve"}},
)
async def readyz(request: Request) -> Response:
    service = getattr(request.app.state, "service", None)
    # Deliberately no upstream query: probes run every few seconds and would turn
    # into a self-inflicted load test against the GraphQL endpoint.
    ready = (
        service is not None
        and bool(service.bundle.templates)
        and service.renderer.prepared
        and service.gateway.connected
    )
    body = ReadyResponse(
        status="ready" if ready else "not_ready",
        version=__version__,
        templates=len(service.bundle.templates) if service is not None else 0,
        upstream=(
            "connected" if service is not None and service.gateway.connected else "disconnected"
        ),
    )
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)


@meta_router.get("/metrics", include_in_schema=False)
async def metrics(service: ServiceDep) -> Response:
    body, content_type = service.metrics.render_text()
    return PlainTextResponse(body, media_type=content_type)


@v1_router.get(
    "/templates",
    response_model=TemplateListResponse,
    summary="List the templates this bundle exposes",
    responses={401: _ERROR_RESPONSES[401]},
)
async def list_templates(service: ServiceDep) -> TemplateListResponse:
    return TemplateListResponse(
        templates=[
            TemplateInfo(
                name=t.name,
                description=t.description,
                args=[
                    ArgInfo(name=a.name, type=a.gql_type, required=a.required, is_list=a.is_list)
                    for a in t.args
                ],
                filename=t.filename,
            )
            for t in service.list_templates()
        ]
    )


@v1_router.post(
    "/render/{name}",
    summary="Render a template to PDF",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
            "description": "The rendered PDF",
        },
        **_ERROR_RESPONSES,
    },
)
async def render(
    service: ServiceDep,
    settings: SettingsDep,
    name: Annotated[str, Path(description="Template name from /v1/templates")],
    body: RenderRequest | None = None,
    disposition: Annotated[Literal["attachment", "inline"], Query()] = "attachment",
) -> Response:
    payload = body or RenderRequest()
    encoded = json.dumps(payload.args, default=str)
    if len(encoded.encode()) > settings.max_args_bytes:
        raise InvalidArgumentsError(f"arguments exceed the {settings.max_args_bytes} byte limit")

    result = await service.render(name, payload.args, payload.filename)
    return Response(
        content=result.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(
                result.filename, inline=disposition == "inline"
            ),
            "Cache-Control": "no-store",
            "X-Render-Duration-Ms": f"{result.duration_ms:.1f}",
        },
    )
