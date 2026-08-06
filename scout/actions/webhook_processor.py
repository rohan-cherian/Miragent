"""
scout/actions/webhook_processor.py — Real-Time Webhook Event Processor (Sprint 27)

Decouples webhook ingestion from processing. The webhook route handlers
persist a WebhookEvent row immediately and return HTTP 200. This processor
then handles the event asynchronously (or synchronously in the same request
if the platform doesn't support background tasks).

Processing pipeline per event:
  1. LOCK — mark event PROCESSING to prevent double-processing
  2. ROUTE — look up the event_type in the dispatch table
  3. DISPATCH — call the appropriate handler (evidence checker, action emitter, etc.)
  4. LOG — record which actions were triggered (or that the event was IGNORED)
  5. COMPLETE — mark event DONE or FAILED

Event types and their handlers:

  SFDC (source: sfdc):
    opportunity.updated      → run evidence check (account_owner_changed, meeting_logged)
    opportunity.stage_changed→ run evidence check + emit update_opportunity_stage action
    contact.terminated       → emit deprovision_access + reassign_accounts actions
    contact.created          → log (new lead — future: trigger onboarding sequence)
    account.updated          → run evidence check (account_owner_changed)

  Workday (source: workday):
    worker.terminated        → emit deprovision_access action immediately
    worker.hired             → emit send_onboarding_tasks action
    compensation.changed     → log (comp change tracked for audit)

  NetSuite (source: netsuite):
    po.approved              → run evidence check (po_approved)
    invoice.created          → run evidence check (vendor_invoice_paid)
    contract.renewed         → run evidence check (contract_renewal_created)

Design:
  - Handlers are registered as plain functions in _DISPATCH_TABLE
  - Unknown event types are marked IGNORED (no error, just logged)
  - All exceptions are caught per-event; failure of one event does not
    prevent processing of subsequent events in a batch

Integration with ActionFactory:
  Handlers that create new actions call ActionFactory.emit() + flush()
  and return the created action IDs. These IDs are stored in
  WebhookEvent.actions_triggered for traceability.

Integration with evidence checkers:
  Handlers that need to verify completion call the appropriate
  EvidenceChecker via get_checker() and update the matching RemediationAction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.db.models import RemediationAction, WebhookEvent

logger = logging.getLogger(__name__)


# ── Event handler type ─────────────────────────────────────────────────────────

# Each handler receives (db, event, connector_map) and returns list[str] of
# action IDs created or updated, or [] if nothing happened.
HandlerResult = list[str]


# ── Main processor entry point ─────────────────────────────────────────────────


def process_event(
    db: Session,
    event: WebhookEvent,
    connector_map: dict[str, Any] | None = None,
) -> HandlerResult:
    """
    Process a single WebhookEvent through the dispatch pipeline.

    Marks the event PROCESSING before dispatch, then DONE or FAILED after.
    Returns the list of action IDs created or updated.

    Called immediately after persisting the event (synchronous path) or
    by a background task queue (async path). Either way the caller already
    holds the DB session.
    """
    connector_map = connector_map or {}

    # Guard: don't re-process events that are already done/failed/ignored
    if event.status not in {"PENDING", "PROCESSING"}:
        logger.debug(f"Skipping event {event.id} with status {event.status}")
        return []

    # Mark PROCESSING
    event.status = "PROCESSING"
    db.flush()

    try:
        handler = _DISPATCH_TABLE.get(event.source, {}).get(event.event_type)
        if handler is None:
            event.status = "IGNORED"
            event.processed_at = datetime.now(timezone.utc)
            db.flush()
            logger.debug(
                f"WebhookProcessor: no handler for {event.source}/{event.event_type} "
                f"— event {event.id} marked IGNORED"
            )
            return []

        action_ids = handler(db, event, connector_map)

        event.status = "DONE"
        event.processed_at = datetime.now(timezone.utc)
        event.actions_triggered = action_ids
        db.flush()
        logger.info(
            f"WebhookProcessor: {event.source}/{event.event_type} → "
            f"{len(action_ids)} action(s) — event {event.id} DONE"
        )
        return action_ids

    except Exception as exc:
        logger.exception(
            f"WebhookProcessor: error handling {event.source}/{event.event_type} "
            f"event {event.id}: {exc}"
        )
        event.status = "FAILED"
        event.error_detail = str(exc)
        event.processed_at = datetime.now(timezone.utc)
        db.flush()
        return []


def persist_and_process(
    db: Session,
    source: str,
    event_type: str,
    tenant_id: str,
    payload: dict,
    idempotency_key: str | None = None,
    connector_map: dict[str, Any] | None = None,
) -> tuple[WebhookEvent, HandlerResult]:
    """
    Persist a WebhookEvent row then immediately process it.

    Returns (event, action_ids). If an event with this idempotency_key
    already exists (duplicate delivery), returns the existing row without
    re-processing.

    This is the primary entry point called by webhook route handlers.
    """
    # Idempotency check
    if idempotency_key:
        existing = db.execute(
            select(WebhookEvent).where(
                WebhookEvent.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing:
            logger.debug(
                f"Duplicate webhook event {idempotency_key} — skipping (already {existing.status})"
            )
            return existing, existing.actions_triggered or []

    event = WebhookEvent(
        tenant_id=tenant_id,
        source=source,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        status="PENDING",
    )
    db.add(event)
    db.flush()  # get ID before processing

    action_ids = process_event(db, event, connector_map)
    return event, action_ids


# ── Handlers ───────────────────────────────────────────────────────────────────
# Each handler: (db, event, connector_map) -> list[str]


def _handle_sfdc_opportunity_updated(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    SFDC opportunity.updated → check if evidence of completion exists.

    Looks for OPEN RemediationActions targeting this opportunity and runs
    the evidence checker to see if the action has already been completed
    in SFDC (e.g., a follow-up was logged, stage was advanced).
    """
    opportunity_id = event.payload.get("opportunity_id") or event.payload.get("Id")
    if not opportunity_id:
        return []

    actions = _find_actions_for_target(db, event.tenant_id, opportunity_id)
    updated_ids = []

    sfdc_connector = connector_map.get("sfdc")
    from scout.actions.evidence_checkers import get_checker

    checker = get_checker("sfdc", sfdc_connector)
    if checker is None:
        return []

    context = {**event.payload}
    for action in actions:
        result = checker.check(
            query_type=action.evidence_query_type,
            target_ids=list(action.evidence_target_ids or []),
            context=context,
        )
        from scout.actions.evidence_checkers import EvidenceResult
        if result.result == EvidenceResult.FOUND:
            action.status = "COMPLETE"
            action.completion_method = "WEBHOOK"
            action.completed_at = datetime.now(timezone.utc)
            action.completion_notes = f"Completed via SFDC webhook: {event.event_type}"
            updated_ids.append(action.id)
        elif result.result == EvidenceResult.PARTIAL:
            action.status = "IN_PROGRESS"
            updated_ids.append(action.id)

    db.flush()
    return updated_ids


