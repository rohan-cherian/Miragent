"""
SOC 2 audit logging middleware.

Records every inbound request and its outcome to a structured JSON log file.
Required for SOC 2 Type II: every access to tenant data must be logged with
who, what, when, and the outcome. Logs are ingested by the SIEM
(Splunk/Datadog) in production.
"""

import json
import logging
import os
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware


class AuditLogMiddleware(BaseHTTPMiddleware):
    """Writes one JSON line per request to the configured audit log file."""

    def __init__(self, app, log_file: str):
        super().__init__(app)
        self._logger = logging.getLogger("scout.audit")

        # Always ensure the log directory exists — idempotent and safe across
        # multiple create_app() calls in tests.
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        # Only add a handler if one hasn't been attached already (avoid duplicates
        # when create_app() is called multiple times in tests).
        if not self._logger.handlers:
            try:
                log_dir = os.path.dirname(log_file)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
                handler = logging.FileHandler(log_file)
                handler.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.INFO)
                # Prevent propagation so audit lines don't appear in the root logger
                self._logger.propagate = False
            except Exception as exc:
                # Fall back to stderr so the app still starts
                logging.getLogger(__name__).warning(
                    f"Could not open audit log file '{log_file}': {exc}. "
                    "Falling back to stderr."
                )
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.INFO)
                self._logger.propagate = False

    async def dispatch(self, request, call_next):
        start = time.time()
        request_id = str(uuid.uuid4())[:8]

        response = await call_next(request)

        duration_ms = round((time.time() - start) * 1000)

        record = {
            "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_string": str(request.url.query),
            "tenant_id": request.query_params.get("tenant_id", ""),
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "user_agent": request.headers.get("user-agent", ""),
        }

        self._logger.info(json.dumps(record))
        return response
