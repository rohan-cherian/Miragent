"""
scout/actions/factory.py — Worker Action Factory (Sprint 26)

Workers surface findings. This module turns findings into executor-ready
RemediationAction rows — complete with the exact payload the executor needs
to write back to the source system.

Design:
  Workers call ActionFactory.from_finding() with the finding data and any
  known source-system IDs. The factory constructs a RemediationAction that
  includes:

    action_type          — which executor to call (reassign_accounts, etc.)
    evidence_source      — which system to write to (sfdc, workday, netsuite)
    evidence_target_ids  — which records to operate on
    execution_payload    — the exact parameters the executor needs
    arr_impact           — estimated ARR impact (for playbook condition checks)
    effort / timeframe   — for the assignee dashboard

  The execution_runner.py already reads execution_payload and passes it
  directly to the executor — no more guessing from generic metadata.

Worker integration pattern:
  At the end of each worker's analysis, after findings are generated,
  the worker calls ActionFactory to emit actions for findings that
  warrant autonomous remediation. These are persisted to the DB and
  picked up by the execution scanner on the next cycle.

  Workers that already have specific IDs (e.g., account IDs from SFDC)
  pass them directly. Workers operating on graph data extrapolate IDs
  from the neo4j records they already queried.

Supported action types by worker:

  HireToRetireWorker:
    - reassign_accounts       (departed rep → accounts to redistribute)
    - deprovision_access      (terminated employee → offboard in Workday)
    - send_onboarding_tasks   (new hire → trigger onboarding sequence)

  IssueToResolutionWorker:
    - update_opportunity_stage (stalled deal → advance or flag)
    - log_activity             (stale deal → log a follow-up task)

  VendorBenchmarkWorker:
    - approve_po               (pending PO in negotiation window)
    - flag_vendor_invoice      (overpaying vendor → flag for finance)
    - route_for_approval       (contract renewal → route through workflow)

  LeadToCashWorker:
    - update_opportunity_stage (stuck lead → advance stage)
    - log_activity             (uncontacted lead → log outreach task)

  ProcessBottleneckWorker:
    - route_for_approval       (blocked document → route to approver)

  OffboardingWorker:
    - deprovision_access       (departed employee → immediate offboarding)
    - reassign_accounts        (departed rep → redistribute accounts)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from scout.db.models import RemediationAction

logger = logging.getLogger(__name__)

# Default due-date offsets by timeframe
_TIMEFRAME_DAYS: dict[str, int] = {
    "IMMEDIATE": 1,
    "SHORT": 7,
    "MEDIUM": 30,
    "LONG": 90,
}


@dataclass
class ActionSpec:
    """
    Everything needed to create one RemediationAction row.

    Workers build these and pass them to ActionFactory.persist().
    Keeping this as a plain dataclass means workers don't need to
    import SQLAlchemy or know about the DB schema.
    """

    # Core identification
    action_type: str               # reassign_accounts | log_activity | etc.
    title: str                     # short headline shown in the dashboard
    description: str               # full context for the assignee

    # Routing
    evidence_source: str           # sfdc | workday | netsuite
    evidence_query_type: str       # for the evidence scanner to verify completion
    evidence_target_ids: list[str] # IDs in the source system

    # Executor payload — exact parameters the executor needs
    execution_payload: dict[str, Any] = field(default_factory=dict)

    # Assignment + prioritisation
    assigned_to_email: str | None = None
    effort: str = "MEDIUM"         # LOW | MEDIUM | HIGH
    timeframe: str = "SHORT"       # IMMEDIATE | SHORT | MEDIUM | LONG
    arr_impact: float | None = None

    # Linking
    finding_hash: str = ""
    worker_name: str = ""


class ActionFactory:
    """
    Converts worker findings into persistent, executor-ready RemediationActions.

    Usage:
        factory = ActionFactory(db, tenant_id="acme-corp")

        # From HireToRetireWorker when a rep departs:
        factory.emit(ActionSpec(
            action_type="reassign_accounts",
            title="Reassign 12 accounts from Sarah Chen (departed)",
            description="Sarah Chen left on 2026-05-14. 12 open accounts need reassignment.",
            evidence_source="sfdc",
            evidence_query_type="account_owner_changed",
            evidence_target_ids=["001AB", "001CD", ...],
            execution_payload={
                "new_owner_id": "005XY",   # VP Sales SFDC User.Id
                "departed_rep_id": "005AB",
            },
            timeframe="IMMEDIATE",
            arr_impact=340000.0,
            finding_hash="h-hire-retire-sarah-chen",
            worker_name="HireToRetireWorker",
        ))

        factory.flush()  # write all emitted actions to DB
    """

    def __init__(self, db: Session, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self._pending: list[ActionSpec] = []

    def emit(self, spec: ActionSpec) -> None:
        """Queue an action for persistence. Call flush() to write."""
        self._pending.append(spec)

    def flush(self) -> list[str]:
        """
        Write all queued ActionSpecs to the DB.
        Returns the list of created action IDs.
        Skips specs where an identical (tenant_id, finding_hash, action_type)
        row already exists — prevents duplicate actions on repeated worker runs.
        """
        created_ids: list[str] = []
        for spec in self._pending:
            action_id = self._persist_one(spec)
            if action_id:
                created_ids.append(action_id)
        self._pending.clear()
        return created_ids

    def _persist_one(self, spec: ActionSpec) -> str | None:
        """Write one ActionSpec to the DB. Returns the action ID or None if skipped."""
        from sqlalchemy import select

        # Idempotency: skip if this (tenant, finding_hash, action_type) already exists
        if spec.finding_hash:
            existing = self.db.execute(
                select(RemediationAction).where(
                    RemediationAction.tenant_id == self.tenant_id,
                    RemediationAction.finding_hash == spec.finding_hash,
                    RemediationAction.action_type == spec.action_type,
                    RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}),
                )
            ).scalar_one_or_none()
            if existing:
                logger.debug(
                    f"Skipping duplicate action {spec.action_type} for {spec.finding_hash}"
                )
                return None

        due_date = datetime.now(timezone.utc) + timedelta(
            days=_TIMEFRAME_DAYS.get(spec.timeframe, 7)
        )

        action = RemediationAction(
            tenant_id=self.tenant_id,
            finding_hash=spec.finding_hash,
            worker_name=spec.worker_name,
            title=spec.title,
            description=spec.description,
            action_type=spec.action_type,
            assigned_to_email=spec.assigned_to_email,
            effort=spec.effort,
            timeframe=spec.timeframe,
            arr_impact=spec.arr_impact,
            status="OPEN",
            due_date=due_date,
            evidence_source=spec.evidence_source,
            evidence_query_type=spec.evidence_query_type,
            evidence_target_ids=spec.evidence_target_ids,
            execution_payload=spec.execution_payload,
        )
        self.db.add(action)
        self.db.flush()  # get ID without committing
        logger.info(
            f"ActionFactory: created {spec.action_type} action {action.id} "
            f"for tenant {self.tenant_id}"
        )
        return action.id


# ── Pre-built action specs for common findings ─────────────────────────────────


def departed_rep_reassignment(
    finding_hash: str,
    worker_name: str,
    rep_name: str,
    rep_sfdc_id: str,
    account_ids: list[str],
    new_owner_sfdc_id: str | None,
    arr_at_risk: float,
    assigned_to_email: str | None = None,
) -> ActionSpec:
    """
    Pre-built spec for reassigning accounts when a rep departs.

    new_owner_sfdc_id: the SFDC User.Id to reassign accounts to.
    If None, the executor will need a human to supply it — action goes
    to approval queue automatically via the HIGH risk playbook default.
    """
    n = len(account_ids)
    return ActionSpec(
        action_type="reassign_accounts",
        title=f"Reassign {n} account{'s' if n != 1 else ''} from {rep_name} (departed)",
        description=(
            f"{rep_name} has left the organisation. "
            f"{n} open account{'s' if n != 1 else ''} with ${arr_at_risk:,.0f} ARR "
            f"{'are' if n != 1 else 'is'} currently unowned. "
            f"Reassign to maintain customer coverage."
        ),
        evidence_source="sfdc",
        evidence_query_type="account_owner_changed",
        evidence_target_ids=account_ids,
        execution_payload={
            "new_owner_id": new_owner_sfdc_id,
            "departed_rep_id": rep_sfdc_id,
            "notify_owner": True,
        },
        assigned_to_email=assigned_to_email,
        effort="LOW",
        timeframe="IMMEDIATE",
        arr_impact=arr_at_risk,
        finding_hash=finding_hash,
        worker_name=worker_name,
    )


def deprovision_departed_employee(
    finding_hash: str,
    worker_name: str,
    employee_name: str,
    workday_id: str,
    assigned_to_email: str | None = None,
) -> ActionSpec:
    """Pre-built spec for deprovisioning a departed employee's access."""
    return ActionSpec(
        action_type="deprovision_access",
        title=f"Deprovision system access for {employee_name} (departed)",
        description=(
            f"{employee_name} has left the organisation. "
            f"Revoke all system access in Workday to prevent security exposure. "
            f"This includes SSO, SaaS app access, and VPN credentials."
        ),
        evidence_source="workday",
        evidence_query_type="termination_processed",
        evidence_target_ids=[workday_id],
        execution_payload={"worker_id": workday_id},
        assigned_to_email=assigned_to_email,
        effort="LOW",
        timeframe="IMMEDIATE",
        finding_hash=finding_hash,
        worker_name=worker_name,
    )


