"""
scout/api/routes/notifications.py — Notification Center API

Endpoints:
  GET  /notifications              ?tenant_id=&unread_only=false&category=  → list[Notification]
  POST /notifications/{id}/read    ?tenant_id=                              → {success: bool}
  POST /notifications/read-all     body: {tenant_id: str}                   → {marked: int}
  POST /notifications/{id}/dismiss ?tenant_id=                              → {success: bool}
  GET  /notifications/summary      ?tenant_id=                              → NotificationSummary

Sprint 76: Unified alert inbox — surfaces critical findings, pending approvals,
churn risk, renewals, and agent activity in one prioritised feed.
"""

from __future__ import annotations

import copy
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])

# ── Mock data ──────────────────────────────────────────────────────────────────

MOCK_NOTIFICATIONS: list[dict] = [
    # Critical findings
    {
        "id": "ntf-001", "category": "finding", "severity": "critical",
        "title": "MFA enrollment dropped to 48% — below critical threshold",
        "body": "SecurityHygieneWorker detected 52% of users have not enrolled in MFA. Policy requires 80% minimum. 3 admin accounts affected.",
        "source_agent": "SecurityHygieneWorker",
        "action_url": "/insights", "action_label": "View Finding",
        "created_at": "2026-05-19T07:14:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"finding_severity": "CRITICAL", "mfa_pct": 48},
    },
    {
        "id": "ntf-002", "category": "finding", "severity": "critical",
        "title": "Vendor onboarding SLA at 107% breach — Frontier Energy stalled 31 days",
        "body": "ProcessConformanceWorker: Vendor onboarding target is 15 business days. Frontier Energy Solutions is at 31 days with an EIN mismatch hold.",
        "source_agent": "ProcessConformanceWorker",
        "action_url": "/vendor-onboarding", "action_label": "View Vendor",
        "created_at": "2026-05-19T06:45:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"vendor": "Frontier Energy Solutions", "days": 31},
    },
    # Pending approvals
    {
        "id": "ntf-003", "category": "approval", "severity": "high",
        "title": "AWS access request pending CISO approval — Yuki Tanaka",
        "body": "David Park requested AWS Console access for Yuki Tanaka (Senior Engineer). CISO approval required. SLA: 3-5 business days.",
        "source_agent": "ITAccessAgent",
        "action_url": "/it-access", "action_label": "Review Request",
        "created_at": "2026-05-18T16:22:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"requester": "david.park@acme-corp.com", "system": "AWS Console"},
    },
    {
        "id": "ntf-004", "category": "approval", "severity": "high",
        "title": "Workday access request pending CISO approval — Elena Kovacs",
        "body": "Rachel Foster requested Workday HCM access for Elena Kovacs (Finance Director). Sensitive system — CISO sign-off required.",
        "source_agent": "ITAccessAgent",
        "action_url": "/it-access", "action_label": "Review Request",
        "created_at": "2026-05-18T14:10:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"requester": "rachel.foster@acme-corp.com", "system": "Workday HCM"},
    },
    {
        "id": "ntf-005", "category": "approval", "severity": "high",
        "title": "Okta Admin access pending CISO — it-admin@acme-corp.com",
        "body": "Nina Lee requested Okta Admin access for IT admin account. Highest-risk system class. Board-level visibility recommended.",
        "source_agent": "ITAccessAgent",
        "action_url": "/it-access", "action_label": "Review Request",
        "created_at": "2026-05-18T11:05:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"system": "Okta Admin", "tier": "ciso"},
    },
    # Churn risk
    {
        "id": "ntf-006", "category": "churn_risk", "severity": "critical",
        "title": "ConsultancyCo submitted cancellation request — $36K ARR at risk",
        "body": "Customer email: 'We've decided not to renew. Contract ends June 30th.' No prior at-risk flag. Immediate CS escalation needed.",
        "source_agent": "CommunicationAgent",
        "action_url": "/communications", "action_label": "View Message",
        "created_at": "2026-05-19T08:01:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"customer": "ConsultancyCo", "arr": 36000, "contract_end": "2026-06-30"},
    },
    {
        "id": "ntf-007", "category": "churn_risk", "severity": "high",
        "title": "Enterprise Client Corp reporting API latency — $180K ARR, renewal next month",
        "body": "CTO email: 'Significant API latency since Tuesday, blocking our integration team. We're evaluating renewal next month.'",
        "source_agent": "CommunicationAgent",
        "action_url": "/communications", "action_label": "View Message",
        "created_at": "2026-05-19T07:30:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"customer": "Enterprise Client Corp", "arr": 180000},
    },
    # Renewal alerts
    {
        "id": "ntf-008", "category": "renewal", "severity": "high",
        "title": "Salesforce license renewal in 18 days — $150K/yr",
        "body": "LicenseManagementWorker: Salesforce contract expires June 6, 2026. 8 licenses at $150/mo each. No renewal initiated.",
        "source_agent": "LicenseManagementWorker",
        "action_url": "/insights", "action_label": "View License",
        "created_at": "2026-05-19T06:00:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"vendor": "Salesforce", "expiry": "2026-06-06", "annual_value": 14400},
    },
    {
        "id": "ntf-009", "category": "renewal", "severity": "medium",
        "title": "eCommerce Shop contract renewal — 43 days, $31K ARR",
        "body": "RenewalWorkflowWorker: eCommerce Shop contract up July 1. Customer asked about annual discount (15%). No renewal discussion initiated.",
        "source_agent": "RenewalWorkflowWorker",
        "action_url": "/communications", "action_label": "View Request",
        "created_at": "2026-05-18T09:00:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"customer": "eCommerce Shop", "arr": 31000, "days_to_renewal": 43},
    },
    # Agent actions
    {
        "id": "ntf-010", "category": "agent_action", "severity": "info",
        "title": "PortalAccessAgent resolved 4 login issues automatically",
        "body": "4 portal access tickets resolved: 2 account unlocks, 1 MFA reset, 1 new user provisioning. No human action required.",
        "source_agent": "PortalAccessAgent",
        "action_url": "/portal-access", "action_label": "View Activity",
        "created_at": "2026-05-19T05:30:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"resolved": 4, "auto": True},
    },
    {
        "id": "ntf-011", "category": "agent_action", "severity": "info",
        "title": "DDQAgent drafted response for Apex Capital — 10 questions, 9 High confidence",
        "body": "Due diligence questionnaire from Apex Capital processed. 9/10 answers at High confidence. 1 requires review (ISO 27001 status).",
        "source_agent": "DDQAgent",
        "action_url": "/ddq", "action_label": "Review Draft",
        "created_at": "2026-05-18T17:45:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"customer": "Apex Capital", "questions": 10, "high_confidence": 9},
    },
    {
        "id": "ntf-012", "category": "agent_action", "severity": "info",
        "title": "PayrollDocumentAgent fulfilled 3 W2 requests",
        "body": "sarah.chen, elena.kovacs, and james.rodriguez successfully retrieved their 2024 W2 documents via self-service.",
        "source_agent": "PayrollDocumentAgent",
        "action_url": "/payroll-documents", "action_label": "View Activity",
        "created_at": "2026-05-18T14:20:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"requests": 3, "document_type": "W2"},
    },
    # Findings
    {
        "id": "ntf-013", "category": "finding", "severity": "high",
        "title": "Pipeline concentration risk — top 3 deals = 31% of weighted pipeline",
        "body": "PipelineVelocityWorker: 3 deals worth $2.16M represent 31% of weighted pipeline. Loss of any single deal materially impacts Q2.",
        "source_agent": "PipelineVelocityWorker",
        "action_url": "/insights", "action_label": "View Finding",
        "created_at": "2026-05-18T08:00:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"concentration_pct": 31, "at_risk_value": 2160000},
    },
    {
        "id": "ntf-014", "category": "finding", "severity": "high",
        "title": "7 open engineering requisitions — 18-week avg fill time",
        "body": "HeadcountEfficiencyWorker: 7 unfilled engineering roles averaging 18 weeks to fill. Feature velocity at risk in Q3 if not resolved.",
        "source_agent": "HeadcountEfficiencyWorker",
        "action_url": "/insights", "action_label": "View Finding",
        "created_at": "2026-05-18T07:45:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"open_reqs": 7, "avg_fill_weeks": 18},
    },
    {
        "id": "ntf-015", "category": "churn_risk", "severity": "high",
        "title": "ScaleUp Inc struggling with onboarding — 2 weeks, no insights yet",
        "body": "Slack message: 'We connected Salesforce 2 weeks ago but still haven't gotten any meaningful insights. Can someone do a call?'",
        "source_agent": "CommunicationAgent",
        "action_url": "/communications", "action_label": "View Message",
        "created_at": "2026-05-18T11:30:00Z", "is_read": False, "is_dismissed": False,
        "metadata": {"customer": "ScaleUp Inc", "arr": 55000},
    },
    {
        "id": "ntf-016", "category": "agent_action", "severity": "info",
        "title": "BenefitsAgent answered 12 employee inquiries this week",
        "body": "PTO balance (5), 401k questions (4), health plan (2), open enrollment (1). 3 employees flagged for low 401k contribution (below match threshold).",
        "source_agent": "BenefitsAgent",
        "action_url": "/benefits", "action_label": "View Activity",
        "created_at": "2026-05-18T06:00:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"inquiries": 12, "action_items_flagged": 3},
    },
    {
        "id": "ntf-017", "category": "finding", "severity": "medium",
        "title": "3 API keys older than 90 days — rotation overdue",
        "body": "SecurityHygieneWorker: svc-deploy, svc-monitor, and api-gateway keys exceed the 90-day rotation policy. Rotate before risk escalates.",
        "source_agent": "SecurityHygieneWorker",
        "action_url": "/insights", "action_label": "View Finding",
        "created_at": "2026-05-17T09:00:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"stale_keys": 3, "max_age_days": 90},
    },
    {
        "id": "ntf-018", "category": "approval", "severity": "medium",
        "title": "Salesforce access pending manager approval — Tom Walsh",
        "body": "James Rodriguez requested Salesforce CRM access for Tom Walsh (Account Executive). Manager approval required. In queue 3 days.",
        "source_agent": "ITAccessAgent",
        "action_url": "/it-access", "action_label": "Review Request",
        "created_at": "2026-05-16T10:15:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"requester": "james.rodriguez@acme-corp.com", "target": "tom.walsh@acme-corp.com"},
    },
    {
        "id": "ntf-019", "category": "agent_action", "severity": "info",
        "title": "VendorOnboardingAgent: 3 vendors advanced to new stages",
        "body": "IntelliCore Systems advanced to erp_setup. CoreSystems Ltd advanced to banking_received. EdgePoint Analytics W9 request sent.",
        "source_agent": "VendorOnboardingAgent",
        "action_url": "/vendor-onboarding", "action_label": "View Pipeline",
        "created_at": "2026-05-17T15:30:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"vendors_advanced": 3},
    },
    {
        "id": "ntf-020", "category": "system", "severity": "info",
        "title": "Scout scan completed — 292 findings across 34 workers",
        "body": "Full tenant scan completed in 14 seconds. 8 critical, 47 high, 128 medium findings. Board report auto-updated.",
        "source_agent": "ScoutEngine",
        "action_url": "/insights", "action_label": "View Insights",
        "created_at": "2026-05-17T06:00:00Z", "is_read": True, "is_dismissed": False,
        "metadata": {"total_findings": 292, "critical": 8, "high": 47, "duration_s": 14},
    },
]

