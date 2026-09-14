"""Structured logging.

Stdlib ``logging`` with a JSON formatter installed on the root handler, rather than
structlog: uvicorn, aiohttp, gql and graphql-core all log through stdlib, so a single
root formatter makes *every* line JSON. Reaching the same place with structlog needs
``ProcessorFormatter`` bridging plus an extra runtime dependency.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import logging.config
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graphql_typst.settings import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        "request_id",
    }
)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED}


class RequestIdFilter(logging.Filter):
    """Stamp every record with the current request id.

    Attached to the handler rather than to our own loggers, so third-party records
    emitted while serving a request are correlated too.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        payload.update(_extras(record))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extras(record)
        return f"{base} {extras}" if extras else base


def configure_logging(settings: Settings) -> None:
    formatter = "json" if settings.log_format == "json" else "console"
    noisy = "DEBUG" if settings.log_level.upper() == "DEBUG" else "WARNING"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "json": {"()": JsonFormatter},
                "console": {"()": ConsoleFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "formatter": formatter,
                    "filters": ["request_id"],
                }
            },
            "root": {"handlers": ["default"], "level": settings.log_level.upper()},
            "loggers": {
                # We emit our own access log with timings and the request id.
                "uvicorn.access": {"handlers": [], "propagate": False, "level": "WARNING"},
                "uvicorn.error": {"level": settings.log_level.upper()},
                "aiohttp": {"level": noisy},
                "gql": {"level": noisy},
                "graphql": {"level": noisy},
            },
        }
    )
