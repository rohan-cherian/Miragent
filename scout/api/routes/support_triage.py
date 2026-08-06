"""
scout/api/routes/support_triage.py — Sprint 64: Support Triage Agent API

Endpoints:
  POST /agents/support-triage/submit        → classify, prioritize, route, draft response
  GET  /agents/support-triage/tickets       → last N tickets for tenant, newest first
  GET  /agents/support-triage/tickets/{id} → single ticket with full result

Auth: JWT — support agents submit tickets on behalf of customers.
The full team can see all tickets for a tenant (no per-user filtering).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.agents.support_triage_agent import SupportTriageAgent
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import SupportTicket, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents/support-triage", tags=["support-triage-agent"])

_agent = SupportTriageAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class SubmitTicketBody(BaseModel):
    customer_email: str
    subject: str
    body: str
    tenant_id: str
    customer_name: str | None = None


class AccountContextSchema(BaseModel):
    customer_email: str
    company_name: str
    arr: float
    health_score: int
    account_status: str
    open_deals: int
    open_deal_value: float
    prior_tickets_30d: int
    csm_name: str
    csm_email: str
    is_enterprise: bool
    contract_tier: str
    source: str


class TriageResultResponse(BaseModel):
    ticket_id: str
    customer_email: str
    subject: str
    category: str
    category_label: str
    priority_score: int
    priority_label: str
    assigned_queue: str
    drafted_response: str
    account_context: AccountContextSchema
    escalation_reason: str | None
    routing_explanation: str
    completed_at: str
    created_at: str
    status: str


class TicketSummaryResponse(BaseModel):
    id: str
    customer_email: str
    subject: str
    category: str | None
    priority_label: str | None
    assigned_queue: str | None
    escalation_reason: str | None
    status: str
    created_at: str


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/submit", response_model=TriageResultResponse)
def submit_support_ticket(
    body: SubmitTicketBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TriageResultResponse:
    """
    Submit a support ticket for triage.

    The SupportTriageAgent classifies the ticket, pulls account context,
    computes priority, assigns a queue, drafts a first response, and flags
    escalation-worthy tickets. The result is persisted and returned immediately.
    """
    ticket_id = str(uuid.uuid4())

    # Create the row immediately so we have a record even if agent fails
    db_row = SupportTicket(
        id=ticket_id,
        tenant_id=body.tenant_id,
        submitted_by=current_user.email,
        customer_email=body.customer_email,
        customer_name=body.customer_name,
        subject=body.subject,
        body=body.body,
        status="triaged",
    )
    db.add(db_row)
    db.commit()

    # Run the agent synchronously
    result = _agent.run(
        customer_email=body.customer_email,
        subject=body.subject,
        body=body.body,
        tenant_id=body.tenant_id,
        ticket_id=ticket_id,
        customer_name=body.customer_name,
    )

    # Persist the triage result
    db_row.category = result.category
    db_row.priority_score = result.priority_score
    db_row.priority_label = result.priority_label
    db_row.assigned_queue = result.assigned_queue
    db_row.drafted_response = result.drafted_response
    db_row.account_context = asdict(result.account_context)
    db_row.escalation_reason = result.escalation_reason
    db_row.status = "escalated" if result.escalation_reason else "draft_ready"
    db_row.completed_at = result.completed_at

    db.commit()
    db.refresh(db_row)

    logger.info(
        "SupportTriage ticket=%s submitted_by=%s customer=%s category=%s priority=%s queue=%s escalated=%s",
        ticket_id,
        current_user.email,
        body.customer_email,
        result.category,
        result.priority_label,
        result.assigned_queue,
        result.escalation_reason is not None,
    )

    return TriageResultResponse(
        ticket_id=ticket_id,
        customer_email=result.customer_email,
        subject=result.subject,
        category=result.category,
        category_label=result.category_label,
        priority_score=result.priority_score,
        priority_label=result.priority_label,
        assigned_queue=result.assigned_queue,
        drafted_response=result.drafted_response,
        account_context=AccountContextSchema(**asdict(result.account_context)),
        escalation_reason=result.escalation_reason,
        routing_explanation=result.routing_explanation,
        completed_at=result.completed_at.isoformat(),
        created_at=db_row.created_at.isoformat(),
        status=db_row.status,
    )


@router.get("/tickets", response_model=list[TicketSummaryResponse])
def list_support_tickets(
    tenant_id: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TicketSummaryResponse]:
    """
    List support tickets for a tenant, newest first.

    Returns a summary view — no full body or drafted response — suitable for
    the recent tickets table in the UI.
    """
    rows = (
        db.execute(
            select(SupportTicket)
            .where(SupportTicket.tenant_id == tenant_id)
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return [
        TicketSummaryResponse(
            id=r.id,
            customer_email=r.customer_email,
            subject=r.subject,
            category=r.category,
            priority_label=r.priority_label,
            assigned_queue=r.assigned_queue,
            escalation_reason=r.escalation_reason,
            status=r.status,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/tickets/{ticket_id}", response_model=TriageResultResponse)
def get_support_ticket(
    ticket_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TriageResultResponse:
    """Get a single support ticket with full triage result."""
    row = db.get(SupportTicket, ticket_id)
    if not row:
        raise HTTPException(status_code=404, detail="Support ticket not found.")

    # Reconstruct account context from JSON
    ac = row.account_context or {}
    account_ctx = AccountContextSchema(
        customer_email=ac.get("customer_email", row.customer_email),
        company_name=ac.get("company_name", ""),
        arr=ac.get("arr", 0.0),
        health_score=ac.get("health_score", 75),
        account_status=ac.get("account_status", "healthy"),
        open_deals=ac.get("open_deals", 0),
        open_deal_value=ac.get("open_deal_value", 0.0),
        prior_tickets_30d=ac.get("prior_tickets_30d", 0),
        csm_name=ac.get("csm_name", "Support Team"),
        csm_email=ac.get("csm_email", "support@miragent.io"),
        is_enterprise=ac.get("is_enterprise", False),
        contract_tier=ac.get("contract_tier", "growth"),
        source=ac.get("source", "mock"),
    )

    return TriageResultResponse(
        ticket_id=row.id,
        customer_email=row.customer_email,
        subject=row.subject,
        category=row.category or "general_inquiry",
        category_label=SupportTriageAgent.CATEGORIES.get(
            row.category or "general_inquiry", {}
        ).get("label", "General Inquiry"),
        priority_score=row.priority_score or 25,
        priority_label=row.priority_label or "P4-Low",
        assigned_queue=row.assigned_queue or "general",
        drafted_response=row.drafted_response or "",
        account_context=account_ctx,
        escalation_reason=row.escalation_reason,
        routing_explanation=ac.get("routing_explanation", ""),
        completed_at=row.completed_at.isoformat() if row.completed_at else "",
        created_at=row.created_at.isoformat(),
        status=row.status,
    )
