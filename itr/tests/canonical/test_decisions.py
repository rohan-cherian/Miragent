"""
Task 20 — decision recording tests.

Skips cleanly (not a failure) if there's no live database available.
This module depends on both Case_ and ProposedAction existing, so each
test creates a throwaway Case + ProposedAction fixture and cleans up
RecommendationDecision + ProposedAction + Case rows afterward.
decision_audit is append-only (Task 23) and never touched, only
counted.

Since Task 22 (scout/canonical/execution.py) now exists,
submit_decision()'s lazy dispatch_write() import for approve /
approve_edited actions succeeds for real, so a WriteExecution row is
now genuinely created alongside each such decision (previously that
import always failed with ImportError and was silently skipped).
RecommendationDecision.write_executions has no delete cascade
configured in models.py, so cleanup must delete WriteExecution rows
before the RecommendationDecision rows they reference, or the FK
NOT NULL constraint on write_execution.decision_id is violated.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scout.canonical.decisions import ValidationError, VersionConflictError, submit_decision
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
        pytest.skip("No live database available — skipping decision tests")
    return engine


def _make_case_and_proposed_action(
    session: Session, recommended_text: str
) -> tuple[Case, ProposedAction]:
    now = datetime.now(timezone.utc)

    case = Case(
        id=uuid.uuid4(),
        case_number=f"ITR-TEST-{uuid.uuid4().hex[:8]}",
        subject="Test case for decisions",
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

    return case, proposed_action


def _cleanup(engine, case_ids: list[uuid.UUID]) -> None:
    if not case_ids:
        return
    with Session(engine) as session:
        # WriteExecution rows must go first — write_execution.decision_id
        # is NOT NULL and has no delete cascade, so deleting a
        # RecommendationDecision first would fail (or, at the ORM level,
        # try to null out the FK, which also violates NOT NULL).
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


def test_fresh_approve_succeeds_and_writes_decision_and_audit():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []

    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(
                session, "Please reset your password using the self-service portal."
            )
            audit_before = _count_approval_audit_rows(session)
            session.commit()
        case_ids.append(case.id)

        result = submit_decision(
            case_id=case.id,
            action="approve",
            payload={},
            idempotency_key=str(uuid.uuid4()),
            if_match=proposed_action.version_token,
            actor="tester",
        )

        assert result["state"] == "approved"
        assert result["replay"] is False

        with Session(engine) as session:
            decision = session.get(RecommendationDecision, result["id"])
            assert decision is not None
            assert decision.state == "approved"
            assert decision.case_id == case.id

            assert _count_approval_audit_rows(session) > audit_before
    finally:
        _cleanup(engine, case_ids)


def test_replay_with_same_idempotency_key_returns_same_decision():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []

    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(
                session, "Please check your VPN client version."
            )
            session.commit()
        case_ids.append(case.id)

        idempotency_key = str(uuid.uuid4())

        first = submit_decision(
            case_id=case.id,
            action="approve",
            payload={},
            idempotency_key=idempotency_key,
            if_match=proposed_action.version_token,
            actor="tester",
        )
        second = submit_decision(
            case_id=case.id,
            action="approve",
            payload={},
            idempotency_key=idempotency_key,
            if_match=proposed_action.version_token,
            actor="tester",
        )

        assert first["id"] == second["id"]
        assert second["replay"] is True

        with Session(engine) as session:
            count = session.execute(
                select(func.count())
                .select_from(RecommendationDecision)
                .where(RecommendationDecision.idempotency_key == idempotency_key)
            ).scalar_one()
            assert count == 1
    finally:
        _cleanup(engine, case_ids)


def test_mismatched_if_match_raises_version_conflict():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []

    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(
                session, "Some recommendation text."
            )
            session.commit()
        case_ids.append(case.id)

        with pytest.raises(VersionConflictError) as exc_info:
            submit_decision(
                case_id=case.id,
                action="approve",
                payload={},
                idempotency_key=str(uuid.uuid4()),
                if_match="definitely-not-the-real-token",
                actor="tester",
            )

        assert exc_info.value.error == "already_decided"
        assert exc_info.value.by is None
        assert exc_info.value.at is None
    finally:
        _cleanup(engine, case_ids)


def test_reject_with_short_reason_raises_validation_error():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []

    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(
                session, "Some recommendation text."
            )
            session.commit()
        case_ids.append(case.id)

        with pytest.raises(ValidationError) as exc_info:
            submit_decision(
                case_id=case.id,
                action="reject",
                payload={"reject_reason": "no"},
                idempotency_key=str(uuid.uuid4()),
                if_match=proposed_action.version_token,
                actor="tester",
            )

        assert exc_info.value.field == "reject_reason"
        assert exc_info.value.min == 10
    finally:
        _cleanup(engine, case_ids)


def test_approve_edited_stores_diff_when_text_changes():
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []

    try:
        original_text = "Please reset your password using the self-service portal."
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(session, original_text)
            session.commit()
        case_ids.append(case.id)

        edited_text = original_text + " Then re-enable multi-factor authentication."

        result = submit_decision(
            case_id=case.id,
            action="approve_edited",
            payload={"edited_text": edited_text},
            idempotency_key=str(uuid.uuid4()),
            if_match=proposed_action.version_token,
            actor="tester",
        )

        assert result["state"] == "edited_approved"

        with Session(engine) as session:
            decision = session.get(RecommendationDecision, result["id"])
            assert decision is not None
            assert decision.edited_text == edited_text
            assert decision.edit_diff is not None
            assert len(decision.edit_diff.get("lines", [])) > 0
    finally:
        _cleanup(engine, case_ids)


def test_second_reviewer_with_stale_if_match_and_new_key_is_blocked():
    """The race the version check exists to prevent: two reviewers see
    the same version_token, the first submits (a genuinely new
    idempotency key), and a second reviewer's separate new attempt
    using that now-stale token must be rejected — not silently
    accepted as if nothing had changed."""
    engine = _make_engine()
    case_ids: list[uuid.UUID] = []

    try:
        with Session(engine, expire_on_commit=False) as session:
            case, proposed_action = _make_case_and_proposed_action(
                session, "Please check your firewall configuration."
            )
            session.commit()
        case_ids.append(case.id)

        stale_if_match = proposed_action.version_token

        first = submit_decision(
            case_id=case.id,
            action="approve",
            payload={},
            idempotency_key=str(uuid.uuid4()),
            if_match=stale_if_match,
            actor="reviewer-one",
        )
        assert first["replay"] is False

        with pytest.raises(VersionConflictError) as exc_info:
            submit_decision(
                case_id=case.id,
                action="approve",
                payload={},
                idempotency_key=str(uuid.uuid4()),  # genuinely new key — not a replay
                if_match=stale_if_match,  # same token the first reviewer used, now stale
                actor="reviewer-two",
            )

        assert exc_info.value.error == "already_decided"
        assert exc_info.value.by == "reviewer-one"
        assert exc_info.value.at is not None
    finally:
        _cleanup(engine, case_ids)
