"""
Task 24, Part D — audit routes: GET /audit, GET /audit/{id}/timeline.

Thin wrappers over Task 23's read functions — no queries reimplemented:
* /audit?target_id=X -> audit.timeline(X)  (list() has NO case filter;
  timeline() is the function built for exactly this)
* /audit (no filter)  -> audit.list()
* /audit/{id}/timeline -> audit.timeline(id)

Documented bridges (contract AuditEntry <-> itr360.decision_audit row):
* target_id (required string) <- str(case_id), or "" when the row has no
  case (e.g. identity_resolution rows are written with case_id=None — a
  known Task 23 finding); the contract field is required and non-nullable.
* at <- created_at
* details <- {category, inputs, outputs, confidence, trace_id} — the row
  fields the contract has no top-level slot for, preserved rather than
  dropped (details is additionalProperties: true).

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from scout.api.schemas import AuditEntry
from scout.governance import audit as audit_module

router = APIRouter()


def _to_entry(row: Any) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        actor=row.actor,
        action=row.action,
        target_id=str(row.case_id) if row.case_id is not None else "",
        at=row.created_at,
        details={
            "category": row.category,
            "inputs": row.inputs,
            "outputs": row.outputs,
            "confidence": float(row.confidence) if row.confidence is not None else None,
            "trace_id": row.trace_id,
        },
    )


@router.get("/audit", response_model=list[AuditEntry])
def list_audit(target_id: str | None = None) -> Any:  # contract query param
    if target_id:
        try:
            case_id = uuid.UUID(target_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="target_id must be a UUID") from exc
        rows = audit_module.timeline(case_id)
    else:
        rows = audit_module.list()
    return [_to_entry(row) for row in rows]


@router.get("/audit/{id}/timeline", response_model=list[AuditEntry])
def get_audit_timeline(id: uuid.UUID) -> Any:  # noqa: A002 — contract PathId
    return [_to_entry(row) for row in audit_module.timeline(id)]
