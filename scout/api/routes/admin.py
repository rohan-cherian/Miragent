"""
scout/api/routes/admin.py — Admin portal API for worker threshold management.

Endpoints:
  GET  /admin/worker-configs/metadata          → full registry (defaults + UI metadata)
  GET  /admin/worker-configs                   → all worker configs for this tenant
  GET  /admin/worker-configs/{worker_name}     → one worker's merged config
  PUT  /admin/worker-configs/{worker_name}     → update thresholds / enabled flag
  DELETE /admin/worker-configs/{worker_name}   → reset to platform defaults

  GET  /admin/actions                          → all remediation actions for tenant
  GET  /admin/actions/mine                     → actions assigned to current user
  POST /admin/actions/{action_id}/disposition  → record ACTED|DISMISSED|DEFERRED|SNOOZED

All write endpoints require admin role.
Read endpoints are accessible to any authenticated user (admin or viewer).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.actions.evidence_scanner import get_action_evidence_history, run_evidence_scan
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import (
    FindingDisposition,
    NoiseProfile,
    RemediationAction,
    ThresholdProposal,
    User,
    WorkerConfig,
)
from scout.engine.noise_scanner import run_noise_scan
from scout.workers.threshold_registry import (
    DEFAULTS,
    get_defaults,
    get_metadata,
    get_worker_names,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Pydantic schemas ───────────────────────────────────────────────────────


class WorkerConfigUpdate(BaseModel):
    enabled: bool | None = None
    thresholds: dict[str, Any] = {}


class WorkerConfigResponse(BaseModel):
    worker_name: str
    enabled: bool
    thresholds: dict[str, Any]          # merged: defaults + overrides
    overrides: dict[str, Any]           # only what this tenant changed
    defaults: dict[str, Any]            # platform defaults for reference
    updated_at: datetime | None
    updated_by: str | None


class DispositionCreate(BaseModel):
    disposition: str                     # ACTED | DISMISSED | DEFERRED | SNOOZED
    reason: str | None = None
    snooze_days: int | None = None


class ActionResponse(BaseModel):
    id: str
    finding_hash: str
    worker_name: str
    title: str
    description: str
    action_type: str
    assigned_to_email: str | None
    assigned_to_name: str | None
    effort: str
    timeframe: str
    arr_impact: float | None
    status: str
    due_date: datetime | None
    evidence_source: str | None
    evidence_query_type: str | None
    completed_at: datetime | None
    completion_method: str | None
    created_at: datetime


# ── Helpers ────────────────────────────────────────────────────────────────


def _load_db_config(
    db: Session, tenant_id: str, worker_name: str
) -> WorkerConfig | None:
    return db.execute(
        select(WorkerConfig).where(
            WorkerConfig.tenant_id == tenant_id,
            WorkerConfig.worker_name == worker_name,
        )
    ).scalar_one_or_none()


def _merged_config(db_row: WorkerConfig | None, worker_name: str) -> dict[str, Any]:
    """Merge platform defaults with tenant overrides."""
    defaults = get_defaults(worker_name)
    if db_row is None:
        return defaults
    return {**defaults, **(db_row.thresholds or {}), "enabled": db_row.enabled}


def _assert_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required for this operation.",
        )


# ── Registry / metadata ────────────────────────────────────────────────────


@router.get("/worker-configs/metadata")
def get_registry_metadata() -> dict:
    """
    Return the full threshold registry: defaults and UI metadata for all workers.

    Used by the admin portal to populate slider labels, data types, min/max
    ranges, and industry benchmark indicators.
    """
    return get_metadata()


# ── Worker config CRUD ─────────────────────────────────────────────────────


@router.get("/worker-configs")
def list_worker_configs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkerConfigResponse]:
    """
    Return the merged config for every known worker for this tenant.

    Workers with no DB row return platform defaults.
    """
    tenant_id = current_user.tenant_id

    # Load all DB rows for this tenant in one query
    rows = db.execute(
        select(WorkerConfig).where(WorkerConfig.tenant_id == tenant_id)
    ).scalars().all()
    row_by_name = {r.worker_name: r for r in rows}

    result = []
    for name in get_worker_names():
        row = row_by_name.get(name)
        defaults = get_defaults(name)
        overrides = (row.thresholds or {}) if row else {}
        enabled = row.enabled if row else True

        result.append(WorkerConfigResponse(
            worker_name=name,
            enabled=enabled,
            thresholds={**defaults, **overrides, "enabled": enabled},
            overrides=overrides,
            defaults=defaults,
            updated_at=row.updated_at if row else None,
            updated_by=row.updated_by if row else None,
        ))

    return result


@router.get("/worker-configs/{worker_name}")
def get_worker_config(
    worker_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkerConfigResponse:
    """Return the merged config for one worker."""
    if worker_name not in DEFAULTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown worker: {worker_name}",
        )

    tenant_id = current_user.tenant_id
    row = _load_db_config(db, tenant_id, worker_name)
    defaults = get_defaults(worker_name)
    overrides = (row.thresholds or {}) if row else {}
    enabled = row.enabled if row else True

    return WorkerConfigResponse(
        worker_name=worker_name,
        enabled=enabled,
        thresholds={**defaults, **overrides, "enabled": enabled},
        overrides=overrides,
        defaults=defaults,
        updated_at=row.updated_at if row else None,
        updated_by=row.updated_by if row else None,
    )


@router.put("/worker-configs/{worker_name}")
def update_worker_config(
    worker_name: str,
    body: WorkerConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkerConfigResponse:
    """
    Update threshold overrides and/or enabled flag for a worker.

    Only the values present in body.thresholds are stored as overrides.
    Absent thresholds continue to use platform defaults.
    """
    _assert_admin(current_user)

    if worker_name not in DEFAULTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown worker: {worker_name}",
        )

    tenant_id = current_user.tenant_id
    row = _load_db_config(db, tenant_id, worker_name)

    if row is None:
        row = WorkerConfig(
            tenant_id=tenant_id,
            worker_name=worker_name,
            enabled=True,
            thresholds={},
        )
        db.add(row)

    # Merge new overrides into existing overrides (don't wipe unrelated keys)
    existing = dict(row.thresholds or {})
    existing.update(body.thresholds)
    row.thresholds = existing

    if body.enabled is not None:
        row.enabled = body.enabled

    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = current_user.email

    db.commit()
    db.refresh(row)

    defaults = get_defaults(worker_name)
    return WorkerConfigResponse(
        worker_name=worker_name,
        enabled=row.enabled,
        thresholds={**defaults, **row.thresholds, "enabled": row.enabled},
        overrides=row.thresholds,
        defaults=defaults,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


@router.delete("/worker-configs/{worker_name}", status_code=status.HTTP_200_OK)
def reset_worker_config(
    worker_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Reset a worker to platform defaults by deleting the tenant override row.

    After this call, the worker will use the values from threshold_registry.DEFAULTS.
    """
    _assert_admin(current_user)

    if worker_name not in DEFAULTS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown worker: {worker_name}",
        )

    tenant_id = current_user.tenant_id
    row = _load_db_config(db, tenant_id, worker_name)

    if row:
        db.delete(row)
        db.commit()

    return {"ok": True, "worker_name": worker_name, "reset_to": "platform_defaults"}