# ── In-memory state ────────────────────────────────────────────────────────────
# Keyed by (tenant_id, notification_id) → {is_read, is_dismissed}
# On restart, resets to defaults (no DB required this sprint).
_STATE: dict[tuple[str, str], dict] = {}


def _get_notifications(tenant_id: str) -> list[dict]:
    """Return the full notification list with per-tenant read/dismiss state applied."""
    result = []
    for n in MOCK_NOTIFICATIONS:
        ntf = copy.deepcopy(n)
        ntf["tenant_id"] = tenant_id
        key = (tenant_id, n["id"])
        if key in _STATE:
            ntf["is_read"] = _STATE[key]["is_read"]
            ntf["is_dismissed"] = _STATE[key]["is_dismissed"]
        result.append(ntf)
    return result


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _sort_key(n: dict) -> tuple:
    """Unread first, then severity, then newest first."""
    return (
        1 if n["is_read"] else 0,
        SEVERITY_ORDER.get(n["severity"], 99),
        n["created_at"],  # lexicographic desc handled by negation below
    )


def get_summary(tenant_id: str) -> dict:
    """Build a NotificationSummary for a tenant."""
    notifications = _get_notifications(tenant_id)
    unread = [n for n in notifications if not n["is_read"] and not n["is_dismissed"]]

    by_category: dict[str, int] = {}
    for n in unread:
        by_category[n["category"]] = by_category.get(n["category"], 0) + 1

    critical_unread = [n for n in unread if n["severity"] == "critical"]

    # Top priority: lowest severity_order, then newest
    top_priority = None
    if unread:
        top_priority = sorted(
            unread,
            key=lambda n: (SEVERITY_ORDER.get(n["severity"], 99), n["created_at"]),
        )[0]
        # Reverse created_at for tie-breaking (newest wins)
        top_priority = sorted(
            [x for x in unread if x["severity"] == top_priority["severity"]],
            key=lambda n: n["created_at"],
            reverse=True,
        )[0]

    return {
        "total_unread": len(unread),
        "critical_unread": len(critical_unread),
        "by_category": by_category,
        "top_priority": top_priority,
    }


