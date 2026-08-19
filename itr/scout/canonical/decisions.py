"""
Task 20 — record the human decision.

The approval record is the object that authorises an external effect,
and it must exist durably and independently of whether a write later
succeeds. This is the first of the two state machines from Task 10
(recommendation_decision vs write_execution) — recording an approval
is NOT the same event as a write succeeding.

No HTTP here: VersionConflictError and ValidationError are typed
exceptions the caller (scout/api/routes/decisions.py, pre-built ahead
of Task 24's API app) translates into HTTP response shapes.

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import difflib
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.models import DecisionState, ProposedAction, RecommendationDecision
from scout.config import settings
from scout.governance.audit import write as audit_write

TENANT_ID = uuid.UUID(str(settings.tenant_id))

_STATE_BY_ACTION = {
    "approve": DecisionState.APPROVED,
    "approve_edited": DecisionState.EDITED_APPROVED,
    "reject": DecisionState.REJECTED,
}

_MIN_REJECT_REASON_LENGTH = 10

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


class VersionConflictError(Exception):
    """if_match didn't match the proposed action's current version_token.

    Carries exactly the three pieces of information the eventual HTTP
    409 body needs: error, by, at.
    """

    def __init__(self, error: str, by: str | None, at: datetime | None):
        self.error = error
        self.by = by
        self.at = at
        super().__init__(f"{error} (by={by!r}, at={at!r})")


class ValidationError(Exception):
    """A field-level validation failure (e.g. reject_reason too short).

    Carries exactly the two pieces of information the eventual HTTP
    422 body needs: field, min.
    """

    def __init__(self, field: str, min: int):
        self.field = field
        self.min = min
        super().__init__(f"{field} must be at least {min} characters")


def _latest_proposed_action(session: Session, case_id: uuid.UUID) -> ProposedAction | None:
    return session.execute(
        select(ProposedAction)
        .where(ProposedAction.case_id == case_id, ProposedAction.tenant_id == TENANT_ID)
        .order_by(ProposedAction.version.desc(), ProposedAction.observed_at.desc())
    ).scalars().first()


def _latest_decision_for_proposed_action(
    session: Session, proposed_action_id: uuid.UUID
) -> RecommendationDecision | None:
    return session.execute(
        select(RecommendationDecision)
        .where(
            RecommendationDecision.proposed_action_id == proposed_action_id,
            RecommendationDecision.tenant_id == TENANT_ID,
        )
        .order_by(RecommendationDecision.decided_at.desc())
    ).scalars().first()


def _existing_decision_by_idempotency_key(
    session: Session, idempotency_key: str
) -> RecommendationDecision | None:
    return session.execute(
        select(RecommendationDecision).where(
            RecommendationDecision.tenant_id == TENANT_ID,
            RecommendationDecision.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def _decision_to_dict(decision: RecommendationDecision, replay: bool) -> dict:
    return {
        "id": decision.id,
        "state": decision.state,
        "case_id": decision.case_id,
        "actor": decision.actor,
        "decided_at": decision.decided_at,
        "version_token": decision.version_token,
        "replay": replay,
    }


def submit_decision(
    case_id: uuid.UUID,
    action: str,
    payload: dict,
    idempotency_key: str,
    if_match: str,
    actor: str,
) -> dict:
    """Record a human decision (approve / approve_edited / reject) on a
    case's current proposed action.

    Preconditions, checked in this exact order:
      1. idempotency_key replay: an existing decision with this exact
         key is returned unchanged — no new row, no error, and
         crucially no version check either. A replay must always
         succeed regardless of the proposed action's current
         version_token, since that's the whole point of an
         idempotency key.
      2. Only for a genuinely new idempotency_key: if_match must equal
         the proposed action's current version_token, or
         VersionConflictError is raised.
      3. action == "reject" requires payload["reject_reason"] to be at
         least 10 characters after stripping, or ValidationError is
         raised.

    On a successful (non-replay) decision, the proposed action's
    version_token is replaced with a fresh one in the same
    transaction. This is what makes the version check actually
    prevent two conflicting decisions: without it, a second reviewer's
    stale if_match would still match after the first reviewer's
    decision, and the check would never fire.

    On success: the audit row is written BEFORE any dispatch attempt
    (explicit ordering requirement). dispatch_write() (Task 22) is
    imported lazily since it doesn't exist in this workspace yet — a
    missing Task 22 logs a message and does not fail this call.
    """
    if action not in _STATE_BY_ACTION:
        raise ValueError(f"Unknown action {action!r} — must be one of {sorted(_STATE_BY_ACTION)}")

    engine = _get_engine()

    with Session(engine, expire_on_commit=False) as session:
        proposed_action = _latest_proposed_action(session, case_id)
        if proposed_action is None:
            raise ValueError(f"No proposed_action found for case_id {case_id}")

        # Step 1 — idempotency replay, checked FIRST. A true replay must
        # succeed unconditionally, without ever consulting version state.
        existing = _existing_decision_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return _decision_to_dict(existing, replay=True)

        # Step 2 — version check. Only reached for a genuinely new
        # idempotency_key.
        if if_match != proposed_action.version_token:
            last_decision = _latest_decision_for_proposed_action(session, proposed_action.id)
            raise VersionConflictError(
                error="already_decided",
                by=last_decision.actor if last_decision is not None else None,
                at=last_decision.decided_at if last_decision is not None else None,
            )

        # Step 3 — reject_reason validation.
        if action == "reject":
            reject_reason = str(payload.get("reject_reason") or "").strip()
            if len(reject_reason) < _MIN_REJECT_REASON_LENGTH:
                raise ValidationError(field="reject_reason", min=_MIN_REJECT_REASON_LENGTH)

        state = _STATE_BY_ACTION[action]
        now = datetime.now(timezone.utc)

        edited_text: str | None = None
        edit_diff: dict | None = None
        reject_reason_value: str | None = None

        if action == "approve":
            hashed_text = proposed_action.recommended_action_text
        elif action == "approve_edited":
            edited_text = payload["edited_text"]
            hashed_text = edited_text
            diff_lines = list(
                difflib.unified_diff(
                    proposed_action.recommended_action_text.splitlines(keepends=True),
                    edited_text.splitlines(keepends=True),
                    fromfile="recommended_action_text",
                    tofile="edited_text",
                )
            )
            edit_diff = {"lines": diff_lines}
        else:  # reject
            reject_reason_value = str(payload.get("reject_reason") or "").strip()
            # No single "final approved text" exists for a rejection — the
            # spec doesn't fully disambiguate what payload_hash should
            # cover here, so this hashes the reject_reason instead, since
            # that's the substantive content of a reject decision.
            hashed_text = reject_reason_value

        payload_hash = hashlib.sha256(hashed_text.encode("utf-8")).hexdigest()
        version_token = str(uuid.uuid4())

        decision = RecommendationDecision(
            id=uuid.uuid4(),
            case_id=case_id,
            proposed_action_id=proposed_action.id,
            state=state.value,
            edited_text=edited_text,
            edit_diff=edit_diff,
            reject_reason=reject_reason_value,
            payload_hash=payload_hash,
            actor=actor,
            decided_at=now,
            version_token=version_token,
            idempotency_key=idempotency_key,
            tenant_id=TENANT_ID,
            # "console" — this row's data originates from a human decision
            # made via the console/API, not any source connector.
            source_system="console",
            is_synthetic=False,
            # No `run` context is passed into submit_decision() (same
            # situation as Task 15's find_or_create_case()) — a fresh
            # connector_run_id treats this call as its own run.
            connector_run_id=uuid.uuid4(),
            observed_at=now,
            valid_from=now,
        )
        session.add(decision)

        # Consume the proposed action's version: a fresh token means a
        # second reviewer's stale if_match will correctly conflict on
        # their next attempt. Without this, the version check above
        # would never actually fire — two reviewers could both submit
        # against the same unchanged token.
        proposed_action.version_token = str(uuid.uuid4())

        session.commit()

    # Audit BEFORE dispatch — explicit ordering requirement from the spec.
    audit_write(
        actor=actor,
        action="submit_decision",
        category="approval",
        case_id=case_id,
        inputs={"action": action, "idempotency_key": idempotency_key},
        outputs={"decision_id": str(decision.id), "state": decision.state},
    )

    if action in ("approve", "approve_edited"):
        try:
            from scout.canonical.execution import dispatch_write  # Task 22 — lazy, may not exist yet

            dispatch_write(decision.id)
        except ImportError:
            print(
                "[decisions] Task 22 not yet implemented — decision recorded, dispatch skipped"
            )

    return _decision_to_dict(decision, replay=False)
