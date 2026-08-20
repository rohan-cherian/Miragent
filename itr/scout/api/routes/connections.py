"""
Task 24, Part B — connections route: GET /connections -> Connection[].

BLOCKED ON: Task 6 (Rohan). The spec's demo mapping backs GET /connections
with "connector_registry + raw_ingest.runs"; NEITHER table exists in this
workspace yet (checked — raw_ingest holds only quarantine, and no schema
file creates a connector_registry anywhere). Same situation reconcile.py
documents for src_gmail.message.

Per the project's established pattern for Rohan-blocked dependencies, this
route is implemented against the contract's shape and the assumed table,
and FAILS NATURALLY with Postgres's own UndefinedTable error when called
before Task 6 lands — no fake rows, no mock fallback. The correct "no data
yet" behaviour is a real error naming the missing table, not invented
health.

Assumed table contract (to be reconciled when Task 6 lands):
    raw_ingest.connector_registry (
        id uuid, source_system text,
        status text,             -- connected | disconnected | error
        last_synced_at timestamptz
    )

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient — the registry is read via plain SQL, never via the
adapter layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from scout.api.deps import get_db_session
from scout.api.schemas import Connection

router = APIRouter()

_LIST_SQL = text(
    """
    SELECT id, source_system, status, last_synced_at
    FROM raw_ingest.connector_registry
    ORDER BY source_system
    """
)


@router.get("/connections", response_model=list[Connection])
def list_connections(session: Session = Depends(get_db_session)) -> Any:
    rows = session.execute(_LIST_SQL).mappings().all()
    return [
        Connection(
            id=row["id"],
            source_system=row["source_system"],
            status=row["status"],
            last_synced_at=row["last_synced_at"],
        )
        for row in rows
    ]