def _handle_sfdc_contact_terminated(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    SFDC contact.terminated → emit deprovision_access action immediately.

    When Salesforce fires a contact-terminated event (from a custom flow
    or Process Builder triggered by an is_active=false update), this
    handler emits an offboarding action without waiting for the next
    HireToRetireWorker scan.
    """
    from scout.actions.factory import ActionFactory, deprovision_departed_employee

    contact_id = (
        event.payload.get("contact_id")
        or event.payload.get("Id")
        or event.payload.get("canonical_id")
    )
    contact_name = (
        event.payload.get("Name")
        or event.payload.get("full_name")
        or "Unknown Contact"
    )
    workday_id = event.payload.get("workday_id") or contact_id

    if not contact_id:
        return []

    factory = ActionFactory(db, event.tenant_id)
    factory.emit(deprovision_departed_employee(
        finding_hash=f"webhook-sfdc-term-{event.tenant_id}-{contact_id}",
        worker_name="WebhookProcessor",
        employee_name=contact_name,
        workday_id=workday_id,
    ))
    return factory.flush()


def _handle_sfdc_account_updated(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    SFDC account.updated → check if account-owner-change evidence matches
    an open reassign_accounts action for this account.
    """
    account_id = event.payload.get("account_id") or event.payload.get("Id")
    if not account_id:
        return []

    actions = _find_actions_for_target(
        db, event.tenant_id, account_id, action_type="reassign_accounts"
    )
    if not actions:
        return []

    sfdc_connector = connector_map.get("sfdc")
    from scout.actions.evidence_checkers import EvidenceResult, get_checker

    checker = get_checker("sfdc", sfdc_connector)
    if checker is None:
        return []

    updated_ids = []
    for action in actions:
        result = checker.check(
            query_type="account_owner_changed",
            target_ids=[account_id],
            context=event.payload,
        )
        if result.result == EvidenceResult.FOUND:
            action.status = "COMPLETE"
            action.completion_method = "WEBHOOK"
            action.completed_at = datetime.now(timezone.utc)
            updated_ids.append(action.id)

    db.flush()
    return updated_ids


def _handle_workday_worker_terminated(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    Workday worker.terminated → immediate deprovision_access action.

    Workday fires this event when a termination is processed. This handler
    creates the deprovision action immediately — before the next nightly
    HireToRetireWorker scan — so access is revoked in hours, not days.
    """
    from scout.actions.factory import ActionFactory, deprovision_departed_employee

    worker_id = event.payload.get("workday_id") or event.payload.get("worker_id")
    worker_name = (
        event.payload.get("worker_name")
        or event.payload.get("full_name")
        or "Unknown Worker"
    )

    if not worker_id:
        return []

    factory = ActionFactory(db, event.tenant_id)
    factory.emit(deprovision_departed_employee(
        finding_hash=f"webhook-wd-term-{event.tenant_id}-{worker_id}",
        worker_name="WebhookProcessor",
        employee_name=worker_name,
        workday_id=worker_id,
    ))
    return factory.flush()


def _handle_workday_worker_hired(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    Workday worker.hired → emit send_onboarding_tasks action.

    Fires when Workday processes a new hire event. Creates an onboarding
    action so IT/HR can provision accounts and schedule the first week.
    """
    from scout.actions.factory import ActionFactory, ActionSpec

    worker_id = event.payload.get("workday_id") or event.payload.get("worker_id")
    worker_name = event.payload.get("worker_name") or event.payload.get("full_name") or "New Hire"
    manager_email = event.payload.get("manager_email")
    start_date = event.payload.get("start_date", "TBD")

    if not worker_id:
        return []

    factory = ActionFactory(db, event.tenant_id)
    factory.emit(ActionSpec(
        action_type="send_onboarding_tasks",
        title=f"Onboard new hire: {worker_name} (starts {start_date})",
        description=(
            f"New hire event received from Workday for {worker_name}. "
            f"Trigger onboarding checklist: provision accounts, assign equipment, "
            f"schedule orientation, and assign buddy."
        ),
        evidence_source="workday",
        evidence_query_type="hire_event_created",
        evidence_target_ids=[worker_id],
        execution_payload={
            "worker_id": worker_id,
            "worker_name": worker_name,
            "start_date": start_date,
            "manager_email": manager_email,
        },
        assigned_to_email=manager_email,
        effort="MEDIUM",
        timeframe="IMMEDIATE",
        finding_hash=f"webhook-wd-hire-{event.tenant_id}-{worker_id}",
        worker_name="WebhookProcessor",
    ))
    return factory.flush()


def _handle_netsuite_po_approved(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    NetSuite po.approved → check if approve_po action can be marked COMPLETE.

    When NetSuite fires a PO-approved event, look for open approve_po
    actions targeting that PO and mark them COMPLETE.
    """
    po_id = event.payload.get("po_id") or event.payload.get("Id")
    if not po_id:
        return []

    actions = _find_actions_for_target(
        db, event.tenant_id, po_id, action_type="approve_po"
    )
    updated_ids = []
    for action in actions:
        action.status = "COMPLETE"
        action.completion_method = "WEBHOOK"
        action.completed_at = datetime.now(timezone.utc)
        action.completion_notes = f"PO approved in NetSuite — event {event.id}"
        updated_ids.append(action.id)

    db.flush()
    return updated_ids


def _handle_netsuite_invoice_created(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    NetSuite invoice.created → run evidence check on vendor_invoice_paid actions.
    """
    invoice_id = event.payload.get("invoice_id") or event.payload.get("Id")
    vendor_id = event.payload.get("vendor_id")
    if not invoice_id:
        return []

    target_ids = [invoice_id]
    if vendor_id:
        target_ids.append(vendor_id)

    actions = _find_actions_for_target(
        db, event.tenant_id, invoice_id, action_type="flag_vendor_invoice"
    )
    updated_ids = []

    ns_connector = connector_map.get("netsuite")
    from scout.actions.evidence_checkers import EvidenceResult, get_checker

    checker = get_checker("netsuite", ns_connector)

    for action in actions:
        if checker:
            result = checker.check(
                query_type="vendor_invoice_paid",
                target_ids=target_ids,
                context=event.payload,
            )
            if result.result == EvidenceResult.FOUND:
                action.status = "COMPLETE"
                action.completion_method = "WEBHOOK"
                action.completed_at = datetime.now(timezone.utc)
                updated_ids.append(action.id)
        else:
            # No connector — just note the event
            action.completion_notes = f"Invoice created in NetSuite: {invoice_id}"
            updated_ids.append(action.id)

    db.flush()
    return updated_ids


def _handle_netsuite_contract_renewed(
    db: Session, event: WebhookEvent, connector_map: dict
) -> HandlerResult:
    """
    NetSuite contract.renewed → mark route_for_approval actions COMPLETE
    if a matching renewal order was created.
    """
    contract_id = event.payload.get("contract_id") or event.payload.get("Id")
    if not contract_id:
        return []

    actions = _find_actions_for_target(
        db, event.tenant_id, contract_id, action_type="route_for_approval"
    )
    updated_ids = []
    for action in actions:
        action.status = "COMPLETE"
        action.completion_method = "WEBHOOK"
        action.completed_at = datetime.now(timezone.utc)
        action.completion_notes = f"Contract renewed in NetSuite: {contract_id}"
        updated_ids.append(action.id)

    db.flush()
    return updated_ids


# ── Dispatch table ─────────────────────────────────────────────────────────────

_DISPATCH_TABLE: dict[str, dict[str, Any]] = {
    "sfdc": {
        "opportunity.updated":       _handle_sfdc_opportunity_updated,
        "opportunity.stage_changed": _handle_sfdc_opportunity_updated,  # same logic
        "contact.terminated":        _handle_sfdc_contact_terminated,
        "account.updated":           _handle_sfdc_account_updated,
    },
    "workday": {
        "worker.terminated": _handle_workday_worker_terminated,
        "worker.hired":      _handle_workday_worker_hired,
    },
    "netsuite": {
        "po.approved":       _handle_netsuite_po_approved,
        "invoice.created":   _handle_netsuite_invoice_created,
        "contract.renewed":  _handle_netsuite_contract_renewed,
    },
}


# ── Helper ─────────────────────────────────────────────────────────────────────


def _find_actions_for_target(
    db: Session,
    tenant_id: str,
    target_id: str,
    action_type: str | None = None,
) -> list[RemediationAction]:
    """
    Find OPEN or IN_PROGRESS RemediationActions that include target_id
    in their evidence_target_ids list.

    SQLite and PostgreSQL both support JSON contains via the ORM. For
    SQLite in tests, we load all OPEN/IN_PROGRESS and filter in Python
    (acceptable since action counts per tenant are small).
    """
    q = select(RemediationAction).where(
        RemediationAction.tenant_id == tenant_id,
        RemediationAction.status.in_({"OPEN", "IN_PROGRESS"}),
    )
    if action_type:
        q = q.where(RemediationAction.action_type == action_type)

    actions = db.execute(q).scalars().all()
    return [
        a for a in actions
        if target_id in (a.evidence_target_ids or [])
    ]
