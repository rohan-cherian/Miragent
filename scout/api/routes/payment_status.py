"""
scout/api/routes/payment_status.py — Sprint 65: Payment Status Agent API

Endpoints:
  POST /payment-status/lookup         → look up single invoice by ID
  POST /payment-status/vendor-lookup  → all invoices for a vendor email
  GET  /payment-status/stuck          → all stuck invoices with approver routing

Auth: JWT — AP team members and vendor-facing portals use these endpoints.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.payment_status_agent import PaymentStatusAgent, PaymentStatusResult
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import User, VendorInquiry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payment-status", tags=["payment-status-agent"])

_agent = PaymentStatusAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class InvoiceLookupBody(BaseModel):
    invoice_id: str
    tenant_id: str


class VendorLookupBody(BaseModel):
    vendor_email: str
    tenant_id: str


class PaymentStatusResponse(BaseModel):
    invoice_id: str
    vendor_name: str
    vendor_email: str
    amount: float
    status: str
    submitted_date: str
    payment_date: str | None
    hold_reason: str | None
    is_stuck: bool
    stuck_reason: str | None
    approver: str | None
    approver_role: str | None
    draft_response: str
    days_outstanding: int


class StuckInvoicesSummaryResponse(BaseModel):
    total_stuck: int
    on_hold: list[PaymentStatusResponse]
    overdue_review: list[PaymentStatusResponse]
    queue_delays: list[PaymentStatusResponse]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(result: PaymentStatusResult) -> PaymentStatusResponse:
    return PaymentStatusResponse(
        invoice_id=result.invoice_id,
        vendor_name=result.vendor_name,
        vendor_email=result.vendor_email,
        amount=result.amount,
        status=result.status,
        submitted_date=result.submitted_date,
        payment_date=result.payment_date,
        hold_reason=result.hold_reason,
        is_stuck=result.is_stuck,
        stuck_reason=result.stuck_reason,
        approver=result.approver,
        approver_role=result.approver_role,
        draft_response=result.draft_response,
        days_outstanding=result.days_outstanding,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/lookup", response_model=PaymentStatusResponse)
def lookup_invoice(
    body: InvoiceLookupBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaymentStatusResponse:
    """
    Look up a single invoice by ID.

    Returns full status, stuck detection result, approver routing, and
    a professional draft vendor response. Persists the inquiry for audit.
    """
    result = _agent.lookup_invoice(body.invoice_id, body.tenant_id, db)

    # Persist the inquiry for audit / analytics
    try:
        inquiry = VendorInquiry(
            tenant_id=body.tenant_id,
            invoice_id=body.invoice_id,
            vendor_email=result.vendor_email or None,
            inquiry_text=f"Invoice lookup: {body.invoice_id}",
            status_result=asdict(result),
            draft_response=result.draft_response,
        )
        db.add(inquiry)
        db.commit()
    except Exception as exc:
        logger.warning("Could not persist VendorInquiry for invoice=%s: %s", body.invoice_id, exc)
        db.rollback()

    logger.info(
        "PaymentStatus lookup invoice=%s tenant=%s status=%s stuck=%s",
        body.invoice_id,
        body.tenant_id,
        result.status,
        result.is_stuck,
    )

    return _to_response(result)


@router.post("/vendor-lookup", response_model=list[PaymentStatusResponse])
def vendor_lookup(
    body: VendorLookupBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PaymentStatusResponse]:
    """
    Look up all invoices for a vendor by email address.

    Returns a list of PaymentStatusResult objects, one per matched invoice.
    An empty list is returned if the vendor has no invoices on file.
    Persists the inquiry for audit.
    """
    results = _agent.lookup_by_vendor(body.vendor_email, body.tenant_id, db)

    try:
        inquiry = VendorInquiry(
            tenant_id=body.tenant_id,
            vendor_email=body.vendor_email,
            inquiry_text=f"Vendor lookup: {body.vendor_email}",
            status_result={"results": [asdict(r) for r in results]},
        )
        db.add(inquiry)
        db.commit()
    except Exception as exc:
        logger.warning("Could not persist VendorInquiry for vendor=%s: %s", body.vendor_email, exc)
        db.rollback()

    logger.info(
        "PaymentStatus vendor-lookup email=%s tenant=%s found=%d",
        body.vendor_email,
        body.tenant_id,
        len(results),
    )

    return [_to_response(r) for r in results]


@router.get("/stuck", response_model=StuckInvoicesSummaryResponse)
def get_stuck_invoices(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StuckInvoicesSummaryResponse:
    """
    Return all stuck invoices across all vendors with approver routing.

    Groups results into three buckets for the AP dashboard:
      on_hold       — invoices blocked by a documented hold reason
      overdue_review — under_review > 30 days or approved > 7 days without schedule
      queue_delays  — received > 14 days without moving to review

    Invoices are sorted by days_outstanding descending within each bucket.
    """
    # Load all invoices from mock store
    all_results = [
        _agent.lookup_invoice(inv["invoice_id"], tenant_id, db)
        for inv in _agent._MOCK_INVOICES
    ]

    on_hold = []
    overdue_review = []
    queue_delays = []

    for r in all_results:
        if not r.is_stuck:
            continue
        if r.status == "on_hold":
            on_hold.append(r)
        elif r.status == "received":
            queue_delays.append(r)
        else:
            # under_review (overdue) or approved (delay)
            overdue_review.append(r)

    # Sort each bucket by days outstanding, most overdue first
    on_hold.sort(key=lambda x: x.days_outstanding, reverse=True)
    overdue_review.sort(key=lambda x: x.days_outstanding, reverse=True)
    queue_delays.sort(key=lambda x: x.days_outstanding, reverse=True)

    total = len(on_hold) + len(overdue_review) + len(queue_delays)

    logger.info(
        "PaymentStatus stuck tenant=%s total=%d on_hold=%d overdue=%d queue=%d",
        tenant_id,
        total,
        len(on_hold),
        len(overdue_review),
        len(queue_delays),
    )

    return StuckInvoicesSummaryResponse(
        total_stuck=total,
        on_hold=[_to_response(r) for r in on_hold],
        overdue_review=[_to_response(r) for r in overdue_review],
        queue_delays=[_to_response(r) for r in queue_delays],
    )
