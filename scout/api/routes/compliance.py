"""
scout/api/routes/compliance.py — Sprint 69: Compliance Response Agent API

Endpoints:
  POST /compliance/process    → answer a customer security questionnaire
  GET  /compliance/sample     → return the built-in sample questionnaire text
  GET  /compliance/kb-topics  → list all KB topics with their keyword triggers
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.compliance_agent import (
    COMPLIANCE_KB,
    SAMPLE_QUESTIONNAIRE,
    ComplianceAgent,
    ComplianceResult,
)
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compliance", tags=["compliance-agent"])

_agent = ComplianceAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class ComplianceAnswerResponse(BaseModel):
    question_number: int
    question_text: str
    topic: str | None
    answer: str
    confidence: float
    confidence_label: str
    evidence: str | None
    needs_review: bool


class ComplianceResultResponse(BaseModel):
    job_id: str
    tenant_id: str
    customer_name: str
    questionnaire_type: str
    total_questions: int
    high_confidence: int
    needs_review: int
    unknown_count: int
    answers: list[ComplianceAnswerResponse]
    summary: str
    submitted_at: str


class ProcessBody(BaseModel):
    customer_name: str
    questionnaire_text: str
    tenant_id: str


class KBTopicResponse(BaseModel):
    topic: str
    keywords: list[str]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _to_response(result: ComplianceResult) -> ComplianceResultResponse:
    return ComplianceResultResponse(
        job_id=result.job_id,
        tenant_id=result.tenant_id,
        customer_name=result.customer_name,
        questionnaire_type=result.questionnaire_type,
        total_questions=result.total_questions,
        high_confidence=result.high_confidence,
        needs_review=result.needs_review,
        unknown_count=result.unknown_count,
        answers=[
            ComplianceAnswerResponse(
                question_number=a.question_number,
                question_text=a.question_text,
                topic=a.topic,
                answer=a.answer,
                confidence=a.confidence,
                confidence_label=a.confidence_label,
                evidence=a.evidence,
                needs_review=a.needs_review,
            )
            for a in result.answers
        ],
        summary=result.summary,
        submitted_at=result.submitted_at,
    )


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/process", response_model=ComplianceResultResponse)
def process_questionnaire(
    body: ProcessBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ComplianceResultResponse:
    """
    Answer a customer security questionnaire.

    Parses the questionnaire text into individual questions, matches each
    to the compliance KB, and returns answers with confidence scores.
    High-confidence answers (≥ 0.85) are ready to use. Items below 0.85
    are flagged for human review.
    """
    result = _agent.process_questionnaire(
        customer_name=body.customer_name,
        questionnaire_text=body.questionnaire_text,
        tenant_id=body.tenant_id,
        db=db,
    )

    logger.info(
        "ComplianceAgent process customer=%s tenant=%s type=%s total=%d high=%d review=%d unknown=%d",
        body.customer_name,
        body.tenant_id,
        result.questionnaire_type,
        result.total_questions,
        result.high_confidence,
        result.needs_review,
        result.unknown_count,
    )

    return _to_response(result)


@router.get("/sample")
def get_sample(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Return the built-in sample security questionnaire text.

    Used by the UI to pre-fill the questionnaire textarea for demos.
    """
    return {"text": SAMPLE_QUESTIONNAIRE}


@router.get("/kb-topics", response_model=list[KBTopicResponse])
def get_kb_topics(
    current_user: User = Depends(get_current_user),
) -> list[KBTopicResponse]:
    """
    List all KB topics with their keyword triggers.

    Lets the UI show which topics the agent knows about and which
    keywords trigger each topic.
    """
    return [
        KBTopicResponse(topic=topic, keywords=entry["keywords"])
        for topic, entry in COMPLIANCE_KB.items()
    ]
