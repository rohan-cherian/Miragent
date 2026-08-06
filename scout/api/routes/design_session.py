"""
scout/api/routes/design_session.py — Design Session Mode (Sprint 72)

Guided 5-step operator onboarding wizard. When a PE firm or company first
sets up Miragent, this wizard shows what Miragent already discovered and
walks the operator through reviewing, approving, and configuring agents.

The wizard never starts from blank — it seeds the session with realistic
mock data representing discovered processes and Scout findings.

Steps:
  1. connect   — confirm connected systems
  2. discover  — show discovered processes and Scout findings summary
  3. review    — operator reviews each blueprint and approves/skips
  4. configure — set thresholds and agent activation per approved blueprint
  5. golive    — summary of what's active + go-live confirmation
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.db.database import get_db
from scout.db.models import DesignSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/design-session", tags=["Design Session"])

# ── Step ordering ──────────────────────────────────────────────────────────────

STEPS = ["connect", "discover", "review", "configure", "golive"]
STEP_NUMBERS = {step: i + 1 for i, step in enumerate(STEPS)}

# ── Mock session seed data ─────────────────────────────────────────────────────

MOCK_SESSION: dict[str, Any] = {
    "connected_systems": [
        {"name": "Salesforce CRM", "status": "connected", "records": 847, "icon": "crm"},
        {"name": "Workday HCM", "status": "connected", "records": 203, "icon": "hr"},
        {"name": "NetSuite ERP", "status": "connected", "records": 1204, "icon": "finance"},
        {"name": "Slack", "status": "connected", "records": 0, "icon": "comms"},
        {"name": "GitHub Enterprise", "status": "available", "records": 0, "icon": "engineering"},
        {"name": "HubSpot Marketing", "status": "available", "records": 0, "icon": "marketing"},
    ],
    "scout_summary": {
        "total_findings": 292,
        "critical": 8,
        "high": 47,
        "medium": 128,
        "low": 109,
        "workers_run": 34,
        "scan_duration_seconds": 14,
    },
    "discovered_blueprints": [
        {
            "id": "bp-portal-access",
            "name": "Portal Access Requests",
            "description": "Employees submit portal login issues. Current resolution: manual IT ticket, avg 4.2 hours.",
            "volume_per_month": 38,
            "automation_potential": 83,
            "sla_gap": "110% over target (4.2h actual vs 2h policy)",
            "recommended_agent": "PortalAccessAgent",
            "estimated_hours_saved_monthly": 24,
            "status": "pending_review",
        },
        {
            "id": "bp-ddq",
            "name": "Due Diligence Questionnaires",
            "description": "Investor and customer DDQs routed manually to multiple stakeholders. Avg 8+ days per response.",
            "volume_per_month": 4,
            "automation_potential": 91,
            "sla_gap": "66% over target (8.3 days actual vs 5 day policy)",
            "recommended_agent": "DDQAgent",
            "estimated_hours_saved_monthly": 32,
            "status": "pending_review",
        },
        {
            "id": "bp-payroll",
            "name": "Payroll Document Requests",
            "description": "Employees request W2s, paystubs via HR email. HR spends ~2h/week on this manually.",
            "volume_per_month": 22,
            "automation_potential": 96,
            "sla_gap": None,
            "recommended_agent": "PayrollDocumentAgent",
            "estimated_hours_saved_monthly": 8,
            "status": "pending_review",
        },
        {
            "id": "bp-vendor-onboarding",
            "name": "Vendor Onboarding",
            "description": "New vendor setup takes 31 days average vs 15 day policy. 7 vendors currently stalled.",
            "volume_per_month": 6,
            "automation_potential": 67,
            "sla_gap": "107% over target (31 days actual vs 15 day policy)",
            "recommended_agent": "VendorOnboardingAgent",
            "estimated_hours_saved_monthly": 18,
            "status": "pending_review",
        },
        {
            "id": "bp-support-triage",
            "name": "Customer Support Triage",
            "description": "Incoming support tickets manually routed. P1 customers sometimes wait in standard queue.",
            "volume_per_month": 91,
            "automation_potential": 78,
            "sla_gap": None,
            "recommended_agent": "SupportTriageAgent",
            "estimated_hours_saved_monthly": 15,
            "status": "pending_review",
        },
    ],
}


# ── Helper: build response shape ──────────────────────────────────────────────


def _session_response(session: DesignSession) -> dict[str, Any]:
    """Build the standardised session response shape for all endpoints."""
    data: dict[str, Any] = session.session_data or {}
    blueprints: list[dict[str, Any]] = [
        dict(bp) for bp in data.get("discovered_blueprints", [])
    ]

    approved: list[str] = session.approved_blueprints or []
    skipped: list[str] = session.skipped_blueprints or []

    # Merge approval decisions into blueprint list
    for bp in blueprints:
        if bp["id"] in approved:
            bp["status"] = "approved"
        elif bp["id"] in skipped:
            bp["status"] = "skipped"

    approved_blueprints = [bp for bp in blueprints if bp["status"] == "approved"]
    estimated_hours = sum(
        bp.get("estimated_hours_saved_monthly", 0) for bp in approved_blueprints
    )

    go_live_summary: dict[str, Any] | None = None
    if session.current_step == "golive" or session.completed_at is not None:
        go_live_summary = {
            "agents_activated": len(approved),
            "estimated_hours_saved_monthly": estimated_hours,
            "processes_automated": len(approved),
            "agent_names": [bp["recommended_agent"] for bp in approved_blueprints],
            "blueprint_names": [bp["name"] for bp in approved_blueprints],
        }

    return {
        "session_id": session.id,
        "tenant_id": session.tenant_id,
        "current_step": session.current_step,
        "step_number": STEP_NUMBERS.get(session.current_step, 1),
        "connected_systems": data.get("connected_systems", []),
        "scout_summary": data.get("scout_summary", {}),
        "blueprints": blueprints,
        "approved_count": len(approved),
        "estimated_hours_saved": estimated_hours,
        "completed": session.completed_at is not None,
        "go_live_summary": go_live_summary,
    }


# ── Pydantic request bodies ────────────────────────────────────────────────────


class StartRequest(BaseModel):
    tenant_id: str


class ApproveBlueprintRequest(BaseModel):
    blueprint_id: str
    approved: bool


class ConfigureRequest(BaseModel):
    blueprint_id: str
    config: dict[str, Any]


class CompleteRequest(BaseModel):
    tenant_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.post(
    "/start",
    summary="Start a new Design Session for a tenant",
    response_model=None,
)
def start_session(body: StartRequest, db: Session = Depends(get_db)) -> dict:
    """
    POST /design-session/start

    Creates a new DesignSession seeded with mock connected systems, Scout
    findings summary, and discovered process blueprints. Always starts at
    step 1 (connect).

    If an incomplete session already exists for this tenant it is returned
    instead of creating a duplicate.
    """
    # Return existing active session rather than creating a duplicate
    existing = db.execute(
        select(DesignSession).where(
            DesignSession.tenant_id == body.tenant_id,
            DesignSession.completed_at.is_(None),
        )
    ).scalar_one_or_none()

    if existing is not None:
        return _session_response(existing)

    session = DesignSession(
        id=str(uuid4()),
        tenant_id=body.tenant_id,
        current_step="connect",
        session_data=MOCK_SESSION,
        approved_blueprints=[],
        skipped_blueprints=[],
        configurations={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    logger.info(f"Design session created: {session.id} for tenant {body.tenant_id}")
    return _session_response(session)


@router.get(
    "/active",
    summary="Get the active (incomplete) Design Session for a tenant",
    response_model=None,
)
def get_active_session(
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db),
) -> dict | None:
    """
    GET /design-session/active?tenant_id=acme-corp

    Returns the first incomplete session for this tenant, or null if none exists.
    """
    session = db.execute(
        select(DesignSession).where(
            DesignSession.tenant_id == tenant_id,
            DesignSession.completed_at.is_(None),
        )
    ).scalar_one_or_none()

    if session is None:
        return None

    return _session_response(session)


@router.get(
    "/{session_id}",
    summary="Get a Design Session by ID",
    response_model=None,
)
def get_session(
    session_id: str,
    tenant_id: str = Query(..., description="Tenant ID"),
    db: Session = Depends(get_db),
) -> dict:
    """GET /design-session/{session_id}?tenant_id=acme-corp"""
    session = db.execute(
        select(DesignSession).where(
            DesignSession.id == session_id,
            DesignSession.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Design session {session_id} not found for tenant {tenant_id}",
        )

    return _session_response(session)


@router.post(
    "/{session_id}/approve-blueprint",
    summary="Approve or skip a discovered blueprint",
    response_model=None,
)
def approve_blueprint(
    session_id: str,
    body: ApproveBlueprintRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    POST /design-session/{session_id}/approve-blueprint

    Marks a blueprint as approved or skipped. Advances the session step
    to 'configure' once all blueprints have been reviewed.
    """
    session = db.execute(
        select(DesignSession).where(DesignSession.id == session_id)
    ).scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Design session {session_id} not found",
        )

    approved: list[str] = list(session.approved_blueprints or [])
    skipped: list[str] = list(session.skipped_blueprints or [])

    bp_id = body.blueprint_id
    if body.approved:
        if bp_id not in approved:
            approved.append(bp_id)
        if bp_id in skipped:
            skipped.remove(bp_id)
    else:
        if bp_id not in skipped:
            skipped.append(bp_id)
        if bp_id in approved:
            approved.remove(bp_id)

    session.approved_blueprints = approved
    session.skipped_blueprints = skipped

    # Advance step if all blueprints have been reviewed
    total_blueprints = len(
        (session.session_data or {}).get("discovered_blueprints", [])
    )
    reviewed_count = len(approved) + len(skipped)
    if reviewed_count >= total_blueprints and session.current_step == "review":
        session.current_step = "configure"

    db.commit()
    db.refresh(session)

    return _session_response(session)


