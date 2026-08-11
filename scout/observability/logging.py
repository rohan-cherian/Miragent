"""
Structured JSON logging.

Every log record emitted after ``configure_json_logging()`` is a single JSON
object including run_id / trace_id / ticket_id when bound in context.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from scout.observability.context import get_context


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line (stdout-friendly for compose)."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_context()
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if ctx is not None:
            payload["run_id"] = ctx.run_id
            if ctx.trace_id:
                payload["trace_id"] = ctx.trace_id
            if ctx.ticket_id:
                payload["ticket_id"] = ctx.ticket_id

        # Optional extras attached via logger.bind-style: logger.info("…", extra={…})
        for key in ("event", "agent", "span", "status_code", "path", "method"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


_CONFIGURED = False


def configure_json_logging(*, level: int = logging.INFO) -> None:
    """Idempotent: attach JSON formatter to root logger (stdout)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet noisy libs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_json_logging()
    return logging.getLogger(name)
