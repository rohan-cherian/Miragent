"""
Task 24, Part A — the FastAPI application skeleton.

Title/version come from openapi/console-api-v1.yaml's info block (the
frozen Task 2 contract): "ITR Scout Console API" / "1.0.0". Routers mount
under /api/v1, the contract's server url. Only the decisions route exists
in Part A; later parts add connections, runs, stores, identity, cases and
audit routers to the same prefix.

GET /health is NOT in the contract — it is a deliberate ops-only extra,
mounted OUTSIDE /api/v1 so the contract surface stays exactly the 21
paths the yaml defines.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from scout.api.routes import router as api_router
from scout.canonical.decisions import ValidationError, VersionConflictError

app = FastAPI(
    title="ITR Scout Console API",  # contract info.title, verbatim
    version="1.0.0",  # contract info.version, verbatim
)

# CORS — neither config.py nor infra/docker-compose.yml pins a console
# origin (checked before writing this), so this allows the common local
# dev servers: Vite's 5173 and CRA/Next's 3000. MUST be tightened to the
# real console origin before any non-local deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """X-Trace-Id on every response, echoed if the caller supplied one.

    The contract declares this header on every 200 (components/headers),
    and decision_audit.trace_id exists to carry it — later parts thread
    request.state.trace_id into audit.write() calls.
    """
    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


# Global handlers for the backend's typed exceptions. Part A's decisions
# route never lets these escape (handle_submit_decision converts them to
# dicts), but any later route that calls scout.canonical.decisions
# directly gets contract-shaped errors for free.


@app.exception_handler(VersionConflictError)
async def version_conflict_handler(request: Request, exc: VersionConflictError) -> JSONResponse:
    # Contract Conflict409 body: {error, by, at}
    return JSONResponse(
        status_code=409,
        content={
            "error": exc.error,
            "by": exc.by,
            "at": exc.at.isoformat() if exc.at is not None else None,
        },
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    # Contract UnprocessableEntity422 body: {field, min}
    return JSONResponse(status_code=422, content={"field": exc.field, "min": exc.min})


@app.get("/health", include_in_schema=False)
def health() -> dict:
    """Ops-only liveness check — deliberately not part of the frozen contract."""
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
