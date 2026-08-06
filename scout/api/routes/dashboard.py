"""
scout/api/routes/dashboard.py — Client Dashboard API (Sprint 28)

Aggregation endpoints that power the Miragent client-facing dashboard.
All endpoints are read-only and designed to serve the dashboard's four
primary views:

  1. SUMMARY PANEL — headline numbers (open actions, arr at risk, approvals pending)
  2. SIGNAL/NOISE SCORECARDS — per-worker signal quality and WIP caps
  3. APPROVALS INBOX — pending human approvals with proposed payloads
  4. ACTIONS LIST — open/in-progress actions with filter/sort controls

Authentication:
  All endpoints require a valid JWT (get_current_user dependency).
  Tenants only see data scoped to their tenant_id.

Design principles:
  - Every endpoint returns pre-aggregated data (no N+1 queries)
  - Responses are pagination-ready (limit/offset on list endpoints)
  - All monetary values are in USD; all dates are UTC ISO-8601
  - Fields are snake_case (Python → camelCase is the frontend's concern)

Endpoint summary:
  GET /dashboard/summary          — headline KPIs for the tenant
  GET /dashboard/signal-scores    — per-worker signal quality scores
  GET /dashboard/actions          — paginated list of open actions
  GET /dashboard/actions/{id}     — single action detail + execution log
  GET /dashboard/approvals        — pending ApprovalRequests
  GET /dashboard/approvals/{id}   — single approval detail
  GET /dashboard/webhook-activity — recent webhook events (last 7 days)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import (
    ApprovalRequest,
    ExecutionLog,
    NoiseProfile,
    RemediationAction,
    User,
    WebhookEvent,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ── Response models ────────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    tenant_id: str
    open_actions: int
    in_progress_actions: int
    completed_actions_30d: int
    pending_approvals: int
    total_arr_at_risk: float
    auto_completed_30d: int
    webhook_completed_30d: int
    human_completed_30d: int
    avg_action_age_days: float | None
    generated_at: str  # ISO-8601 UTC


class WorkerSignalScore(BaseModel):
    worker_name: str
    signal_score: float | None
    acted_rate: float | None
    dismissed_rate: float | None
    active_action_cap: int | None
    total_surfaced: int | None
    last_updated: str | None


class ActionSummary(BaseModel):
    id: str
    action_type: str
    title: str
    status: str
    effort: str | None
    timeframe: str | None
    arr_impact: float | None
    evidence_source: str | None
    worker_name: str | None
    assigned_to_email: str | None
    due_date: str | None
    created_at: str | None


class ActionDetail(BaseModel):
    id: str
    action_type: str
    title: str
    description: str | None
    status: str
    effort: str | None
    timeframe: str | None
    arr_impact: float | None
    evidence_source: str | None
    evidence_query_type: str | None
    evidence_target_ids: list[str]
    execution_payload: dict[str, Any]
    worker_name: str | None
    finding_hash: str | None
    assigned_to_email: str | None
    due_date: str | None
    completed_at: str | None
    completion_method: str | None
    completion_notes: str | None
    created_at: str | None
    execution_logs: list[dict]


class ApprovalSummary(BaseModel):
    id: str
    action_id: str
    action_type: str
    risk_tier: str | None
    rationale: str | None
    status: str
    requested_by: str | None
    reviewed_by: str | None
    expires_at: str | None
    created_at: str | None


class WebhookActivitySummary(BaseModel):
    total_events: int
    done_events: int
    failed_events: int
    ignored_events: int
    actions_triggered_total: int
    by_source: dict[str, int]
    by_status: dict[str, int]


class PaginatedActions(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ActionSummary]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Tenant dashboard headline KPIs",
)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DashboardSummary:
    """
    Returns the headline KPIs for the tenant dashboard:
      - Open / in-progress / completed action counts
      - Pending approval count
      - Total ARR at risk across all open actions
      - Completion breakdown by method (auto, webhook, human)
      - Average action age in days

    All counts are scoped to the authenticated user's tenant.
    Completed counts cover the last 30 days.
    """
    tenant_id = current_user.tenant_id
    cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)

    # Status counts
    status_rows = db.execute(
        select(RemediationAction.status, func.count().label("cnt"))
        .where(RemediationAction.tenant_id == tenant_id)
        .group_by(RemediationAction.status)
    ).all()
    status_counts: dict[str, int] = {row.status: row.cnt for row in status_rows}

    open_actions = status_counts.get("OPEN", 0)
    in_progress = status_counts.get("IN_PROGRESS", 0)

    # Completed in last 30 days
    completed_30d_rows = db.execute(
        select(
            RemediationAction.completion_method,
            func.count().label("cnt"),
        )
        .where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.status == "COMPLETE",
            RemediationAction.completed_at >= cutoff_30d,
        )
        .group_by(RemediationAction.completion_method)
    ).all()
    completed_by_method: dict[str, int] = {
        (row.completion_method or "UNKNOWN"): row.cnt
        for row in completed_30d_rows
    }
    completed_30d = sum(completed_by_method.values())
    auto_completed = completed_by_method.get("AUTO", 0)
    webhook_completed = completed_by_method.get("WEBHOOK", 0)
    human_completed = completed_by_method.get("MANUAL", 0) + completed_by_method.get("HUMAN", 0)

    # ARR at risk (open + in-progress actions)
    arr_row = db.execute(
        select(func.coalesce(func.sum(RemediationAction.arr_impact), 0.0))
        .where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}),
        )
    ).scalar()
    total_arr_at_risk = float(arr_row or 0.0)

    # Pending approvals
    pending_approvals = db.execute(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.status == "PENDING",
        )
    ).scalar() or 0

    # Average action age (open + in-progress)
    open_actions_list = db.execute(
        select(RemediationAction.created_at)
        .where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}),
            RemediationAction.created_at.isnot(None),
        )
    ).scalars().all()

    avg_age: float | None = None
    if open_actions_list:
        now = datetime.now(timezone.utc)
        ages = []
        for created in open_actions_list:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            ages.append((now - created).total_seconds() / 86400)
        avg_age = round(sum(ages) / len(ages), 1)

    return DashboardSummary(
        tenant_id=tenant_id,
        open_actions=open_actions,
        in_progress_actions=in_progress,
        completed_actions_30d=completed_30d,
        pending_approvals=pending_approvals,
        total_arr_at_risk=round(total_arr_at_risk, 2),
        auto_completed_30d=auto_completed,
        webhook_completed_30d=webhook_completed,
        human_completed_30d=human_completed,
        avg_action_age_days=avg_age,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/signal-scores",
    response_model=list[WorkerSignalScore],
    summary="Per-worker signal quality scores",
)
def get_signal_scores(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkerSignalScore]:
    """
    Returns signal/noise quality scores for each worker.

    Signal score = acted_rate / (acted_rate + dismissed_rate).
    A score near 1.0 means the worker's findings are highly actionable.
    A score near 0.0 means findings are mostly dismissed (noisy).

    Results are ordered by signal_score descending (best workers first).
    """
    tenant_id = current_user.tenant_id

    profiles = db.execute(
        select(NoiseProfile)
        .where(NoiseProfile.tenant_id == tenant_id)
        .order_by(NoiseProfile.signal_score.desc())
    ).scalars().all()

    return [
        WorkerSignalScore(
            worker_name=p.worker_name,
            signal_score=round(p.signal_score, 3) if p.signal_score is not None else None,
            acted_rate=round(p.acted_rate, 3) if p.acted_rate is not None else None,
            dismissed_rate=round(p.dismissed_rate, 3) if p.dismissed_rate is not None else None,
            active_action_cap=p.active_action_cap,
            total_surfaced=p.total_surfaced,
            last_updated=_fmt(p.updated_at),
        )
        for p in profiles
    ]


@router.get(
    "/actions",
    response_model=PaginatedActions,
    summary="Paginated list of actions",
)
def list_actions(
    status: str | None = Query(default=None, description="Filter by status: OPEN|IN_PROGRESS|COMPLETE"),
    action_type: str | None = Query(default=None, description="Filter by action type"),
    worker_name: str | None = Query(default=None, description="Filter by worker"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedActions:
    """
    Paginated list of actions for the tenant.

    Filters:
      - status: OPEN | IN_PROGRESS | COMPLETE (default: all non-complete)
      - action_type: reassign_accounts | log_activity | etc.
      - worker_name: HireToRetireWorker | IssueToResolutionWorker | etc.

    Ordered by: due_date asc (most urgent first), then arr_impact desc.
    """
    tenant_id = current_user.tenant_id

    q = select(RemediationAction).where(RemediationAction.tenant_id == tenant_id)

    if status:
        q = q.where(RemediationAction.status == status.upper())
    else:
        # Default: show open and in-progress (not completed noise)
        q = q.where(RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}))

    if action_type:
        q = q.where(RemediationAction.action_type == action_type)
    if worker_name:
        q = q.where(RemediationAction.worker_name == worker_name)

    total = db.execute(
        select(func.count()).select_from(q.subquery())
    ).scalar() or 0

    actions = db.execute(
        q.order_by(
            RemediationAction.due_date.asc().nullslast(),
            RemediationAction.arr_impact.desc().nullslast(),
        )
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return PaginatedActions(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            ActionSummary(
                id=a.id,
                action_type=a.action_type,
                title=a.title,
                status=a.status,
                effort=a.effort,
                timeframe=a.timeframe,
                arr_impact=a.arr_impact,
                evidence_source=a.evidence_source,
                worker_name=a.worker_name,
                assigned_to_email=a.assigned_to_email,
                due_date=_fmt(a.due_date),
                created_at=_fmt(a.created_at),
            )
            for a in actions
        ],
    )


@router.get(
    "/actions/{action_id}",
    response_model=ActionDetail,
    summary="Single action detail with execution log",
)
def get_action_detail(
    action_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ActionDetail:
    """
    Full detail for a single action, including its execution log history.

    Used by the dashboard's action detail drawer/modal to show:
    - Full description and recommended steps
    - Execution payload (what the executor will do)
    - Evidence target IDs (which records in the source system)
    - Execution log entries (what happened when the executor ran)
    """
    from fastapi import HTTPException

    tenant_id = current_user.tenant_id
    action = db.execute(
        select(RemediationAction).where(
            RemediationAction.id == action_id,
            RemediationAction.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    logs = db.execute(
        select(ExecutionLog)
        .where(ExecutionLog.action_id == action_id)
        .order_by(ExecutionLog.executed_at.desc())
        .limit(10)
    ).scalars().all()

    log_dicts = [
        {
            "id": lg.id,
            "result": lg.result,
            "result_detail": lg.result_detail,
            "source_system": lg.source_system,
            "executed_by": lg.executed_by,
            "executed_at": _fmt(lg.executed_at),
        }
        for lg in logs
    ]

    return ActionDetail(
        id=action.id,
        action_type=action.action_type,
        title=action.title,
        description=action.description,
        status=action.status,
        effort=action.effort,
        timeframe=action.timeframe,
        arr_impact=action.arr_impact,
        evidence_source=action.evidence_source,
        evidence_query_type=action.evidence_query_type,
        evidence_target_ids=list(action.evidence_target_ids or []),
        execution_payload=dict(action.execution_payload or {}),
        worker_name=action.worker_name,
        finding_hash=action.finding_hash,
        assigned_to_email=action.assigned_to_email,
        due_date=_fmt(action.due_date),
        completed_at=_fmt(action.completed_at),
        completion_method=action.completion_method,
        completion_notes=action.completion_notes,
        created_at=_fmt(action.created_at),
        execution_logs=log_dicts,
    )


@router.get(
    "/approvals",
    response_model=list[ApprovalSummary],
    summary="Pending approval requests (inbox)",
)
def list_approvals(
    status: str = Query(default="PENDING", description="Filter by status: PENDING|APPROVED|REJECTED"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ApprovalSummary]:
    """
    Returns the approval inbox for the tenant.

    The dashboard's approval inbox shows all PENDING approval requests —
    actions the agent wants to execute but needs a human sign-off first.
    Each row includes the rationale and proposed_payload so the approver
    can make an informed decision without opening another system.
    """
    tenant_id = current_user.tenant_id

    approvals = db.execute(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.status == status.upper(),
        )
        .order_by(ApprovalRequest.created_at.desc())
        .limit(limit)
    ).scalars().all()

    return [
        ApprovalSummary(
            id=a.id,
            action_id=a.action_id,
            action_type=a.action_type,
            risk_tier=a.risk_tier,
            rationale=a.rationale,
            status=a.status,
            requested_by=a.requested_by,
            reviewed_by=a.reviewed_by,
            expires_at=_fmt(a.expires_at),
            created_at=_fmt(a.created_at),
        )
        for a in approvals
    ]


@router.get(
    "/approvals/{approval_id}",
    response_model=dict,
    summary="Approval detail with proposed payload",
)
def get_approval_detail(
    approval_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Full detail for a single approval request, including the proposed_payload.

    The proposed_payload contains the exact parameters the executor will use
    if the approval is granted — shown in the approval modal so the approver
    can verify the action is correct before approving.
    """
    from fastapi import HTTPException

    tenant_id = current_user.tenant_id
    approval = db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()

    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    return {
        "id": approval.id,
        "action_id": approval.action_id,
        "action_type": approval.action_type,
        "risk_tier": approval.risk_tier,
        "rationale": approval.rationale,
        "proposed_payload": approval.proposed_payload or {},
        "status": approval.status,
        "requested_by": approval.requested_by,
        "reviewed_by": approval.reviewed_by,
        "reviewed_at": _fmt(approval.reviewed_at),
        "expires_at": _fmt(approval.expires_at),
        "executed_at": _fmt(approval.executed_at),
        "created_at": _fmt(approval.created_at),
    }


