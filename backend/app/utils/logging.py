"""Structured JSON logging with a per-request correlation id."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

from app.utils.security import redact

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_var.get(),
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
        if extra:
            payload.update(redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
