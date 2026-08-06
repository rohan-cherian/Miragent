"""
scout/actions/execution_runner.py — Autonomous Action Orchestrator (Sprint 25)

Ties the playbook engine, approval gate, and executors together into a
single pipeline. This is the "brain" that decides whether an agent acts
immediately, requests approval, or does nothing.

Pipeline for every action:

  1. GATE CHECK — is the agent even allowed to try?
     PlaybookRule: BLOCKED → stop, log, return
     PlaybookRule: HIGH → skip to step 3 (create ApprovalRequest)

  2. CONDITION CHECK — does the context meet the auto-execute conditions?
     max_arr_impact, max_accounts_affected, business_hours_only, etc.
     Conditions fail → skip to step 3 (create ApprovalRequest)

  3. APPROVAL GATE — does a human need to sign off?
     can_auto_execute=False → create ApprovalRequest, notify approver, stop
     can_auto_execute=True  → proceed to step 4

  4. EXECUTE — call the right ActionExecutor
     SUCCESS  → mark RemediationAction COMPLETE, write ExecutionLog
     PARTIAL  → mark RemediationAction IN_PROGRESS, write ExecutionLog
     FAILURE  → leave RemediationAction status, write ExecutionLog with error

  5. POST-EXECUTE — update related evidence for future noise scoring
     Signal: action executed → the worker's signal score increases

The same pipeline runs for:
  - Scheduled automatic execution (background job, every N hours)
  - Admin-triggered "Execute Now" button (POST /admin/actions/{id}/execute)
  - Post-approval execution (when an ApprovalRequest is APPROVED)

Connector injection:
  connector_map: {source_name → connector_instance}
  Omitted sources → executor receives None → returns FAILURE (safe)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.actions.executors import (
    ACTION_SOURCE_MAP,
    ExecutionStatus,
    get_executor,
)
from scout.actions.playbook import evaluate as evaluate_playbook
from scout.db.models import ApprovalRequest, ExecutionLog, RemediationAction

logger = logging.getLogger(__name__)

# Approval requests expire after this many hours if no response
APPROVAL_EXPIRY_HOURS = 48


# ── Main pipeline ──────────────────────────────────────────────────────────────


def run_action(
    db: Session,
    action: RemediationAction,
    connector_map: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Run the full execution pipeline for one action.

    Returns a summary dict:
      {
        "outcome": "executed" | "approval_requested" | "blocked" | "dry_run" | "error",
        "detail": str,
        "execution_log_id": str | None,
        "approval_request_id": str | None,
      }
    """
    connector_map = connector_map or {}

    # Build execution context for playbook + condition evaluation
    context = _build_context(action, connector_map)

    # 1 + 2: Playbook gate + condition check
    decision = evaluate_playbook(
        db=db,
        tenant_id=action.tenant_id,
        action_type=action.action_type,
        execution_context=context,
    )

    if decision.risk_tier == "BLOCKED":
        logger.info(f"Action {action.id} blocked by playbook: {decision.blocking_reason}")
        return {
            "outcome": "blocked",
            "detail": decision.blocking_reason,
            "execution_log_id": None,
            "approval_request_id": None,
        }

    # 3: Approval gate
    if not decision.can_auto_execute:
        if dry_run:
            return {
                "outcome": "dry_run",
                "detail": f"Would request approval: {decision.blocking_reason}",
                "execution_log_id": None,
                "approval_request_id": None,
            }
        approval_id = _create_approval_request(db, action, decision, context)
        db.commit()
        return {
            "outcome": "approval_requested",
            "detail": decision.blocking_reason,
            "execution_log_id": None,
            "approval_request_id": approval_id,
        }

    # 4: Execute
    source = ACTION_SOURCE_MAP.get(action.action_type)
    executor = get_executor(action.action_type, connector_map.get(source))

    if executor is None:
        detail = f"No executor registered for action type '{action.action_type}'"
        log_id = _write_execution_log(
            db, action, source or "unknown",
            payload={}, result="FAILURE", detail=detail,
        )
        db.commit()
        return {"outcome": "error", "detail": detail, "execution_log_id": log_id, "approval_request_id": None}

    # Build the execution payload from action metadata
    payload = _build_payload(action)

    result = executor.execute(
        action_type=action.action_type,
        target_ids=list(action.evidence_target_ids or []),
        payload=payload,
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "outcome": "dry_run",
            "detail": result.detail,
            "execution_log_id": None,
            "approval_request_id": None,
        }

    # 5: Write log + update action status
    log_id = _write_execution_log(
        db, action, source or "unknown",
        payload=payload,
        result=result.status.value,
        detail=result.detail,
        error_detail=result.error_detail,
        source_system_response=result.source_system_response,
        targets_succeeded=result.targets_succeeded,
        targets_failed=result.targets_failed,
    )

    _update_action_status(action, result)
    db.commit()

    outcome_map = {
        ExecutionStatus.SUCCESS: "executed",
        ExecutionStatus.PARTIAL: "partially_executed",
        ExecutionStatus.FAILURE: "error",
        ExecutionStatus.ROLLED_BACK: "rolled_back",
    }
    return {
        "outcome": outcome_map.get(result.status, "error"),
        "detail": result.detail,
        "execution_log_id": log_id,
        "approval_request_id": None,
    }


