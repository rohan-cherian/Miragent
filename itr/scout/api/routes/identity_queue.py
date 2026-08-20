"""
Task 24, Part C — identity-queue routes.

The frozen contract defines exactly TWO identity-queue paths:

    GET  /identity/queue                 -> IdentityQueueItem[]
    POST /identity/queue/{qid}/resolve   -> IdentityQueueItem (200) | 409 | 422

Task 14's queue.py also exposes mark_as_new_actor() and dismiss(), and the
console will eventually need both — but the contract has NO paths for them,
and this project does not invent endpoints outside the frozen contract.
They stay reachable only from Python until the contract grows those paths
in a signed-off revision. (Recorded as a known gap, not silently skipped.)

Documented bridges (contract <-> Task 14 backend), same pattern as Part B:

1. status enum drift — itr360.identity_unresolved_queue.status is
   pending | resolved | dismissed; the contract's IdentityQueueItem.status
   is unresolved | resolved | rejected. Mapped: pending -> unresolved,
   dismissed -> rejected, resolved -> resolved.
2. resolve_as_candidate() returns None; the contract's 200 body is the
   updated item — the row is re-fetched (read-only) after the call.
3. If-Match has nothing to check against: queue rows carry no version
   token (unlike proposed_action). The header is accepted as required per
   the contract but not compared; the honest 409 is "already actioned" —
   a non-pending row returns the Conflict409 shape {error, by, at} from
   resolved_by / resolved_at. Adding real token semantics would be new
   backend logic, out of Part C's wiring-only scope.
4. An unknown qid returns 404 (the contract defines only 200/409/422 for
   this path; a 404 is still the honest answer and is documented here
   rather than smuggled into a 409).

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.api.deps import get_actor, get_db_session
from scout.api.schemas import IdentityQueueItem
from scout.canonical.identity import queue as identity_queue
from scout.canonical.models import IdentityUnresolvedQueue

router = APIRouter()

# Bridge 1 — model status -> contract enum.
_STATUS_MAP = {"pending": "unresolved", "resolved": "resolved", "dismissed": "rejected"}


class ResolveRequest(BaseModel):
    """POST /identity/queue/{qid}/resolve requestBody — contract-exact."""

    person_id: uuid.UUID


def _to_item(row: IdentityUnresolvedQueue) -> IdentityQueueItem:
    return IdentityQueueItem(
        id=row.id,
        candidate_email=str(row.sender_email),
        status=_STATUS_MAP.get(row.status, row.status),
        created_at=row.created_at,
        candidate_score=(
            float(row.best_confidence) if row.best_confidence is not None else None
        ),
    )


@router.get("/identity/queue", response_model=list[IdentityQueueItem])
def list_identity_queue() -> Any:
    """Task 14's list_pending(), verbatim — pending rows only, mapped to
    the contract's item shape (status 'unresolved')."""
    return [_to_item(row) for row in identity_queue.list_pending()]


@router.post(
    "/identity/queue/{qid}/resolve",
    response_model=IdentityQueueItem,
    responses={409: {"description": "Conflict"}, 422: {"description": "Unprocessable Entity"}},
)
def resolve_identity_queue_item(
    qid: uuid.UUID,  # contract PathQueueId
    body: ResolveRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),  # required per contract
    if_match: str = Header(alias="If-Match"),  # required per contract; see bridge 3
    actor: str = Depends(get_actor),
    session: Session = Depends(get_db_session),
) -> Any:
    row = session.get(IdentityUnresolvedQueue, qid)
    if row is None:
        raise HTTPException(status_code=404, detail="identity queue item not found")

    if row.status != "pending":
        # Bridge 3 — the honest 409: already actioned by someone.
        return JSONResponse(
            status_code=409,
            content={
                "error": "already_resolved",
                "by": row.resolved_by,
                "at": row.resolved_at.isoformat() if row.resolved_at else None,
            },
        )

    # Task 14's function does the real work: closes the row, writes the
    # verified alias (0.99), writes the audit rows. Nothing reimplemented.
    identity_queue.resolve_as_candidate(qid, body.person_id, actor)

    session.expire_all()  # Bridge 2 — re-read the row the backend just updated
    updated = session.get(IdentityUnresolvedQueue, qid)
    return _to_item(updated)
