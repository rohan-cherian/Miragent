"""
ASGI middleware: bind run_id + trace_id for every request.

Accepts inbound headers:
  X-Run-Id / X-Ticket-Id / traceparent (W3C, handled by OTel instrumentation)

Emits response headers:
  X-Run-Id, X-Trace-Id, X-Ticket-Id (when known)

Uses raw ASGI (not BaseHTTPMiddleware) so contextvars stay on the same task
as the route handler / threadpool copy.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from scout.observability.context import bind_context, clear_context, new_run_id
from scout.observability.logging import get_logger
from scout.observability.tracing import get_current_trace_id

logger = get_logger("scout.observability.middleware")

HEADER_RUN_ID = b"x-run-id"
HEADER_TRACE_ID = b"x-trace-id"
HEADER_TICKET_ID = b"x-ticket-id"


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            text = value.decode("latin-1").strip()
            return text or None
    return None


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return

        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        run_id = _header(headers, HEADER_RUN_ID) or new_run_id()
        ticket_id = _header(headers, HEADER_TICKET_ID)

        token = bind_context(run_id=run_id, ticket_id=ticket_id)
        status_code_box = {"code": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_code_box["code"] = int(message.get("status", 0))
                raw_headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                trace_id = get_current_trace_id()
                if trace_id:
                    bind_context(run_id=run_id, ticket_id=ticket_id, trace_id=trace_id)
                    raw_headers.append((HEADER_TRACE_ID, trace_id.encode("latin-1")))
                raw_headers.append((HEADER_RUN_ID, run_id.encode("latin-1")))
                if ticket_id:
                    raw_headers.append((HEADER_TICKET_ID, ticket_id.encode("latin-1")))
                message = {**message, "headers": raw_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            logger.info(
                "request.completed",
                extra={
                    "event": "request.completed",
                    "method": scope.get("method"),
                    "path": path,
                    "status_code": status_code_box["code"],
                },
            )
        finally:
            clear_context(token)


def install_observability_middleware(app) -> None:
    """Register middleware (call after creating FastAPI app)."""
    app.add_middleware(ObservabilityMiddleware)
