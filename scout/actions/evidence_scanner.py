"""
scout/actions/evidence_scanner.py — Organic Action Completion Orchestrator (Sprint 23)

Loops over all OPEN/IN_PROGRESS RemediationActions for a tenant, calls
the appropriate EvidenceChecker, updates action status, and logs results
to EvidenceCheckLog.

Design principles:
  - Idempotent: safe to run multiple times; already-COMPLETE actions are skipped
  - Connector-agnostic: connectors are injected, making the scanner fully testable
  - Fail-safe: a broken connector (ERROR) leaves the action status unchanged
    and logs the error; the scanner continues to the next action

Invoked by:
  - Background job (scheduler runs every 2–4 hours, see infra/scheduler)
  - Admin portal "Re-check now" button → POST /admin/actions/{id}/recheck
  - Manually during debugging

Scheduling recommendation:
  Every 2 hours during business hours (8am–8pm tenant-local time).
  No value in checking at 3am when source system webhooks aren't firing.
  In a future sprint, replace polling with webhook-triggered checks
  (SFDC Flow → POST /webhooks/sfdc-evidence, etc.).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.actions.evidence_checkers import EvidenceResult, get_checker
from scout.db.models import ActionReminder, EvidenceCheckLog, RemediationAction

logger = logging.getLogger(__name__)

# Actions in these statuses are eligible for evidence checking
CHECKABLE_STATUSES = {"OPEN", "IN_PROGRESS"}

# How many reminders to schedule per action (e.g., 3 days before due, 1 day before)
REMINDER_DAYS_BEFORE = [3, 1]


def run_evidence_scan(
    db: Session,
    tenant_id: str,
    connector_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run the full evidence scan for one tenant.

    connector_map: {source_name → connector_instance}
      e.g. {"sfdc": sfdc_connector, "workday": wd_connector}
      Omitted sources default to None (checker returns NOT_YET).

    Returns a summary dict:
      {
        "actions_checked": int,
        "auto_completed": int,
        "marked_in_progress": int,
        "errors": int,
        "skipped": int,
      }
    """
    connector_map = connector_map or {}

    # Load all checkable actions for this tenant
    actions = db.execute(
        select(RemediationAction).where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.status.in_(CHECKABLE_STATUSES),
            RemediationAction.evidence_source.isnot(None),
            RemediationAction.evidence_query_type.isnot(None),
        )
    ).scalars().all()

    summary = {
        "actions_checked": 0,
        "auto_completed": 0,
        "marked_in_progress": 0,
        "errors": 0,
        "skipped": 0,
    }

    for action in actions:
        result = _check_one_action(db, action, connector_map)
        summary["actions_checked"] += 1
        summary[result] = summary.get(result, 0) + 1

    db.commit()
    _schedule_reminders(db, tenant_id)
    db.commit()

    logger.info(
        f"Evidence scan complete for {tenant_id}: "
        f"{summary['auto_completed']} auto-completed, "
        f"{summary['errors']} errors, "
        f"{summary['actions_checked']} total checked."
    )
    return summary


def _check_one_action(
    db: Session,
    action: RemediationAction,
    connector_map: dict[str, Any],
) -> str:
    """
    Check one action and update its status.

    Returns one of: "auto_completed", "marked_in_progress", "errors", "skipped"
    """
    source = action.evidence_source
    query_type = action.evidence_query_type
    target_ids = list(action.evidence_target_ids or [])

    checker = get_checker(source, connector_map.get(source))
    if checker is None:
        _log(db, action, "NOT_YET", f"No checker registered for source '{source}'.")
        return "skipped"

    context = {
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "due_date": action.due_date.isoformat() if action.due_date else None,
        "assigned_to_email": action.assigned_to_email,
        "action_type": action.action_type,
        # Checkers can pull additional context keys from here
    }

    check_result = checker.check(query_type, target_ids, context)

    # Log every check
    _log(
        db, action,
        check_result.result.value,
        check_result.detail,
        check_result.error_detail,
    )

    # Update action status based on result
    if check_result.result == EvidenceResult.FOUND:
        action.status = "COMPLETE"
        action.completion_method = "AUTO"
        action.evidence_detected_at = datetime.now(timezone.utc)
        action.completed_at = datetime.now(timezone.utc)
        action.completion_notes = check_result.detail
        logger.info(
            f"Action {action.id} auto-completed via {source}/{query_type}: "
            f"{check_result.detail}"
        )
        return "auto_completed"

    elif check_result.result == EvidenceResult.PARTIAL:
        action.status = "IN_PROGRESS"
        return "marked_in_progress"

    elif check_result.result == EvidenceResult.ERROR:
        # Don't change status — leave for next scan cycle
        logger.warning(
            f"Evidence check error for action {action.id}: {check_result.error_detail}"
        )
        return "errors"

    else:  # NOT_YET or SKIPPED
        return "skipped"


def _log(
    db: Session,
    action: RemediationAction,
    result: str,
    detail: str = "",
    error_detail: str = "",
) -> None:
    """Append an EvidenceCheckLog row."""
    log = EvidenceCheckLog(
        action_id=action.id,
        tenant_id=action.tenant_id,
        evidence_source=action.evidence_source or "unknown",
        evidence_query_type=action.evidence_query_type or "unknown",
        result=result,
        detail=detail or None,
        error_detail=error_detail or None,
    )
    db.add(log)


def _schedule_reminders(db: Session, tenant_id: str) -> None:
    """
    Create ActionReminder rows for actions approaching their due date.

    Only creates reminders that don't already exist (idempotent).
    Skips completed or cancelled actions.
    """
    now = datetime.now(timezone.utc)

    # Load all open actions with due dates and assignees
    actions = db.execute(
        select(RemediationAction).where(
            RemediationAction.tenant_id == tenant_id,
            RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}),
            RemediationAction.due_date.isnot(None),
            RemediationAction.assigned_to_email.isnot(None),
        )
    ).scalars().all()

    for action in actions:
        due = action.due_date
        if due is None:
            continue

        # Make timezone-aware if needed
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)

        for days_before in REMINDER_DAYS_BEFORE:
            from datetime import timedelta
            send_at = due - timedelta(days=days_before)

            # Only schedule future reminders
            if send_at <= now:
                continue

            # Check if this reminder already exists
            existing = db.execute(
                select(ActionReminder).where(
                    ActionReminder.action_id == action.id,
                    ActionReminder.send_at == send_at,
                )
            ).scalar_one_or_none()

            if existing:
                continue

            reminder = ActionReminder(
                action_id=action.id,
                tenant_id=tenant_id,
                assigned_to_email=action.assigned_to_email,
                delivery_method="email",
                send_at=send_at,
            )
            db.add(reminder)


def get_action_evidence_history(
    db: Session, action_id: str, tenant_id: str
) -> list[dict]:
    """
    Return the evidence check log for one action (most recent first).

    Used by the admin portal "Evidence Trail" panel to show:
    - When the action was last checked
    - What was found each time
    - Any connector errors
    """
    rows = db.execute(
        select(EvidenceCheckLog)
        .where(
            EvidenceCheckLog.action_id == action_id,
            EvidenceCheckLog.tenant_id == tenant_id,
        )
        .order_by(EvidenceCheckLog.checked_at.desc())
    ).scalars().all()

    return [
        {
            "result": r.result,
            "detail": r.detail,
            "error_detail": r.error_detail,
            "evidence_source": r.evidence_source,
            "evidence_query_type": r.evidence_query_type,
            "checked_at": r.checked_at.isoformat(),
        }
        for r in rows
    ]
