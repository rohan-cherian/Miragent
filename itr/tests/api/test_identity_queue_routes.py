"""
Task 24, Part C — tests for the identity-queue routes.

Skips cleanly without a live database. Covers the TWO contract paths only:
the contract defines no mark-as-new-actor or dismiss endpoints (see
scout/api/routes/identity_queue.py's docstring), so there is nothing to
test at the HTTP layer for those — queue.py's own suite covers them.

Fixture queue rows are inserted via Task 14's own queue.put(), the same
entry point the waterfall uses, so the row shape is exactly production's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.api.app import app
from scout.canonical.identity import queue as identity_queue
from scout.canonical.models import IdentityUnresolvedQueue, Person, PersonEmailAlias
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping identity-queue route tests")
    return engine


def _enqueue(sender_email: str) -> uuid.UUID:
    """A pending queue row through Task 14's own put()."""
    return identity_queue.put(
        src_message_id=f"api-test-{uuid.uuid4().hex[:10]}",
        sender_email=sender_email,
        sender_display="API Test Sender",
        best_guess_person_id=None,
        best_confidence=0.42,
        evidence=[{"signal": "test_fixture", "value": sender_email, "weight": 0.42}],
        connector_run_id=uuid.uuid4(),
        is_synthetic=True,
    )


def _make_person(engine, name: str) -> uuid.UUID:
    now = datetime.now(UTC)
    person_id = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            Person(
                id=person_id,
                org_id=None,
                display_name=name,
                primary_email=None,
                tenant_id=TENANT_ID,
                source_system="test",
                is_synthetic=True,
                connector_run_id=uuid.uuid4(),
                observed_at=now,
                valid_from=now,
            )
        )
        session.commit()
    return person_id


def _cleanup(engine, queue_ids, person_ids, emails) -> None:
    with Session(engine) as session:
        if emails:
            for row in (
                session.query(PersonEmailAlias).filter(PersonEmailAlias.email.in_(emails)).all()
            ):
                session.delete(row)
        for row in (
            session.query(IdentityUnresolvedQueue)
            .filter(IdentityUnresolvedQueue.id.in_(queue_ids))
            .all()
        ):
            session.delete(row)
        if person_ids:
            for row in session.query(Person).filter(Person.id.in_(person_ids)).all():
                session.delete(row)
        session.commit()


def _headers() -> dict:
    return {
        "Idempotency-Key": str(uuid.uuid4()),
        "If-Match": "unchecked-see-bridge-3",
        "X-Actor-Name": "identity-route-test",
    }


def test_list_returns_pending_items_in_contract_shape():
    engine = _make_engine()
    email = f"pending-{uuid.uuid4().hex[:8]}@example.test"
    qid = _enqueue(email)
    try:
        response = client.get("/api/v1/identity/queue")
        assert response.status_code == 200
        by_id = {row["id"]: row for row in response.json()}
        assert str(qid) in by_id

        item = by_id[str(qid)]
        # IdentityQueueItem, contract-exact required fields
        assert set(item) >= {"id", "candidate_email", "status", "created_at"}
        assert item["candidate_email"] == email
        assert item["status"] == "unresolved", "model 'pending' maps to contract 'unresolved'"
        assert item["candidate_score"] == pytest.approx(0.42)
    finally:
        _cleanup(engine, [qid], [], [email])


def test_resolve_closes_the_row_writes_verified_alias_and_returns_item():
    engine = _make_engine()
    email = f"resolve-{uuid.uuid4().hex[:8]}@example.test"
    qid = _enqueue(email)
    person_id = _make_person(engine, "Resolved Person")
    try:
        response = client.post(
            f"/api/v1/identity/queue/{qid}/resolve",
            json={"person_id": str(person_id)},
            headers=_headers(),
        )

        assert response.status_code == 200, response.text
        item = response.json()
        assert item["id"] == str(qid)
        assert item["status"] == "resolved"
        assert response.headers.get("X-Trace-Id")

        # queue.py's own contract: a VERIFIED alias at 0.99 now exists.
        with Session(engine) as session:
            alias = (
                session.query(PersonEmailAlias)
                .filter(PersonEmailAlias.email == email)
                .one()
            )
            assert alias.person_id == person_id
            assert alias.verified is True
            assert float(alias.confidence) == pytest.approx(0.99)

        # the pending list no longer shows it
        listed = {row["id"] for row in client.get("/api/v1/identity/queue").json()}
        assert str(qid) not in listed
    finally:
        _cleanup(engine, [qid], [person_id], [email])


def test_second_resolve_returns_409_already_resolved():
    engine = _make_engine()
    email = f"twice-{uuid.uuid4().hex[:8]}@example.test"
    qid = _enqueue(email)
    person_id = _make_person(engine, "First Resolver Target")
    try:
        first = client.post(
            f"/api/v1/identity/queue/{qid}/resolve",
            json={"person_id": str(person_id)},
            headers=_headers(),
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/identity/queue/{qid}/resolve",
            json={"person_id": str(person_id)},
            headers=_headers(),
        )
        assert second.status_code == 409, second.text
        body = second.json()
        assert set(body) >= {"error", "by", "at"}  # contract Conflict409 shape
        assert body["error"] == "already_resolved"
        assert body["by"] == "identity-route-test"
    finally:
        _cleanup(engine, [qid], [person_id], [email])


def test_unknown_qid_is_404_and_missing_headers_are_422():
    engine = _make_engine()
    person_id = _make_person(engine, "Nobody Home")
    try:
        missing = client.post(
            f"/api/v1/identity/queue/{uuid.uuid4()}/resolve",
            json={"person_id": str(person_id)},
            headers=_headers(),
        )
        assert missing.status_code == 404

        # Idempotency-Key / If-Match are required:true in the contract.
        no_headers = client.post(
            f"/api/v1/identity/queue/{uuid.uuid4()}/resolve",
            json={"person_id": str(person_id)},
        )
        assert no_headers.status_code == 422

        # body person_id is required
        no_body = client.post(
            f"/api/v1/identity/queue/{uuid.uuid4()}/resolve",
            json={},
            headers=_headers(),
        )
        assert no_body.status_code == 422
    finally:
        _cleanup(engine, [], [person_id], [])