def stalled_deal_followup(
    finding_hash: str,
    worker_name: str,
    opportunity_name: str,
    opportunity_id: str,
    account_id: str,
    days_stalled: int,
    owner_email: str | None = None,
    arr_at_risk: float | None = None,
) -> ActionSpec:
    """Pre-built spec for logging a follow-up task on a stalled deal."""
    return ActionSpec(
        action_type="log_activity",
        title=f"Log follow-up for stalled deal: {opportunity_name}",
        description=(
            f"'{opportunity_name}' has had no activity for {days_stalled} days. "
            f"Log a follow-up call or email to re-engage the prospect and "
            f"update the opportunity stage."
        ),
        evidence_source="sfdc",
        evidence_query_type="meeting_logged",
        evidence_target_ids=[opportunity_id, account_id],
        execution_payload={
            "subject": f"Miragent: Follow-up required — {opportunity_name}",
            "description": (
                f"This deal has been stalled for {days_stalled} days. "
                f"Miragent flagged it as at-risk. Please log your next step."
            ),
            "type": "Task",
        },
        assigned_to_email=owner_email,
        effort="LOW",
        timeframe="IMMEDIATE",
        arr_impact=arr_at_risk,
        finding_hash=finding_hash,
        worker_name=worker_name,
    )


def overpaying_vendor_flag(
    finding_hash: str,
    worker_name: str,
    vendor_name: str,
    invoice_ids: list[str],
    overpay_pct: float,
    annual_spend: float,
    assigned_to_email: str | None = None,
) -> ActionSpec:
    """Pre-built spec for flagging an overpaying vendor invoice."""
    return ActionSpec(
        action_type="flag_vendor_invoice",
        title=f"Flag {vendor_name} invoices — {overpay_pct:.0f}% over market benchmark",
        description=(
            f"{vendor_name} annual spend of ${annual_spend:,.0f} is "
            f"{overpay_pct:.0f}% above the market benchmark. "
            f"Finance should review before next payment cycle."
        ),
        evidence_source="netsuite",
        evidence_query_type="vendor_invoice_paid",
        evidence_target_ids=invoice_ids,
        execution_payload={
            "reason": (
                f"Miragent: {vendor_name} spend is {overpay_pct:.0f}% over market benchmark. "
                f"Hold for renegotiation review."
            ),
        },
        assigned_to_email=assigned_to_email,
        effort="LOW",
        timeframe="SHORT",
        arr_impact=annual_spend * (overpay_pct / 100),
        finding_hash=finding_hash,
        worker_name=worker_name,
    )


def comp_review_needed(
    finding_hash: str,
    worker_name: str,
    employee_name: str,
    workday_id: str,
    reason: str,
    effective_date: str,
    assigned_to_email: str | None = None,
) -> ActionSpec:
    """Pre-built spec for initiating a compensation review."""
    return ActionSpec(
        action_type="initiate_comp_review",
        title=f"Initiate compensation review for {employee_name}",
        description=(
            f"Compensation review required for {employee_name}. "
            f"Reason: {reason}. "
            f"Proposed effective date: {effective_date}."
        ),
        evidence_source="workday",
        evidence_query_type="comp_event_completed",
        evidence_target_ids=[workday_id],
        execution_payload={
            "worker_id": workday_id,
            "reason": reason,
            "effective_date": effective_date,
        },
        assigned_to_email=assigned_to_email,
        effort="MEDIUM",
        timeframe="MEDIUM",
        finding_hash=finding_hash,
        worker_name=worker_name,
    )
