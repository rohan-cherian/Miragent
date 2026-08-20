"""
Task 24, Part B — cases routes: GET /cases, /cases/{id}/360, /cases/{id}/timeline.

The contract defines NO bare GET /cases/{id} — the single-case detail view is
/cases/{id}/360 (free-shape object, additionalProperties: true). All three
routes are read-only queries against itr360.case_ / person / case_event.

Two contract-to-schema mappings, documented rather than silent:
* Case.requester (required string in the contract) <- person.display_name via
  case_.requester_id; an unresolved requester (NULL requester_id, Task 14's
  unresolved band) maps to "" — the contract field is required and
  non-nullable, and an empty string is honest "unknown".
* Case.updated_at (required in the contract) has no direct column —
  itr360.case_ carries opened_at / closed_at / observed_at. created_at <-
  opened_at, updated_at <- observed_at (the provenance "last seen" stamp).

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.api.deps import get_db_session, get_tenant_id
from scout.api.schemas import Case as CaseDTO
from scout.canonical.models import Case, CaseEvent, Message, Person, ProposedAction, TriageResult

router = APIRouter()


def _requester_name(session: Session, requester_id: uuid.UUID | None) -> str:
    if requester_id is None:
        return ""
    person = session.get(Person, requester_id)
    return person.display_name if person is not None else ""


def _to_case_dto(session: Session, case: Case) -> CaseDTO:
    return CaseDTO(
        id=case.id,
        status=str(getattr(case.status, "value", case.status)),
        subject=case.subject,
        requester=_requester_name(session, case.requester_id),
        created_at=case.opened_at,
        updated_at=case.observed_at,
    )


@router.get("/cases", response_model=list[CaseDTO])
def list_cases(
    status: str | None = None,  # contract query param, CaseStatus enum values
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> Any:
    statement = (
        select(Case)
        .where(Case.tenant_id == tenant_id)
        .order_by(Case.opened_at.desc())
    )
    if status is not None:
        statement = statement.where(Case.status == status)
    cases = session.execute(statement).scalars().all()
    return [_to_case_dto(session, case) for case in cases]


@router.get("/cases/{id}/360")
def get_case_360(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Free-shape per the contract (additionalProperties: true): the case, its
    requester, message count, latest triage and latest proposed action."""
    case = session.get(Case, id)
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="case not found")

    message_count = len(
        session.execute(select(Message.id).where(Message.case_id == id)).all()
    )
    latest_triage = session.execute(
        select(TriageResult)
        .where(TriageResult.case_id == id)
        .order_by(TriageResult.version.desc(), TriageResult.observed_at.desc())
    ).scalars().first()
    latest_action = session.execute(
        select(ProposedAction)
        .where(ProposedAction.case_id == id)
        .order_by(ProposedAction.version.desc(), ProposedAction.observed_at.desc())
    ).scalars().first()

    return {
        "case": _to_case_dto(session, case).model_dump(mode="json"),
        "case_number": case.case_number,
        "priority": case.priority,
        "intent_class": case.intent_class,
        "reopened_count": case.reopened_count,
        "related_case_ids": [str(cid) for cid in (case.related_case_ids or [])],
        "message_count": message_count,
        "latest_triage": (
            {
                "band": str(getattr(latest_triage.band, "value", latest_triage.band)),
                "category": latest_triage.category,
                "intent_class": latest_triage.intent_class,
                "confidence": float(latest_triage.confidence),
                "tier_used": latest_triage.tier_used,
            }
            if latest_triage is not None
            else None
        ),
        "latest_proposed_action": (
            {
                "id": str(latest_action.id),
                "status": latest_action.status,
                "risk": latest_action.risk,
                "confidence": (
                    float(latest_action.confidence)
                    if latest_action.confidence is not None
                    else None
                ),
            }
            if latest_action is not None
            else None
        ),
    }


@router.get("/cases/{id}/timeline")
def get_case_timeline(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> list[dict[str, Any]]:
    """itr360.case_event rows, oldest first — free-shape per the contract."""
    case = session.get(Case, id)
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="case not found")

    events = session.execute(
        select(CaseEvent).where(CaseEvent.case_id == id).order_by(CaseEvent.occurred_at.asc())
    ).scalars().all()
    return [
        {
            "id": str(event.id),
            "event_type": event.event_type,
            "payload": event.payload,
            "occurred_at": event.occurred_at.isoformat(),
            "actor": event.actor,
        }
        for event in events
    ]