def execute_approved_action(
    db: Session,
    approval_request: ApprovalRequest,
    connector_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute an action that was previously approved by a human.

    Called after an ApprovalRequest transitions to APPROVED.
    Bypasses the playbook gate — approval is the authorization.
    """
    connector_map = connector_map or {}
    action = db.get(RemediationAction, approval_request.action_id)
    if not action:
        return {"outcome": "error", "detail": "Action not found."}

    source = ACTION_SOURCE_MAP.get(action.action_type)
    executor = get_executor(action.action_type, connector_map.get(source))

    if executor is None:
        return {"outcome": "error", "detail": f"No executor for '{action.action_type}'"}

    payload = approval_request.proposed_payload or _build_payload(action)
    result = executor.execute(
        action_type=action.action_type,
        target_ids=list(action.evidence_target_ids or []),
        payload=payload,
    )

    log_id = _write_execution_log(
        db, action, source or "unknown",
        payload=payload,
        result=result.status.value,
        detail=result.detail,
        error_detail=result.error_detail,
        source_system_response=result.source_system_response,
        executed_by=approval_request.reviewed_by or "system",
        approval_request_id=approval_request.id,
    )

    _update_action_status(action, result)

    if result.status == ExecutionStatus.SUCCESS:
        approval_request.status = "EXECUTED"
        approval_request.executed_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "outcome": "executed" if result.status == ExecutionStatus.SUCCESS else "error",
        "detail": result.detail,
        "execution_log_id": log_id,
        "approval_request_id": approval_request.id,
    }


def run_execution_scan(
    db: Session,
    tenant_id: str,
    connector_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run the execution pipeline for all OPEN/IN_PROGRESS actions for a tenant.

    This is the batch mode — called by the background scheduler.
    Skips actions with existing PENDING approval requests (don't double-request).
    Executes approved actions.
    """
    connector_map = connector_map or {}

    # Execute already-approved actions first
    approved_requests = db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.status == "APPROVED",
        )
    ).scalars().all()

    executed = 0
    for req in approved_requests:
        result = execute_approved_action(db, req, connector_map)
        if result["outcome"] == "executed":
            executed += 1

    # Check for new actions to execute or queue for approval
    # (skip actions that already have a PENDING approval request)
    pending_action_ids = {
        row.action_id for row in db.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.status == "PENDING",
            )
        ).scalars().all()
    }

    actions = db.execute(
        select(RemediationAction).where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}),
            RemediationAction.action_type.in_(list(ACTION_SOURCE_MAP.keys())),
        )
    ).scalars().all()

    outcomes: dict[str, int] = {
        "executed": executed,
        "approval_requested": 0,
        "blocked": 0,
        "error": 0,
        "skipped_pending_approval": 0,
    }

    for action in actions:
        if action.id in pending_action_ids:
            outcomes["skipped_pending_approval"] += 1
            continue

        result = run_action(db, action, connector_map)
        key = result["outcome"] if result["outcome"] in outcomes else "error"
        outcomes[key] = outcomes.get(key, 0) + 1

    logger.info(
        f"Execution scan for {tenant_id}: {outcomes}"
    )
    return outcomes


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_context(action: RemediationAction, connector_map: dict) -> dict:
    """Build the execution context dict for playbook condition evaluation."""
    return {
        "arr_impact": action.arr_impact or 0,
        "accounts_affected": len(action.evidence_target_ids or []),
        "users_affected": len(action.evidence_target_ids or []),
        "is_business_hours": _is_business_hours(),
        "action_type": action.action_type,
        "assigned_to_email": action.assigned_to_email,
    }


