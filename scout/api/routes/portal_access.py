"""
scout/api/routes/portal_access.py — Sprint 63: Portal Access Agent API

Endpoints:
  POST /agents/portal-access/request           → diagnose and resolve login failure
  GET  /agents/portal-access/requests          → last 20 requests for tenant
  GET  /agents/portal-access/requests/{id}     → single request with full result_json

Auth: JWT (support agent submits on behalf of customer, or customer self-serves).
The support team can see all requests for a tenant — no per-user filtering.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.agents.portal_access_agent import PortalAccessAgent
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import PortalAccessRequest, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/portal-access", tags=["portal-access-agent"])

_agent = PortalAccessAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class PortalAccessRequestBody(BaseModel):
    customer_email: str
    reported_issue: str
    tenant_id: str


class DiagnosisSchema(BaseModel):
    diagnosis_code: str
    diagnosis_text: str
    auto_resolvable: bool
    resolution_steps: list[str]
    customer_message: str
    support_instructions: str
    severity: str


class PortalAccessResultResponse(BaseModel):
    request_id: str
    customer_email: str
    reported_issue: str
    diagnosis: DiagnosisSchema | None
    auto_resolved: bool
    status: str
    error: str | None
    completed_at: str
    created_at: str


class PortalAccessRequestSummary(BaseModel):
    id: str
    customer_email: str
    reported_issue: str
    diagnosis_code: str | None
    auto_resolved: bool
    status: str
    created_at: str


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/request", response_model=PortalAccessResultResponse)
def request_portal_access(
    body: PortalAccessRequestBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortalAccessResultResponse:
    """
    Submit a portal access diagnosis request.

    The agent looks up the customer's IdP account, diagnoses the root cause,
    and either resolves it autonomously or generates support instructions.
    Low-risk cases (locked, not provisioned, MFA reset) are resolved immediately.
    High-risk cases (suspended, not found) are escalated to the support team.
    """
    request_id = str(uuid.uuid4())

    # Create pending row immediately
    db_row = PortalAccessRequest(
        id=request_id,
        tenant_id=body.tenant_id,
        submitted_by=current_user.email,
        customer_email=body.customer_email,
        reported_issue=body.reported_issue,
        status="analyzing",
    )
    db.add(db_row)
    db.commit()

    # Run the agent synchronously
    result = _agent.run(
        customer_email=body.customer_email,
        reported_issue=body.reported_issue,
        tenant_id=body.tenant_id,
        request_id=request_id,
    )

    # Persist result
    db_row.status = result.status
    db_row.auto_resolved = result.auto_resolved
    db_row.error = result.error
    db_row.completed_at = result.completed_at

    if result.diagnosis:
        db_row.diagnosis = result.diagnosis.diagnosis_text
        db_row.diagnosis_code = result.diagnosis.diagnosis_code
        db_row.resolution = result.diagnosis.support_instructions
        db_row.result_json = asdict(result.diagnosis)

    db.commit()
    db.refresh(db_row)

    logger.info(
        "PortalAccess request=%s submitted_by=%s customer=%s code=%s status=%s",
        request_id, current_user.email, body.customer_email,
        result.diagnosis.diagnosis_code if result.diagnosis else "error",
        result.status,
    )

    diagnosis_out = None
    if result.diagnosis:
        diagnosis_out = DiagnosisSchema(
            diagnosis_code=result.diagnosis.diagnosis_code,
            diagnosis_text=result.diagnosis.diagnosis_text,
            auto_resolvable=result.diagnosis.auto_resolvable,
            resolution_steps=result.diagnosis.resolution_steps,
            customer_message=result.diagnosis.customer_message,
            support_instructions=result.diagnosis.support_instructions,
            severity=result.diagnosis.severity,
        )

    return PortalAccessResultResponse(
        request_id=request_id,
        customer_email=body.customer_email,
        reported_issue=body.reported_issue,
        diagnosis=diagnosis_out,
        auto_resolved=result.auto_resolved,
        status=result.status,
        error=result.error,
        completed_at=result.completed_at.isoformat(),
        created_at=db_row.created_at.isoformat(),
    )


@router.get("/requests", response_model=list[PortalAccessRequestSummary])
def list_portal_access_requests(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PortalAccessRequestSummary]:
    """
    List portal access requests for a tenant.

    Returns all requests for the tenant (not filtered by submitter) so
    the support team has full visibility across all cases.
    """
    rows = db.execute(
        select(PortalAccessRequest)
        .where(PortalAccessRequest.tenant_id == tenant_id)
        .order_by(PortalAccessRequest.created_at.desc())
        .limit(20)
    ).scalars().all()

    return [
        PortalAccessRequestSummary(
            id=r.id,
            customer_email=r.customer_email,
            reported_issue=r.reported_issue,
            diagnosis_code=r.diagnosis_code,
            auto_resolved=r.auto_resolved,
            status=r.status,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/requests/{request_id}", response_model=PortalAccessResultResponse)
def get_portal_access_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PortalAccessResultResponse:
    """Get a single portal access request with full result payload."""
    row = db.get(PortalAccessRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Portal access request not found.")

    diagnosis_out = None
    if row.result_json:
        rj = row.result_json
        diagnosis_out = DiagnosisSchema(
            diagnosis_code=rj.get("diagnosis_code", ""),
            diagnosis_text=rj.get("diagnosis_text", ""),
            auto_resolvable=rj.get("auto_resolvable", False),
            resolution_steps=rj.get("resolution_steps", []),
            customer_message=rj.get("customer_message", ""),
            support_instructions=rj.get("support_instructions", ""),
            severity=rj.get("severity", "medium"),
        )

    return PortalAccessResultResponse(
        request_id=row.id,
        customer_email=row.customer_email,
        reported_issue=row.reported_issue,
        diagnosis=diagnosis_out,
        auto_resolved=row.auto_resolved,
        status=row.status,
        error=row.error,
        completed_at=row.completed_at.isoformat() if row.completed_at else "",
        created_at=row.created_at.isoformat(),
    )
