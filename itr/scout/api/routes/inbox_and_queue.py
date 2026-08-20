"""
Task 24, Part F — the final two backable contract paths.

    GET /inbox  -> Case[]   "Unified inbox view"
    GET /queue  -> Case[]   "Human triage / review queue"

The contract defines NO query parameters on either — the distinction is
semantic, so it is pinned here rather than guessed per-call:

* /inbox — every tenant case, opened_at DESC. The Slice-1 spec's demo
  mapping backs this path with "itr360.case_ + latest message" for the
  Incoming Signal (email list) screen: it is the arrival view, unfiltered.
  It differs from GET /cases only in accepting no ?status= param.
* /queue — cases needing a HUMAN right now, which is richer than a status
  filter (the contract's summary says "triage / review"):
      latest itr360.triage_result row banded 'needs_human_triage'
      OR an itr360.proposed_action row in status 'draft_pending'
  Both conditions are EXISTS subqueries against real Task 10 tables.
  Band/status literals are taken from scout.canonical.models' enums
  (TriageBand.NEEDS_HUMAN_TRIAGE / DecisionState.DRAFT_PENDING), never
  free-typed strings.

The Case DTO shaping is cases.py's _to_case_dto(), imported — one mapper,
no drift between /cases, /inbox and /queue.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from scout.api.deps import get_db_session, get_tenant_id
from scout.api.routes.cases import _to_case_dto
from scout.api.schemas import Case as CaseDTO
from scout.canonical.models import (
    Case,
    DecisionState,
    ProposedAction,
    TriageBand,
    TriageResult,
)

router = APIRouter()


@router.get("/inbox", response_model=list[CaseDTO])
def list_inbox(
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> Any:
    cases = session.execute(
        select(Case).where(Case.tenant_id == tenant_id).order_by(Case.opened_at.desc())
    ).scalars().all()
    return [_to_case_dto(session, case) for case in cases]


@router.get("/queue", response_model=list[CaseDTO])
def list_queue(
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> Any:
    needs_human_triage = exists(
        select(TriageResult.id).where(
            TriageResult.case_id == Case.id,
            TriageResult.band == TriageBand.NEEDS_HUMAN_TRIAGE.value,
        )
    )
    awaiting_decision = exists(
        select(ProposedAction.id).where(
            ProposedAction.case_id == Case.id,
            ProposedAction.status == DecisionState.DRAFT_PENDING.value,
        )
    )
    cases = session.execute(
        select(Case)
        .where(Case.tenant_id == tenant_id, needs_human_triage | awaiting_decision)
        .order_by(Case.opened_at.desc())
    ).scalars().all()
    return [_to_case_dto(session, case) for case in cases]
