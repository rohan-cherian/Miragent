"""
scout/api/routes/vendor_onboarding.py — Sprint 67: Vendor Onboarding Agent API

Endpoints:
  GET  /vendor-onboarding/status      → lookup vendor onboarding status by email
  POST /vendor-onboarding/initiate    → initiate a new vendor onboarding workflow
  GET  /vendor-onboarding/in-progress → all vendors actively in process
  GET  /vendor-onboarding/blocked     → on_hold + stalled vendors (> 14 days)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.vendor_onboarding_agent import VendorOnboardingAgent, VendorOnboardingRecord
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vendor-onboarding", tags=["vendor-onboarding-agent"])

_agent = VendorOnboardingAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class VendorOnboardingRecordResponse(BaseModel):
    vendor_id: str
    vendor_name: str
    vendor_email: str
    stage: str
    entity_type: str
    ein: str | None
    bank_info: str | None
    hold_reason: str | None
    submitted_date: str | None
    completed_date: str | None
    days_in_process: int
    checklist: list[str]
    next_step: str
    internal_contact: str
    confirmation_message: str
    is_stalled: bool


class InitiateOnboardingBody(BaseModel):
    vendor_name: str
    vendor_email: str
    entity_type: str
    tenant_id: str


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(record: VendorOnboardingRecord) -> VendorOnboardingRecordResponse:
    return VendorOnboardingRecordResponse(
        vendor_id=record.vendor_id,
        vendor_name=record.vendor_name,
        vendor_email=record.vendor_email,
        stage=record.stage,
        entity_type=record.entity_type,
        ein=record.ein,
        bank_info=record.bank_info,
        hold_reason=record.hold_reason,
        submitted_date=record.submitted_date,
        completed_date=record.completed_date,
        days_in_process=record.days_in_process,
        checklist=record.checklist,
        next_step=record.next_step,
        internal_contact=record.internal_contact,
        confirmation_message=record.confirmation_message,
        is_stalled=record.is_stalled,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/status", response_model=VendorOnboardingRecordResponse)
def get_vendor_status(
    vendor_email: str = Query(...),
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VendorOnboardingRecordResponse:
    """
    Look up a vendor's onboarding status by email.

    Returns the full onboarding record including stage, checklist of remaining
    items, confirmation message, days in process, and internal contact.
    """
    record = _agent.get_status(vendor_email, tenant_id, db)

    logger.info(
        "VendorOnboarding status email=%s tenant=%s stage=%s",
        vendor_email,
        tenant_id,
        record.stage,
    )

    return _to_response(record)


@router.post("/initiate", response_model=VendorOnboardingRecordResponse)
def initiate_onboarding(
    body: InitiateOnboardingBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> VendorOnboardingRecordResponse:
    """
    Initiate a new vendor onboarding workflow.

    Creates a new vendor record at stage=initiated and returns the full
    onboarding record with checklist and next steps.
    """
    record = _agent.initiate_onboarding(
        vendor_name=body.vendor_name,
        vendor_email=body.vendor_email,
        entity_type=body.entity_type,
        tenant_id=body.tenant_id,
        db=db,
    )

    logger.info(
        "VendorOnboarding initiate vendor=%s email=%s entity=%s tenant=%s",
        body.vendor_name,
        body.vendor_email,
        body.entity_type,
        body.tenant_id,
    )

    return _to_response(record)


@router.get("/in-progress", response_model=list[VendorOnboardingRecordResponse])
def get_in_progress(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VendorOnboardingRecordResponse]:
    """
    Return all vendors actively in the onboarding pipeline.

    Covers stages: initiated, w9_requested, w9_received, banking_requested,
    banking_received, erp_setup. Does not include active or on_hold vendors.
    """
    records = _agent.get_all_in_progress(tenant_id, db)

    logger.info(
        "VendorOnboarding in-progress tenant=%s count=%d",
        tenant_id,
        len(records),
    )

    return [_to_response(r) for r in records]


@router.get("/blocked", response_model=list[VendorOnboardingRecordResponse])
def get_blocked(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[VendorOnboardingRecordResponse]:
    """
    Return all on_hold vendors plus stalled vendors (> 14 days in process,
    not yet active or on_hold).

    Used to surface the "Needs Attention" section of the pipeline dashboard.
    """
    records = _agent.get_blocked(tenant_id, db)

    logger.info(
        "VendorOnboarding blocked tenant=%s count=%d",
        tenant_id,
        len(records),
    )

    return [_to_response(r) for r in records]
