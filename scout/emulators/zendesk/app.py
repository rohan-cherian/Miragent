"""
W1-SRC-05 — Zendesk Support API emulator (FastAPI).

Endpoints:
  GET  /api/v2/incremental/tickets/cursor  — cursor incremental export
  GET  /api/v2/tickets/{id}                — single ticket (+ optional sideloads)
  PUT  /api/v2/tickets/{id}                — ticket update (write-back) + webhook

Data backend:
  - PostgreSQL ``src_zendesk`` only (live dump data)
  - Tests may inject an in-memory ``ZendeskStore`` via ``store=``

Every request:
  1. AuthStub (401 Zendesk envelope if no token)
  2. ChaosSwitch (?chaos=429|500|slow|partial)
  3. Account-wide EmulatorRateLimiter (real 429 + Retry-After)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from scout.emulators.zendesk.base import TicketStore
from scout.emulators.zendesk.export import (
    DEFAULT_PAGE_SIZE,
    incremental_tickets_page,
    parse_include,
)
from scout.emulators.zendesk.factory import create_store, store_info
from scout.emulators.zendesk.webhooks import emit_ticket_webhook
from scout.shared import (
    AuthStub,
    ChaosSwitch,
    EmulatorRateLimiter,
    ErrorKind,
    Vendor,
    build_error_body,
    error_response,
)

VENDOR = Vendor.ZENDESK


def create_zendesk_app(
    *,
    store: TicketStore | None = None,
    database_url: str | None = None,
    rate_limit_max: int = 100,
    rate_limit_window_seconds: int = 60,
) -> FastAPI:
    """
    Build a standalone Zendesk emulator FastAPI app.

    Args:
        store: Optional injected store (unit tests only).
        database_url: Postgres DSN; overrides ``ZENDESK_DATABASE_URL``.
        rate_limit_max: Account-wide request budget per window.
        rate_limit_window_seconds: Sliding window length.

    Requires live Postgres when ``store`` is not injected.
    """
    from scout.observability.logging import configure_json_logging
    from scout.observability.middleware import install_observability_middleware
    from scout.observability.tracing import init_tracing, instrument_fastapi

    configure_json_logging()
    init_tracing(service_name="miragent-zendesk-emulator")

    app = FastAPI(
        title="Zendesk API Emulator",
        version="0.1.0",
        docs_url="/docs",
    )
    install_observability_middleware(app)
    instrument_fastapi(app, service_name="miragent-zendesk-emulator")

    if store is None:
        store = create_store(database_url=database_url)

    auth = AuthStub(VENDOR)
    chaos = ChaosSwitch(VENDOR, slow_seconds=0.05)  # short delay for tests
    limiter = EmulatorRateLimiter(
        max_requests=rate_limit_max,
        window_seconds=rate_limit_window_seconds,
    )

    app.state.store = store
    app.state.auth = auth
    app.state.chaos = chaos
    app.state.limiter = limiter

    def _gates(request: Request) -> Response | None:
        """Auth → chaos → account-wide rate limit. Return Response to short-circuit."""
        blocked = auth.enforce(request.headers)
        if blocked is not None:
            return blocked

        chaos_result = chaos.apply(request.query_params)
        if chaos_result.response is not None:
            return chaos_result.response

        # Stash partial flag for handlers that paginate.
        request.state.chaos_partial = chaos_result.effects.partial

        limited = limiter.enforce(
            "account",
            body=build_error_body(VENDOR, ErrorKind.RATE_LIMITED),
        )
        if limited is not None:
            return limited
        return None

    @app.get("/health")
    def health() -> dict[str, str]:
        info = store_info(store)
        return {"status": "ok", **info}

    @app.get("/api/v2/incremental/tickets/cursor")
    @app.get("/api/v2/incremental/tickets/cursor.json")
    def incremental_tickets(request: Request) -> Response:
        gated = _gates(request)
        if gated is not None:
            return gated

        params = request.query_params
        cursor = params.get("cursor")
        start_raw = params.get("start_time")
        include = parse_include(params.get("include"))

        per_page = DEFAULT_PAGE_SIZE
        if params.get("per_page"):
            try:
                per_page = max(1, int(params.get("per_page", DEFAULT_PAGE_SIZE)))
            except ValueError:
                return error_response(
                    VENDOR,
                    ErrorKind.BAD_REQUEST,
                    message="per_page must be an integer",
                )

        start_time: int | None = None
        if cursor is None:
            if start_raw is None or str(start_raw).strip() == "":
                return error_response(
                    VENDOR,
                    ErrorKind.BAD_REQUEST,
                    message="start_time is required when cursor is not provided",
                )
            try:
                start_time = int(start_raw)
            except ValueError:
                return error_response(
                    VENDOR,
                    ErrorKind.BAD_REQUEST,
                    message="start_time must be a Unix timestamp",
                )

        try:
            body = incremental_tickets_page(
                store,
                start_time=start_time,
                cursor=cursor,
                page_size=per_page,
                include=include,
                force_partial=bool(getattr(request.state, "chaos_partial", False)),
            )
        except ValueError as exc:
            return error_response(VENDOR, ErrorKind.BAD_REQUEST, message=str(exc))

        return JSONResponse(content=body)

    @app.get("/api/v2/tickets/{ticket_id}")
    @app.get("/api/v2/tickets/{ticket_id}.json")
    def get_ticket(ticket_id: int, request: Request) -> Response:
        gated = _gates(request)
        if gated is not None:
            return gated

        ticket = store.get_ticket(ticket_id)
        if ticket is None:
            return error_response(VENDOR, ErrorKind.NOT_FOUND, message="Not found")

        include = parse_include(request.query_params.get("include"))
        body: dict[str, Any] = {"ticket": ticket}
        if include:
            body.update(store.sideload_for_tickets([ticket], include))
        return JSONResponse(content=body)

    @app.put("/api/v2/tickets/{ticket_id}")
    @app.put("/api/v2/tickets/{ticket_id}.json")
    async def update_ticket(ticket_id: int, request: Request) -> Response:
        gated = _gates(request)
        if gated is not None:
            return gated

        try:
            payload = await request.json()
        except Exception:
            return error_response(
                VENDOR,
                ErrorKind.BAD_REQUEST,
                message="Request body must be JSON",
            )

        if not isinstance(payload, dict):
            return error_response(
                VENDOR,
                ErrorKind.BAD_REQUEST,
                message="Request body must be an object",
            )

        patch = payload.get("ticket", payload)
        if not isinstance(patch, dict):
            return error_response(
                VENDOR,
                ErrorKind.BAD_REQUEST,
                message="ticket must be an object",
            )

        before = store.get_ticket(ticket_id)
        if before is None:
            return error_response(VENDOR, ErrorKind.NOT_FOUND, message="Not found")

        previous = {
            "status": before.get("status"),
            "priority": before.get("priority"),
        }
        updated = store.update_ticket(ticket_id, patch)
        assert updated is not None

        emit_ticket_webhook(store, updated, previous=previous)

        include = parse_include(request.query_params.get("include"))
        body: dict[str, Any] = {"ticket": updated}
        if include:
            body.update(store.sideload_for_tickets([updated], include))
        return JSONResponse(content=body)

    return app
