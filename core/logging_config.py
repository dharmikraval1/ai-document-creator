# core/logging_config.py
from __future__ import annotations

import contextvars
import json
import logging
from datetime import datetime, timezone

REQUEST_ID_VAR: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "request_id": getattr(record, "request_id", "-"),
                "message": record.getMessage(),
            },
            ensure_ascii=False,
        )


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID_VAR.get("-")
        return True


def setup_logging(json_mode: bool = False) -> None:
    """Configure the root logger. Call once at process startup."""
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if json_mode:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
