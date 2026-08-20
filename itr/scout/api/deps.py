"""
Task 24, Part A — shared FastAPI dependencies.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import Header
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.config import settings

# Lazy module-level singleton — the same engine pattern
# scout/governance/audit.py's _get_engine() established. One engine per
# process, created on first use, never per-request.
_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def get_db_session() -> Iterator[Session]:
    """One SQLAlchemy session per request, closed when the request ends."""
    session = Session(_get_engine())
    try:
        yield session
    finally:
        session.close()


def get_actor(x_actor_name: str | None = Header(default=None, alias="X-Actor-Name")) -> str:
    """Actor identity for audit rows and decision records.

    Slice 1 has NO real authentication — that is explicit future work.
    The frozen OpenAPI contract defines no actor field in any request
    body and no auth header, so this reads an X-Actor-Name header (the
    console can set it trivially) and falls back to a fixed default.
    Replace with real auth resolution when an identity provider lands.
    """
    actor = (x_actor_name or "").strip()
    return actor or "console-user"


def get_tenant_id() -> uuid.UUID:
    """Slice 1 is single-tenant: always settings.tenant_id.

    Multi-tenant resolution (from auth claims or a header) is future
    work — every query that filters on tenant should already take this
    as a parameter so that change is a one-liner here, not a sweep.
    """
    return uuid.UUID(str(settings.tenant_id))
