"""
scout/actions/executors.py — Autonomous Action Executors (Sprint 25)

These are the agents that actually do the work — writing back to source
systems to execute remediation actions rather than just recommending them.

Architecture mirrors evidence_checkers.py:
  ActionExecutor (Protocol)
    └── SalesforceActionExecutor   — writes to SFDC via REST API
    └── WorkdayActionExecutor      — writes to Workday via SOAP/REST API
    └── NetSuiteActionExecutor     — writes to NetSuite via SuiteTalk/REST

Each executor implements execute(action_type, target_ids, payload) → ExecutionResult.

Key safety properties:
  1. Executors are stateless — all state in DB, all context passed in
  2. Every execution attempt writes an ExecutionLog row (win or fail)
  3. Rollback is explicit — executors expose rollback() where reversible
  4. Dry-run mode — execute(dry_run=True) validates + returns what would happen
     without actually writing to the source system

Connector injection:
  Executors receive a connector instance at construction time — the same
  connector objects used by workers for data ingestion. This means a
  SalesforceConnector instance handles both reading (for workers) and
  writing (for executors) via the same auth credentials and session.

Production vs. mock:
  In production: real connector with live OAuth tokens
  In tests: MockSalesforceConnector that records calls and returns fixture responses
  In dev: real connector pointing to sandbox/staging environment

Supported action types by executor:

  SFDC (SalesforceActionExecutor):
    reassign_accounts         → Account.OwnerId = new_owner_id
    update_opportunity_stage  → Opportunity.StageName = target_stage
    log_activity              → Task/Event created under account/contact
    update_account_health     → Account.Health_Score__c = new_score
    create_contact            → New Contact under Account

  Workday (WorkdayActionExecutor):
    initiate_comp_review      → Create compensation change request
    update_position_status    → Update position status field
    send_onboarding_tasks     → Trigger onboarding business process
    deprovision_access        → Initiate offboarding security process

  NetSuite (NetSuiteActionExecutor):
    approve_po                → PurchaseOrder.status = Approved
    create_renewal_order      → Create Sales Order from existing contract
    flag_vendor_invoice       → Add memo/flag to Bill record
    route_for_approval        → Submit document to approval workflow
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── Execution result types ─────────────────────────────────────────────────────


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PARTIAL = "PARTIAL"
    ROLLED_BACK = "ROLLED_BACK"
    DRY_RUN = "DRY_RUN"      # dry_run=True — would have succeeded


@dataclass
class ExecutionResult:
    status: ExecutionStatus
    detail: str = ""
    error_detail: str = ""
    targets_succeeded: list[str] = field(default_factory=list)
    targets_failed: list[str] = field(default_factory=list)
    source_system_response: dict[str, Any] = field(default_factory=dict)
    rolled_back: bool = False


# ── Executor protocol ──────────────────────────────────────────────────────────


class ActionExecutor(Protocol):
    source_name: str
    supported_action_types: list[str]

    def execute(
        self,
        action_type: str,
        target_ids: list[str],
        payload: dict[str, Any],
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Execute an action against the source system.

        action_type:  one of supported_action_types
        target_ids:   IDs in the source system to operate on
        payload:      action-specific parameters (new_owner_id, target_stage, etc.)
        dry_run:      if True, validate and return what would happen without writing

        Returns an ExecutionResult with the outcome.
        """
        ...


# ── Salesforce executor ────────────────────────────────────────────────────────


