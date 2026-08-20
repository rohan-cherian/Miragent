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
from scout.api.schemas import Run
from scout.canonical.models import Quarantine

router = APIRouter()

_COLUMNS = (
    "id, source_system, status, started_at, finished_at, "
    "messages_seen, messages_written, messages_skipped, errors"
)

_LIST_SQL = f"""
    SELECT {_COLUMNS}
    FROM raw_ingest.runs
    WHERE (:source_system IS NULL OR source_system = :source_system)
      AND (:status IS NULL OR status = :status)
    ORDER BY started_at DESC
"""

_GET_SQL = f"""
    SELECT {_COLUMNS}
    FROM raw_ingest.runs
    WHERE id = :id
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
    rows = session.execute(
        text(_LIST_SQL), {"source_system": source_system, "status": db_status}
    ).mappings().all()
    return [_to_run(row) for row in rows]


@router.get("/runs/{id}", response_model=Run)
def get_run(
    id: uuid.UUID,  # noqa: A002 — contract PathRunId
    session: Session = Depends(get_db_session),
) -> Any:
    row = session.execute(text(_GET_SQL), {"id": id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")  # contract 404
    return _to_run(row)


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
