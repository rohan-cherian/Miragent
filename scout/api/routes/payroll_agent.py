"""
scout/api/routes/payroll_agent.py — Sprint 61: Payroll Document Agent API

Endpoints:
  POST /agents/payroll/request              → submit a document request (self-service)
  GET  /agents/payroll/requests             → list own request history
  GET  /agents/payroll/requests/{id}        → get one request with full document

All endpoints require JWT auth. Employees can only retrieve their own documents —
the requesting user's email is used as the employee_email automatically.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.agents.payroll_agent import PayrollDocumentAgent
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import PayrollRequest, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/payroll", tags=["payroll-agent"])

_agent = PayrollDocumentAgent()


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PayrollRequestBody(BaseModel):
    document_type: str   # w2 | paystub | 1099 | ytd
    period: str          # "2025", "latest", or ISO date
    tenant_id: str


class PayrollRequestResponse(BaseModel):
    request_id: str
    status: str
    document_type: str
    period: str
    document: dict | None
    error: str | None
    completed_at: str | None
    created_at: str


class PayrollRequestSummary(BaseModel):
    id: str
    document_type: str
    period: str
    status: str
    created_at: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/request", response_model=PayrollRequestResponse)
def request_payroll_document(
    body: PayrollRequestBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PayrollRequestResponse:
    """
    Submit a payroll document request.

    The agent uses the authenticated user's email as the employee_email —
    employees can only retrieve their own documents.
    """
    _validate_document_type(body.document_type)

    request_id = str(uuid.uuid4())
    employee_email = current_user.email

    # Create a pending DB row immediately
    db_row = PayrollRequest(
        id=request_id,
        tenant_id=body.tenant_id,
        requested_by=employee_email,
        document_type=body.document_type,
        period=body.period,
        status="pending",
    )
    db.add(db_row)
    db.commit()

    # Run the agent synchronously
    result = _agent.run(
        employee_email=employee_email,
        document_type=body.document_type,
        period=body.period,
        tenant_id=body.tenant_id,
        request_id=request_id,
    )

    # Update the DB row with the result
    db_row.status = result.status
    db_row.result_json = result.document
    db_row.error = result.error
    db_row.completed_at = result.completed_at
    db.commit()
    db.refresh(db_row)

    logger.info(
        "Payroll request %s: user=%s type=%s period=%s status=%s",
        request_id, employee_email, body.document_type, body.period, result.status,
    )

    return PayrollRequestResponse(
        request_id=request_id,
        status=result.status,
        document_type=body.document_type,
        period=body.period,
        document=result.document,
        error=result.error,
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
        created_at=db_row.created_at.isoformat(),
    )


@router.get("/requests", response_model=list[PayrollRequestSummary])
def list_payroll_requests(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PayrollRequestSummary]:
    """
    List payroll document requests for the current user.

    Only returns requests belonging to the authenticated user — no cross-employee access.
    """
    rows = db.execute(
        select(PayrollRequest)
        .where(
            PayrollRequest.tenant_id == tenant_id,
            PayrollRequest.requested_by == current_user.email,
        )
        .order_by(PayrollRequest.created_at.desc())
        .limit(50)
    ).scalars().all()

    return [
        PayrollRequestSummary(
            id=r.id,
            document_type=r.document_type,
            period=r.period,
            status=r.status,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/requests/{request_id}", response_model=PayrollRequestResponse)
def get_payroll_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PayrollRequestResponse:
    """
    Get a single payroll request with the full document payload.

    Enforces ownership — a user can only fetch their own requests.
    """
    row = db.get(PayrollRequest, request_id)
    if not row:
        raise HTTPException(status_code=404, detail="Payroll request not found.")

    # Ownership check — employees only see their own documents
    if row.requested_by != current_user.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this payroll request.",
        )

    return PayrollRequestResponse(
        request_id=row.id,
        status=row.status,
        document_type=row.document_type,
        period=row.period,
        document=row.result_json,
        error=row.error,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        created_at=row.created_at.isoformat(),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_document_type(doc_type: str) -> None:
    allowed = {"w2", "paystub", "1099", "ytd"}
    if doc_type not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"document_type must be one of {sorted(allowed)}. Got: {doc_type!r}",
        )
