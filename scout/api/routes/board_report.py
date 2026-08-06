"""
scout/api/routes/board_report.py — Sprint 70: Board Report Agent API

Endpoints:
  POST /board-report/generate    body: {tenant_id, period?} → BoardReport JSON
  GET  /board-report/latest      ?tenant_id=               → most recent report,
                                                              or generate fresh if none
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.agents.board_report_agent import BoardReport, BoardReportAgent
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import BoardReportJob, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/board-report", tags=["board-report"])

_agent = BoardReportAgent()


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class GenerateBody(BaseModel):
    tenant_id: str
    period: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _persist(report: BoardReport, db: Session) -> None:
    """Save the board report to the DB for later retrieval."""
    job = BoardReportJob(
        id=report.report_id,
        tenant_id=report.tenant_id,
        period=report.period,
        report_data=asdict(report),
    )
    db.add(job)
    db.commit()


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post("/generate")
def generate_report(
    body: GenerateBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Generate a fresh board report for the given tenant and optional period.

    Builds all seven sections (Revenue, Pipeline, Customer Success, Headcount,
    Financials, Engineering, Strategic Risks), computes DORA classification,
    and returns structured data ready for the board package UI.
    """
    report = _agent.generate_report(
        tenant_id=body.tenant_id,
        period=body.period,
        db=db,
    )
    _persist(report, db)

    logger.info(
        "BoardReportAgent generated report_id=%s tenant=%s period=%s dora=%s sections=%d",
        report.report_id,
        report.tenant_id,
        report.period,
        report.dora_tier,
        len(report.sections),
    )

    return asdict(report)


@router.get("/latest")
def get_latest_report(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Return the most recent board report for a tenant.

    If no report has been generated yet, generates one on the fly and
    persists it. This ensures the page always loads with data.
    """
    job = (
        db.query(BoardReportJob)
        .filter(BoardReportJob.tenant_id == tenant_id)
        .order_by(BoardReportJob.created_at.desc())
        .first()
    )

    if job and job.report_data:
        logger.info(
            "BoardReportAgent returning cached report_id=%s tenant=%s",
            job.id,
            tenant_id,
        )
        return job.report_data

    # No existing report — generate fresh
    report = _agent.generate_report(tenant_id=tenant_id, period=None, db=db)
    _persist(report, db)

    logger.info(
        "BoardReportAgent generated fresh report_id=%s for tenant=%s (no prior reports found)",
        report.report_id,
        tenant_id,
    )

    return asdict(report)