@router.post(
    "/{session_id}/configure",
    summary="Save threshold configuration for an approved blueprint",
    response_model=None,
)
def configure_blueprint(
    session_id: str,
    body: ConfigureRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    POST /design-session/{session_id}/configure

    Saves the operator's threshold and activation configuration for a
    blueprint. After saving, advances the step to 'golive'.
    """
    session = db.execute(
        select(DesignSession).where(DesignSession.id == session_id)
    ).scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Design session {session_id} not found",
        )

    configs: dict[str, Any] = dict(session.configurations or {})
    configs[body.blueprint_id] = body.config
    session.configurations = configs

    # Advance to golive once configure step is reached and configs saved
    if session.current_step == "configure":
        session.current_step = "golive"

    db.commit()
    db.refresh(session)

    return _session_response(session)


@router.post(
    "/{session_id}/complete",
    summary="Mark the Design Session as complete (go live)",
    response_model=None,
)
def complete_session(
    session_id: str,
    body: CompleteRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    POST /design-session/{session_id}/complete

    Finalises the design session. Sets completed_at and advances to the
    golive step. The go_live_summary is populated in the response.
    """
    session = db.execute(
        select(DesignSession).where(
            DesignSession.id == session_id,
            DesignSession.tenant_id == body.tenant_id,
        )
    ).scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Design session {session_id} not found for tenant {body.tenant_id}",
        )

    session.current_step = "golive"
    session.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)

    logger.info(
        f"Design session {session_id} completed for tenant {body.tenant_id} "
        f"with {len(session.approved_blueprints or [])} approved blueprints"
    )

    return _session_response(session)
