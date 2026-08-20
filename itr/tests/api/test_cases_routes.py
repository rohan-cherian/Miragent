"""
Task 24, Part B — tests for the cases routes.

Skips cleanly without a live database (same convention as every other
integration test in this repo). Fixtures reuse the Case/Person shape
tests/canonical/test_decisions.py established; sessions are built with
expire_on_commit=False per the Part A fixture fix.
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
from scout.canonical.models import Case, CaseEvent, Person
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping cases-route tests")
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


def _make_person(session: Session, name: str) -> Person:
    person = Person(
        id=uuid.uuid4(),
        org_id=None,
        display_name=name,
        primary_email=f"{uuid.uuid4().hex[:8]}@example.test",
        **_provenance(datetime.now(UTC)),
    )
    session.add(person)
    session.flush()
    return person


def _make_case(session: Session, subject: str, status: str, requester_id=None) -> Case:
    now = datetime.now(UTC)
    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject=subject,
        status=status,
        opened_at=now,
        requester_id=requester_id,
        **_provenance(now),
    )
    session.add(case)
    session.flush()
    return case


def _cleanup(engine, case_ids: list[uuid.UUID], person_ids: list[uuid.UUID]) -> None:
    with Session(engine) as session:
        for row in session.query(CaseEvent).filter(CaseEvent.case_id.in_(case_ids)).all():
            session.delete(row)
        for row in session.query(Case).filter(Case.id.in_(case_ids)).all():
            session.delete(row)
        if person_ids:
            for row in session.query(Person).filter(Person.id.in_(person_ids)).all():
                session.delete(row)
        session.commit()


def test_list_cases_returns_case_shaped_rows_and_status_filter_works():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    person_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            person = _make_person(session, "Priya Test")
            person_ids.append(person.id)
            open_case = _make_case(session, "Open API test case", "open", person.id)
            solved_case = _make_case(session, "Solved API test case", "solved")
            case_ids += [open_case.id, solved_case.id]
            session.commit()

        response = client.get("/api/v1/cases")
        assert response.status_code == 200
        body = response.json()
        by_id = {row["id"]: row for row in body}
        assert str(open_case.id) in by_id and str(solved_case.id) in by_id

        row = by_id[str(open_case.id)]
        # Case schema, contract-exact required fields
        assert set(row) >= {"id", "status", "subject", "requester", "created_at", "updated_at"}
        assert row["status"] == "open"
        assert row["requester"] == "Priya Test"
        assert by_id[str(solved_case.id)]["requester"] == "", "unresolved requester maps to ''"

        # contract filter: ?status=
        filtered = client.get("/api/v1/cases", params={"status": "solved"}).json()
        filtered_ids = {row["id"] for row in filtered}
        assert str(solved_case.id) in filtered_ids
        assert str(open_case.id) not in filtered_ids
    finally:
        _cleanup(engine, case_ids, person_ids)


def test_case_360_returns_detail_and_404_for_unknown_id():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "360 test case", "open")
            case_ids.append(case.id)
            session.commit()

        response = client.get(f"/api/v1/cases/{case.id}/360")
        assert response.status_code == 200
        body = response.json()
        assert body["case"]["id"] == str(case.id)
        assert body["case_number"].startswith("ITR-TEST-")
        assert body["message_count"] == 0
        assert body["latest_triage"] is None
        assert body["latest_proposed_action"] is None

        missing = client.get(f"/api/v1/cases/{uuid.uuid4()}/360")
        assert missing.status_code == 404
    finally:
        _cleanup(engine, case_ids, [])


def test_case_timeline_returns_events_oldest_first():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "Timeline test case", "open")
            case_ids.append(case.id)
            now = datetime.now(UTC)
            for index, event_type in enumerate(["case_created_new", "case_reopened"]):
                session.add(
                    CaseEvent(
                        id=uuid.uuid4(),
                        case_id=case.id,
                        event_type=event_type,
                        payload={"reason": event_type},
                        occurred_at=now.replace(microsecond=index * 1000),
                        actor="system",
                    )
                )
            session.commit()

        response = client.get(f"/api/v1/cases/{case.id}/timeline")
        assert response.status_code == 200
        events = response.json()
        assert [event["event_type"] for event in events] == ["case_created_new", "case_reopened"]

        missing = client.get(f"/api/v1/cases/{uuid.uuid4()}/timeline")
        assert missing.status_code == 404
    finally:
        _cleanup(engine, case_ids, [])
