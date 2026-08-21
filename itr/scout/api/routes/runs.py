"""
Task 24, Part B — runs routes: GET /runs, /runs/{id}, /runs/{id}/quarantine.

Task 6 has LANDED (schema/004_raw_ingest.sql): raw_ingest.runs is real.
Columns confirmed against the actual DDL: id, tenant_id, source_system,
mode, started_at, finished_at, status, cursor_before, cursor_after,
messages_seen, messages_written, messages_skipped, errors (jsonb).

Two documented bridges against the FROZEN contract (schemas.py is pinned):
* status vocabulary — the DB writes running | success | failed | partial;
  the contract's RunStatus enum is pending | running | succeeded | failed.
  Mapped: success -> succeeded, running -> running, failed -> failed, and
  partial -> failed (LOSSY: a partial run completed with errors and the
  contract has no slot for that — flagged for a contract revision; the
  composed counts dict still carries the skip/error numbers so the
  information is not lost). "pending" never occurs in the DB — a run row
  is created already running; no gap in practice.
* counts — the DB has no counts column; the contract's Run.counts
  (dict[str,int]) is COMPOSED from messages_seen / messages_written /
  messages_skipped plus the errors-array length.

GET /runs/{id}/quarantine is NOT blocked: raw_ingest.quarantine is real
(Task 16, schema/008), keyed by connector_run_id — this route works against
real data today.

GET /runs/{id}/stream (SSE) remains deferred: raw_ingest.run_stage_event
now exists (schema/004), but the SSE plumbing does not — half the blocker
cleared, the route still needs its own build.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from scout.api.deps import get_db_session
from scout.api.schemas import Run, RunStage
from scout.canonical.models import Quarantine

router = APIRouter()

_COLUMNS = (
    "id, source_system, status, started_at, finished_at, "
    "messages_seen, messages_written, messages_skipped, errors"
)

_LIST_SQL_BASE = f"""
    SELECT {_COLUMNS}
    FROM raw_ingest.runs
    WHERE true
"""

# id is bound as a str, not a uuid.UUID: with a raw text() statement (no
# SQLAlchemy column typing) psycopg can't adapt a bare UUID object, and
# raises "can't adapt type 'UUID'". CAST(:id AS uuid) on the SQL side lets
# Postgres do the conversion instead — the same convention
# scripts/ingest_canonical.py already uses for CAST(:thread_id AS uuid).
# Task 24 requires GET /runs/{id} to carry "the seven stages with progress,
# per-stage duration and log lines" — that is what drives the console's
# Pipeline Scan bars and mini-logs, so it is read on the detail route.
_STAGES_SQL = """
    SELECT stage, progress_pct, log_line, duration_ms, created_at
    FROM raw_ingest.run_stage_event
    WHERE run_id = CAST(:id AS uuid)
    ORDER BY id
"""


_GET_SQL = f"""
    SELECT {_COLUMNS}
    FROM raw_ingest.runs
    WHERE id = CAST(:id AS uuid)
"""

# DB status -> contract RunStatus (see module docstring; partial is lossy).
_DB_TO_CONTRACT_STATUS = {
    "running": "running",
    "success": "succeeded",
    "failed": "failed",
    "partial": "failed",
}
# Contract filter value -> DB value(s) for the ?status= query param.
_CONTRACT_TO_DB_STATUS = {
    "running": "running",
    "succeeded": "success",
    "failed": "failed",  # NOTE: matches DB 'failed' only; 'partial' rows are
    #        reported as failed in responses but filterable only via their
    #        own DB value — acceptable until the contract grows 'partial'.
    "pending": "__never__",  # no DB equivalent; matches nothing, honestly
}


def _to_run(row: Any) -> Run:
    errors = row["errors"] or []
    return Run(
        id=row["id"],
        source_system=row["source_system"],
        status=_DB_TO_CONTRACT_STATUS.get(row["status"], "failed"),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        counts={
            "messages_seen": row["messages_seen"],
            "messages_written": row["messages_written"],
            "messages_skipped": row["messages_skipped"],
            "errors": len(errors),
        },
    )


@router.get("/runs", response_model=list[Run])
def list_runs(
    source_system: str | None = None,  # contract query param
    status: str | None = None,  # contract query param
    session: Session = Depends(get_db_session),
) -> Any:
    db_status = _CONTRACT_TO_DB_STATUS.get(status, status) if status else None

    # Built dynamically rather than `(:param IS NULL OR col = :param)`:
    # binding a bare NULL through that pattern leaves Postgres unable to
    # infer the parameter's type ("could not determine data type of
    # parameter $1") when the filter isn't supplied. Appending a clause
    # only when its filter is actually set means every bound parameter is
    # always a real, typed value.
    clauses = []
    params: dict[str, Any] = {}
    if source_system is not None:
        clauses.append("source_system = :source_system")
        params["source_system"] = source_system
    if db_status is not None:
        clauses.append("status = :status")
        params["status"] = db_status

    sql = _LIST_SQL_BASE + "".join(f" AND {c}" for c in clauses) + " ORDER BY started_at DESC"
    rows = session.execute(text(sql), params).mappings().all()
    return [_to_run(row) for row in rows]


@router.get("/runs/{id}", response_model=Run)
def get_run(
    id: uuid.UUID,  # noqa: A002 — contract PathRunId
    session: Session = Depends(get_db_session),
) -> Any:
    row = session.execute(text(_GET_SQL), {"id": str(id)}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")  # contract 404
    run = _to_run(row)
    stages = session.execute(text(_STAGES_SQL), {"id": str(id)}).mappings().all()
    run.stages = [RunStage(**dict(r)) for r in stages]
    return run


@router.get("/runs/{id}/quarantine")
def get_run_quarantine(
    id: uuid.UUID,  # noqa: A002 — contract PathRunId
    session: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Free-shape per the contract. Real data: raw_ingest.quarantine exists."""
    rows = session.execute(
        select(Quarantine)
        .where(Quarantine.connector_run_id == id)
        .order_by(Quarantine.first_seen_at.asc())
    ).scalars().all()
    return [
        {
            "id": str(row.id),
            "source_system": row.source_system,
            "external_id": row.external_id,
            "object_path": row.object_path,
            "error_code": row.error_code,
            "error_reason": row.error_reason,
            "retry_count": row.retry_count,
            "max_retries": row.max_retries,
            "status": row.status,
            "first_seen_at": row.first_seen_at.isoformat(),
            "last_attempt_at": (
                row.last_attempt_at.isoformat() if row.last_attempt_at else None
            ),
        }
        for row in rows
    ]
