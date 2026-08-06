"""
scout/api/routes/it_access.py — Sprint 68: IT Access Agent API

Endpoints:
  POST /it-access/request          → submit a new IT access request
  GET  /it-access/request/{id}     → look up a request by ID
  GET  /it-access/pending          → list all pending requests
  GET  /it-access/catalog          → list all systems in the catalog
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.it_access_agent import ITAccessAgent, ITAccessResult, SYSTEM_CATALOG
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/it-access", tags=["it-access-agent"])

_agent = ITAccessAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class ITAccessResultResponse(BaseModel):
    request_id: str
    requester_email: str
    requester_name: str
    target_user_email: str
    system_key: str
    system_display_name: str
    okta_group: str
    approval_tier: str
    approver_email: str
    status: str
    submitted_date: str
    completed_date: str | None
    rejection_reason: str | None
    license_cost_monthly: float
    requires_training: bool
    training_url: str | None
    sla_days: int
    authority_verified: bool
    authority_note: str
    next_steps: list[str]


class SystemCatalogEntryResponse(BaseModel):
    system_key: str
    display_name: str
    approval_tier: str
    license_cost_monthly: float
    requires_training: bool
    okta_group: str
    owner: str


class AccessRequestBody(BaseModel):
    requester_email: str
    target_user_email: str
    system_name: str
    tenant_id: str


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(result: ITAccessResult) -> ITAccessResultResponse:
    return ITAccessResultResponse(
        request_id=result.request_id,
        requester_email=result.requester_email,
        requester_name=result.requester_name,
        target_user_email=result.target_user_email,
        system_key=result.system_key,
        system_display_name=result.system_display_name,
        okta_group=result.okta_group,
        approval_tier=result.approval_tier,
        approver_email=result.approver_email,
        status=result.status,
        submitted_date=result.submitted_date,
        completed_date=result.completed_date,
        rejection_reason=result.rejection_reason,
        license_cost_monthly=result.license_cost_monthly,
        requires_training=result.requires_training,
        training_url=result.training_url,
        sla_days=result.sla_days,
        authority_verified=result.authority_verified,
        authority_note=result.authority_note,
        next_steps=result.next_steps,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/request", response_model=ITAccessResultResponse)
def submit_access_request(
    body: AccessRequestBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ITAccessResultResponse:
    """
    Submit a new IT access provisioning request.

    Validates the system name against the catalog, verifies the requester's
    authority, determines the approval tier and routes to the correct approver.
    """
    result = _agent.submit_request(
        requester_email=body.requester_email,
        target_user_email=body.target_user_email,
        system_name=body.system_name,
        tenant_id=body.tenant_id,
        db=db,
    )

    logger.info(
        "ITAccess submit requester=%s target=%s system=%s tenant=%s status=%s tier=%s",
        body.requester_email,
        body.target_user_email,
        body.system_name,
        body.tenant_id,
        result.status,
        result.approval_tier,
    )

    return _to_response(result)


@router.get("/request/{request_id}", response_model=ITAccessResultResponse)
def get_access_request(
    request_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ITAccessResultResponse:
    """
    Look up an IT access request by its ID.

    Returns the full request record including status, next steps, and
    authority verification details.
    """
    result = _agent.get_request(request_id, tenant_id, db)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Request {request_id} not found")

    logger.info(
        "ITAccess get_request id=%s tenant=%s status=%s",
        request_id,
        tenant_id,
        result.status,
    )

    return _to_response(result)


@router.get("/pending", response_model=list[ITAccessResultResponse])
def get_pending_requests(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ITAccessResultResponse]:
    """
    Return all pending IT access requests for a tenant.

    Covers statuses: pending_manager, pending_it, pending_ciso, in_progress.
    """
    results = _agent.get_pending_queue(tenant_id, db)

    logger.info(
        "ITAccess pending tenant=%s count=%d",
        tenant_id,
        len(results),
    )

    return [_to_response(r) for r in results]


@router.get("/catalog", response_model=list[SystemCatalogEntryResponse])
def get_system_catalog(
    current_user: User = Depends(get_current_user),
) -> list[SystemCatalogEntryResponse]:
    """
    Return the full IT system catalog.

    Lists all 14 supported systems with their approval tiers, license costs,
    Okta group assignments, and training requirements.
    """
    entries = []
    for system_key, info in SYSTEM_CATALOG.items():
        entries.append(
            SystemCatalogEntryResponse(
                system_key=system_key,
                display_name=info["display_name"],
                approval_tier=info["approval_tier"],
                license_cost_monthly=float(info["license_cost_monthly"]),
                requires_training=info["requires_training"],
                okta_group=info["okta_group"],
                owner=info["owner"],
            )
        )
    return entries
