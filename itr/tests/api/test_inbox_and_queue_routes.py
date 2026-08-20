"""
Task 24, Part F — tests for /inbox and /queue.

Skips cleanly without a live database. The fixture builds four cases:
  A  open,   needs_human_triage triage row      -> queue (triage arm)
  B  open,   draft_pending proposed action      -> queue (decision arm)
  C  open,   high-band triage, approved action  -> inbox only
  D  solved, nothing attached                   -> inbox only
/inbox must return all four; /queue exactly A and B; every row must carry
the same Case DTO shape GET /cases emits (one shared mapper, no drift).
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
from scout.canonical.models import Case, ProposedAction, TriageResult
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping inbox/queue route tests")
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


def _make_case(session: Session, subject: str, status: str) -> Case:
    now = datetime.now(UTC)
    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject=subject,
        status=status,
        opened_at=now,
        **_provenance(now),
    )
    session.add(case)
    session.flush()
    return case


def _add_triage(session: Session, case_id: uuid.UUID, band: str) -> None:
    now = datetime.now(UTC)
    session.add(
        TriageResult(
            id=uuid.uuid4(),
            case_id=case_id,
            message_id=uuid.uuid4(),
            confidence=0.4 if band == "needs_human_triage" else 0.9,
            band=band,
            rationale="fixture",
            model_name="test-model",
            prompt_version="v1",
            tier_used="fast",
            version=1,
            **_provenance(now),
        )
    )


def _add_proposed_action(session: Session, case_id: uuid.UUID, status: str) -> None:
    now = datetime.now(UTC)
    session.add(
        ProposedAction(
            id=uuid.uuid4(),
            case_id=case_id,
            triage_result_id=None,
            recommended_action_text="fixture",
            draft_sentences=[],
            evidence=[],
            approval_required=True,
            model_name="test-model",
            prompt_version="v1",
            version=1,
            version_token=str(uuid.uuid4()),
            status=status,
            **_provenance(now),
        )
    )


def _cleanup(engine, case_ids: list[uuid.UUID]) -> None:
    with Session(engine) as session:
        for model in (TriageResult, ProposedAction):
            for row in session.query(model).filter(model.case_id.in_(case_ids)).all():
                session.delete(row)
        for row in session.query(Case).filter(Case.id.in_(case_ids)).all():
            session.delete(row)
        session.commit()


def test_inbox_returns_all_cases_and_queue_returns_only_human_attention_cases():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case_a = _make_case(session, "A needs human triage", "open")
            _add_triage(session, case_a.id, "needs_human_triage")
            case_b = _make_case(session, "B awaiting decision", "open")
            _add_proposed_action(session, case_b.id, "draft_pending")
            case_c = _make_case(session, "C confidently handled", "open")
            _add_triage(session, case_c.id, "high")
            _add_proposed_action(session, case_c.id, "approved")
            case_d = _make_case(session, "D solved quiet case", "solved")
            case_ids += [case_a.id, case_b.id, case_c.id, case_d.id]
            session.commit()

        fixture_ids = {str(cid) for cid in case_ids}

        inbox = client.get("/api/v1/inbox")
        assert inbox.status_code == 200
        inbox_ids = {row["id"] for row in inbox.json()} & fixture_ids
        assert inbox_ids == fixture_ids, "inbox is the unfiltered arrival view — all four"

        queue = client.get("/api/v1/queue")
        assert queue.status_code == 200
        queue_ids = {row["id"] for row in queue.json()} & fixture_ids
        assert queue_ids == {str(case_a.id), str(case_b.id)}, (
            "queue = needs_human_triage OR draft_pending — C (handled) and D (solved) excluded"
        )
    finally:
        _cleanup(engine, case_ids)


def test_inbox_and_queue_emit_the_same_case_dto_shape_as_get_cases():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "Shape parity case", "open")
            _add_proposed_action(session, case.id, "draft_pending")
            case_ids.append(case.id)
            session.commit()

        def row_for(path: str) -> dict:
            rows = [r for r in client.get(f"/api/v1/{path}").json() if r["id"] == str(case.id)]
            assert rows, f"{path} must contain the fixture case"
            return rows[0]

        cases_row = row_for("cases")
        inbox_row = row_for("inbox")
        queue_row = row_for("queue")

        # one shared mapper — identical keys AND identical values
        assert set(cases_row) == set(inbox_row) == set(queue_row)
        assert cases_row == inbox_row == queue_row
        assert set(cases_row) >= {"id", "status", "subject", "requester", "created_at", "updated_at"}
    finally:
        _cleanup(engine, case_ids)
