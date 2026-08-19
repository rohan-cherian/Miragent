"""
Task 13 — idempotency test for the canonical ingest upsert.

Skips cleanly (not a failure) if there's no live database to test
against. src_gmail.message (Task 5, Rohan's side) doesn't exist yet in
this workspace, so this exercises the upsert/persist logic directly
with a synthetic canonical-message dict rather than the full
normalise_message() -> src_gmail pipeline. A full pipeline-level
idempotency test needs real src_gmail data to run end-to-end.

itr360.message.case_id is NOT NULL (Task 10), so this test creates and
cleans up one throwaway itr360.case_ row purely to satisfy that
constraint — scripts/ingest_canonical.py itself never does this; real
ingest runs skip persist entirely until Task 15 (case correlation)
exists. See scripts/ingest_canonical.py's module docstring.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical.models import Case, Message
from scout.config import settings

try:
    from scripts.ingest_canonical import _persist_message
except ImportError:
    _persist_message = None


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping idempotency check")
    return engine


def _make_test_case(session: Session) -> Case:
    now = datetime.now(timezone.utc)
    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject="Idempotency test case",
        status="open",
        opened_at=now,
        tenant_id=uuid.UUID(str(settings.tenant_id)),
        source_system="test",
        is_synthetic=True,
        connector_run_id=uuid.uuid4(),
        observed_at=now,
        valid_from=now,
    )
    session.add(case)
    session.flush()
    return case


def _fake_canonical_row(external_id: str, case_id: uuid.UUID) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "case_id": case_id,
        "person_id": None,
        "direction": "inbound",
        "channel": "email",
        "subject": "Idempotency test message",
        "body_redacted": "This is a test message body with no PII.",
        "pii_map": {},
        "pii_status": "clean",
        # Message.src_message_id is typed UUID (Task 10) — note that real
        # Gmail message IDs are hex strings, not UUIDs, so this may need
        # to change once Task 5's actual src_gmail.message.message_id
        # shape is confirmed. Using a fresh UUID here purely to satisfy
        # the existing column type for this test.
        "src_message_id": uuid.uuid4(),
        "sent_at": now,
        "tenant_id": uuid.UUID(str(settings.tenant_id)),
        "source_system": "gmail",
        "external_id": external_id,
        "is_synthetic": True,
        "connector_run_id": uuid.uuid4(),
        "observed_at": now,
        "valid_from": now,
    }


def _count_rows(session: Session, external_id: str) -> int:
    rows = session.execute(
        select(Message).where(
            Message.source_system == "gmail",
            Message.external_id == external_id,
        )
    ).scalars().all()
    return len(rows)


def test_persist_message_is_idempotent():
    """Calling the upsert logic twice with the same (source_system,
    external_id) pair must not create two itr360.message rows."""
    if _persist_message is None:
        pytest.skip(
            "scripts.ingest_canonical could not be imported — skipping idempotency check"
        )

    engine = _make_engine()
    external_id = f"idempotency-test-{uuid.uuid4()}"
    case_id: uuid.UUID | None = None

    try:
        with Session(engine) as session:
            case = _make_test_case(session)
            case_id = case.id
            session.commit()

            canonical = _fake_canonical_row(external_id, case_id)

            _persist_message(session, canonical)
            session.commit()
            assert _count_rows(session, external_id) == 1

            # Same natural key, run again — must update in place, not duplicate.
            _persist_message(session, canonical)
            session.commit()
            assert _count_rows(session, external_id) == 1, "second upsert created a duplicate row"
    finally:
        with Session(engine) as session:
            for row in session.execute(
                select(Message).where(
                    Message.source_system == "gmail",
                    Message.external_id == external_id,
                )
            ).scalars().all():
                session.delete(row)
            if case_id is not None:
                existing_case = session.get(Case, case_id)
                if existing_case is not None:
                    session.delete(existing_case)
            session.commit()