@router.get(
    "/webhook-activity",
    response_model=WebhookActivitySummary,
    summary="Recent webhook event activity summary",
)
def get_webhook_activity(
    days: int = Query(default=7, ge=1, le=90, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WebhookActivitySummary:
    """
    Summary of webhook events received and processed in the lookback window.

    Helps the dashboard surface real-time integration health:
    - High failed count → source system is sending malformed events
    - High ignored count → new event types not yet mapped to handlers
    - actions_triggered_total → the real-time throughput of the agentic pipeline

    Grouped by source (sfdc/workday/netsuite) and status for the operations panel.
    """
    tenant_id = current_user.tenant_id
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    events = db.execute(
        select(WebhookEvent.status, WebhookEvent.source, WebhookEvent.actions_triggered)
        .where(
            WebhookEvent.tenant_id == tenant_id,
            WebhookEvent.received_at >= cutoff,
        )
    ).all()

    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    total_actions = 0

    for row in events:
        status = row.status or "UNKNOWN"
        source = row.source or "unknown"
        by_status[status] = by_status.get(status, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        total_actions += len(row.actions_triggered or [])

    return WebhookActivitySummary(
        total_events=len(events),
        done_events=by_status.get("DONE", 0),
        failed_events=by_status.get("FAILED", 0),
        ignored_events=by_status.get("IGNORED", 0),
        actions_triggered_total=total_actions,
        by_source=by_source,
        by_status=by_status,
    )
