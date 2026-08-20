"""
Task 24, Part B — runs routes: GET /runs, /runs/{id}, /runs/{id}/quarantine.

BLOCKED ON (partially): Task 6 (Rohan). GET /runs and GET /runs/{id} read
raw_ingest.runs, which does not exist in this workspace yet (checked — the
raw_ingest schema holds only quarantine). Both are implemented against the
contract's Run shape and the assumed table below, and FAIL NATURALLY with
Postgres's UndefinedTable error until Task 6 lands — no fake rows. Same
pattern as connections.py and reconcile.py's BLOCKED-ON note.

GET /runs/{id}/quarantine is NOT blocked: raw_ingest.quarantine is real
(Task 16, schema/008), keyed by connector_run_id — this route works against
real data today.

Assumed raw_ingest.runs contract (to be reconciled when Task 6 lands):
    raw_ingest.runs (
        id uuid, source_system text,
        status text,              -- pending | running | succeeded | failed
        started_at timestamptz, finished_at timestamptz,
        counts jsonb              -- {"messages": 9, "attachments": 1, ...}
    )

GET /runs/{id}/stream (SSE) is deliberately deferred to a later Task 24
part: it needs the run_stage_event table (Task 6) AND server-sent-events
plumbing, neither of which exists yet.

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

_LIST_SQL = """
    SELECT id, source_system, status, started_at, finished_at,
               jsonb_build_object(
                   'messages', messages_seen,
                   'written', messages_written,
                   'skipped', messages_skipped,
                   'attachments', 0
               ) AS counts
    FROM raw_ingest.runs
    -- Casts required: an untyped NULL bind leaves Postgres unable to infer
    -- the parameter type (AmbiguousParameter).
    WHERE (CAST(:source_system AS text) IS NULL OR source_system = :source_system)
      AND (CAST(:status AS text) IS NULL OR status = :status)
    ORDER BY started_at DESC
"""

_GET_SQL = """
    SELECT id, source_system, status, started_at, finished_at,
               jsonb_build_object(
                   'messages', messages_seen,
                   'written', messages_written,
                   'skipped', messages_skipped,
                   'attachments', 0
               ) AS counts
    FROM raw_ingest.runs
    WHERE id = :id
"""


# Task 6's DDL and Task 2's contract disagree on this vocabulary:
#   storage  (raw_ingest.runs.status): running | success | failed | partial
#   contract (Run.status)            : pending | running | succeeded | failed
# The contract is frozen and the console renders on it, so translate here
# rather than changing either side. 'partial' has no contract variant — it
# is reported as failed because a partial run did not complete, and
# flattering it to 'succeeded' would hide a real outcome. Worth an
# amendment to Task 2 so partial can be shown honestly.
_STATUS_TO_CONTRACT = {
    "success": "succeeded",
    "partial": "failed",
}


def _to_run(row: Any) -> Run:
    return Run(
        id=row["id"],
        source_system=row["source_system"],
        status=_STATUS_TO_CONTRACT.get(row["status"], row["status"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        counts=row["counts"],
    )


@router.get("/runs", response_model=list[Run])
def list_runs(
    source_system: str | None = None,  # contract query param
    status: str | None = None,  # contract query param
    session: Session = Depends(get_db_session),
) -> Any:
    rows = session.execute(
        text(_LIST_SQL), {"source_system": source_system, "status": status}
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
