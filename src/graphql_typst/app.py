"""Application factory and lifespan."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from graphql_typst import __version__
from graphql_typst.bundle import load_bundle
from graphql_typst.errors import GraphQLTypstError, RenderFailedError
from graphql_typst.graphql_client import GraphQLGateway
from graphql_typst.log import configure_logging, request_id_var
from graphql_typst.metrics import build_metrics
from graphql_typst.middleware import AccessLogMiddleware, RequestIdMiddleware
from graphql_typst.models import ErrorDetail, ErrorResponse
from graphql_typst.renderer import TypstRenderer
from graphql_typst.routes import meta_router, v1_router
from graphql_typst.service import RenderService
from graphql_typst.settings import Settings

_log = logging.getLogger(__name__)

HTTP_SERVICE_UNAVAILABLE = 503
HTTP_INTERNAL_SERVER_ERROR = 500


def _error_response(
    status_code: int, code: str, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id_var.get(),
            details=details or None,
        )
    )
    headers = {"Retry-After": "1"} if status_code == HTTP_SERVICE_UNAVAILABLE else None
    return JSONResponse(body.model_dump(), status_code=status_code, headers=headers)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings)

    if settings.api_key is None:
        _log.warning(
            "auth.disabled",
            extra={"hint": "set GRAPHQL_TYPST_API_KEY to require a key on /v1"},
        )

    # Fail fast: a missing URL or an invalid bundle raises out of the lifespan and
    # uvicorn refuses to start, rather than serving 500s for every request.
    settings.require_graphql_url()
    bundle = load_bundle(settings.bundle_dir)
    _log.info("bundle.loaded", extra={"templates": bundle.names(), "root": str(bundle.root)})

    renderer = TypstRenderer(bundle, settings)
    renderer.prepare()

    gateway = GraphQLGateway(settings)
    await gateway.start()

    app.state.service = RenderService(bundle, gateway, renderer, settings, build_metrics(settings))
    try:
        yield
    finally:
        await gateway.aclose()
        renderer.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="graphql-typst",
        version=__version__,
        summary="Render Typst PDFs from GraphQL queries",
        lifespan=lifespan,
        root_path=settings.root_path,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings

    # No GZipMiddleware: a PDF is already compressed, so gzipping it burns CPU for
    # roughly no saving.
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition", settings.request_id_header],
        )
    if settings.access_log:
        app.add_middleware(AccessLogMiddleware)
    # Added last, so it is outermost and every log line (and error body) has an id.
    app.add_middleware(RequestIdMiddleware, header=settings.request_id_header)

    app.include_router(meta_router)
    app.include_router(v1_router)

    @app.exception_handler(GraphQLTypstError)
    async def _domain_error(_request: Request, exc: Exception) -> JSONResponse:
        exc = cast(GraphQLTypstError, exc)
        details = dict(exc.details)
        if isinstance(exc, RenderFailedError):
            # Typst diagnostics quote template source, so they are logged in full but
            # only returned when explicitly enabled.
            _log.error(
                "typst.compile_failed",
                extra={
                    "template": exc.template,
                    # Not "message": LogRecord reserves that attribute name.
                    "typst_message": exc.typst_message,
                    "hints": exc.hints,
                    "trace": exc.trace,
                },
            )
            if settings.debug_errors:
                details = exc.debug_details()
        level = logging.ERROR if exc.status_code >= HTTP_INTERNAL_SERVER_ERROR else logging.INFO
        _log.log(level, "request.failed", extra={"code": exc.code, "status": exc.status_code})
        return _error_response(exc.status_code, exc.code, exc.message, details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
        exc = cast(RequestValidationError, exc)
        return _error_response(
            422, "invalid_request", "request body is invalid", {"errors": exc.errors()}
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        _log.exception("request.unhandled", extra={"error_class": type(exc).__name__})
        return _error_response(500, "internal_error", "internal server error")

    return app
