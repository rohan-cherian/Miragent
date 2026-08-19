"""
Task 23 (writer half) — append-only audit trail.

Every decision the system makes (a scan finding, an identity match, a
redaction, a human approval, a system event) gets one row in
itr360.decision_audit. This module can only ever add rows: there is no
update() and no delete() anywhere here, on purpose. If a row needs
correcting, that's a new row — never an edit of an old one.

NOTE: itr360.decision_audit is assumed to already exist (Task 10). As
of writing this module, that table does NOT yet exist in this
project's database — schema creation is out of scope here, so this
module is written against the assumed column set below and will raise
a normal "relation does not exist" database error until Task 10 lands.
Assumed columns: id, tenant_id, case_id, actor, action, category,
inputs, outputs, confidence, trace_id, created_at.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    MetaData,
    Table,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Engine

from scout.config import settings

VALID_CATEGORIES = ("scan", "identity", "redaction", "approval", "system")

_metadata = MetaData()

_decision_audit = Table(
    "decision_audit",
    _metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("case_id", UUID(as_uuid=True), nullable=True),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("inputs", JSONB, nullable=True),
    Column("outputs", JSONB, nullable=True),
    Column("confidence", Float, nullable=True),
    Column("trace_id", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema="itr360",
)


@dataclass
class AuditRow:
    id: uuid.UUID
    tenant_id: uuid.UUID
    case_id: uuid.UUID | None
    actor: str
    action: str
    category: str
    inputs: dict | None
    outputs: dict | None
    confidence: float | None
    trace_id: str | None
    created_at: datetime


_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


def _row_to_audit_row(row) -> AuditRow:
    return AuditRow(
        id=row["id"],
        tenant_id=row["tenant_id"],
        case_id=row["case_id"],
        actor=row["actor"],
        action=row["action"],
        category=row["category"],
        inputs=row["inputs"],
        outputs=row["outputs"],
        confidence=row["confidence"],
        trace_id=row["trace_id"],
        created_at=row["created_at"],
    )


def write(
    actor: str,
    action: str,
    category: str,
    case_id: uuid.UUID | None = None,
    inputs: dict | None = None,
    outputs: dict | None = None,
    confidence: float | None = None,
    trace_id: str | None = None,
) -> uuid.UUID:
    """Insert one append-only audit row and return its id."""
    if category not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid audit category {category!r} - must be one of {VALID_CATEGORIES}."
        )

    new_id = uuid.uuid4()
    tenant_id = uuid.UUID(str(settings.tenant_id))

    statement = _decision_audit.insert().values(
        id=new_id,
        tenant_id=tenant_id,
        case_id=case_id,
        actor=actor,
        action=action,
        category=category,
        inputs=inputs,
        outputs=outputs,
        confidence=confidence,
        trace_id=trace_id,
        created_at=func.now(),  # server-side, UTC
    )

    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(statement)

    return new_id


def list(
    category: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    actor: str | None = None,
) -> list[AuditRow]:
    """Return decision_audit rows matching any combination of filters, oldest first."""
    statement = select(_decision_audit).order_by(_decision_audit.c.created_at.asc())

    if category is not None:
        statement = statement.where(_decision_audit.c.category == category)
    if from_ts is not None:
        statement = statement.where(_decision_audit.c.created_at >= from_ts)
    if to_ts is not None:
        statement = statement.where(_decision_audit.c.created_at <= to_ts)
    if actor is not None:
        statement = statement.where(_decision_audit.c.actor == actor)

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(statement).mappings().all()

    return [_row_to_audit_row(row) for row in rows]


def timeline(case_id: uuid.UUID) -> list[AuditRow]:
    """Return the full ordered audit chain for one case, oldest first."""
    statement = (
        select(_decision_audit)
        .where(_decision_audit.c.case_id == case_id)
        .order_by(_decision_audit.c.created_at.asc())
    )

    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(statement).mappings().all()

    return [_row_to_audit_row(row) for row in rows]
