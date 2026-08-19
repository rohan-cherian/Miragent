"""
Task 14 — identity waterfall + queue tests.

Skips cleanly (not a failure) if there's no live database available.
Uses the real Task 11 persona seed data (Priya Sharma / Marcus Chen's
verified aliases) for the "resolves confidently" case, since that's
exactly what those personas exist for — skips with a clear message if
scripts/seed_personas.py hasn't been run with real PERSONA_*_EMAIL
values yet.

decision_audit is append-only (Task 23) — these tests never delete
audit rows, only assert the count went up. The synthetic
identity_unresolved_queue row created here is cleaned up afterward.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical.identity import queue
from scout.canonical.identity.waterfall import Run, resolve
from scout.canonical.models import DecisionAudit, IdentityUnresolvedQueue, PersonEmailAlias
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping identity waterfall tests")
    return engine


def _count_identity_audit_rows(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(DecisionAudit).where(DecisionAudit.category == "identity")
    ).scalar_one()


def test_verified_alias_resolves_confidently():
    engine = _make_engine()

    email = settings.persona_1_email.strip() or settings.persona_2_email.strip()
    if not email:
        pytest.skip("PERSONA_1_EMAIL / PERSONA_2_EMAIL not configured — skipping")

    with Session(engine) as session:
        alias = session.execute(
            select(PersonEmailAlias).where(
                PersonEmailAlias.tenant_id == TENANT_ID,
                PersonEmailAlias.email == email,
                PersonEmailAlias.verified.is_(True),
            )
        ).scalar_one_or_none()
        if alias is None:
            pytest.skip(f"No verified alias for {email} — run scripts/seed_personas.py first")
        expected_person_id = alias.person_id
        audit_before = _count_identity_audit_rows(session)

    src_message = {
        "from_email": email,
        "from_display_name": "Test Sender",
        "thread_id": f"test-thread-{uuid.uuid4()}",
        "signature_block": None,
        "message_id": f"test-msg-{uuid.uuid4()}",
    }
    run = Run(connector_run_id=uuid.uuid4(), is_synthetic=True)

    match = resolve(src_message, run)

    assert match.person_id == expected_person_id
    assert match.confidence == 0.99
    assert match.band == "apply"

    with Session(engine) as session:
        assert _count_identity_audit_rows(session) > audit_before


def test_unmatched_email_queues_for_review():
    engine = _make_engine()

    with Session(engine) as session:
        audit_before = _count_identity_audit_rows(session)

    unknown_email = f"nobody-{uuid.uuid4()}@example.com"
    src_message = {
        "from_email": unknown_email,
        "from_display_name": "Totally Unknown Sender",
        "thread_id": f"test-thread-{uuid.uuid4()}",
        "signature_block": None,
        "message_id": f"test-msg-{uuid.uuid4()}",
    }
    run = Run(connector_run_id=uuid.uuid4(), is_synthetic=True)

    try:
        match = resolve(src_message, run)

        assert match.person_id is None
        assert match.band == "unresolved"

        with Session(engine) as session:
            queue_row = session.execute(
                select(IdentityUnresolvedQueue).where(
                    IdentityUnresolvedQueue.tenant_id == TENANT_ID,
                    IdentityUnresolvedQueue.sender_email == unknown_email,
                )
            ).scalar_one_or_none()
            assert queue_row is not None
            assert queue_row.status == "pending"

            assert _count_identity_audit_rows(session) > audit_before
    finally:
        with Session(engine) as session:
            for row in session.execute(
                select(IdentityUnresolvedQueue).where(
                    IdentityUnresolvedQueue.tenant_id == TENANT_ID,
                    IdentityUnresolvedQueue.sender_email == unknown_email,
                )
            ).scalars().all():
                session.delete(row)
            session.commit()


def test_dismiss_requires_a_reason():
    _make_engine()  # keep the "skip if no live database" behavior consistent

    with pytest.raises(ValueError):
        queue.dismiss(uuid.uuid4(), reason="", actor="tester")

    with pytest.raises(ValueError):
        queue.dismiss(uuid.uuid4(), reason="   ", actor="tester")