# ── Pydantic models ────────────────────────────────────────────────────────────

class MarkAllReadBody(BaseModel):
    tenant_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("")
def list_notifications(
    tenant_id: str = Query(...),
    unread_only: bool = Query(False),
    category: Optional[str] = Query(None),
) -> list[dict]:
    notifications = _get_notifications(tenant_id)
    # Filter dismissed
    notifications = [n for n in notifications if not n["is_dismissed"]]
    if unread_only:
        notifications = [n for n in notifications if not n["is_read"]]
    if category:
        notifications = [n for n in notifications if n["category"] == category]
    # Sort: unread first, then severity, then newest
    notifications.sort(
        key=lambda n: (
            1 if n["is_read"] else 0,
            SEVERITY_ORDER.get(n["severity"], 99),
            # Negate string sort: use reverse=False but prefix with negative epoch
        )
    )
    # Secondary sort: within same (read, severity) bucket, newest first
    notifications = sorted(
        notifications,
        key=lambda n: (
            1 if n["is_read"] else 0,
            SEVERITY_ORDER.get(n["severity"], 99),
            # Python sorts strings lex; ISO timestamps sort correctly desc when negated
            # We'll just use a tuple and sort newest-first as third key in reverse
        ),
    )
    # Apply created_at desc within groups using a stable two-pass sort
    notifications = sorted(
        notifications,
        key=lambda n: n["created_at"],
        reverse=True,
    )
    notifications = sorted(
        notifications,
        key=lambda n: (
            1 if n["is_read"] else 0,
            SEVERITY_ORDER.get(n["severity"], 99),
        ),
    )
    return notifications


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: str,
    tenant_id: str = Query(...),
) -> dict:
    # Verify notification exists
    ids = {n["id"] for n in MOCK_NOTIFICATIONS}
    if notification_id not in ids:
        raise HTTPException(status_code=404, detail="Notification not found")
    key = (tenant_id, notification_id)
    existing = _STATE.get(key, {})
    _STATE[key] = {**existing, "is_read": True, "is_dismissed": existing.get("is_dismissed", False)}
    return {"success": True}


@router.post("/read-all")
def mark_all_read(body: MarkAllReadBody) -> dict:
    tenant_id = body.tenant_id
    count = 0
    for n in MOCK_NOTIFICATIONS:
        key = (tenant_id, n["id"])
        existing = _STATE.get(key, {})
        if not existing.get("is_read", n["is_read"]):
            _STATE[key] = {**existing, "is_read": True, "is_dismissed": existing.get("is_dismissed", n["is_dismissed"])}
            count += 1
    return {"marked": count}


@router.post("/{notification_id}/dismiss")
def dismiss_notification(
    notification_id: str,
    tenant_id: str = Query(...),
) -> dict:
    ids = {n["id"] for n in MOCK_NOTIFICATIONS}
    if notification_id not in ids:
        raise HTTPException(status_code=404, detail="Notification not found")
    key = (tenant_id, notification_id)
    existing = _STATE.get(key, {})
    _STATE[key] = {**existing, "is_read": existing.get("is_read", True), "is_dismissed": True}
    return {"success": True}


@router.get("/summary")
def notification_summary(tenant_id: str = Query(...)) -> dict:
    return get_summary(tenant_id)
