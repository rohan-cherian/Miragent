"""
Task 15 — case correlation tests.

Skips cleanly (not a failure) if there's no live database available.

scripts/ingest_canonical.py isn't wired to correlation yet (a later
task), so "three messages with the same thread_id" is simulated here:
each call to find_or_create_case() is followed by manually persisting
an itr360.message row carrying that thread_id + the resulting case_id
— exactly what a real ingest pipeline will eventually do — so the
NEXT call's same_thread lookup has something to match against.

decision_audit is append-only (Task 23) and never cleaned up here,
only counted. Synthetic Case/Message/CaseEvent/Person rows created by
these tests are cleaned up afterward.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical.correlation import find_or_create_case
from scout.canonical.models import Case, CaseEvent, DecisionAudit, Message, Person
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping case correlation tests")
    return engine


def _make_test_person(session: Session, display_name: str) -> Person:
    now = datetime.now(timezone.utc)
    person = Person(
        id=uuid.uuid4(),
        org_id=None,
        display_name=display_name,
        primary_email=None,
        job_title=None,
        department=None,
        tenant_id=TENANT_ID,
        source_system="test",
        is_synthetic=True,
        connector_run_id=uuid.uuid4(),
        observed_at=now,
        valid_from=now,
    )
    session.add(person)
    session.flush()
    return person


def _persist_message_for_case(
    session: Session, case_id: uuid.UUID, thread_id: str, src_message_id: str, sent_at: datetime
) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        Message(
            id=uuid.uuid4(),
            case_id=case_id,
            person_id=None,
            direction="inbound",
            channel="email",
            subject="Test message",
            body_redacted="Test body, no PII.",
            pii_map={},
            pii_status="clean",
            src_message_id=src_message_id,
            thread_id=thread_id,
            sent_at=sent_at,
            tenant_id=TENANT_ID,
            source_system="gmail",
            is_synthetic=True,
            connector_run_id=uuid.uuid4(),
            observed_at=now,
            valid_from=now,
        )
    )


def _count_scan_audit_rows(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(DecisionAudit).where(DecisionAudit.category == "scan")
    ).scalar_one()


def _count_case_events(session: Session, case_ids: list[uuid.UUID]) -> int:
    return session.execute(
        select(func.count()).select_from(CaseEvent).where(CaseEvent.case_id.in_(case_ids))
    ).scalar_one()


def _cleanup(engine, case_ids: list[uuid.UUID], person_ids: list[uuid.UUID]) -> None:
    with Session(engine) as session:
        for row in session.execute(
            select(Message).where(Message.case_id.in_(case_ids))
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(CaseEvent).where(CaseEvent.case_id.in_(case_ids))
        ).scalars().all():
            session.delete(row)
        for case_id in case_ids:
            case = session.get(Case, case_id)
            if case is not None:
                session.delete(case)
        for person_id in person_ids:
            person = session.get(Person, person_id)
            if person is not None:
                session.delete(person)
        session.commit()


def test_same_thread_correlates_to_one_case():
    """Mirrors the E1/E2/E3 scenario: three messages in one thread all land on one case."""
    engine = _make_engine()
    thread_id = f"test-thread-{uuid.uuid4()}"
    case_ids: list[uuid.UUID] = []

    try:
        for i in range(3):
            src_message = {
                "from_email": "sender@example.com",
                "thread_id": thread_id,
                "in_reply_to": None,
                "subject": "Same conversation",
                "sent_at": datetime.now(timezone.utc),
            }
            case, reason = find_or_create_case(src_message, person_id=None)
            case_ids.append(case.id)

            if i == 0:
                assert reason == "new_case"
            else:
                assert reason == "same_thread"

            with Session(engine) as session:
                _persist_message_for_case(
                    session, case.id, thread_id, f"msg-{i}-{uuid.uuid4()}", src_message["sent_at"]
                )
                session.commit()

        assert len(set(case_ids)) == 1
    finally:
        _cleanup(engine, list(set(case_ids)), [])


def test_dedup_creates_linked_case_not_merge():
    """No thread match, but a similar-subject case from the same person
    within the dedup window links via related_case_ids — never merges."""
    engine = _make_engine()
    now = datetime.now(timezone.utc)
    person_id = None
    case_ids: list[uuid.UUID] = []

    try:
        with Session(engine) as session:
            person = _make_test_person(session, "Dedup Test Person")
            session.commit()
            person_id = person.id

        with Session(engine) as session:
            audit_before = _count_scan_audit_rows(session)

        first_message = {
            "from_email": "dedup-tester@example.com",
            "thread_id": f"test-thread-a-{uuid.uuid4()}",
            "in_reply_to": None,
            "subject": "License key not working",
            "sent_at": now,
        }
        first_case, first_reason = find_or_create_case(first_message, person_id)
        case_ids.append(first_case.id)
        assert first_reason == "new_case"

        second_message = {
            "from_email": "dedup-tester@example.com",
            "thread_id": f"test-thread-b-{uuid.uuid4()}",  # different thread — no same_thread match
            "in_reply_to": None,
            "subject": "License key is not working",  # similar subject, same person, same window
            "sent_at": now + timedelta(minutes=5),
        }
        second_case, second_reason = find_or_create_case(second_message, person_id)
        case_ids.append(second_case.id)

        assert second_reason == "dedup_link"
        assert second_case.id != first_case.id  # linked, NOT merged — two distinct case rows

        with Session(engine) as session:
            reloaded_first = session.get(Case, first_case.id)
            reloaded_second = session.get(Case, second_case.id)
            assert reloaded_first is not None and reloaded_second is not None
            assert reloaded_second.id in reloaded_first.related_case_ids
            assert reloaded_first.id in reloaded_second.related_case_ids

            assert _count_scan_audit_rows(session) > audit_before
            assert _count_case_events(session, case_ids) >= 2
    finally:
        _cleanup(engine, case_ids, [person_id] if person_id else [])
