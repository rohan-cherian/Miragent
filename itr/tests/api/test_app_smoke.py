"""
Task 24, Part A — smoke tests for the FastAPI skeleton.

Two tiers, per the project's established convention:
* No infrastructure needed: /health, the auto-generated OpenAPI schema,
  and the X-Trace-Id middleware — these always run (they need FastAPI
  installed, nothing else).
* Live database needed: the decisions endpoint end-to-end, reusing the
  exact Case + ProposedAction fixture pattern from
  tests/canonical/test_decisions.py. Skips cleanly without Postgres,
  same as every other integration test in this repo.
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
from scout.canonical.models import (
    Case,
    ProposedAction,
    RecommendationDecision,
    WriteExecution,
)
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))

client = TestClient(app)


# ── No infrastructure required ────────────────────────────────────────────


def test_health_returns_200_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_schema_generates_without_error():
    schema = app.openapi()
    assert schema["info"]["title"] == "ITR Scout Console API"  # contract info.title
    assert schema["info"]["version"] == "1.0.0"
    assert "/api/v1/cases/{id}/decision" in schema["paths"]


def test_every_response_carries_x_trace_id():
    response = client.get("/health")
    assert response.headers.get("X-Trace-Id")

    echoed = client.get("/health", headers={"X-Trace-Id": "trace-abc-123"})
    assert echoed.headers["X-Trace-Id"] == "trace-abc-123"


def test_decision_endpoint_requires_the_contract_headers():
    """Idempotency-Key and If-Match are required:true in the contract."""
    response = client.post(
        f"/api/v1/cases/{uuid.uuid4()}/decision", json={"action": "approve"}
    )
    assert response.status_code == 422  # FastAPI rejects missing required headers


# ── Live database required — same skip convention as tests/canonical/ ─────


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping decision-route smoke tests")
    return engine


def _make_case_and_proposed_action(session: Session, text: str) -> tuple[Case, ProposedAction]:
    """Same fixture shape tests/canonical/test_decisions.py builds."""
    now = datetime.now(UTC)
    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject="API smoke test case",
        status="open",
        opened_at=now,
        tenant_id=TENANT_ID,
        source_system="test",
        is_synthetic=True,
        connector_run_id=uuid.uuid4(),
        observed_at=now,
        valid_from=now,
    )
    session.add(case)
    session.flush()
    proposed_action = ProposedAction(
        id=uuid.uuid4(),
        case_id=case.id,
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
        tenant_id=TENANT_ID,
        source_system="test",
        is_synthetic=True,
        connector_run_id=uuid.uuid4(),
        observed_at=now,
        valid_from=now,
    )
    session.add(proposed_action)
    session.flush()
    return case, proposed_action


def _cleanup(engine, case_ids: list[uuid.UUID]) -> None:
    if not case_ids:
        return
    with Session(engine) as session:
        for model in (WriteExecution, RecommendationDecision, ProposedAction, Case):
            column = model.case_id if model is not Case else model.id
            for row in session.query(model).filter(column.in_(case_ids)).all():
                session.delete(row)
        session.commit()


def _headers(if_match: str) -> dict:
    return {
        "Idempotency-Key": str(uuid.uuid4()),
        "If-Match": if_match,
        "X-Actor-Name": "smoke-test",
    }


def test_approve_returns_contract_shaped_recommendation():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        # expire_on_commit=False: case.id / version_token stay readable after
        # commit + session close (same fix Task 15's correlation.py needed).
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(
                session, "Recommended action: reissue the licence key."
            )
            case_ids.append(case.id)
            token = proposed_action.version_token
            session.commit()

        response = client.post(
            f"/api/v1/cases/{case.id}/decision",
            json={"action": "approve"},
            headers=_headers(token),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        # Recommendation, contract-exact: required fields all present
        assert set(body) >= {"case_id", "draft_text", "citations", "decision_state", "generated_at"}
        assert body["case_id"] == str(case.id)
        assert body["draft_text"] == "Recommended action: reissue the licence key."
        assert body["decision_state"] == "approved"
        assert response.headers.get("X-Trace-Id")
    finally:
        _cleanup(engine, case_ids)


def test_stale_if_match_returns_409_with_contract_error_body():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        # expire_on_commit=False: case.id / version_token stay readable after
        # commit + session close (same fix Task 15's correlation.py needed).
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(session, "Approve me twice.")
            case_ids.append(case.id)
            token = proposed_action.version_token
            session.commit()

        first = client.post(
            f"/api/v1/cases/{case.id}/decision",
            json={"action": "approve"},
            headers=_headers(token),
        )
        assert first.status_code == 200

        # Second reviewer, stale token, new idempotency key -> contract 409.
        second = client.post(
            f"/api/v1/cases/{case.id}/decision",
            json={"action": "approve"},
            headers=_headers(token),
        )

        assert second.status_code == 409, second.text
        body = second.json()
        assert body["error"] == "already_decided"
        assert set(body) >= {"error", "by", "at"}
        assert body["by"] == "smoke-test"
    finally:
        _cleanup(engine, case_ids)


def test_reject_with_short_note_returns_422_with_contract_error_body():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []
    try:
        # expire_on_commit=False: case.id / version_token stay readable after
        # commit + session close (same fix Task 15's correlation.py needed).
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(session, "Reject me.")
            case_ids.append(case.id)
            token = proposed_action.version_token
            session.commit()

        response = client.post(
            f"/api/v1/cases/{case.id}/decision",
            json={"action": "reject", "note": "nope"},  # < 10 chars
            headers=_headers(token),
        )

        assert response.status_code == 422, response.text
        assert response.json() == {"field": "reject_reason", "min": 10}
    finally:
        _cleanup(engine, case_ids)
