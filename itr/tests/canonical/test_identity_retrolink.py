"""
Tests for resolve_as_candidate()'s retro-link (the Task 14 TODO, closed).

Skips cleanly without a live database. Fixture chain mirrors production's:
a pending identity_unresolved_queue row (via queue.put, naming a
src_message_id), a case with requester_id NULL, and a canonical message
linking the two through message.src_message_id — the only sender-attribution
path itr360 offers (message has no sender-email column).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical.identity import queue as identity_queue
from scout.canonical.models import (
    Case,
    IdentityUnresolvedQueue,
    Message,
    Person,
    PersonEmailAlias,
)
from scout.config import settings
from scout.governance import audit

TENANT_ID = uuid.UUID(str(settings.tenant_id))


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping retro-link tests")
    return engine


def _provenance(now: datetime) -> dict:
    return {
        "tenant_id": TENANT_ID,
        "source_system": "test",
        "is_synthetic": True,
        "connector_run_id": uuid.uuid4(),
        "observed_at": now,
        "valid_from": now,
    }


def _make_person(session: Session, name: str) -> uuid.UUID:
    person_id = uuid.uuid4()
    session.add(
        Person(id=person_id, org_id=None, display_name=name, primary_email=None,
               **_provenance(datetime.now(UTC)))
    )
    session.flush()
    return person_id


def _make_case_with_message(
    session: Session, src_message_id: str, requester_id=None
) -> uuid.UUID:
    now = datetime.now(UTC)
    case_id = uuid.uuid4()
    session.add(
        Case(id=case_id, case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
             subject="Retro-link fixture", status="open", opened_at=now,
             requester_id=requester_id, **_provenance(now))
    )
    session.flush()
    session.add(
        Message(id=uuid.uuid4(), case_id=case_id, person_id=None,
                direction="inbound", channel="email", subject="fixture",
                body_redacted="fixture body", pii_map=None, pii_status="clean",
                src_message_id=src_message_id, thread_id=None, sent_at=now,
                **_provenance(now))
    )
    session.flush()
    return case_id


def _enqueue(sender_email: str, src_message_id: str) -> uuid.UUID:
    return identity_queue.put(
        src_message_id=src_message_id,
        sender_email=sender_email,
        sender_display="Retro Fixture",
        best_guess_person_id=None,
        best_confidence=0.3,
        evidence=[{"signal": "test_fixture", "value": sender_email, "weight": 0.3}],
        connector_run_id=uuid.uuid4(),
        is_synthetic=True,
    )


def _cleanup(engine, case_ids, person_ids, emails, queue_ids):
    with Session(engine) as session:
        for row in session.query(Message).filter(Message.case_id.in_(case_ids)).all():
            session.delete(row)
        for row in session.query(Case).filter(Case.id.in_(case_ids)).all():
            session.delete(row)
        if emails:
            for row in session.query(PersonEmailAlias).filter(
                PersonEmailAlias.email.in_(emails)
            ).all():
                session.delete(row)
        if queue_ids:
            for row in session.query(IdentityUnresolvedQueue).filter(
                IdentityUnresolvedQueue.id.in_(queue_ids)
            ).all():
                session.delete(row)
        if person_ids:
            for row in session.query(Person).filter(Person.id.in_(person_ids)).all():
                session.delete(row)
        session.commit()


def test_resolve_retrolinks_requesterless_case_and_audits_it():
    engine = _make_engine()
    email = f"retro-{uuid.uuid4().hex[:8]}@example.test"
    src_message_id = f"retro-src-{uuid.uuid4().hex[:10]}"
    case_ids, person_ids, queue_ids = [], [], []
    try:
        with Session(engine, expire_on_commit=False) as session:
            person_id = _make_person(session, "Retro Person")
            person_ids.append(person_id)
            case_id = _make_case_with_message(session, src_message_id, requester_id=None)
            case_ids.append(case_id)
            session.commit()
        qid = _enqueue(email, src_message_id)
        queue_ids.append(qid)

        identity_queue.resolve_as_candidate(qid, person_id, actor="retro-test")

        with Session(engine) as session:
            case = session.get(Case, case_id)
            assert case.requester_id == person_id, "requester retro-linked"

        timeline = audit.timeline(case_id)
        retro_rows = [row for row in timeline if row.action == "case_retrolinked"]
        assert len(retro_rows) == 1, "the case's OWN timeline now shows the identity event"
        assert retro_rows[0].outputs["person_id"] == str(person_id)
        assert retro_rows[0].outputs["previously_unresolved_since"] is not None
    finally:
        _cleanup(engine, case_ids, person_ids, [email], queue_ids)


def test_existing_requester_is_never_overwritten():
    engine = _make_engine()
    email = f"keep-{uuid.uuid4().hex[:8]}@example.test"
    src_message_id = f"keep-src-{uuid.uuid4().hex[:10]}"
    case_ids, person_ids, queue_ids = [], [], []
    try:
        with Session(engine, expire_on_commit=False) as session:
            original_owner = _make_person(session, "Original Owner")
            late_arrival = _make_person(session, "Late Arrival")
            person_ids += [original_owner, late_arrival]
            case_id = _make_case_with_message(
                session, src_message_id, requester_id=original_owner
            )
            case_ids.append(case_id)
            session.commit()
        qid = _enqueue(email, src_message_id)
        queue_ids.append(qid)

        identity_queue.resolve_as_candidate(qid, late_arrival, actor="retro-test")

        with Session(engine) as session:
            case = session.get(Case, case_id)
            assert case.requester_id == original_owner, "existing resolution untouched"
        assert not [
            row for row in audit.timeline(case_id) if row.action == "case_retrolinked"
        ], "no retro-link audit row for an untouched case"
    finally:
        _cleanup(engine, case_ids, person_ids, [email], queue_ids)


def test_no_matching_cases_is_a_normal_outcome():
    engine = _make_engine()
    email = f"lonely-{uuid.uuid4().hex[:8]}@example.test"
    person_ids, queue_ids = [], []
    try:
        with Session(engine, expire_on_commit=False) as session:
            person_id = _make_person(session, "Nobody To Link")
            person_ids.append(person_id)
            session.commit()
        # queue row whose src_message_id matches NO canonical message
        qid = _enqueue(email, f"orphan-src-{uuid.uuid4().hex[:10]}")
        queue_ids.append(qid)

        identity_queue.resolve_as_candidate(qid, person_id, actor="retro-test")  # no raise

        with Session(engine) as session:
            row = session.get(IdentityUnresolvedQueue, qid)
            assert row.status == "resolved", "resolution itself still completed"
            alias = session.execute(
                select(PersonEmailAlias).where(PersonEmailAlias.email == email)
            ).scalars().one()
            assert alias.verified is True
    finally:
        _cleanup(engine, [], person_ids, [email], queue_ids)
