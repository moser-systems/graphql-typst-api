"""FastAPI dependencies."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from graphql_typst_api.errors import UnauthorizedError
from graphql_typst_api.service import RenderService
from graphql_typst_api.settings import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_service(request: Request) -> RenderService:
    service: RenderService = request.app.state.service
    return service


SettingsDep = Annotated[Settings, Depends(get_settings)]
ServiceDep = Annotated[RenderService, Depends(get_service)]

# Declared purely so the OpenAPI document advertises the scheme and /docs offers an
# input box. The actual header name is read from settings, which may differ.
_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    settings: SettingsDep,
    _documented: Annotated[str | None, Security(_api_key_scheme)] = None,
) -> None:
    """Reject the request unless it carries the configured API key.

    When no key is configured the API is open, which is the right default behind an
    ingress that already authenticates. Startup logs a warning in that case so it is
    never a silent accident.
    """
    if settings.api_key is None:
        return
    provided = request.headers.get(settings.api_key_header)
    expected = settings.api_key.get_secret_value()
    # Constant-time: a naive == leaks the key one character at a time under timing.
    if provided is None or not hmac.compare_digest(provided, expected):
        raise UnauthorizedError
