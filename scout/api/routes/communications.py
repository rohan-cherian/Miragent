"""
scout/api/routes/communications.py — Sprint 73: Communication Analysis API

Analyzes customer-facing communications to surface sentiment trends, churn risks,
and expansion signals.

DATA SCOPE (GDPR-safe — customer-to-company only):
  - Support email queue (support@company.com, help@company.com)
  - Shared Slack channels (#customer-success, #support-general, #enterprise-customers)
  - Zendesk/Freshservice ticket comments from customers

EXPLICITLY EXCLUDED:
  - Employee DMs or internal Slack messages
  - Internal email threads

Endpoints:
  GET /communications/summary     ?tenant_id=   → CommAnalysisSummary
  GET /communications/messages    ?tenant_id=&sentiment=&topic=  → list[CommMessage]
  GET /communications/at-risk     ?tenant_id=   → list[CommMessage]
  GET /communications/expansion   ?tenant_id=   → list[CommMessage]
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.communication_agent import CommunicationAgent
from scout.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/communications", tags=["communications"])

_agent = CommunicationAgent()


# ── Pydantic response schemas ─────────────────────────────────────────────────


class CommMessageResponse(BaseModel):
    id: str
    channel: str
    source: str
    customer: str
    arr: float
    date: str
    subject: str | None
    body_preview: str
    sentiment: str
    topic: str
    signals: list[str]
    requires_action: bool
    action_suggestion: str | None


class CommAnalysisSummaryResponse(BaseModel):
    total_messages: int
    by_sentiment: dict[str, int]
    by_topic: dict[str, int]
    by_channel: dict[str, int]
    churn_risk_arr: float
    expansion_arr: float
    top_customers_at_risk: list[CommMessageResponse]
    top_expansion_opportunities: list[CommMessageResponse]
    urgent_unresolved: int
    sentiment_trend: str
    analysis_date: str


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/summary", response_model=CommAnalysisSummaryResponse)
def get_communications_summary(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> CommAnalysisSummaryResponse:
    """
    Return an aggregate analysis summary across all customer-facing communications.

    Includes sentiment distribution, topic breakdown, churn risk ARR, expansion ARR,
    top at-risk customers, and top expansion opportunities.

    Scope: customer-facing only (support email + shared Slack). No internal DMs.
    """
    summary = _agent.analyze_all(tenant_id, db)

    logger.info(
        "communications.summary tenant=%s total=%d churn_arr=%.0f expansion_arr=%.0f trend=%s",
        tenant_id,
        summary.total_messages,
        summary.churn_risk_arr,
        summary.expansion_arr,
        summary.sentiment_trend,
    )

    return CommAnalysisSummaryResponse(
        total_messages=summary.total_messages,
        by_sentiment=summary.by_sentiment,
        by_topic=summary.by_topic,
        by_channel=summary.by_channel,
        churn_risk_arr=summary.churn_risk_arr,
        expansion_arr=summary.expansion_arr,
        top_customers_at_risk=[
            CommMessageResponse(**asdict(m)) for m in summary.top_customers_at_risk
        ],
        top_expansion_opportunities=[
            CommMessageResponse(**asdict(m)) for m in summary.top_expansion_opportunities
        ],
        urgent_unresolved=summary.urgent_unresolved,
        sentiment_trend=summary.sentiment_trend,
        analysis_date=summary.analysis_date,
    )


@router.get("/messages", response_model=list[CommMessageResponse])
def get_communications_messages(
    tenant_id: str = Query(...),
    sentiment: str | None = Query(default=None),
    topic: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[CommMessageResponse]:
    """
    Return all customer communications with optional sentiment/topic filters.

    sentiment filter: positive | negative | urgent | churn_risk | expansion_signal | neutral
    topic filter: technical_issue | billing_question | feature_request | compliance_security |
                  expansion_upsell | churn_risk | onboarding | positive_feedback | general_inquiry

    Scope: customer-facing only. No internal DMs or employee messages.
    """
    messages = _agent.get_messages(tenant_id, db, filter_sentiment=sentiment, filter_topic=topic)
    return [CommMessageResponse(**asdict(m)) for m in messages]


@router.get("/at-risk", response_model=list[CommMessageResponse])
def get_at_risk_communications(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[CommMessageResponse]:
    """
    Return messages with churn_risk or urgent signals, sorted by ARR descending.

    These require immediate CSM or engineering attention.
    """
    messages = _agent.get_at_risk(tenant_id, db)
    return [CommMessageResponse(**asdict(m)) for m in messages]


@router.get("/expansion", response_model=list[CommMessageResponse])
def get_expansion_communications(
    tenant_id: str = Query(...),
    db: Session = Depends(get_db),
) -> list[CommMessageResponse]:
    """
    Return messages with expansion signals, sorted by ARR descending.

    Route to Account Executive team for discovery calls.
    """
    messages = _agent.get_expansion_opportunities(tenant_id, db)
    return [CommMessageResponse(**asdict(m)) for m in messages]