def _build_payload(action: RemediationAction) -> dict:
    """
    Extract executor payload from the action's execution_payload field.

    Workers (Sprint 26+) populate action.execution_payload with the exact
    parameters the executor needs. This field is preferred over generic
    metadata. If not set, fall back to safe defaults so older actions
    (created before Sprint 26) still work.
    """
    if action.execution_payload:
        return dict(action.execution_payload)
    # Legacy fallback for actions created before Sprint 26
    return {
        "action_type": action.action_type,
        "finding_hash": action.finding_hash,
        "assigned_to_email": action.assigned_to_email,
    }


def _is_business_hours() -> bool:
    """Return True if current UTC time is approximately business hours (Mon–Fri 8–18)."""
    now = datetime.now(timezone.utc)
    return now.weekday() < 5 and 8 <= now.hour < 18


def _create_approval_request(
    db: Session,
    action: RemediationAction,
    decision: Any,
    context: dict,
) -> str:
    """Create an ApprovalRequest and return its ID."""
    payload = _build_payload(action)
    rationale = (
        f"Agent wants to execute '{action.action_type}' for finding '{action.finding_hash}'. "
        f"Reason for approval requirement: {decision.blocking_reason}. "
        f"Impact: ARR ~${context.get('arr_impact', 0):,.0f}, "
        f"{context.get('accounts_affected', 0)} records affected."
    )

    req = ApprovalRequest(
        tenant_id=action.tenant_id,
        action_id=action.id,
        action_type=action.action_type,
        risk_tier=decision.risk_tier,
        proposed_payload=payload,
        rationale=rationale,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=APPROVAL_EXPIRY_HOURS),
    )
    db.add(req)
    db.flush()  # get the ID without committing
    return req.id


def _write_execution_log(
    db: Session,
    action: RemediationAction,
    source_system: str,
    payload: dict,
    result: str,
    detail: str = "",
    error_detail: str = "",
    source_system_response: dict | None = None,
    executed_by: str = "system",
    approval_request_id: str | None = None,
    targets_succeeded: list | None = None,
    targets_failed: list | None = None,
) -> str:
    """Write an ExecutionLog row and return its ID."""
    all_targets = list(action.evidence_target_ids or [])
    log = ExecutionLog(
        tenant_id=action.tenant_id,
        action_id=action.id,
        approval_request_id=approval_request_id,
        action_type=action.action_type,
        source_system=source_system,
        target_ids=all_targets,
        payload=payload,
        result=result,
        result_detail=detail or error_detail or None,
        source_system_response=source_system_response,
        executed_by=executed_by,
    )
    db.add(log)
    db.flush()
    return log.id


def _update_action_status(action: RemediationAction, result: Any) -> None:
    """Update the RemediationAction status based on execution outcome."""
    now = datetime.now(timezone.utc)
    if result.status == ExecutionStatus.SUCCESS:
        action.status = "COMPLETE"
        action.completion_method = "AUTO"
        action.completed_at = now
        action.completion_notes = result.detail
    elif result.status == ExecutionStatus.PARTIAL:
        action.status = "IN_PROGRESS"
    # FAILURE and ROLLED_BACK leave the status unchanged
