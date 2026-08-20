"""
Task 24, Part E — recommendation + write-execution routes.

    GET  /cases/{id}/recommendation          -> Recommendation
    GET  /cases/{id}/write-execution         -> {case_id, state, attempts, last_error}
    POST /cases/{id}/write-execution/refire  -> {case_id, state} | 409 | 422

All three call into or read what Tasks 19b/20/22 already built — nothing
reimplemented. refire() is scout.canonical.execution.refire, verbatim.

LAYERING NOTE: scout/canonical/execution.py holds the project's ONE
sanctioned GmailAdapter load (dynamic, inside a function body). This module
calls execution.py's FUNCTIONS and imports nothing from scout.gmail /
scout.connectors / googleapiclient itself.

Documented bridges, same pattern as Parts B/C/D:
1. GET recommendation does NOT reuse Part A's _compose_recommendation():
   that helper takes a decision_id and presumes a decision exists (it runs
   after a successful POST). This GET must work BEFORE any human decision —
   decision_state falls back to the ProposedAction's own status, and
   "draft_pending" is a legal DecisionState value, so the contract shape
   holds in both worlds. With a decision: draft_text prefers edited_text,
   generated_at is decided_at. Without: recommended_action_text/observed_at.
2. contract `last_error` <- model column `error`.
3. A real case with NO WriteExecution row yet returns state "not_started"
   (that is exactly what WriteState's not_started means); an unknown case
   id returns 404 (contract defines only 200 here; documented).
4. If-Match is accepted-but-unchecked on refire — WriteExecution rows carry
   no version token (Part C's bridge for queue rows, same reasoning). The
   honest 409 is RefireNotAllowedError -> {error: "refire_not_allowed",
   by, at} built from the latest row's provenance.
5. The optional request-body `reason` is accepted and ignored: refire()
   takes (case_id, actor) only, and threading a reason through would mean
   modifying Task 22. Recorded as a gap for a Task 22 revision.
6. The write-execution read also carries `suppressed_reason` as an extra
   key (the contract object does not forbid additional properties):
   under ACTION_MODE=draft_only a suppressed write IS the correct MVP
   Phase 1 outcome, and the console needs to show why nothing was sent —
   suppression is surfaced plainly, never treated as an error.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.api.deps import get_actor, get_db_session, get_tenant_id
from scout.api.schemas import Recommendation
from scout.canonical.execution import RefireNotAllowedError, refire
from scout.canonical.models import (
    Case,
    ProposedAction,
    RecommendationDecision,
    WriteExecution,
)

router = APIRouter()


class RefireRequest(BaseModel):
    """POST .../refire requestBody (optional) — contract-exact."""

    reason: str | None = None  # accepted, ignored — bridge 5


def _require_case(session: Session, case_id: uuid.UUID, tenant_id: uuid.UUID) -> Case:
    case = session.get(Case, case_id)
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="case not found")
    return case


def _latest_proposed_action(session: Session, case_id: uuid.UUID, tenant_id) -> ProposedAction | None:
    # Same ordering decisions.py's private helper uses (version DESC, observed_at DESC).
    return session.execute(
        select(ProposedAction)
        .where(ProposedAction.case_id == case_id, ProposedAction.tenant_id == tenant_id)
        .order_by(ProposedAction.version.desc(), ProposedAction.observed_at.desc())
    ).scalars().first()


def _latest_write_execution(session: Session, case_id: uuid.UUID, tenant_id) -> WriteExecution | None:
    # Same ordering execution.py's private helper uses (observed_at DESC).
    return session.execute(
        select(WriteExecution)
        .where(WriteExecution.case_id == case_id, WriteExecution.tenant_id == tenant_id)
        .order_by(WriteExecution.observed_at.desc())
    ).scalars().first()


@router.get("/cases/{id}/recommendation", response_model=Recommendation)
def get_case_recommendation(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> Any:
    _require_case(session, id, tenant_id)
    proposed_action = _latest_proposed_action(session, id, tenant_id)
    if proposed_action is None:
        raise HTTPException(status_code=404, detail="no recommendation for this case yet")

    decision = session.execute(
        select(RecommendationDecision)
        .where(RecommendationDecision.proposed_action_id == proposed_action.id)
        .order_by(RecommendationDecision.decided_at.desc())
    ).scalars().first()

    if decision is not None:  # bridge 1 — post-decision shape
        draft_text = decision.edited_text or proposed_action.recommended_action_text
        decision_state = str(getattr(decision.state, "value", decision.state))
        generated_at = decision.decided_at
    else:  # bridge 1 — pre-decision shape
        draft_text = proposed_action.recommended_action_text
        decision_state = proposed_action.status  # "draft_pending" is a DecisionState value
        generated_at = proposed_action.observed_at

    return Recommendation(
        case_id=proposed_action.case_id,
        draft_text=draft_text,
        citations=list(proposed_action.evidence or []),
        decision_state=decision_state,
        generated_at=generated_at,
    )


@router.get("/cases/{id}/write-execution")
def get_case_write_execution(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> dict[str, Any]:
    _require_case(session, id, tenant_id)
    row = _latest_write_execution(session, id, tenant_id)

    if row is None:  # bridge 3 — nothing dispatched yet IS not_started
        return {"case_id": str(id), "state": "not_started", "attempts": 0, "last_error": None}

    return {
        "case_id": str(id),
        "state": str(getattr(row.state, "value", row.state)),
        "attempts": row.attempts,
        "last_error": row.error,  # bridge 2 — contract name for the error column
        "suppressed_reason": row.suppressed_reason,  # bridge 6 — draft_only visibility
        "execution_ref": row.execution_ref,
    }


@router.post(
    "/cases/{id}/write-execution/refire",
    responses={409: {"description": "Conflict"}, 422: {"description": "Unprocessable Entity"}},
)
def refire_write_execution(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    body: RefireRequest | None = None,
    idempotency_key: str = Header(alias="Idempotency-Key"),  # required per contract
    if_match: str = Header(alias="If-Match"),  # required per contract; bridge 4
    actor: str = Depends(get_actor),
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> Any:
    _require_case(session, id, tenant_id)

    try:
        # Task 22's refire, verbatim: legal only from state='failed', reuses
        # the SAME decision_id, never creates a second decision row.
        execution = refire(id, actor)
    except RefireNotAllowedError:
        latest = _latest_write_execution(session, id, tenant_id)
        return JSONResponse(
            status_code=409,
            content={
                "error": "refire_not_allowed",
                "by": actor,
                "at": latest.observed_at.isoformat() if latest is not None else None,
            },
        )

    return {"case_id": str(id), "state": str(getattr(execution.state, "value", execution.state))}
