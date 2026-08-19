"""
Task 22 — dispatch, write state machine, and draft-only gate tests.

Skips cleanly if there's no live database available. ACTION_MODE is
monkeypatched directly on the shared scout.config.settings instance
for the duration of each test — never touches the real .env.local.
Fixture data (Case_, ProposedAction, RecommendationDecision) is
created directly, mirroring test_decisions.py's pattern, and cleaned
up afterward. decision_audit is append-only (Task 23) and never
touched, only counted.

Note: scout.gmail.adapter.GmailAdapter doesn't exist in this
workspace (Task 21 hasn't landed), so a real send can never actually
succeed here yet. The refire() test below keeps GMAIL_FORCE_SEND_FAIL
set for that reason — it proves refire() is legal and reuses the same
decision, not that a real Gmail send succeeds, which isn't achievable
in this environment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical.execution import RefireNotAllowedError, dispatch_write, refire
from scout.canonical.models import (
    Case,
    CaseStatus,
    DecisionAudit,
    ProposedAction,
    RecommendationDecision,
    WriteExecution,
)
from scout.config import settings

TENANT_ID = uuid.UUID(str(settings.tenant_id))


def _make_engine():
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        pytest.skip("No live database available — skipping execution tests")
    return engine


def _make_fixture(
    session: Session, recommended_text: str, decision_state: str = "approved"
) -> tuple[Case, ProposedAction, RecommendationDecision]:
    now = datetime.now(timezone.utc)

    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject="Test case for execution",
        status=CaseStatus.OPEN.value,
        opened_at=now,
        reopened_count=0,
        related_case_ids=[],
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
        recommended_action_text=recommended_text,
        draft_sentences=[{"text": recommended_text, "citation_refs": [], "withheld": False}],
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

    decision = RecommendationDecision(
        id=uuid.uuid4(),
        case_id=case.id,
        proposed_action_id=proposed_action.id,
        state=decision_state,
        edited_text=None,
        edit_diff=None,
        reject_reason=None,
        payload_hash="test-hash",
        actor="tester",
        decided_at=now,
        version_token=str(uuid.uuid4()),
        idempotency_key=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        source_system="test",
        is_synthetic=True,
        connector_run_id=uuid.uuid4(),
        observed_at=now,
        valid_from=now,
    )
    session.add(decision)
    session.flush()

    return case, proposed_action, decision


def _cleanup(engine, case_ids: list[uuid.UUID]) -> None:
    if not case_ids:
        return
    with Session(engine) as session:
        for row in session.execute(
            select(WriteExecution).where(WriteExecution.case_id.in_(case_ids))
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(RecommendationDecision).where(RecommendationDecision.case_id.in_(case_ids))
        ).scalars().all():
            session.delete(row)
        for row in session.execute(
            select(ProposedAction).where(ProposedAction.case_id.in_(case_ids))
        ).scalars().all():
            session.delete(row)
        for case_id in case_ids:
            case = session.get(Case, case_id)
            if case is not None:
                session.delete(case)
        session.commit()


def _count_approval_audit_rows(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(DecisionAudit).where(DecisionAudit.category == "approval")
    ).scalar_one()


def test_draft_only_suppresses_without_touching_gmail(monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr(settings, "action_mode", "draft_only")

    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action, decision = _make_fixture(
                session, "Please reset your password using the self-service portal."
            )
            audit_before = _count_approval_audit_rows(session)
            session.commit()
        case_ids.append(case.id)

        # scout.gmail.adapter doesn't exist in this workspace — if draft_only
        # somehow reached the send path, this call would raise ImportError
        # (or worse). It succeeding at all is part of the proof.
        write_execution = dispatch_write(decision.id)

        assert write_execution.state == "not_started"
        assert write_execution.suppressed_reason == "ACTION_MODE=draft_only (MVP Phase 1)"

        with Session(engine) as session:
            assert _count_approval_audit_rows(session) > audit_before
    finally:
        _cleanup(engine, case_ids)


def test_gated_execute_exhausts_retries_and_leaves_decision_untouched(monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr(settings, "action_mode", "gated_execute")
    monkeypatch.setenv("GMAIL_FORCE_SEND_FAIL", "true")

    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action, decision = _make_fixture(
                session, "Please check your VPN client version.", decision_state="approved"
            )
            session.commit()
        case_ids.append(case.id)

        write_execution = dispatch_write(decision.id)

        assert write_execution.state == "failed"
        assert write_execution.attempts == 3

        with Session(engine) as session:
            reloaded_decision = session.get(RecommendationDecision, decision.id)
            assert reloaded_decision is not None
            assert reloaded_decision.state == "approved"  # untouched by the failed write
    finally:
        _cleanup(engine, case_ids)


def test_refire_on_failed_write_is_legal_and_reuses_same_decision(monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr(settings, "action_mode", "gated_execute")
    monkeypatch.setenv("GMAIL_FORCE_SEND_FAIL", "true")

    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action, decision = _make_fixture(
                session, "Please check your invoice.", decision_state="approved"
            )
            session.commit()
        case_ids.append(case.id)

        first_attempt = dispatch_write(decision.id)
        assert first_attempt.state == "failed"

        with Session(engine) as session:
            decision_count_before = session.execute(
                select(func.count())
                .select_from(RecommendationDecision)
                .where(RecommendationDecision.case_id == case.id)
            ).scalar_one()
        assert decision_count_before == 1

        # GmailAdapter still doesn't exist in this workspace, so this
        # refire also can't genuinely succeed — GMAIL_FORCE_SEND_FAIL
        # stays set. What's under test is that refire() is legal, reuses
        # the same decision, and never creates a second one.
        refired = refire(case.id, actor="tester")

        assert refired.decision_id == decision.id

        with Session(engine) as session:
            decision_count_after = session.execute(
                select(func.count())
                .select_from(RecommendationDecision)
                .where(RecommendationDecision.case_id == case.id)
            ).scalar_one()
        assert decision_count_after == 1  # still just 1 — no second decision created
    finally:
        _cleanup(engine, case_ids)


def test_refire_when_not_failed_raises(monkeypatch):
    engine = _make_engine()
    monkeypatch.setattr(settings, "action_mode", "draft_only")

    case_ids: list[uuid.UUID] = []
    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action, decision = _make_fixture(
                session, "Some recommendation text.", decision_state="approved"
            )
            session.commit()
        case_ids.append(case.id)

        write_execution = dispatch_write(decision.id)
        assert write_execution.state == "not_started"  # NOT "failed"

        with pytest.raises(RefireNotAllowedError):
            refire(case.id, actor="tester")
    finally:
        _cleanup(engine, case_ids)