# ── Finding disposition ────────────────────────────────────────────────────


@router.post("/findings/{finding_hash}/disposition")
def record_disposition(
    finding_hash: str,
    body: DispositionCreate,
    worker_name: str = Query(...),
    severity: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Record how an executive responded to a surfaced finding.

    This powers the signal/noise feedback loop. After enough DISMISSED
    dispositions for the same worker, the system generates a threshold
    adjustment proposal (Sprint 22).

    disposition values: ACTED | DISMISSED | DEFERRED | SNOOZED
    """
    allowed = {"ACTED", "DISMISSED", "DEFERRED", "SNOOZED"}
    if body.disposition not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"disposition must be one of {sorted(allowed)}",
        )

    snooze_until = None
    if body.disposition == "SNOOZED" and body.snooze_days:
        snooze_until = datetime.now(timezone.utc) + timedelta(days=body.snooze_days)

    disp = FindingDisposition(
        tenant_id=current_user.tenant_id,
        finding_hash=finding_hash,
        worker_name=worker_name,
        severity=severity,
        disposition=body.disposition,
        reason=body.reason,
        snooze_until=snooze_until,
        disposed_by=current_user.email,
    )
    db.add(disp)
    db.commit()

    return {
        "ok": True,
        "finding_hash": finding_hash,
        "disposition": body.disposition,
        "snooze_until": snooze_until.isoformat() if snooze_until else None,
    }


@router.get("/findings/{finding_hash}/dispositions")
def get_disposition_history(
    finding_hash: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return disposition history for one finding hash (useful for debugging)."""
    rows = db.execute(
        select(FindingDisposition)
        .where(
            FindingDisposition.tenant_id == current_user.tenant_id,
            FindingDisposition.finding_hash == finding_hash,
        )
        .order_by(FindingDisposition.disposed_at.desc())
    ).scalars().all()

    return [
        {
            "disposition": r.disposition,
            "reason": r.reason,
            "disposed_by": r.disposed_by,
            "disposed_at": r.disposed_at.isoformat(),
        }
        for r in rows
    ]


# ── Remediation actions ────────────────────────────────────────────────────


@router.get("/actions")
def list_all_actions(
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ActionResponse]:
    """Admin view of all remediation actions for the tenant."""
    _assert_admin(current_user)

    q = select(RemediationAction).where(
        RemediationAction.tenant_id == current_user.tenant_id
    )
    if status_filter:
        q = q.where(RemediationAction.status == status_filter.upper())
    q = q.order_by(RemediationAction.created_at.desc())

    rows = db.execute(q).scalars().all()
    return [_action_response(r) for r in rows]


@router.get("/actions/mine")
def list_my_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ActionResponse]:
    """
    Return remediation actions assigned to the current user.

    This is the personal action dashboard — what a VP Sales or HR director
    sees when they log in to check their open responsibilities.
    """
    email = current_user.email
    q = (
        select(RemediationAction)
        .where(
            RemediationAction.tenant_id == current_user.tenant_id,
            RemediationAction.assigned_to_email == email,
            RemediationAction.status.in_(["OPEN", "IN_PROGRESS"]),
        )
        .order_by(RemediationAction.due_date.asc())
    )
    rows = db.execute(q).scalars().all()
    return [_action_response(r) for r in rows]


