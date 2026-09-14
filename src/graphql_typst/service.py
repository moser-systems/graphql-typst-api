"""Orchestration: template lookup, query, transform, render."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graphql_typst.arguments import validate_args
from graphql_typst.bundle import ArgSpec, Bundle, LoadedTemplate
from graphql_typst.errors import GraphQLTypstError, UpstreamError
from graphql_typst.graphql_client import GraphQLGateway
from graphql_typst.metrics import Metrics
from graphql_typst.renderer import TypstRenderer
from graphql_typst.settings import Settings
from graphql_typst.transform import build_document_data

_log = logging.getLogger(__name__)

# Unicode letters are kept on purpose: German templates produce names like
# "Rechnung Öl.pdf", and the Content-Disposition header carries them in its RFC 5987
# form. Stripping them here would make that form pointless. Path separators, quotes
# and control characters are removed.
_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)
_MAX_FILENAME = 100


def sanitise_filename(candidate: str, fallback: str) -> str:
    """Reduce ``candidate`` to a safe single-segment ``.pdf`` filename."""
    name = Path(candidate.replace("\\", "/")).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = _UNSAFE.sub("-", name).strip(" .-")
    if not name:
        return fallback
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    if len(name) > _MAX_FILENAME:
        name = f"{name[: _MAX_FILENAME - 4]}.pdf"
    return name


@dataclass(frozen=True, slots=True)
class TemplateSummary:
    name: str
    description: str | None
    args: list[ArgSpec]
    filename: str


@dataclass(frozen=True, slots=True)
class RenderResult:
    pdf: bytes
    filename: str
    template: str
    duration_ms: float
    upstream_ms: float
    compile_ms: float


class RenderService:
    def __init__(
        self,
        bundle: Bundle,
        gateway: GraphQLGateway,
        renderer: TypstRenderer,
        settings: Settings,
        metrics: Metrics,
    ) -> None:
        self.bundle = bundle
        self.gateway = gateway
        self.renderer = renderer
        self.settings = settings
        self.metrics = metrics

    def list_templates(self) -> list[TemplateSummary]:
        return [
            TemplateSummary(
                name=t.name,
                description=t.description,
                args=[t.args[k] for k in sorted(t.args)],
                filename=t.filename_pattern,
            )
            for t in (self.bundle.templates[n] for n in self.bundle.names())
        ]

    def _filename(self, template: LoadedTemplate, args: Mapping[str, Any]) -> str:
        fallback = f"{template.name}.pdf"
        try:
            rendered = template.filename_pattern.format(name=template.name, **args)
        except (KeyError, IndexError, ValueError):
            # The pattern was validated at load time, but an optional arg may be
            # absent at request time. A cosmetic filename is never worth a 500.
            return fallback
        return sanitise_filename(rendered, fallback)

    async def render(
        self,
        name: str,
        args: Mapping[str, Any],
        filename: str | None = None,
    ) -> RenderResult:
        started = time.perf_counter()
        try:
            return await self._render(name, args, filename, started)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started) * 1000
            code = exc.code if isinstance(exc, GraphQLTypstError) else "internal_error"
            self.metrics.observe_render(name, code, duration_ms)
            _log.warning(
                "render.failed",
                extra={
                    "template": name,
                    "arg_keys": sorted(args),
                    "code": code,
                    "error_class": type(exc).__name__,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise

    async def _render(
        self,
        name: str,
        args: Mapping[str, Any],
        filename: str | None,
        started: float,
    ) -> RenderResult:
        template = self.bundle.get(name)
        variables = validate_args(template, args)

        upstream_started = time.perf_counter()
        try:
            data = await self.gateway.execute(template, variables)
        except UpstreamError:
            self.metrics.inc_upstream("error")
            raise
        upstream_ms = (time.perf_counter() - upstream_started) * 1000
        self.metrics.inc_upstream("ok")

        document = build_document_data(self.bundle, template, data)

        compile_started = time.perf_counter()
        pdf = await self.renderer.render(template, document)
        compile_ms = (time.perf_counter() - compile_started) * 1000

        duration_ms = (time.perf_counter() - started) * 1000
        self.metrics.observe_render(template.name, "ok", duration_ms)
        _log.info(
            "render.completed",
            extra={
                "template": template.name,
                # Argument *values* are customer identifiers and are never logged.
                "arg_keys": sorted(variables),
                "duration_ms": round(duration_ms, 2),
                "upstream_ms": round(upstream_ms, 2),
                "compile_ms": round(compile_ms, 2),
                "bytes": len(pdf),
            },
        )
        return RenderResult(
            pdf=pdf,
            filename=(
                sanitise_filename(filename, f"{template.name}.pdf")
                if filename
                else self._filename(template, variables)
            ),
            template=template.name,
            duration_ms=duration_ms,
            upstream_ms=upstream_ms,
            compile_ms=compile_ms,
        )
