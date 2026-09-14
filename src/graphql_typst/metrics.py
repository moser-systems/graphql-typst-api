"""Metrics hook.

A Protocol with a no-op default, so the service always has something to call and
swapping Prometheus for OpenTelemetry later touches only this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from graphql_typst.settings import Settings


class Metrics(Protocol):
    def observe_render(self, template: str, status: str, duration_ms: float) -> None: ...

    def inc_upstream(self, status: str) -> None: ...

    def render_text(self) -> tuple[str, str]:
        """Return ``(body, content_type)`` for the ``/metrics`` endpoint."""
        ...


class NullMetrics:
    enabled = False

    def observe_render(self, template: str, status: str, duration_ms: float) -> None:  # noqa: ARG002
        return

    def inc_upstream(self, status: str) -> None:  # noqa: ARG002
        return

    def render_text(self) -> tuple[str, str]:
        return "", "text/plain; charset=utf-8"


class PrometheusMetrics:
    enabled = True

    def __init__(self) -> None:
        # Optional extra: importing at module scope would make prometheus-client a
        # hard dependency of every install.
        from prometheus_client import CollectorRegistry, Counter, Histogram  # noqa: PLC0415

        self._registry = CollectorRegistry()
        self._renders = Histogram(
            "graphql_typst_render_duration_seconds",
            "End-to-end render duration",
            labelnames=("template", "status"),
            registry=self._registry,
        )
        self._upstream = Counter(
            "graphql_typst_upstream_requests_total",
            "GraphQL requests by outcome",
            labelnames=("status",),
            registry=self._registry,
        )

    def observe_render(self, template: str, status: str, duration_ms: float) -> None:
        self._renders.labels(template=template, status=status).observe(duration_ms / 1000)

    def inc_upstream(self, status: str) -> None:
        self._upstream.labels(status=status).inc()

    def render_text(self) -> tuple[str, str]:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # noqa: PLC0415

        return generate_latest(self._registry).decode(), CONTENT_TYPE_LATEST


def build_metrics(settings: Settings) -> Metrics:
    if not settings.metrics_enabled:
        return NullMetrics()
    try:
        return PrometheusMetrics()
    except ImportError:  # pragma: no cover - depends on the optional extra
        import logging  # noqa: PLC0415

        logging.getLogger(__name__).warning(
            "metrics.disabled", extra={"reason": "install graphql-typst[metrics]"}
        )
        return NullMetrics()
