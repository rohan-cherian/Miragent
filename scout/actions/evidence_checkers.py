"""
scout/actions/evidence_checkers.py — Organic Action Completion Detection (Sprint 23)

The core insight: instead of asking people to check off to-do items (which they
won't maintain), we watch the source systems for evidence that the work was done.

Architecture:
  EvidenceChecker (abstract base)
    └── SalesforceEvidenceChecker   — account owner changes, meetings logged
    └── WorkdayEvidenceChecker      — compensation events, hire/term events
    └── NetSuiteEvidenceChecker     — PO changes, vendor payments, invoice status
    └── CalendarEvidenceChecker     — meeting scheduled, meeting held

Each checker implements check(action, context) → EvidenceResult.

The orchestrator (run_evidence_scan) loops over all OPEN/IN_PROGRESS actions
for a tenant, calls the right checker based on action.evidence_source, and
auto-completes actions where FOUND evidence appears.

Why this architecture?
  - Adding a new source system = one new subclass, no other changes
  - Mock checkers (used in tests) implement the same interface
  - The checker is stateless; all state lives in the DB
  - Evidence checking can run on any schedule without affecting workers

Evidence query types by source:

  SFDC:
    account_owner_changed   — Account.OwnerId changed to a non-departed rep
    meeting_logged          — Activity logged against account/contact
    opportunity_stage_advanced — Opp moved past a given stage
    contact_created         — New Contact record created under Account
    account_health_updated  — Custom Health Score field updated

  Workday:
    comp_event_completed    — Compensation change event in effective range
    hire_event_created      — New hire record for a role
    position_filled         — Open position status changed to FILLED
    termination_processed   — Termination event finalized (for offboarding check)

  NetSuite:
    po_approved             — Purchase Order status moved to APPROVED/RECEIVED
    vendor_invoice_paid     — Bill payment applied to vendor
    contract_renewal_created— Renewal order/contract record created

  Calendar:
    meeting_scheduled       — Invite created with required attendees
    meeting_held            — Invite in the past, attendees accepted
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── Evidence result types ──────────────────────────────────────────────────────


class EvidenceResult(str, Enum):
    FOUND = "FOUND"        # strong evidence — auto-complete the action
    PARTIAL = "PARTIAL"    # weak evidence — mark IN_PROGRESS
    NOT_YET = "NOT_YET"   # nothing yet — check again later
    ERROR = "ERROR"        # connector error — log and skip
    SKIPPED = "SKIPPED"    # action already done or irrelevant


@dataclass
class EvidenceCheckResult:
    result: EvidenceResult
    detail: str = ""
    error_detail: str = ""
    evidence_data: dict[str, Any] = field(default_factory=dict)


# ── Base class ─────────────────────────────────────────────────────────────────


class EvidenceChecker(Protocol):
    """
    Protocol (interface) that every evidence checker must implement.

    source_name identifies which connector this checker handles.
    supported_query_types lists the query types this checker can answer.
    check() is the main method — called once per action per scan cycle.
    """

    source_name: str
    supported_query_types: list[str]

    def check(
        self,
        query_type: str,
        target_ids: list[str],
        context: dict[str, Any],
    ) -> EvidenceCheckResult:
        """
        Check for evidence of action completion.

        query_type:  the evidence_query_type on the RemediationAction
        target_ids:  IDs in the source system to check (accounts, people, etc.)
        context:     additional data from the action (due_date, assigned_to, etc.)

        Returns an EvidenceCheckResult describing what was found.
        """
        ...


# ── SFDC checker ──────────────────────────────────────────────────────────────


class SalesforceEvidenceChecker:
    """
    Checks Salesforce for evidence that a remediation action was completed.

    In production, this uses the SFDC REST API via a stored OAuth token
    (connection config stored in the Tenant's connector settings).

    In test/mock mode, it reads from the MockSFDCConnector's fixture data.
    """

    source_name = "sfdc"
    supported_query_types = [
        "account_owner_changed",
        "meeting_logged",
        "opportunity_stage_advanced",
        "contact_created",
        "account_health_updated",
    ]

    def __init__(self, connector: Any | None = None):
        """
        connector: a SFDCConnector instance (or mock). If None, returns NOT_YET
        for all checks — safe fallback for environments without credentials.
        """
        self.connector = connector

    def check(
        self,
        query_type: str,
        target_ids: list[str],
        context: dict[str, Any],
    ) -> EvidenceCheckResult:
        if self.connector is None:
            return EvidenceCheckResult(
                result=EvidenceResult.NOT_YET,
                detail="SFDC connector not configured for this tenant.",
            )

        try:
            if query_type == "account_owner_changed":
                return self._check_account_owner_changed(target_ids, context)
            elif query_type == "meeting_logged":
                return self._check_meeting_logged(target_ids, context)
            elif query_type == "opportunity_stage_advanced":
                return self._check_opportunity_stage(target_ids, context)
            else:
                return EvidenceCheckResult(
                    result=EvidenceResult.NOT_YET,
                    detail=f"Query type '{query_type}' not yet implemented for SFDC.",
                )
        except Exception as exc:
            logger.warning(f"SFDC evidence check error: {exc}", exc_info=True)
            return EvidenceCheckResult(
                result=EvidenceResult.ERROR,
                error_detail=str(exc),
            )

    def _check_account_owner_changed(
        self, account_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """
        Check whether Account.OwnerId has changed since the action was created.

        The action context includes:
          context["created_at"]       — when the action was created
          context["departed_rep_id"]  — the SFDC User.Id we're moving away from
        """
        created_at = context.get("created_at")
        departed_id = context.get("departed_rep_id")

        changed = []
        still_owned = []

        for acct_id in account_ids:
            # In production: SOQL query via connector
            # SELECT OwnerId, LastModifiedDate FROM Account WHERE Id = :acct_id
            acct = self.connector.get_account(acct_id)
            if acct is None:
                continue
            owner_id = acct.get("OwnerId")
            last_modified = acct.get("LastModifiedDate")

            if owner_id and owner_id != departed_id:
                if last_modified and last_modified > (created_at or ""):
                    changed.append(acct_id)
            else:
                still_owned.append(acct_id)

        total = len(account_ids)
        n_changed = len(changed)

        if n_changed == total:
            return EvidenceCheckResult(
                result=EvidenceResult.FOUND,
                detail=f"All {total} accounts have been reassigned.",
                evidence_data={"changed_accounts": changed},
            )
        elif n_changed > 0:
            return EvidenceCheckResult(
                result=EvidenceResult.PARTIAL,
                detail=f"{n_changed}/{total} accounts reassigned. Still pending: {still_owned}",
                evidence_data={"changed_accounts": changed, "pending_accounts": still_owned},
            )
        else:
            return EvidenceCheckResult(
                result=EvidenceResult.NOT_YET,
                detail=f"None of the {total} accounts have been reassigned yet.",
            )

    def _check_meeting_logged(
        self, contact_or_account_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """Check whether a meeting/call was logged in SFDC Activity after action creation."""
        created_at = context.get("created_at", "")

        for obj_id in contact_or_account_ids:
            activities = self.connector.get_activities(obj_id, after=created_at)
            if activities:
                return EvidenceCheckResult(
                    result=EvidenceResult.FOUND,
                    detail=f"Activity logged against {obj_id} after action was created.",
                    evidence_data={"activity_count": len(activities)},
                )

        return EvidenceCheckResult(
            result=EvidenceResult.NOT_YET,
            detail="No activities logged against the target records since action creation.",
        )

    def _check_opportunity_stage(
        self, opportunity_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """Check whether opportunities have advanced past a target stage."""
        target_stage = context.get("target_stage", "Proposal/Price Quote")
        advanced = []

        for opp_id in opportunity_ids:
            opp = self.connector.get_opportunity(opp_id)
            if opp and opp.get("StageName", "") >= target_stage:
                advanced.append(opp_id)

        if len(advanced) == len(opportunity_ids):
            return EvidenceCheckResult(
                result=EvidenceResult.FOUND,
                detail=f"All {len(opportunity_ids)} opportunities past '{target_stage}'.",
            )
        elif advanced:
            return EvidenceCheckResult(
                result=EvidenceResult.PARTIAL,
                detail=f"{len(advanced)}/{len(opportunity_ids)} opportunities advanced.",
            )
        return EvidenceCheckResult(
            result=EvidenceResult.NOT_YET,
            detail="No opportunities have advanced stage yet.",
        )


# ── Workday checker ───────────────────────────────────────────────────────────


class WorkdayEvidenceChecker:
    """Checks Workday for HR action completion evidence."""

    source_name = "workday"
    supported_query_types = [
        "comp_event_completed",
        "hire_event_created",
        "position_filled",
        "termination_processed",
    ]

    def __init__(self, connector: Any | None = None):
        self.connector = connector

    def check(
        self,
        query_type: str,
        target_ids: list[str],
        context: dict[str, Any],
    ) -> EvidenceCheckResult:
        if self.connector is None:
            return EvidenceCheckResult(
                result=EvidenceResult.NOT_YET,
                detail="Workday connector not configured for this tenant.",
            )

        try:
            if query_type == "comp_event_completed":
                return self._check_comp_event(target_ids, context)
            elif query_type == "position_filled":
                return self._check_position_filled(target_ids, context)
            elif query_type == "hire_event_created":
                return self._check_hire_event(target_ids, context)
            elif query_type == "termination_processed":
                return self._check_termination(target_ids, context)
            else:
                return EvidenceCheckResult(
                    result=EvidenceResult.NOT_YET,
                    detail=f"Query type '{query_type}' not implemented for Workday.",
                )
        except Exception as exc:
            logger.warning(f"Workday evidence check error: {exc}", exc_info=True)
            return EvidenceCheckResult(
                result=EvidenceResult.ERROR,
                error_detail=str(exc),
            )

    def _check_comp_event(
        self, worker_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """
        Check for compensation change events for specified workers.

        In production, queries the Workday Compensation API for
        effective-dated events after action.created_at.
        """
        created_at = context.get("created_at")
        completed = []

        for wid in worker_ids:
            events = self.connector.get_comp_events(wid, after=created_at)
            if events:
                completed.append(wid)

        if len(completed) == len(worker_ids):
            return EvidenceCheckResult(
                result=EvidenceResult.FOUND,
                detail=f"Compensation events found for all {len(worker_ids)} workers.",
                evidence_data={"workers_updated": completed},
            )
        elif completed:
            return EvidenceCheckResult(
                result=EvidenceResult.PARTIAL,
                detail=f"Comp events found for {len(completed)}/{len(worker_ids)} workers.",
            )
        return EvidenceCheckResult(
            result=EvidenceResult.NOT_YET,
            detail="No compensation events found yet.",
        )

    def _check_position_filled(
        self, position_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """Check whether open positions have moved to FILLED status."""
        filled = []
        for pos_id in position_ids:
            pos = self.connector.get_position(pos_id)
            if pos and pos.get("status") == "FILLED":
                filled.append(pos_id)

        if len(filled) == len(position_ids):
            return EvidenceCheckResult(
                result=EvidenceResult.FOUND,
                detail=f"All {len(position_ids)} positions filled.",
            )
        elif filled:
            return EvidenceCheckResult(
                result=EvidenceResult.PARTIAL,
                detail=f"{len(filled)}/{len(position_ids)} positions filled.",
            )
        return EvidenceCheckResult(
            result=EvidenceResult.NOT_YET,
            detail="No positions filled yet.",
        )

    def _check_hire_event(
        self, requisition_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """Check whether hire events (onboarding records) exist for open reqs."""
        created_at = context.get("created_at")
        hired = [
            req_id for req_id in requisition_ids
            if self.connector.get_hire_event(req_id, after=created_at)
        ]

        if len(hired) == len(requisition_ids):
            return EvidenceCheckResult(result=EvidenceResult.FOUND,
                detail=f"Hire events found for all {len(requisition_ids)} requisitions.")
        elif hired:
            return EvidenceCheckResult(result=EvidenceResult.PARTIAL,
                detail=f"Hire events found for {len(hired)}/{len(requisition_ids)} reqs.")
        return EvidenceCheckResult(result=EvidenceResult.NOT_YET,
            detail="No hire events found yet.")

    def _check_termination(
        self, worker_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        """Check whether termination events have been finalized (for offboarding)."""
        terminated = [
            wid for wid in worker_ids
            if self.connector.is_terminated(wid)
        ]
        if len(terminated) == len(worker_ids):
            return EvidenceCheckResult(result=EvidenceResult.FOUND,
                detail=f"Termination finalized for all {len(worker_ids)} workers.")
        elif terminated:
            return EvidenceCheckResult(result=EvidenceResult.PARTIAL,
                detail=f"{len(terminated)}/{len(worker_ids)} terminations processed.")
        return EvidenceCheckResult(result=EvidenceResult.NOT_YET,
            detail="Termination events not yet finalized.")


# ── NetSuite checker ───────────────────────────────────────────────────────────


class NetSuiteEvidenceChecker:
    """Checks NetSuite for vendor/finance action completion evidence."""

    source_name = "netsuite"
    supported_query_types = [
        "po_approved",
        "vendor_invoice_paid",
        "contract_renewal_created",
    ]

    def __init__(self, connector: Any | None = None):
        self.connector = connector

    def check(
        self,
        query_type: str,
        target_ids: list[str],
        context: dict[str, Any],
    ) -> EvidenceCheckResult:
        if self.connector is None:
            return EvidenceCheckResult(
                result=EvidenceResult.NOT_YET,
                detail="NetSuite connector not configured for this tenant.",
            )

        try:
            if query_type == "po_approved":
                return self._check_po_approved(target_ids, context)
            elif query_type == "vendor_invoice_paid":
                return self._check_invoice_paid(target_ids, context)
            elif query_type == "contract_renewal_created":
                return self._check_contract_renewal(target_ids, context)
            else:
                return EvidenceCheckResult(
                    result=EvidenceResult.NOT_YET,
                    detail=f"Query type '{query_type}' not implemented for NetSuite.",
                )
        except Exception as exc:
            logger.warning(f"NetSuite evidence check error: {exc}", exc_info=True)
            return EvidenceCheckResult(
                result=EvidenceResult.ERROR,
                error_detail=str(exc),
            )

    def _check_po_approved(
        self, po_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        approved = [
            po_id for po_id in po_ids
            if self.connector.get_po_status(po_id) in ("Approved", "Received", "Fully Billed")
        ]
        if len(approved) == len(po_ids):
            return EvidenceCheckResult(result=EvidenceResult.FOUND,
                detail=f"All {len(po_ids)} POs approved.")
        elif approved:
            return EvidenceCheckResult(result=EvidenceResult.PARTIAL,
                detail=f"{len(approved)}/{len(po_ids)} POs approved.")
        return EvidenceCheckResult(result=EvidenceResult.NOT_YET,
            detail="POs not yet approved.")

    def _check_invoice_paid(
        self, vendor_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        created_at = context.get("created_at")
        paid = [
            vid for vid in vendor_ids
            if self.connector.get_recent_payments(vid, after=created_at)
        ]
        if len(paid) == len(vendor_ids):
            return EvidenceCheckResult(result=EvidenceResult.FOUND,
                detail=f"Invoice payments found for all {len(vendor_ids)} vendors.")
        elif paid:
            return EvidenceCheckResult(result=EvidenceResult.PARTIAL,
                detail=f"Payments found for {len(paid)}/{len(vendor_ids)} vendors.")
        return EvidenceCheckResult(result=EvidenceResult.NOT_YET,
            detail="No invoice payments detected yet.")

    def _check_contract_renewal(
        self, vendor_ids: list[str], context: dict
    ) -> EvidenceCheckResult:
        created_at = context.get("created_at")
        renewed = [
            vid for vid in vendor_ids
            if self.connector.get_renewal_records(vid, after=created_at)
        ]
        if len(renewed) == len(vendor_ids):
            return EvidenceCheckResult(result=EvidenceResult.FOUND,
                detail=f"Renewal records found for all {len(vendor_ids)} vendors.")
        elif renewed:
            return EvidenceCheckResult(result=EvidenceResult.PARTIAL,
                detail=f"Renewals found for {len(renewed)}/{len(vendor_ids)} vendors.")
        return EvidenceCheckResult(result=EvidenceResult.NOT_YET,
            detail="No renewal records created yet.")


# ── Registry ───────────────────────────────────────────────────────────────────

# Maps evidence_source → checker class
CHECKER_REGISTRY: dict[str, type] = {
    "sfdc": SalesforceEvidenceChecker,
    "workday": WorkdayEvidenceChecker,
    "netsuite": NetSuiteEvidenceChecker,
}


def get_checker(source: str, connector: Any = None) -> EvidenceChecker | None:
    """Return a checker instance for the given source name."""
    cls = CHECKER_REGISTRY.get(source)
    if cls is None:
        return None
    return cls(connector=connector)
