"""
scout/api/routes/mission_control.py — Mission Control API (Sprint 62)

The operator dashboard data layer. Provides full-stack visibility into:
  - Active agent deployments and their runtime metrics
  - Process blueprints discovered from ticket/activity data
  - Connector health across the 31-connector catalog
  - Recent audit trail entries
  - Summary stats for the dashboard header

All write endpoints require authentication. Read endpoints accept a
tenant_id query parameter and require a valid JWT.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.config import settings
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import (
    AgentDeployment,
    ApprovalRequest,
    ProcessBlueprint,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mission-control", tags=["Mission Control"])


# ── Mock seed data ─────────────────────────────────────────────────────────────

_SEED_BLUEPRINTS = [
    {
        "process_name": "Client Portal Access",
        "category": "customer_support",
        "volume_per_week": 47.0,
        "median_resolution_hours": 4.2,
        "automation_potential": 83,
        "recommended_agent": "PortalAccessAgent",
        "systems_involved": ["Zendesk", "Okta", "Salesforce"],
        "resolution_patterns": {
            "account_locked": 0.61,
            "not_provisioned": 0.22,
            "sso_mismatch": 0.11,
            "mfa_reset": 0.06,
        },
        "status": "discovered",
        "sop_coverage": True,
        "conformance_gap": "Median resolution 4.2h vs. 2h SOP commitment",
    },
    {
        "process_name": "DDQ / Security Questionnaire",
        "category": "sales",
        "volume_per_week": 8.3,
        "median_resolution_hours": 66.4,
        "automation_potential": 91,
        "recommended_agent": "DDQAgent",
        "systems_involved": ["Email", "Sharepoint", "Salesforce"],
        "resolution_patterns": {
            "manual_drafting": 0.78,
            "partial_template": 0.22,
        },
        "status": "active",
        "sop_coverage": False,
        "conformance_gap": "No SOP exists. Average 8.3 days vs. industry benchmark 2 days.",
    },
    {
        "process_name": "Payroll Document Requests",
        "category": "hr",
        "volume_per_week": 23.0,
        "median_resolution_hours": 28.0,
        "automation_potential": 96,
        "recommended_agent": "PayrollDocumentAgent",
        "systems_involved": ["ADP", "Workday", "Email"],
        "resolution_patterns": {
            "w2_request": 0.35,
            "paystub_request": 0.45,
            "ytd_request": 0.20,
        },
        "status": "active",
        "sop_coverage": True,
        "conformance_gap": None,
    },
    {
        "process_name": "New Vendor Onboarding",
        "category": "vendor",
        "volume_per_week": 4.1,
        "median_resolution_hours": 248.0,
        "automation_potential": 67,
        "recommended_agent": "VendorOnboardingAgent",
        "systems_involved": ["Email", "NetSuite", "DocuSign"],
        "resolution_patterns": {
            "w9_collection": 0.30,
            "banking_setup": 0.25,
            "approval_routing": 0.45,
        },
        "status": "discovered",
        "sop_coverage": True,
        "conformance_gap": "31 days actual vs. 15 day SOP — 107% SLA breach",
    },
    {
        "process_name": "Billing Dispute Resolution",
        "category": "finance",
        "volume_per_week": 6.8,
        "median_resolution_hours": 72.0,
        "automation_potential": 54,
        "recommended_agent": None,
        "systems_involved": ["Zendesk", "NetSuite", "Email"],
        "resolution_patterns": {
            "invoice_discrepancy": 0.55,
            "contract_terms_dispute": 0.30,
            "duplicate_charge": 0.15,
        },
        "status": "discovered",
        "sop_coverage": False,
        "conformance_gap": None,
    },
]

_SEED_DEPLOYMENTS = [
    {
        "agent_name": "DDQAgent",
        "status": "active",
        "config": {"knowledge_base": "enabled", "auto_draft": True},
        "requests_handled": 23,
        "requests_today": 3,
        "resolution_rate": 0.89,
    },
    {
        "agent_name": "PayrollDocumentAgent",
        "status": "active",
        "config": {"payroll_connector": "workday_mock", "auto_deliver": True},
        "requests_handled": 67,
        "requests_today": 8,
        "resolution_rate": 0.97,
    },
]

# Mock connector catalog — 31 connectors from the full catalog
# Salesforce, Workday, NetSuite, HubSpot marked as "connected" for demo
_CONNECTOR_CATALOG = [
    {"name": "Salesforce",     "status": "connected"},
    {"name": "Workday",        "status": "connected"},
    {"name": "NetSuite",       "status": "connected"},
    {"name": "HubSpot",        "status": "connected"},
    {"name": "Okta",           "status": "available"},
    {"name": "ADP",            "status": "available"},
    {"name": "Zendesk",        "status": "available"},
    {"name": "GitHub",         "status": "available"},
    {"name": "Slack",          "status": "available"},
    {"name": "Jira",           "status": "available"},
    {"name": "DocuSign",       "status": "available"},
    {"name": "QuickBooks",     "status": "available"},
    {"name": "Stripe",         "status": "available"},
    {"name": "Shopify",        "status": "available"},
    {"name": "Greenhouse",     "status": "available"},
    {"name": "Rippling",       "status": "available"},
    {"name": "Lever",          "status": "available"},
    {"name": "BambooHR",       "status": "available"},
    {"name": "Lattice",        "status": "available"},
    {"name": "Asana",          "status": "available"},
    {"name": "Monday.com",     "status": "available"},
    {"name": "Notion",         "status": "available"},
    {"name": "Confluence",     "status": "available"},
    {"name": "Intercom",       "status": "available"},
    {"name": "Freshdesk",      "status": "available"},
    {"name": "ServiceNow",     "status": "available"},
    {"name": "Coupa",          "status": "available"},
    {"name": "Concur",         "status": "available"},
    {"name": "Box",            "status": "available"},
    {"name": "Dropbox",        "status": "available"},
    {"name": "Google Workspace","status": "available"},
]


# ── Helpers ────────────────────────────────────────────────────────────────────


def _seed_blueprints(tenant_id: str, db: Session) -> None:
    """Seed mock blueprints if none exist for this tenant."""
    existing = db.execute(
        select(ProcessBlueprint).where(ProcessBlueprint.tenant_id == tenant_id)
    ).scalar_one_or_none()

    if existing is not None:
        return  # already seeded

    for bp_data in _SEED_BLUEPRINTS:
        bp = ProcessBlueprint(
            tenant_id=tenant_id,
            **bp_data,
        )
        db.add(bp)
    db.commit()


def _seed_deployments(tenant_id: str, db: Session) -> None:
    """Seed mock agent deployments if none exist for this tenant."""
    existing = db.execute(
        select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
    ).scalar_one_or_none()

    if existing is not None:
        return  # already seeded

    now = datetime.utcnow()
    for dep_data in _SEED_DEPLOYMENTS:
        dep = AgentDeployment(
            tenant_id=tenant_id,
            last_activity_at=now - timedelta(minutes=14),
            deployed_at=now - timedelta(days=7),
            deployed_by="system",
            **dep_data,
        )
        db.add(dep)
    db.commit()


def _read_audit_log(n: int = 50) -> list[dict[str, Any]]:
    """Read the last N entries from the audit log file."""
    audit_file = Path(settings.audit_log_file)
    if not audit_file.exists():
        return []

    try:
        lines = audit_file.read_text().strip().splitlines()
        recent = lines[-n:] if len(lines) > n else lines
        entries = []
        for line in reversed(recent):
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
        return entries
    except Exception as exc:
        logger.warning(f"Could not read audit log: {exc}")
        return []


def _blueprint_to_dict(bp: ProcessBlueprint) -> dict[str, Any]:
    return {
        "id": bp.id,
        "tenant_id": bp.tenant_id,
        "process_name": bp.process_name,
        "category": bp.category,
        "volume_per_week": bp.volume_per_week,
        "median_resolution_hours": bp.median_resolution_hours,
        "automation_potential": bp.automation_potential,
        "recommended_agent": bp.recommended_agent,
        "systems_involved": bp.systems_involved or [],
        "resolution_patterns": bp.resolution_patterns or {},
        "status": bp.status,
        "sop_coverage": bp.sop_coverage,
        "conformance_gap": bp.conformance_gap,
        "created_at": bp.created_at.isoformat() if bp.created_at else None,
        "reviewed_at": bp.reviewed_at.isoformat() if bp.reviewed_at else None,
        "reviewed_by": bp.reviewed_by,
    }


def _deployment_to_dict(dep: AgentDeployment) -> dict[str, Any]:
    return {
        "id": dep.id,
        "tenant_id": dep.tenant_id,
        "agent_name": dep.agent_name,
        "status": dep.status,
        "blueprint_id": dep.blueprint_id,
        "config": dep.config or {},
        "requests_handled": dep.requests_handled,
        "requests_today": dep.requests_today,
        "resolution_rate": dep.resolution_rate,
        "last_activity_at": dep.last_activity_at.isoformat() if dep.last_activity_at else None,
        "deployed_at": dep.deployed_at.isoformat() if dep.deployed_at else None,
        "deployed_by": dep.deployed_by,
    }


def _connector_health() -> list[dict[str, Any]]:
    """Return connector health list with mock last_sync for connected ones."""
    now = datetime.utcnow()
    result = []
    for c in _CONNECTOR_CATALOG:
        entry = dict(c)
        if c["status"] == "connected":
            entry["last_sync"] = (now - timedelta(minutes=37)).isoformat()
        else:
            entry["last_sync"] = None
        result.append(entry)
    return result


def _pending_approval_count(tenant_id: str, db: Session) -> int:
    """Count PENDING approval requests for the tenant."""
    try:
        return (
            db.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.status == "PENDING",
                )
            )
            .scalars()
            .all()
        ).__len__()
    except Exception:
        return 3  # mock fallback


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class BlueprintReviewResponse(BaseModel):
    ok: bool
    blueprint_id: str
    new_status: str


class AgentStatusResponse(BaseModel):
    ok: bool
    agent_id: str
    new_status: str


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get(
    "/summary",
    summary="Mission Control — full dashboard data in one call",
    response_model=None,
)
def get_summary(
    tenant_id: str = Query(..., description="Tenant ID", examples=["acme-corp"]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    GET /mission-control/summary?tenant_id=acme-corp

    Returns everything the Mission Control dashboard needs in a single
    request to avoid waterfall loading on the frontend.
    """
    _seed_blueprints(tenant_id, db)
    _seed_deployments(tenant_id, db)

    blueprints = (
        db.execute(
            select(ProcessBlueprint)
            .where(ProcessBlueprint.tenant_id == tenant_id)
            .order_by(ProcessBlueprint.automation_potential.desc())
        )
        .scalars()
        .all()
    )

    deployments = (
        db.execute(
            select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    )

    active_agents = sum(1 for d in deployments if d.status == "active")
    paused_agents = sum(1 for d in deployments if d.status == "paused")
    blueprints_discovered = sum(1 for b in blueprints if b.status == "discovered")
    blueprints_active = sum(1 for b in blueprints if b.status == "active")

    pending_approvals = _pending_approval_count(tenant_id, db)
    audit_entries = _read_audit_log(10)

    return {
        "last_scan_at": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
        "active_agents": active_agents,
        "paused_agents": paused_agents,
        "pending_approvals": pending_approvals,
        "blueprints_discovered": blueprints_discovered,
        "blueprints_active": blueprints_active,
        "findings_this_week": 47,   # mock — would come from finding_dispositions in prod
        "critical_findings": 3,     # mock — would come from finding_dispositions in prod
        "connectors": _connector_health(),
        "agents": [_deployment_to_dict(d) for d in deployments],
        "blueprints": [_blueprint_to_dict(b) for b in blueprints[:5]],
        "recent_actions": audit_entries,
    }


@router.get(
    "/blueprints",
    summary="List process blueprints for tenant",
    response_model=None,
)
def list_blueprints(
    tenant_id: str = Query(..., description="Tenant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """GET /mission-control/blueprints?tenant_id=acme-corp"""
    _seed_blueprints(tenant_id, db)

    blueprints = (
        db.execute(
            select(ProcessBlueprint)
            .where(ProcessBlueprint.tenant_id == tenant_id)
            .order_by(ProcessBlueprint.automation_potential.desc())
        )
        .scalars()
        .all()
    )

    return [_blueprint_to_dict(b) for b in blueprints]


@router.post(
    "/blueprints/{blueprint_id}/review",
    summary="Mark a blueprint as reviewed",
    response_model=BlueprintReviewResponse,
)
def review_blueprint(
    blueprint_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BlueprintReviewResponse:
    """POST /mission-control/blueprints/{id}/review"""
    bp = db.execute(
        select(ProcessBlueprint).where(ProcessBlueprint.id == blueprint_id)
    ).scalar_one_or_none()

    if bp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Blueprint {blueprint_id} not found",
        )

    bp.status = "reviewed"
    bp.reviewed_at = datetime.utcnow()
    bp.reviewed_by = current_user.email
    db.commit()

    return BlueprintReviewResponse(
        ok=True,
        blueprint_id=blueprint_id,
        new_status="reviewed",
    )


@router.get(
    "/agents",
    summary="List agent deployments for tenant",
    response_model=None,
)
def list_agents(
    tenant_id: str = Query(..., description="Tenant ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """GET /mission-control/agents?tenant_id=acme-corp"""
    _seed_deployments(tenant_id, db)

    deployments = (
        db.execute(
            select(AgentDeployment).where(AgentDeployment.tenant_id == tenant_id)
        )
        .scalars()
        .all()
    )

    return [_deployment_to_dict(d) for d in deployments]


@router.post(
    "/agents/{agent_id}/pause",
    summary="Pause an agent deployment",
    response_model=AgentStatusResponse,
)
def pause_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentStatusResponse:
    """POST /mission-control/agents/{id}/pause"""
    dep = db.execute(
        select(AgentDeployment).where(AgentDeployment.id == agent_id)
    ).scalar_one_or_none()

    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent deployment {agent_id} not found",
        )

    dep.status = "paused"
    db.commit()

    return AgentStatusResponse(ok=True, agent_id=agent_id, new_status="paused")


@router.post(
    "/agents/{agent_id}/resume",
    summary="Resume a paused agent deployment",
    response_model=AgentStatusResponse,
)
def resume_agent(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentStatusResponse:
    """POST /mission-control/agents/{id}/resume"""
    dep = db.execute(
        select(AgentDeployment).where(AgentDeployment.id == agent_id)
    ).scalar_one_or_none()

    if dep is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent deployment {agent_id} not found",
        )

    dep.status = "active"
    dep.last_activity_at = datetime.utcnow()
    db.commit()

    return AgentStatusResponse(ok=True, agent_id=agent_id, new_status="active")


@router.get(
    "/audit-trail",
    summary="Last N audit log entries for tenant",
    response_model=None,
)
def get_audit_trail(
    tenant_id: str = Query(..., description="Tenant ID"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """GET /mission-control/audit-trail?tenant_id=acme-corp"""
    entries = _read_audit_log(limit)
    # Filter to tenant if entries have tenant_id field
    tenant_entries = [
        e for e in entries
        if not e.get("tenant_id") or e.get("tenant_id") == tenant_id
    ]
    return tenant_entries[:limit]
