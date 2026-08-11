"""
W1-SRC-06 — Workday RaaS emulator (FastAPI).

Endpoints:
  GET /health
  GET /ccx/service/customreport2/{tenant}              — list report names
  GET /ccx/service/customreport2/{tenant}/{report}     — RaaS JSON extract

Reports (dual column variants for the same underlying rows):
  Worker_Census          ↔ Worker_Directory
  Organization_Hierarchy ↔ Org_Structure

Data backend:
  - PostgreSQL ``src_workday`` only when running
  - Tests may inject in-memory ``WorkdayStore`` via ``store=``

Every request:
  1. AuthStub (401 Workday envelope if no token)
  2. ChaosSwitch (?chaos=429|500|slow|partial)
  3. Account-wide EmulatorRateLimiter
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from scout.emulators.workday.base import WorkdayDataStore
from scout.emulators.workday.factory import create_store, store_info
from scout.emulators.workday.reports import (
    REPORT_CATALOG,
    build_raas_payload,
    known_report_names,
    project_rows,
)
from scout.shared import (
    AuthStub,
    ChaosSwitch,
    EmulatorRateLimiter,
    ErrorKind,
    Vendor,
    build_error_body,
    error_response,
)

VENDOR = Vendor.WORKDAY
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000


def create_workday_app(
    *,
    store: WorkdayDataStore | None = None,
    database_url: str | None = None,
    rate_limit_max: int = 100,
    rate_limit_window_seconds: int = 60,
) -> FastAPI:
    """
    Build a standalone Workday RaaS emulator FastAPI app.

    Requires live Postgres when ``store`` is not injected.
    """
    from scout.observability.logging import configure_json_logging
    from scout.observability.middleware import install_observability_middleware
    from scout.observability.tracing import init_tracing, instrument_fastapi

    configure_json_logging()
    init_tracing(service_name="miragent-workday-emulator")

    app = FastAPI(
        title="Workday RaaS Emulator",
        version="0.1.0",
        docs_url="/docs",
    )
    install_observability_middleware(app)
    instrument_fastapi(app, service_name="miragent-workday-emulator")

    if store is None:
        store = create_store(database_url=database_url)

    auth = AuthStub(VENDOR)
    chaos = ChaosSwitch(VENDOR, slow_seconds=0.05)
    limiter = EmulatorRateLimiter(
        max_requests=rate_limit_max,
        window_seconds=rate_limit_window_seconds,
    )

    app.state.store = store
    app.state.auth = auth
    app.state.chaos = chaos
    app.state.limiter = limiter

    def _gates(request: Request) -> Response | None:
        blocked = auth.enforce(request.headers)
        if blocked is not None:
            return blocked

        chaos_result = chaos.apply(request.query_params)
        if chaos_result.response is not None:
            return chaos_result.response

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

    @app.get("/ccx/service/customreport2/{tenant}")
    def list_reports(tenant: str, request: Request) -> Any:
        gated = _gates(request)
        if gated is not None:
            return gated
        return {
            "tenant": tenant,
            "reports": [
                {
                    "name": name,
                    "entity": REPORT_CATALOG[name][0],
                    "variant": REPORT_CATALOG[name][1],
                }
                for name in known_report_names()
            ],
        }

    @app.get("/ccx/service/customreport2/{tenant}/{report_name}")
    def run_report(
        tenant: str,
        report_name: str,
        request: Request,
        format: str = "json",
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Any:
        gated = _gates(request)
        if gated is not None:
            return gated

        if format.lower() != "json":
            return error_response(
                VENDOR,
                ErrorKind.BAD_REQUEST,
                message="Only format=json is supported by this emulator",
            )

        meta = REPORT_CATALOG.get(report_name)
        if meta is None:
            return error_response(
                VENDOR,
                ErrorKind.NOT_FOUND,
                message=f"Report '{report_name}' does not exist",
            )

        entity, variant = meta
        offset = max(0, offset)
        limit = min(max(1, limit), MAX_PAGE_SIZE)

        # Chaos partial → short page (still useful for pagination tests)
        if getattr(request.state, "chaos_partial", False):
            limit = min(limit, 2)

        if entity == "workers":
            rows, total = store.list_workers(offset=offset, limit=limit)
        else:
            rows, total = store.list_organizations(offset=offset, limit=limit)

        entries = project_rows(entity, variant, rows)
        payload = build_raas_payload(entries)
        payload["total"] = total
        payload["offset"] = offset
        payload["limit"] = limit
        payload["report"] = report_name
        payload["tenant"] = tenant
        payload["variant"] = variant
        return payload

    return app
