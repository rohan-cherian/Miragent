"""
Task 24, Part E — tests for the recommendation and write-execution routes.

Skips cleanly without a live database. Fixtures reuse the exact Case +
ProposedAction + RecommendationDecision + WriteExecution shapes
tests/canonical/test_execution.py established; sessions use
expire_on_commit=False per the Part A fix.

NOTE on the refire test: refire() re-runs the gated execution path, whose
GmailAdapter module does not exist yet (Task 21, Rohan) — so a refire on a
failed row legitimately ends failed again after 3 fast attempts
(GMAIL_FORCE_SEND_FAIL short-circuits before the import). The assertions
here are about the ROUTE's contract: 200 with a WriteState, the SAME
decision reused, no second decision row — exactly what
tests/canonical/test_execution.py asserts at the function level.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.api.app import app
from scout.canonical.models import (
    Case,
    ProposedAction,
    RecommendationDecision,
    WriteExecution,
)
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping execution-route tests")
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


def _make_case(session: Session, subject: str) -> Case:
    now = datetime.now(UTC)
    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject=subject,
        status="open",
        opened_at=now,
        **_provenance(now),
    )
    session.add(case)
    session.flush()
    return case


def _make_proposed_action(session: Session, case_id: uuid.UUID, text: str) -> ProposedAction:
    now = datetime.now(UTC)
    proposed_action = ProposedAction(
        id=uuid.uuid4(),
        case_id=case_id,
        triage_result_id=None,
        resolution_path=None,
        recommended_action_text=text,
        draft_sentences=[{"text": text, "citation_refs": [], "withheld": False}],
        confidence=0.9,
        risk=None,
        recommended_owner=None,
        evidence=[],
        policy_ref=None,
        approval_required=True,
        model_name="test-model",
        prompt_version="v1",
        version=1,
        version_token=str(uuid.uuid4()),
        status="draft_pending",
        **_provenance(now),
    )
    session.add(proposed_action)
    session.flush()
    return proposed_action


def _make_decision(session: Session, case_id, proposed_action_id, state="approved") -> RecommendationDecision:
    now = datetime.now(UTC)
    decision = RecommendationDecision(
        id=uuid.uuid4(),
        case_id=case_id,
        proposed_action_id=proposed_action_id,
        state=state,
        edited_text=None,
        edit_diff=None,
        reject_reason=None,
        payload_hash="test-hash",
        actor="execution-route-test",
        decided_at=now,
        version_token=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        **_provenance(now),
    )
    session.add(decision)
    session.flush()
    return decision


def _make_write_execution(session: Session, case_id, decision_id, state, **extra) -> WriteExecution:
    now = datetime.now(UTC)
    row = WriteExecution(
        id=uuid.uuid4(),
        decision_id=decision_id,
        case_id=case_id,
        action_type="GMAIL_SEND_REPLY",
        state=state,
        attempts=extra.pop("attempts", 0),
        execution_ref=None,
        suppressed_reason=extra.pop("suppressed_reason", None),
        error=extra.pop("error", None),
        started_at=None,
        finished_at=None,
        **_provenance(now),
    )
    session.add(row)
    session.flush()
    return row


def _cleanup(engine, case_ids: list[uuid.UUID]) -> None:
    with Session(engine) as session:
        for model in (WriteExecution, RecommendationDecision, ProposedAction):
            for row in session.query(model).filter(model.case_id.in_(case_ids)).all():
                session.delete(row)
        for row in session.query(Case).filter(Case.id.in_(case_ids)).all():
            session.delete(row)
        session.commit()


def _headers() -> dict:
    return {
        "Idempotency-Key": str(uuid.uuid4()),
        "If-Match": "unchecked-see-bridge-4",
        "X-Actor-Name": "execution-route-test",
    }


# ── Recommendation ────────────────────────────────────────────────────────


def test_recommendation_pre_and_post_decision_shapes_and_404():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "Recommendation test")
            case_ids.append(case.id)
            proposed_action = _make_proposed_action(
                session, case.id, "Recommended action: reissue the licence key."
            )
            session.commit()

        # pre-decision: decision_state falls back to the proposed action's status
        pre = client.get(f"/api/v1/cases/{case.id}/recommendation")
        assert pre.status_code == 200, pre.text
        body = pre.json()
        assert set(body) >= {"case_id", "draft_text", "citations", "decision_state", "generated_at"}
        assert body["decision_state"] == "draft_pending"
        assert body["draft_text"] == "Recommended action: reissue the licence key."

        with Session(engine, expire_on_commit=False) as session:
            _make_decision(session, case.id, proposed_action.id, state="approved")
            session.commit()

        post = client.get(f"/api/v1/cases/{case.id}/recommendation")
        assert post.json()["decision_state"] == "approved"

        # case exists but no proposed action -> 404; unknown case -> 404
        with Session(engine, expire_on_commit=False) as session:
            bare_case = _make_case(session, "No recommendation yet")
            case_ids.append(bare_case.id)
            session.commit()
        assert client.get(f"/api/v1/cases/{bare_case.id}/recommendation").status_code == 404
        assert client.get(f"/api/v1/cases/{uuid.uuid4()}/recommendation").status_code == 404
    finally:
        _cleanup(engine, case_ids)


# ── Write-execution read ──────────────────────────────────────────────────


def test_write_execution_read_reflects_draft_only_suppression_and_not_started():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "Suppression visibility test")
            case_ids.append(case.id)
            proposed_action = _make_proposed_action(session, case.id, "Approve me.")
            decision = _make_decision(session, case.id, proposed_action.id)
            _make_write_execution(
                session, case.id, decision.id, "not_started",
                suppressed_reason="ACTION_MODE=draft_only (MVP Phase 1)",
            )
            session.commit()

        response = client.get(f"/api/v1/cases/{case.id}/write-execution")
        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {"case_id", "state"}  # contract-required fields
        assert body["state"] == "not_started"
        assert body["suppressed_reason"] == "ACTION_MODE=draft_only (MVP Phase 1)"
        assert body["last_error"] is None

        # a real case with no WriteExecution row at all -> honest not_started
        with Session(engine, expire_on_commit=False) as session:
            bare_case = _make_case(session, "Nothing dispatched")
            case_ids.append(bare_case.id)
            session.commit()
        bare = client.get(f"/api/v1/cases/{bare_case.id}/write-execution").json()
        assert bare == {
            "case_id": str(bare_case.id), "state": "not_started",
            "attempts": 0, "last_error": None,
        }

        assert client.get(f"/api/v1/cases/{uuid.uuid4()}/write-execution").status_code == 404
    finally:
        _cleanup(engine, case_ids)


# ── Refire ────────────────────────────────────────────────────────────────


def test_refire_on_failed_row_returns_200_and_never_creates_a_second_decision(monkeypatch):
    monkeypatch.setenv("GMAIL_FORCE_SEND_FAIL", "true")  # fast, deterministic path
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "Refire test")
            case_ids.append(case.id)
            proposed_action = _make_proposed_action(session, case.id, "Send this.")
            decision = _make_decision(session, case.id, proposed_action.id)
            _make_write_execution(
                session, case.id, decision.id, "failed",
                attempts=3, error="forced failure (fixture)",
            )
            session.commit()

        response = client.post(
            f"/api/v1/cases/{case.id}/write-execution/refire",
            json={"reason": "transient failure, retrying"},
            headers=_headers(),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["case_id"] == str(case.id)
        assert body["state"] in {"succeeded", "failed"}  # a WriteState — with the
        # adapter absent + FORCE_SEND_FAIL it lands failed; the route contract holds

        with Session(engine) as session:
            decisions = session.execute(
                select(RecommendationDecision).where(RecommendationDecision.case_id == case.id)
            ).scalars().all()
            assert len(decisions) == 1, "refire reuses the SAME decision — never a second row"
            assert decisions[0].id == decision.id
            latest_we = session.execute(
                select(WriteExecution)
                .where(WriteExecution.case_id == case.id)
                .order_by(WriteExecution.observed_at.desc())
            ).scalars().first()
            assert latest_we.decision_id == decision.id
    finally:
        _cleanup(engine, case_ids)


def test_refire_on_non_failed_row_returns_409_conflict_shape():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case = _make_case(session, "Refire not allowed test")
            case_ids.append(case.id)
            proposed_action = _make_proposed_action(session, case.id, "Suppressed.")
            decision = _make_decision(session, case.id, proposed_action.id)
            _make_write_execution(
                session, case.id, decision.id, "not_started",
                suppressed_reason="ACTION_MODE=draft_only (MVP Phase 1)",
            )
            session.commit()

        response = client.post(
            f"/api/v1/cases/{case.id}/write-execution/refire",
            headers=_headers(),
        )

        assert response.status_code == 409, response.text
        body = response.json()
        assert set(body) >= {"error", "by", "at"}  # contract Conflict409 shape
        assert body["error"] == "refire_not_allowed"

        # missing required headers -> 422
        no_headers = client.post(f"/api/v1/cases/{case.id}/write-execution/refire")
        assert no_headers.status_code == 422
    finally:
        _cleanup(engine, case_ids)