@router.post("/actions/{action_id}/assign")
def assign_action(
    action_id: str,
    assignee_email: str = Query(...),
    assignee_name: str = Query(""),
    due_date: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActionResponse:
    """Assign a remediation action to a specific person."""
    _assert_admin(current_user)

    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")

    row.assigned_to_email = assignee_email
    row.assigned_to_name = assignee_name
    if due_date:
        row.due_date = due_date

    db.commit()
    db.refresh(row)
    return _action_response(row)


@router.post("/actions/{action_id}/complete")
def manually_complete_action(
    action_id: str,
    notes: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActionResponse:
    """
    Manually mark an action as complete.

    The organic evidence checker (Sprint 23 background job) auto-completes
    actions when it detects changes in source systems. This endpoint is the
    fallback for actions that don't leave a detectable evidence trail
    (e.g., 'Schedule a conversation with Sarah about her career path').
    """
    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")

    row.status = "COMPLETE"
    row.completion_method = "MANUAL"
    row.completed_at = datetime.now(timezone.utc)
    row.completion_notes = notes

    db.commit()
    db.refresh(row)
    return _action_response(row)


@router.post("/actions/{action_id}/defer")
def defer_action(
    action_id: str,
    reason: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActionResponse:
    """Defer an action — acknowledged but intentionally deprioritized."""
    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found")

    row.status = "DEFERRED"
    row.completion_notes = reason
    db.commit()
    db.refresh(row)
    return _action_response(row)


def _action_response(row: RemediationAction) -> ActionResponse:
    return ActionResponse(
        id=row.id,
        finding_hash=row.finding_hash,
        worker_name=row.worker_name,
        title=row.title,
        description=row.description,
        action_type=row.action_type,
        assigned_to_email=row.assigned_to_email,
        assigned_to_name=row.assigned_to_name,
        effort=row.effort,
        timeframe=row.timeframe,
        arr_impact=row.arr_impact,
        status=row.status,
        due_date=row.due_date,
        evidence_source=row.evidence_source,
        evidence_query_type=row.evidence_query_type,
        completed_at=row.completed_at,
        completion_method=row.completion_method,
        created_at=row.created_at,
    )


# ── Sprint 22: Signal / Noise API ──────────────────────────────────────────────


class NoiseProfileResponse(BaseModel):
    worker_name: str
    signal_score: float
    dismissed_rate: float
    acted_rate: float
    total_surfaced: int
    total_acted: int
    total_dismissed: int
    active_action_cap: int
    computed_at: datetime | None


class ProposalResponse(BaseModel):
    id: str
    worker_name: str
    threshold_key: str
    current_value: float
    proposed_value: float
    direction: str
    rationale: str
    confidence: float
    dismissed_count: int
    dismissed_rate: float
    status: str
    created_at: datetime


@router.get("/noise-profiles")
def list_noise_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[NoiseProfileResponse]:
    """
    Return signal/noise profiles for all workers for this tenant.

    Used by the admin portal to show which workers are generating
    mostly signal (high acted_rate) vs. mostly noise (high dismissed_rate).
    Workers with low signal_score are candidates for threshold adjustment.
    """
    rows = db.execute(
        select(NoiseProfile).where(
            NoiseProfile.tenant_id == current_user.tenant_id
        ).order_by(NoiseProfile.signal_score.asc())
    ).scalars().all()

    return [
        NoiseProfileResponse(
            worker_name=r.worker_name,
            signal_score=round(r.signal_score, 3),
            dismissed_rate=round(r.dismissed_rate, 3),
            acted_rate=round(r.acted_rate, 3),
            total_surfaced=r.total_surfaced,
            total_acted=r.total_acted,
            total_dismissed=r.total_dismissed,
            active_action_cap=r.active_action_cap,
            computed_at=r.computed_at,
        )
        for r in rows
    ]


@router.post("/noise-profiles/refresh")
def refresh_noise_profiles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Trigger an immediate noise scan for this tenant.

    In production this runs on a schedule (every 6 hours). This endpoint
    lets admins force a refresh after making threshold changes or after
    a batch of dispositions.
    """
    _assert_admin(current_user)
    summary = run_noise_scan(db, current_user.tenant_id)
    return {"ok": True, **summary}


@router.get("/proposals")
def list_proposals(
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProposalResponse]:
    """
    Return AI-generated threshold adjustment proposals for this tenant.

    Proposals are generated by the noise scanner when a worker's dismiss
    rate exceeds 60% over a 30-day rolling window. Admins review and
    either accept (applies the change) or reject (keeps current value).
    """
    q = select(ThresholdProposal).where(
        ThresholdProposal.tenant_id == current_user.tenant_id
    )
    if status_filter:
        q = q.where(ThresholdProposal.status == status_filter.upper())
    q = q.order_by(ThresholdProposal.created_at.desc())

    rows = db.execute(q).scalars().all()
    return [_proposal_response(r) for r in rows]


@router.post("/proposals/{proposal_id}/accept")
def accept_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Accept an AI threshold proposal and apply it to the worker config.

    Applies the proposed_value to the tenant's WorkerConfig override —
    identical to what the admin portal PUT endpoint does manually. After
    acceptance, the next scan cycle uses the new threshold.
    """
    _assert_admin(current_user)

    proposal = db.get(ThresholdProposal, proposal_id)
    if not proposal or proposal.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}.")

    # Apply to WorkerConfig (same mechanism as the admin portal PUT)
    row = db.execute(
        select(WorkerConfig).where(
            WorkerConfig.tenant_id == current_user.tenant_id,
            WorkerConfig.worker_name == proposal.worker_name,
        )
    ).scalar_one_or_none()

    if row is None:
        row = WorkerConfig(
            tenant_id=current_user.tenant_id,
            worker_name=proposal.worker_name,
            enabled=True,
            thresholds={},
        )
        db.add(row)

    existing = dict(row.thresholds or {})
    existing[proposal.threshold_key] = proposal.proposed_value
    row.thresholds = existing
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = current_user.email

    proposal.status = "ACCEPTED"
    proposal.reviewed_by = current_user.email
    proposal.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    return {
        "ok": True,
        "proposal_id": proposal_id,
        "worker_name": proposal.worker_name,
        "threshold_key": proposal.threshold_key,
        "applied_value": proposal.proposed_value,
    }


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reject an AI threshold proposal — keeps the current value unchanged."""
    _assert_admin(current_user)

    proposal = db.get(ThresholdProposal, proposal_id)
    if not proposal or proposal.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if proposal.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}.")

    proposal.status = "REJECTED"
    proposal.reviewed_by = current_user.email
    proposal.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    return {"ok": True, "proposal_id": proposal_id, "status": "REJECTED"}


# ── Sprint 23: Evidence trail API ─────────────────────────────────────────────


@router.get("/actions/{action_id}/evidence")
def get_evidence_trail(
    action_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """
    Return the full evidence check history for one action.

    Shows every time the evidence scanner checked for completion, what
    it found, and any errors. Used by the admin portal "Evidence Trail"
    panel to give visibility into why an action is still OPEN.
    """
    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found.")

    return get_action_evidence_history(db, action_id, current_user.tenant_id)


@router.post("/actions/{action_id}/recheck")
def recheck_action_evidence(
    action_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Immediately re-run the evidence check for one action.

    Useful after an admin manually updates a source system and wants to
    confirm the completion is detected without waiting for the next
    scheduled scan cycle.
    """
    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found.")

    if row.status in ("COMPLETE", "CANCELLED", "DEFERRED"):
        return {
            "ok": True,
            "action_id": action_id,
            "status": row.status,
            "message": "Action is already in a terminal state — no check needed.",
        }

    # Run with no connectors — returns NOT_YET for all sources
    # In production, the scheduler injects live connectors.
    # This endpoint is primarily for testing the plumbing.
    from scout.actions.evidence_scanner import _check_one_action
    result_key = _check_one_action(db, row, connector_map={})
    db.commit()

    return {
        "ok": True,
        "action_id": action_id,
        "check_result": result_key,
        "new_status": row.status,
    }


def _proposal_response(row: ThresholdProposal) -> ProposalResponse:
    return ProposalResponse(
        id=row.id,
        worker_name=row.worker_name,
        threshold_key=row.threshold_key,
        current_value=row.current_value,
        proposed_value=row.proposed_value,
        direction=row.direction,
        rationale=row.rationale,
        confidence=row.confidence,
        dismissed_count=row.dismissed_count,
        dismissed_rate=row.dismissed_rate,
        status=row.status,
        created_at=row.created_at,
    )


# ── Sprint 24: Playbook + Approval Gate API ────────────────────────────────────


class PlaybookRuleUpdate(BaseModel):
    risk_tier: str                     # LOW | MEDIUM | HIGH | BLOCKED
    auto_execute: bool = False
    conditions: dict[str, Any] = {}


class ApprovalRequestResponse(BaseModel):
    id: str
    action_id: str
    action_type: str
    risk_tier: str
    rationale: str
    status: str
    proposed_payload: dict[str, Any]
    expires_at: datetime | None
    created_at: datetime


@router.get("/playbook")
def get_playbook(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """
    Return the full operational playbook for this tenant.

    Shows all supported action types, their current risk tiers, whether
    auto-execution is enabled, and any conditions that bound autonomous
    execution. Used by the admin portal Playbook page.
    """
    from scout.actions.playbook import get_playbook as _get_playbook
    return _get_playbook(db, current_user.tenant_id)


@router.put("/playbook/{action_type}")
def update_playbook_rule(
    action_type: str,
    body: PlaybookRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Update the playbook rule for one action type.

    This is how admins grant the agent permission to execute actions
    autonomously. Setting risk_tier=LOW and auto_execute=True means the
    agent acts immediately without human approval.

    Example: allow auto-reassignment of ≤10 accounts under $25k ARR impact:
      PUT /admin/playbook/reassign_accounts
      {"risk_tier": "MEDIUM", "auto_execute": true,
       "conditions": {"max_accounts_affected": 10, "max_arr_impact": 25000}}
    """
    _assert_admin(current_user)

    from scout.actions.playbook import PLATFORM_DEFAULTS, upsert_rule
    if action_type not in PLATFORM_DEFAULTS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown action type: '{action_type}'. "
                   f"Valid types: {sorted(PLATFORM_DEFAULTS.keys())}",
        )

    valid_tiers = {"LOW", "MEDIUM", "HIGH", "BLOCKED"}
    if body.risk_tier not in valid_tiers:
        raise HTTPException(
            status_code=422,
            detail=f"risk_tier must be one of {sorted(valid_tiers)}",
        )

    rule = upsert_rule(
        db=db,
        tenant_id=current_user.tenant_id,
        action_type=action_type,
        risk_tier=body.risk_tier,
        auto_execute=body.auto_execute,
        conditions=body.conditions,
        updated_by=current_user.email,
    )

    return {
        "ok": True,
        "action_type": action_type,
        "risk_tier": rule.risk_tier,
        "auto_execute": rule.auto_execute,
        "conditions": rule.conditions,
        "updated_by": rule.updated_by,
    }


@router.get("/approvals")
def list_approvals(
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApprovalRequestResponse]:
    """
    Return pending (and recent) agent approval requests for this tenant.

    This is the approver's inbox — where executives or IT admins see what
    the agent wants to do and decide whether to approve or reject.
    """
    _assert_admin(current_user)

    from scout.db.models import ApprovalRequest as AR
    q = select(AR).where(AR.tenant_id == current_user.tenant_id)
    if status_filter:
        q = q.where(AR.status == status_filter.upper())
    q = q.order_by(AR.created_at.desc())

    rows = db.execute(q).scalars().all()
    return [_approval_request_response(r) for r in rows]


@router.post("/approvals/{approval_id}/approve")
def approve_request(
    approval_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Approve an agent's request to execute an action.

    After approval, the action is queued for execution on the next scan
    cycle (or immediately if POST /admin/actions/{id}/execute is called).
    """
    _assert_admin(current_user)

    from scout.db.models import ApprovalRequest as AR
    req = db.get(AR, approval_id)
    if not req or req.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if req.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Request already {req.status}.")

    req.status = "APPROVED"
    req.reviewed_by = current_user.email
    req.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "ok": True,
        "approval_id": approval_id,
        "status": "APPROVED",
        "message": "Action approved. Will execute on next scan cycle.",
    }


@router.post("/approvals/{approval_id}/reject")
def reject_request(
    approval_id: str,
    reason: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reject an agent's request — the action stays OPEN for manual handling."""
    _assert_admin(current_user)

    from scout.db.models import ApprovalRequest as AR
    req = db.get(AR, approval_id)
    if not req or req.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Approval request not found.")
    if req.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Request already {req.status}.")

    req.status = "REJECTED"
    req.reviewed_by = current_user.email
    req.reviewed_at = datetime.now(timezone.utc)
    req.rejection_reason = reason
    db.commit()

    return {"ok": True, "approval_id": approval_id, "status": "REJECTED"}


# ── Sprint 25: Autonomous Execution API ───────────────────────────────────────


@router.post("/actions/{action_id}/execute")
def execute_action(
    action_id: str,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Trigger immediate execution of a remediation action.

    With dry_run=true: validates everything and returns what would happen
    without writing to any source system. Use this to test playbook rules.

    Without dry_run: runs the full pipeline — playbook check → approval
    gate → executor → execution log.

    If the action requires approval, an ApprovalRequest is created and
    returned. If the action can auto-execute, it runs immediately.
    """
    _assert_admin(current_user)

    from scout.actions.execution_runner import run_action
    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found.")

    if row.status in ("COMPLETE", "CANCELLED"):
        return {
            "ok": False,
            "message": f"Action is already {row.status} — cannot execute.",
            "action_id": action_id,
        }

    result = run_action(db, row, connector_map={}, dry_run=dry_run)
    return {"ok": True, "action_id": action_id, **result}


@router.get("/actions/{action_id}/execution-log")
def get_execution_log(
    action_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """
    Return the full execution log for one action — every attempt, outcome, and payload.

    The compliance layer: shows exactly what the agent did, when, on whose
    authority, and what the source system returned.
    """
    row = db.get(RemediationAction, action_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Action not found.")

    from scout.db.models import ExecutionLog as EL
    logs = db.execute(
        select(EL)
        .where(EL.action_id == action_id)
        .order_by(EL.executed_at.desc())
    ).scalars().all()

    return [
        {
            "id": l.id,
            "action_type": l.action_type,
            "source_system": l.source_system,
            "result": l.result,
            "result_detail": l.result_detail,
            "executed_by": l.executed_by,
            "executed_at": l.executed_at.isoformat(),
            "approval_request_id": l.approval_request_id,
            "target_ids": l.target_ids,
            "payload": l.payload,
        }
        for l in logs
    ]


@router.post("/actions/execute-scan")
def trigger_execution_scan(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Trigger an immediate execution scan for all open actions.

    Runs the full pipeline for every OPEN/IN_PROGRESS action:
    - Executes already-approved actions
    - Runs playbook evaluation for new actions
    - Requests approval or auto-executes based on playbook rules

    In production, this runs on a schedule (every 4 hours). Use this
    endpoint to trigger immediately after updating a playbook rule.
    """
    _assert_admin(current_user)

    from scout.actions.execution_runner import run_execution_scan
    summary = run_execution_scan(db, current_user.tenant_id, connector_map={})
    return {"ok": True, **summary}


def _approval_request_response(row: Any) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=row.id,
        action_id=row.action_id,
        action_type=row.action_type,
        risk_tier=row.risk_tier,
        rationale=row.rationale,
        status=row.status,
        proposed_payload=row.proposed_payload or {},
        expires_at=row.expires_at,
        created_at=row.created_at,
    )
