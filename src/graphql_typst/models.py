"""Request and response schemas for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Values for the template's GraphQL variables.",
        examples=[{"id": "10"}],
    )
    filename: str | None = Field(
        default=None,
        max_length=200,
        description="Override the Content-Disposition filename.",
    )


class ArgInfo(BaseModel):
    name: str
    type: str
    required: bool
    is_list: bool


class TemplateInfo(BaseModel):
    name: str
    description: str | None = None
    args: list[ArgInfo]
    filename: str


class TemplateListResponse(BaseModel):
    templates: list[TemplateInfo]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    version: str
    templates: int
    upstream: Literal["connected", "disconnected"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
