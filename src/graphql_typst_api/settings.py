"""Runtime configuration, read from the environment with the ``GRAPHQL_TYPST_API_`` prefix."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import DirectoryPath, Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from graphql_typst_api.errors import ConfigurationError

# The set typst accepts; declaring it here means a typo fails at startup rather
# than at the first render.
PdfStandard = Literal[
    "1.4",
    "1.5",
    "1.6",
    "1.7",
    "2.0",
    "a-1a",
    "a-1b",
    "a-2a",
    "a-2b",
    "a-2u",
    "a-3a",
    "a-3b",
    "a-3u",
    "a-4",
    "a-4e",
    "a-4f",
    "ua-1",
]


def _default_concurrency() -> int:
    # os.process_cpu_count() is 3.13+; os.cpu_count() covers 3.11 and 3.12.
    counter = getattr(os, "process_cpu_count", os.cpu_count)
    return max(2, counter() or 1)


class Settings(BaseSettings):
    """All knobs, with defaults that are safe for a single-replica deployment."""

    model_config = SettingsConfigDict(
        env_prefix="GRAPHQL_TYPST_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- bundle ---------------------------------------------------------------
    bundle_dir: DirectoryPath

    # --- upstream GraphQL -----------------------------------------------------
    # Optional in the model, required to serve: `check` and `warm-cache` are
    # purely local and must work in a container build with no upstream at all.
    graphql_url: HttpUrl | None = None
    graphql_auth_header_name: str = "Authorization"
    graphql_auth_header_value: SecretStr | None = None
    graphql_extra_headers: dict[str, str] = Field(default_factory=dict)
    graphql_timeout_s: float = 30.0
    graphql_execute_timeout_s: float = 30.0
    graphql_verify_ssl: bool = True
    graphql_pool_size: int = 20
    graphql_retry_execute: bool = True

    # --- inbound auth ---------------------------------------------------------
    api_key: SecretStr | None = None
    api_key_header: str = "X-API-Key"

    # --- rendering ------------------------------------------------------------
    render_concurrency: int = Field(default_factory=_default_concurrency, ge=1)
    compiler_pool_size: int | None = Field(default=None, ge=1)
    render_queue_timeout_s: float = 10.0
    max_args_bytes: int = 65536

    # --- typst ----------------------------------------------------------------
    typst_package_cache_path: Path | None = None
    typst_package_path: Path | None = None
    ignore_system_fonts: bool = False
    font_paths: list[Path] = Field(default_factory=list)
    pdf_standards: list[PdfStandard] = Field(default_factory=list)
    pdf_timestamp: int | None = None

    # --- server / ops ---------------------------------------------------------
    host: str = "0.0.0.0"  # noqa: S104 - containers bind all interfaces by design
    port: int = 8000
    workers: int = 1
    root_path: str = ""
    docs_enabled: bool = True
    cors_allow_origins: list[str] = Field(default_factory=list)
    request_id_header: str = "X-Request-ID"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    access_log: bool = True
    debug_errors: bool = False
    metrics_enabled: bool = False

    @model_validator(mode="after")
    def _apply_derived_defaults(self) -> Settings:
        if self.compiler_pool_size is None:
            # One compiler per concurrent render: fewer would serialise renders of the
            # same template, more would just hold idle memory.
            object.__setattr__(self, "compiler_pool_size", self.render_concurrency)
        return self

    @property
    def pool_size(self) -> int:
        return self.compiler_pool_size or self.render_concurrency

    def require_graphql_url(self) -> str:
        if self.graphql_url is None:
            raise ConfigurationError(
                "GRAPHQL_TYPST_API_GRAPHQL_URL is required to query a GraphQL endpoint"
            )
        return str(self.graphql_url)

    def upstream_headers(self) -> dict[str, str]:
        headers = dict(self.graphql_extra_headers)
        if self.graphql_auth_header_value is not None:
            headers[self.graphql_auth_header_name] = (
                self.graphql_auth_header_value.get_secret_value()
            )
        return headers
