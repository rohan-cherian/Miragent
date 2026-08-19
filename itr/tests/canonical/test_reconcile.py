"""
Task 16 — reconciliation + quarantine tests.

Skips cleanly (not a failure) if there's no live database available.
Synthetic quarantine rows created here are cleaned up afterward;
decision_audit is append-only (Task 23) and never touched, only
counted.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical import quarantine
from scout.canonical.models import DecisionAudit, Quarantine
from scout.canonical.reconcile import reconcile
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

_ERROR_CODE_PATTERN = re.compile(r"^[A-Z]{2}-ERR-\d{4}$")


class _FakeRun:
    """Minimal duck-typed run context — see quarantine.put()'s docstring."""

    def __init__(self, connector_run_id: uuid.UUID, source_system: str):
        self.connector_run_id = connector_run_id
        self.source_system = source_system


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping reconcile/quarantine tests")
    return engine


def _count_system_audit_rows(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(DecisionAudit).where(DecisionAudit.category == "system")
    ).scalar_one()


def test_put_produces_well_formed_error_code_and_audit_row():
    engine = _make_engine()

    with Session(engine) as session:
        audit_before = _count_system_audit_rows(session)

    run = _FakeRun(connector_run_id=uuid.uuid4(), source_system="gmail")
    src_row = {"message_id": f"test-msg-{uuid.uuid4()}"}
    exception = ValueError("invalid email format")

    quarantine_id = quarantine.put(src_row, exception, run)

    try:
        with Session(engine) as session:
            row = session.get(Quarantine, quarantine_id)
            assert row is not None
            assert _ERROR_CODE_PATTERN.match(row.error_code), row.error_code
            assert row.status == "pending"

            assert _count_system_audit_rows(session) > audit_before
    finally:
        with Session(engine) as session:
            row = session.get(Quarantine, quarantine_id)
            if row is not None:
                session.delete(row)
            session.commit()


def test_retry_pending_moves_row_to_dead_without_deleting():
    engine = _make_engine()
    now = datetime.now(timezone.utc)
    row_id = uuid.uuid4()

    with Session(engine) as session:
        session.add(
            Quarantine(
                id=row_id,
                object_path=None,
                error_code="GM-ERR-9999",
                error_reason="test fixture",
                retry_count=4,  # max_retries - 1
                max_retries=5,
                status="pending",
                first_seen_at=now,
                last_attempt_at=None,  # no backoff wait — eligible immediately
                tenant_id=TENANT_ID,
                source_system="gmail",
                external_id=None,
                is_synthetic=True,
                connector_run_id=uuid.uuid4(),
                observed_at=now,
                valid_from=now,
            )
        )
        session.commit()

    try:
        touched = quarantine.retry_pending()
        touched_ids = {row.id for row in touched}
        assert row_id in touched_ids

        with Session(engine) as session:
            reloaded = session.get(Quarantine, row_id)
            assert reloaded is not None  # never deleted
            assert reloaded.status == "dead"
            assert reloaded.retry_count == 5
    finally:
        with Session(engine) as session:
            reloaded = session.get(Quarantine, row_id)
            if reloaded is not None:
                session.delete(reloaded)
            session.commit()


def test_reconcile_trivial_case_is_100_percent():
    _make_engine()

    result = reconcile("nonexistent_source_system_xyz")

    assert result.completeness_pct == 100.0
    assert result.passed is True
