"""
scout/api/routes/benefits.py — Sprint 66: Benefits Agent API

Endpoints:
  POST /benefits/query    → ask a benefits question for a given employee
  GET  /benefits/summary  → full benefits snapshot (all categories)

Auth: JWT — employees self-serve their own benefits data.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.benefits_agent import BenefitsAgent, BenefitsResult
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import BenefitsInquiry, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/benefits", tags=["benefits-agent"])

_agent = BenefitsAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class BenefitsQueryBody(BaseModel):
    employee_email: str
    question: str
    tenant_id: str


class BenefitsResultResponse(BaseModel):
    employee_email: str
    employee_name: str
    department: str
    question_category: str
    answer: str
    key_facts: dict
    action_items: list[str]
    contact: str


class BenefitsSummaryResponse(BaseModel):
    found: bool
    employee_email: str
    employee_name: str | None = None
    department: str | None = None
    pto_remaining: int | None = None
    pto_total: int | None = None
    ytd_pto_used: int | None = None
    health_plan: str | None = None
    monthly_contribution: str | None = None
    contrib_pct: int | None = None
    match_pct: int | None = None
    match_captured: bool | None = None
    enrollment_window: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(result: BenefitsResult) -> BenefitsResultResponse:
    return BenefitsResultResponse(
        employee_email=result.employee_email,
        employee_name=result.employee_name,
        department=result.department,
        question_category=result.question_category,
        answer=result.answer,
        key_facts=result.key_facts,
        action_items=result.action_items,
        contact=result.contact,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/query", response_model=BenefitsResultResponse)
def query_benefits(
    body: BenefitsQueryBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BenefitsResultResponse:
    """
    Answer an employee's benefits question.

    Classifies the question, looks up the employee's benefits profile,
    generates a natural-language answer with key facts and action items,
    and routes to the correct contact. Persists the inquiry for audit.
    """
    result = _agent.get_benefits(body.employee_email, body.question, body.tenant_id, db)

    # Persist for audit / analytics
    try:
        inquiry = BenefitsInquiry(
            tenant_id=body.tenant_id,
            employee_email=body.employee_email,
            question=body.question,
            question_category=result.question_category,
            result=asdict(result),
        )
        db.add(inquiry)
        db.commit()
    except Exception as exc:
        logger.warning(
            "Could not persist BenefitsInquiry for email=%s: %s",
            body.employee_email,
            exc,
        )
        db.rollback()

    logger.info(
        "Benefits query email=%s tenant=%s category=%s actions=%d",
        body.employee_email,
        body.tenant_id,
        result.question_category,
        len(result.action_items),
    )

    return _to_response(result)


@router.get("/summary", response_model=BenefitsSummaryResponse)
def get_summary(
    employee_email: str = Query(...),
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BenefitsSummaryResponse:
    """
    Return a full benefits snapshot for all four benefit categories.

    Used by the Benefits Snapshot panel in the UI to populate the
    2x2 mini-card grid. Returns all categories in a single call.
    """
    summary = _agent.get_summary(employee_email, tenant_id, db)

    logger.info(
        "Benefits summary email=%s tenant=%s found=%s",
        employee_email,
        tenant_id,
        summary.get("found"),
    )

    if not summary.get("found"):
        return BenefitsSummaryResponse(
            found=False,
            employee_email=employee_email,
        )

    return BenefitsSummaryResponse(
        found=True,
        employee_email=employee_email,
        employee_name=summary["employee_name"],
        department=summary["department"],
        pto_remaining=summary["pto_remaining"],
        pto_total=summary["pto_total"],
        ytd_pto_used=summary["ytd_pto_used"],
        health_plan=summary["health_plan"],
        monthly_contribution=summary["monthly_contribution"],
        contrib_pct=summary["contrib_pct"],
        match_pct=summary["match_pct"],
        match_captured=summary["match_captured"],
        enrollment_window=summary["enrollment_window"],
    )
