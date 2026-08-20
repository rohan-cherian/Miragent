"""
Task 24, Part A — the decisions route, wrapping the pre-built Task 20 logic.

scout/api/routes/decisions.py (untouched) owns the call into
scout.canonical.decisions.submit_decision() and returns either the decision
dict or one of two HTTP-error-shaped dicts. This module is transport only:
parse the contract's request, map its vocabulary onto the backend's, call
handle_submit_decision(), and shape the contract's response.

Three deliberate contract-to-backend bridges, all owned HERE (neither the
frozen contract nor decisions.py changes):

1. action "edit" (contract enum) -> "approve_edited" (backend vocabulary).
2. body "note" -> payload["reject_reason"] for reject: the contract carries
   no reject_reason field, and the backend's 422 rule (min 10 chars) reads
   reject_reason. The 422 body still names "reject_reason", matching the
   contract's Error422 {field, min} shape.
3. The contract's 200 body is a Recommendation, not the decision record —
   composed by reading the persisted decision row and its ProposedAction
   (read-only; importing scout.canonical.models is layering-legal).

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from scout.api.deps import get_actor, get_db_session
from scout.api.routes.decisions import handle_submit_decision
from scout.api.schemas import DecisionRequest, Recommendation
from scout.canonical.models import ProposedAction, RecommendationDecision

router = APIRouter()

# Contract enum -> scout.canonical.decisions._STATE_BY_ACTION vocabulary.
_ACTION_MAP = {"approve": "approve", "reject": "reject", "edit": "approve_edited"}


def _compose_recommendation(
    session: Session, decision_id: uuid.UUID
) -> Recommendation:
    """The contract's 200 body, built from the rows submit_decision() wrote."""
    decision = session.get(RecommendationDecision, decision_id)
    proposed_action = session.get(ProposedAction, decision.proposed_action_id)

    draft_text = decision.edited_text or proposed_action.recommended_action_text
    return Recommendation(
        case_id=decision.case_id,
        draft_text=draft_text,
        citations=list(proposed_action.evidence or []),
        decision_state=str(getattr(decision.state, "value", decision.state)),
        generated_at=decision.decided_at,
    )


@router.post(
    "/cases/{id}/decision",
    response_model=Recommendation,
    responses={409: {"description": "Conflict"}, 422: {"description": "Unprocessable Entity"}},
)
def submit_decision_route(
    id: uuid.UUID,  # noqa: A002 — the contract's PathId parameter is named `id`
    body: DecisionRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),  # required per contract
    if_match: str = Header(alias="If-Match"),  # required per contract
    actor: str = Depends(get_actor),
    session: Session = Depends(get_db_session),
) -> Any:
    payload: dict[str, Any] = {}
    if body.edited_text is not None:
        payload["edited_text"] = body.edited_text
    if body.note is not None:
        payload["note"] = body.note
        if body.action.value == "reject":
            payload["reject_reason"] = body.note  # bridge 2 (module docstring)

    result = handle_submit_decision(
        case_id=id,
        action=_ACTION_MAP[body.action.value],
        payload=payload,
        idempotency_key=idempotency_key,
        if_match=if_match,
        actor=actor,
    )

    # handle_submit_decision() returns dicts, not raises — map by shape.
    if "error" in result:  # {"error": "already_decided", "by": ..., "at": ...}
        return JSONResponse(status_code=409, content=_jsonable(result))
    if "field" in result:  # {"field": "reject_reason", "min": 10}
        return JSONResponse(status_code=422, content=_jsonable(result))

    return _compose_recommendation(session, result["id"])


def _jsonable(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else
        (str(value) if isinstance(value, uuid.UUID) else value)
        for key, value in record.items()
    }

# ── Task 24, Part B — mount the cases / connections / runs routers. ────────
# Imported at the bottom, after `router` exists, because the submodules
# attach to the same package; nothing above this line changed.
from scout.api.routes import cases as _cases  # noqa: E402
from scout.api.routes import connections as _connections  # noqa: E402
from scout.api.routes import runs as _runs  # noqa: E402

router.include_router(_cases.router)
router.include_router(_connections.router)
router.include_router(_runs.router)

# ── Task 24, Part C — identity-queue router, same append-only pattern. ─────
from scout.api.routes import identity_queue as _identity_queue  # noqa: E402

router.include_router(_identity_queue.router)

# ── Task 24, Part D — context-pack / triage / audit routers, same pattern. ─
from scout.api.routes import audit as _audit  # noqa: E402
from scout.api.routes import context as _context  # noqa: E402
from scout.api.routes import triage as _triage  # noqa: E402

router.include_router(_context.router)
router.include_router(_triage.router)
router.include_router(_audit.router)