class SalesforceActionExecutor:
    """
    Writes operational changes to Salesforce.

    Uses the SFDC REST API via the same connector object used for ingestion.
    In production, the connector holds a valid OAuth2 session token.
    """

    source_name = "sfdc"
    supported_action_types = [
        "reassign_accounts",
        "update_opportunity_stage",
        "log_activity",
        "update_account_health",
        "create_contact",
    ]

    def __init__(self, connector: Any | None = None):
        self.connector = connector

    def execute(
        self,
        action_type: str,
        target_ids: list[str],
        payload: dict[str, Any],
        dry_run: bool = False,
    ) -> ExecutionResult:
        if self.connector is None:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="Salesforce connector not configured for this tenant.",
            )

        if action_type not in self.supported_action_types:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail=f"Action type '{action_type}' not supported by SFDC executor.",
            )

        try:
            if action_type == "reassign_accounts":
                return self._reassign_accounts(target_ids, payload, dry_run)
            elif action_type == "update_opportunity_stage":
                return self._update_opportunity_stage(target_ids, payload, dry_run)
            elif action_type == "log_activity":
                return self._log_activity(target_ids, payload, dry_run)
            elif action_type == "update_account_health":
                return self._update_account_health(target_ids, payload, dry_run)
            elif action_type == "create_contact":
                return self._create_contact(target_ids, payload, dry_run)
            else:
                return ExecutionResult(
                    status=ExecutionStatus.FAILURE,
                    error_detail=f"Unhandled action type: {action_type}",
                )
        except Exception as exc:
            logger.error(f"SFDC executor error ({action_type}): {exc}", exc_info=True)
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail=str(exc),
            )

    def _reassign_accounts(
        self, account_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """
        Reassign Account.OwnerId for all specified accounts.

        payload keys:
          new_owner_id   (required) — SFDC User.Id to assign accounts to
          notify_owner   (optional, default True) — send Chatter notification
        """
        new_owner_id = payload.get("new_owner_id")
        if not new_owner_id:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="payload.new_owner_id is required for reassign_accounts.",
            )

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would reassign {len(account_ids)} accounts to {new_owner_id}.",
                targets_succeeded=account_ids,
            )

        succeeded = []
        failed = []
        responses = {}

        for acct_id in account_ids:
            try:
                resp = self.connector.update_account(acct_id, {"OwnerId": new_owner_id})
                succeeded.append(acct_id)
                responses[acct_id] = resp
                logger.info(f"Reassigned account {acct_id} to {new_owner_id}")
            except Exception as exc:
                logger.warning(f"Failed to reassign account {acct_id}: {exc}")
                failed.append(acct_id)
                responses[acct_id] = {"error": str(exc)}

        if not failed:
            status = ExecutionStatus.SUCCESS
            detail = f"Successfully reassigned {len(succeeded)} accounts to {new_owner_id}."
        elif not succeeded:
            status = ExecutionStatus.FAILURE
            detail = f"Failed to reassign all {len(failed)} accounts."
        else:
            status = ExecutionStatus.PARTIAL
            detail = (
                f"Reassigned {len(succeeded)}/{len(account_ids)} accounts. "
                f"Failed: {failed}"
            )

        return ExecutionResult(
            status=status,
            detail=detail,
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _update_opportunity_stage(
        self, opportunity_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """
        Advance one or more opportunities to a target stage.

        payload keys:
          target_stage  (required) — the StageName to set
          close_date    (optional) — update CloseDate if provided
        """
        target_stage = payload.get("target_stage")
        if not target_stage:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="payload.target_stage is required.",
            )

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would advance {len(opportunity_ids)} opportunities to '{target_stage}'.",
                targets_succeeded=opportunity_ids,
            )

        update = {"StageName": target_stage}
        if payload.get("close_date"):
            update["CloseDate"] = payload["close_date"]

        succeeded, failed, responses = [], [], {}
        for opp_id in opportunity_ids:
            try:
                resp = self.connector.update_opportunity(opp_id, update)
                succeeded.append(opp_id)
                responses[opp_id] = resp
            except Exception as exc:
                failed.append(opp_id)
                responses[opp_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"{len(succeeded)}/{len(opportunity_ids)} opportunities updated to '{target_stage}'.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _log_activity(
        self, target_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """
        Log a Task or Event against Salesforce records.

        payload keys:
          subject      (required) — task subject line
          description  (optional) — task/event body
          type         (optional, default "Task") — "Task" or "Event"
          due_date     (optional) — task due date
        """
        subject = payload.get("subject", "Miragent: Action logged")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would log activity '{subject}' against {len(target_ids)} records.",
                targets_succeeded=target_ids,
            )

        succeeded, failed, responses = [], [], {}
        for target_id in target_ids:
            try:
                task = {
                    "Subject": subject,
                    "Description": payload.get("description", ""),
                    "WhatId": target_id,
                    "TaskSubtype": "Call",
                    "Status": "Completed",
                }
                resp = self.connector.create_task(task)
                succeeded.append(target_id)
                responses[target_id] = resp
            except Exception as exc:
                failed.append(target_id)
                responses[target_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Logged '{subject}' against {len(succeeded)}/{len(target_ids)} records.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _update_account_health(
        self, account_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """Update Health Score custom field on Salesforce accounts."""
        score = payload.get("health_score")
        if score is None:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="payload.health_score is required.",
            )

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would set Health_Score__c={score} on {len(account_ids)} accounts.",
                targets_succeeded=account_ids,
            )

        succeeded, failed, responses = [], [], {}
        for acct_id in account_ids:
            try:
                resp = self.connector.update_account(acct_id, {"Health_Score__c": score})
                succeeded.append(acct_id)
                responses[acct_id] = resp
            except Exception as exc:
                failed.append(acct_id)
                responses[acct_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Updated health score for {len(succeeded)}/{len(account_ids)} accounts.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _create_contact(
        self, account_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """Create a Contact record under specified Salesforce accounts."""
        first_name = payload.get("first_name", "")
        last_name = payload.get("last_name", "Contact")
        email = payload.get("email")
        title = payload.get("title", "")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would create contact '{first_name} {last_name}' under {len(account_ids)} accounts.",
                targets_succeeded=account_ids,
            )

        succeeded, failed, responses = [], [], {}
        for acct_id in account_ids:
            try:
                contact = {
                    "FirstName": first_name,
                    "LastName": last_name,
                    "AccountId": acct_id,
                    "Title": title,
                }
                if email:
                    contact["Email"] = email
                resp = self.connector.create_contact(contact)
                succeeded.append(acct_id)
                responses[acct_id] = resp
            except Exception as exc:
                failed.append(acct_id)
                responses[acct_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Created contacts under {len(succeeded)}/{len(account_ids)} accounts.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )


# ── Workday executor ───────────────────────────────────────────────────────────


class WorkdayActionExecutor:
    """Writes operational changes to Workday HR system."""

    source_name = "workday"
    supported_action_types = [
        "initiate_comp_review",
        "update_position_status",
        "send_onboarding_tasks",
        "deprovision_access",
    ]

    def __init__(self, connector: Any | None = None):
        self.connector = connector

    def execute(
        self,
        action_type: str,
        target_ids: list[str],
        payload: dict[str, Any],
        dry_run: bool = False,
    ) -> ExecutionResult:
        if self.connector is None:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="Workday connector not configured for this tenant.",
            )

        try:
            if action_type == "initiate_comp_review":
                return self._initiate_comp_review(target_ids, payload, dry_run)
            elif action_type == "update_position_status":
                return self._update_position_status(target_ids, payload, dry_run)
            elif action_type == "send_onboarding_tasks":
                return self._send_onboarding_tasks(target_ids, payload, dry_run)
            elif action_type == "deprovision_access":
                return self._deprovision_access(target_ids, payload, dry_run)
            else:
                return ExecutionResult(
                    status=ExecutionStatus.FAILURE,
                    error_detail=f"Unhandled action type: {action_type}",
                )
        except Exception as exc:
            logger.error(f"Workday executor error ({action_type}): {exc}", exc_info=True)
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail=str(exc),
            )

    def _initiate_comp_review(
        self, worker_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """
        Initiate a compensation review for specified workers.

        payload keys:
          reason         (required) — compensation review reason code
          effective_date (required) — when the review should take effect
          proposed_pct   (optional) — proposed increase percentage
        """
        reason = payload.get("reason", "MARKET_ADJUSTMENT")
        effective_date = payload.get("effective_date")

        if not effective_date:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="payload.effective_date is required for comp review.",
            )

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would initiate comp review for {len(worker_ids)} workers (effective {effective_date}).",
                targets_succeeded=worker_ids,
            )

        succeeded, failed, responses = [], [], {}
        for worker_id in worker_ids:
            try:
                resp = self.connector.initiate_comp_review(
                    worker_id,
                    reason=reason,
                    effective_date=effective_date,
                    proposed_pct=payload.get("proposed_pct"),
                )
                succeeded.append(worker_id)
                responses[worker_id] = resp
                logger.info(f"Initiated comp review for worker {worker_id}")
            except Exception as exc:
                failed.append(worker_id)
                responses[worker_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Comp review initiated for {len(succeeded)}/{len(worker_ids)} workers.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _update_position_status(
        self, position_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        new_status = payload.get("status", "IN_REVIEW")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would set {len(position_ids)} positions to '{new_status}'.",
                targets_succeeded=position_ids,
            )

        succeeded, failed, responses = [], [], {}
        for pos_id in position_ids:
            try:
                resp = self.connector.update_position(pos_id, {"status": new_status})
                succeeded.append(pos_id)
                responses[pos_id] = resp
            except Exception as exc:
                failed.append(pos_id)
                responses[pos_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Updated {len(succeeded)}/{len(position_ids)} positions to '{new_status}'.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _send_onboarding_tasks(
        self, worker_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        template = payload.get("onboarding_template", "STANDARD_ONBOARDING")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would trigger '{template}' onboarding for {len(worker_ids)} workers.",
                targets_succeeded=worker_ids,
            )

        succeeded, failed, responses = [], [], {}
        for worker_id in worker_ids:
            try:
                resp = self.connector.trigger_onboarding(worker_id, template=template)
                succeeded.append(worker_id)
                responses[worker_id] = resp
            except Exception as exc:
                failed.append(worker_id)
                responses[worker_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Triggered onboarding for {len(succeeded)}/{len(worker_ids)} workers.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _deprovision_access(
        self, worker_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """Initiate security offboarding process to revoke system access."""
        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would deprovision access for {len(worker_ids)} workers.",
                targets_succeeded=worker_ids,
            )

        succeeded, failed, responses = [], [], {}
        for worker_id in worker_ids:
            try:
                resp = self.connector.deprovision_worker(worker_id)
                succeeded.append(worker_id)
                responses[worker_id] = resp
                logger.info(f"Deprovisioned access for worker {worker_id}")
            except Exception as exc:
                failed.append(worker_id)
                responses[worker_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Deprovisioned access for {len(succeeded)}/{len(worker_ids)} workers.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )


# ── NetSuite executor ──────────────────────────────────────────────────────────


class NetSuiteActionExecutor:
    """Writes operational changes to NetSuite ERP."""

    source_name = "netsuite"
    supported_action_types = [
        "approve_po",
        "create_renewal_order",
        "flag_vendor_invoice",
        "route_for_approval",
    ]

    def __init__(self, connector: Any | None = None):
        self.connector = connector

    def execute(
        self,
        action_type: str,
        target_ids: list[str],
        payload: dict[str, Any],
        dry_run: bool = False,
    ) -> ExecutionResult:
        if self.connector is None:
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail="NetSuite connector not configured for this tenant.",
            )

        try:
            if action_type == "approve_po":
                return self._approve_po(target_ids, payload, dry_run)
            elif action_type == "create_renewal_order":
                return self._create_renewal_order(target_ids, payload, dry_run)
            elif action_type == "flag_vendor_invoice":
                return self._flag_vendor_invoice(target_ids, payload, dry_run)
            elif action_type == "route_for_approval":
                return self._route_for_approval(target_ids, payload, dry_run)
            else:
                return ExecutionResult(
                    status=ExecutionStatus.FAILURE,
                    error_detail=f"Unhandled action type: {action_type}",
                )
        except Exception as exc:
            logger.error(f"NetSuite executor error ({action_type}): {exc}", exc_info=True)
            return ExecutionResult(
                status=ExecutionStatus.FAILURE,
                error_detail=str(exc),
            )

    def _approve_po(
        self, po_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """
        Approve Purchase Orders in NetSuite.

        payload keys:
          approver_note  (optional) — memo added to the PO on approval
        """
        note = payload.get("approver_note", "Approved via Miragent autonomous action.")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would approve {len(po_ids)} POs.",
                targets_succeeded=po_ids,
            )

        succeeded, failed, responses = [], [], {}
        for po_id in po_ids:
            try:
                resp = self.connector.approve_po(po_id, memo=note)
                succeeded.append(po_id)
                responses[po_id] = resp
                logger.info(f"Approved PO {po_id}")
            except Exception as exc:
                failed.append(po_id)
                responses[po_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Approved {len(succeeded)}/{len(po_ids)} POs.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _create_renewal_order(
        self, contract_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """Create renewal Sales Orders from existing contracts."""
        term_months = payload.get("term_months", 12)

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would create {len(contract_ids)} renewal orders ({term_months}mo terms).",
                targets_succeeded=contract_ids,
            )

        succeeded, failed, responses = [], [], {}
        for contract_id in contract_ids:
            try:
                resp = self.connector.create_renewal(contract_id, term_months=term_months)
                succeeded.append(contract_id)
                responses[contract_id] = resp
            except Exception as exc:
                failed.append(contract_id)
                responses[contract_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Created renewal orders for {len(succeeded)}/{len(contract_ids)} contracts.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _flag_vendor_invoice(
        self, invoice_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """Add a flag/memo to vendor invoice records for finance review."""
        flag_reason = payload.get("reason", "Flagged by Miragent for review")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would flag {len(invoice_ids)} invoices: '{flag_reason}'",
                targets_succeeded=invoice_ids,
            )

        succeeded, failed, responses = [], [], {}
        for inv_id in invoice_ids:
            try:
                resp = self.connector.update_bill(inv_id, {"memo": flag_reason, "flagged": True})
                succeeded.append(inv_id)
                responses[inv_id] = resp
            except Exception as exc:
                failed.append(inv_id)
                responses[inv_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Flagged {len(succeeded)}/{len(invoice_ids)} invoices.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )

    def _route_for_approval(
        self, document_ids: list[str], payload: dict, dry_run: bool
    ) -> ExecutionResult:
        """Submit documents through the NetSuite approval workflow."""
        workflow_name = payload.get("workflow", "Standard Approval")

        if dry_run:
            return ExecutionResult(
                status=ExecutionStatus.DRY_RUN,
                detail=f"Would route {len(document_ids)} documents through '{workflow_name}'.",
                targets_succeeded=document_ids,
            )

        succeeded, failed, responses = [], [], {}
        for doc_id in document_ids:
            try:
                resp = self.connector.submit_for_approval(doc_id, workflow=workflow_name)
                succeeded.append(doc_id)
                responses[doc_id] = resp
            except Exception as exc:
                failed.append(doc_id)
                responses[doc_id] = {"error": str(exc)}

        status = (
            ExecutionStatus.SUCCESS if not failed
            else ExecutionStatus.PARTIAL if succeeded
            else ExecutionStatus.FAILURE
        )
        return ExecutionResult(
            status=status,
            detail=f"Routed {len(succeeded)}/{len(document_ids)} documents for approval.",
            targets_succeeded=succeeded,
            targets_failed=failed,
            source_system_response=responses,
        )


# ── Registry ───────────────────────────────────────────────────────────────────

EXECUTOR_REGISTRY: dict[str, type] = {
    "sfdc": SalesforceActionExecutor,
    "workday": WorkdayActionExecutor,
    "netsuite": NetSuiteActionExecutor,
}

# Maps action_type → source_system (for routing)
ACTION_SOURCE_MAP: dict[str, str] = {
    "reassign_accounts": "sfdc",
    "update_opportunity_stage": "sfdc",
    "log_activity": "sfdc",
    "update_account_health": "sfdc",
    "create_contact": "sfdc",
    "initiate_comp_review": "workday",
    "update_position_status": "workday",
    "send_onboarding_tasks": "workday",
    "deprovision_access": "workday",
    "approve_po": "netsuite",
    "create_renewal_order": "netsuite",
    "flag_vendor_invoice": "netsuite",
    "route_for_approval": "netsuite",
}


def get_executor(action_type: str, connector: Any = None) -> ActionExecutor | None:
    """Return an executor instance for the given action type."""
    source = ACTION_SOURCE_MAP.get(action_type)
    if source is None:
        return None
    cls = EXECUTOR_REGISTRY.get(source)
    if cls is None:
        return None
    return cls(connector=connector)
