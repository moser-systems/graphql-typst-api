"""Request-scoped middleware: request ids and the access log."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from graphql_typst_api.log import request_id_var

_log = logging.getLogger("graphql_typst_api.access")

Dispatch = Callable[[Request], Awaitable[Response]]


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Adopt or mint a request id, publish it as a ContextVar, echo it on the response."""

    def __init__(self, app: object, header: str = "X-Request-ID") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.header = header

    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        request_id = request.headers.get(self.header) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[self.header] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _log.exception(
                "http.request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        _log.info(
            "http.request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response
