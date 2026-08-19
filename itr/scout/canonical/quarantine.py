"""
Task 16 — quarantine: put() failed records here instead of dropping
them; retry_pending() advances or retires them. A dead row that
vanishes is a bug that vanishes with it — nothing here is ever
deleted.

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.models import Quarantine
from scout.config import settings
from scout.governance.audit import write as audit_write

TENANT_ID = uuid.UUID(str(settings.tenant_id))

_DEFAULT_MAX_RETRIES = 5

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


# Exception -> {SRC}-ERR-{NNNN} classification. {SRC} is source_system's
# first two letters, uppercased (e.g. "gmail" -> "GM"). This mapping is
# inherently a judgment call, not a formal taxonomy — keep it simple:
#   ERR-1001  TypeError / KeyError           missing or malformed field
#   ERR-1021  ValueError mentioning "email"  bad email format
#   ERR-1022  ValueError (any other message) bad/unexpected value
#   ERR-1041  RedactionError                 PII redaction failed (matched
#                                             by class name, not imported,
#                                             to avoid a scout.governance
#                                             dependency here beyond audit)
#   ERR-9999  anything else                  unclassified fallback
_ERROR_CODE_RULES: list[tuple] = [
    (lambda exc: isinstance(exc, ValueError) and "email" in str(exc).lower(), "1021"),
    (lambda exc: isinstance(exc, ValueError), "1022"),
    (lambda exc: isinstance(exc, (TypeError, KeyError)), "1001"),
    (lambda exc: type(exc).__name__ == "RedactionError", "1041"),
]
_FALLBACK_ERROR_CODE = "9999"


def _source_prefix(source_system: str) -> str:
    prefix = (source_system or "")[:2].upper()
    return prefix or "XX"


def _classify_error(source_system: str, exception: Exception) -> str:
    for matches, code in _ERROR_CODE_RULES:
        if matches(exception):
            return f"{_source_prefix(source_system)}-ERR-{code}"
    return f"{_source_prefix(source_system)}-ERR-{_FALLBACK_ERROR_CODE}"


def put(src_row: dict, exception: Exception, run) -> uuid.UUID:
    """Quarantine a record that failed processing instead of dropping it.

    `run` must provide `connector_run_id` (uuid.UUID) and
    `source_system` (str) — same duck-typed convention Tasks 14/15 use
    for `src_message`; this module doesn't invent either value itself.
    """
    source_system = run.source_system
    now = datetime.now(timezone.utc)
    row_id = uuid.uuid4()
    error_code = _classify_error(source_system, exception)

    external_id = src_row.get("message_id") or src_row.get("id")

    row = Quarantine(
        id=row_id,
        object_path=src_row.get("object_path"),
        error_code=error_code,
        error_reason=str(exception) or type(exception).__name__,
        retry_count=0,
        max_retries=_DEFAULT_MAX_RETRIES,
        status="pending",
        first_seen_at=now,
        last_attempt_at=None,
        tenant_id=TENANT_ID,
        source_system=source_system,
        external_id=str(external_id) if external_id is not None else None,
        is_synthetic=bool(src_row.get("is_synthetic", False)),
        connector_run_id=run.connector_run_id,
        observed_at=now,
        valid_from=now,
    )

    engine = _get_engine()
    with Session(engine) as session:
        session.add(row)
        session.commit()

    audit_write(
        actor="system",
        action="quarantine_put",
        category="system",
        inputs={"source_system": source_system, "error_code": error_code},
        outputs={"quarantine_id": str(row_id), "status": "pending"},
    )

    return row_id


def retry_pending() -> list[Quarantine]:
    """Advance eligible quarantine rows one step.

    Rows still under max_retries get retry_count incremented and
    last_attempt_at bumped (status -> 'retrying'); rows that have used
    up all their retries move to 'dead'. Never deletes a row.

    Exponential backoff: a row already attempted is only touched again
    once 2**retry_count minutes have passed since last_attempt_at.
    Actually re-running the failed operation is out of scope here —
    this only manages queue state. The real retry execution is a
    future integration point once this is wired into
    scripts/ingest_canonical.py.
    """
    engine = _get_engine()
    now = datetime.now(timezone.utc)
    touched: list[Quarantine] = []

    with Session(engine, expire_on_commit=False) as session:
        candidates = session.execute(
            select(Quarantine).where(
                Quarantine.tenant_id == TENANT_ID,
                Quarantine.status.in_(("pending", "retrying")),
                Quarantine.retry_count < Quarantine.max_retries,
            )
        ).scalars().all()

        for row in candidates:
            if row.last_attempt_at is not None:
                backoff = timedelta(minutes=2**row.retry_count)
                if now - row.last_attempt_at < backoff:
                    continue  # not enough time has passed yet

            row.retry_count += 1
            row.last_attempt_at = now
            row.status = "dead" if row.retry_count >= row.max_retries else "retrying"
            touched.append(row)

        session.commit()

    for row in touched:
        audit_write(
            actor="system",
            action="quarantine_dead" if row.status == "dead" else "quarantine_retry",
            category="system",
            inputs={"quarantine_id": str(row.id), "retry_count": row.retry_count},
            outputs={"status": row.status},
        )

    return touched
