"""
Task 24, Part D — GET /cases/{id}/triage -> TriageResult (contract shape).

READS the latest persisted itr360.triage_result row — it does NOT call
scout.agents.triage.triage() live. Chosen deliberately: the contract path is
a GET described as "Triage result for a case" (a read), triage runs in the
ingestion pipeline (Task 19a), and a live call would spend an LLM request
per console page-load. The freshest row (version DESC — one row per model
call, escalation = version 2) is the case's current triage.

Documented bridges (contract <-> itr360.triage_result), same pattern as B/C:
* reasons[]   <- [rationale]  (the model's quoted-evidence explanation; the
                 row has no separate reasons array)
* citations[] <- []           (triage persists evidence_spans — character
                 offsets into the message — not Citation DTOs; an empty
                 list is honest, inventing DTOs from offsets is not)
* generated_at <- observed_at (provenance stamp of the triage row)
* no triage row yet -> 404 (contract defines only 200; documented)

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
from scout.api.schemas import TriageResult as TriageResultDTO
from scout.canonical.models import TriageResult

router = APIRouter()


@router.get("/cases/{id}/triage", response_model=TriageResultDTO)
def get_case_triage(
    id: uuid.UUID,  # noqa: A002 — contract PathId
    session: Session = Depends(get_db_session),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> Any:
    row = session.execute(
        select(TriageResult)
        .where(TriageResult.case_id == id, TriageResult.tenant_id == tenant_id)
        .order_by(TriageResult.version.desc(), TriageResult.observed_at.desc())
    ).scalars().first()

    if row is None:
        raise HTTPException(status_code=404, detail="no triage result for this case")

    return TriageResultDTO(
        case_id=row.case_id,
        band=str(getattr(row.band, "value", row.band)),
        confidence=float(row.confidence),
        reasons=[row.rationale] if row.rationale else [],
        citations=[],  # bridge — see module docstring
        generated_at=row.observed_at,
    )
