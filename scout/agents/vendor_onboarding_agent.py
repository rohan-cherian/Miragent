"""
VendorOnboardingAgent — Sprint 67

Manages the vendor onboarding lifecycle: W9 collection, banking info, ERP
vendor record creation, and confirmation. Tracks onboarding status per vendor
through 8 stages from initial contact to fully active.

Business scenario:
  A new vendor contacts procurement: "We've been selected as your new software
  vendor — what do we need to do to get set up for payment?" The agent manages
  the W9 collection process, banking info collection, ERP vendor record creation,
  and sends confirmation. It tracks onboarding status per vendor.

Onboarding stages (in order):
  initiated          — vendor submits their info request
  w9_requested       — W9 form requested from vendor
  w9_received        — W9 received, under review
  banking_requested  — banking info requested (after W9 cleared)
  banking_received   — ACH/wire details received
  erp_setup          — vendor record being created in NetSuite/QuickBooks
  active             — fully onboarded, ready for payment
  on_hold            — missing info, action required

Stall detection: any vendor with stage NOT in (active, on_hold) and
  days_in_process > 14 is considered stalled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class VendorOnboardingRecord:
    vendor_id: str
    vendor_name: str
    vendor_email: str
    stage: str                       # see module docstring for valid values
    entity_type: str
    ein: str | None
    bank_info: str | None            # masked last 4 only
    hold_reason: str | None
    submitted_date: str | None
    completed_date: str | None
    days_in_process: int
    checklist: list[str]
    next_step: str
    internal_contact: str            # who at company handles this vendor
    confirmation_message: str        # vendor-facing status message
    is_stalled: bool                 # True if > 14 days in process and not active/on_hold


# ── Agent class ────────────────────────────────────────────────────────────────


class VendorOnboardingAgent:
    """
    Autonomous vendor onboarding workflow agent.

    Uses a mock vendor roster (10 vendors) for demo/dev. In production this
    would query the ERP (NetSuite, QuickBooks) and procurement systems directly.
    Stage transitions are deterministic — no LLM needed.
    """

    # ── Mock vendor data ───────────────────────────────────────────────────────

    _MOCK_VENDORS: list[dict] = [
        {
            "vendor_id": "VND-001",
            "vendor_name": "Apex Financial Partners",
            "vendor_email": "ap@apexfinancial.com",
            "stage": "active",
            "entity_type": "LLC",
            "ein": "82-1234567",
            "bank_info": "Chase ****4821",
            "hold_reason": None,
            "submitted_date": "2024-01-05",
            "completed_date": "2024-01-10",
        },
        {
            "vendor_id": "VND-002",
            "vendor_name": "BlueSky Marketing Group",
            "vendor_email": "invoices@blueskymarketing.com",
            "stage": "w9_received",
            "entity_type": "S-Corp",
            "ein": "pending_review",
            "bank_info": None,
            "hold_reason": None,
            "submitted_date": "2024-03-01",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-003",
            "vendor_name": "CoreSystems Ltd",
            "vendor_email": "finance@coresystems.io",
            "stage": "banking_requested",
            "entity_type": "C-Corp",
            "ein": "45-9876543",
            "bank_info": "pending",
            "hold_reason": None,
            "submitted_date": "2024-02-15",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-004",
            "vendor_name": "DataBridge Pro",
            "vendor_email": "ap@databridgepro.io",
            "stage": "active",
            "entity_type": "LLC",
            "ein": "73-5551234",
            "bank_info": "BofA ****7732",
            "hold_reason": None,
            "submitted_date": "2024-01-25",
            "completed_date": "2024-02-01",
        },
        {
            "vendor_id": "VND-005",
            "vendor_name": "EdgePoint Analytics",
            "vendor_email": "billing@edgepoint.ai",
            "stage": "initiated",
            "entity_type": "unknown",
            "ein": None,
            "bank_info": None,
            "hold_reason": None,
            "submitted_date": "2024-03-20",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-006",
            "vendor_name": "Frontier Energy Solutions",
            "vendor_email": "ar@frontierenergy.com",
            "stage": "on_hold",
            "entity_type": "Corporation",
            "ein": "58-3334444",
            "bank_info": "pending",
            "hold_reason": "W9 mismatch — EIN does not match IRS records",
            "submitted_date": "2024-01-28",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-007",
            "vendor_name": "GlobalLink Media",
            "vendor_email": "payments@globallink.com",
            "stage": "erp_setup",
            "entity_type": "LLC",
            "ein": "91-2223333",
            "bank_info": "Wells Fargo ****9910",
            "hold_reason": None,
            "submitted_date": "2024-03-05",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-008",
            "vendor_name": "HorizonPath Consulting",
            "vendor_email": "billing@horizonpath.com",
            "stage": "w9_requested",
            "entity_type": "unknown",
            "ein": None,
            "bank_info": None,
            "hold_reason": None,
            "submitted_date": "2024-03-18",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-009",
            "vendor_name": "IntelliCore Systems",
            "vendor_email": "ap@intellicore.tech",
            "stage": "banking_received",
            "entity_type": "C-Corp",
            "ein": "22-8887777",
            "bank_info": "Citibank ****3312",
            "hold_reason": None,
            "submitted_date": "2024-02-20",
            "completed_date": None,
        },
        {
            "vendor_id": "VND-010",
            "vendor_name": "JetStream Logistics",
            "vendor_email": "finance@jetstream.biz",
            "stage": "active",
            "entity_type": "LLC",
            "ein": "64-1119999",
            "bank_info": "Chase ****5543",
            "hold_reason": None,
            "submitted_date": "2023-12-01",
            "completed_date": "2023-12-15",
        },
    ]

    # ── Stage metadata ─────────────────────────────────────────────────────────

    # Valid stages in order
    _STAGE_ORDER: list[str] = [
        "initiated",
        "w9_requested",
        "w9_received",
        "banking_requested",
        "banking_received",
        "erp_setup",
        "active",
        "on_hold",
    ]

    _CHECKLISTS: dict[str, list[str]] = {
        "initiated":         ["Submit W9 form", "Provide banking information", "Confirm entity type"],
        "w9_requested":      ["Return completed W9 form to procurement"],
        "w9_received":       ["Await W9 review completion (2-3 business days)", "Prepare banking info for next step"],
        "banking_requested": ["Provide ACH routing number", "Provide account number", "Provide bank name", "Confirm account type (checking/savings)"],
        "banking_received":  ["ERP vendor record creation in progress — internal task"],
        "erp_setup":         [],
        "active":            [],
        "on_hold":           [],  # populated dynamically from hold_reason
    }

    _NEXT_STEPS: dict[str, str] = {
        "initiated":         "Procurement will send a W9 request within 1-2 business days",
        "w9_requested":      "Complete and return the W9 form to procurement",
        "w9_received":       "Await W9 review — procurement will follow up within 2-3 business days",
        "banking_requested": "Submit ACH banking details (routing, account number, bank, account type) to procurement",
        "banking_received":  "Internal: create ERP vendor record in NetSuite/QuickBooks",
        "erp_setup":         "Internal processing only — vendor will be notified upon completion",
        "active":            "Submit invoices to ap@company.com — payment terms are Net-30",
        "on_hold":           "Contact procurement@company.com to resolve the hold condition",
    }

    _CONFIRMATION_MESSAGES: dict[str, str] = {
        "initiated":
            "Thank you for your interest in becoming a vendor. Our procurement team has received your request. "
            "Please watch for an email requesting your W9 within 1-2 business days.",
        "w9_requested":
            "We have sent a W9 request. Please complete and return it to complete the verification step.",
        "w9_received":
            "We have received your W9 and are reviewing it. Once verified, we will send banking information instructions. "
            "Typical review time: 2-3 business days.",
        "banking_requested":
            "Your W9 has been verified. Please provide your ACH banking details (routing number, account number, "
            "account type, bank name) by replying to our procurement email.",
        "banking_received":
            "We have received your banking information. Our team is now setting up your vendor record in our payment system. "
            "You will receive a confirmation within 3-5 business days.",
        "erp_setup":
            "Your vendor record is being created in our payment system. No action needed from you. "
            "Estimated completion: 1-3 business days.",
        "active":
            "You are fully onboarded as an approved vendor. You may now submit invoices to ap@company.com. "
            "Payment terms are Net-30 unless otherwise agreed.",
        "on_hold":
            "Your onboarding is temporarily on hold. {hold_reason}. "
            "Please contact procurement@company.com to resolve.",
    }

    # ── Internal contact routing ───────────────────────────────────────────────

    _CONTACTS: dict[str, str] = {
        "VND-001": "Maria Santos (Procurement Lead) — procurement@company.com",
        "VND-002": "Maria Santos (Procurement Lead) — procurement@company.com",
        "VND-003": "Maria Santos (Procurement Lead) — procurement@company.com",
        "VND-004": "Maria Santos (Procurement Lead) — procurement@company.com",
        "VND-005": "Maria Santos (Procurement Lead) — procurement@company.com",
        "VND-006": "James Park (Senior Vendor Manager) — procurement@company.com",
        "VND-007": "James Park (Senior Vendor Manager) — procurement@company.com",
        "VND-008": "James Park (Senior Vendor Manager) — procurement@company.com",
        "VND-009": "James Park (Senior Vendor Manager) — procurement@company.com",
        "VND-010": "James Park (Senior Vendor Manager) — procurement@company.com",
    }

    _DEFAULT_CONTACT = "procurement@company.com"

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_status(self, vendor_email: str, tenant_id: str, db) -> VendorOnboardingRecord:
        """
        Look up a vendor's onboarding status by email.

        Returns a fully hydrated VendorOnboardingRecord with checklist, next step,
        confirmation message, and internal contact. If not found, returns a
        not-found sentinel record.
        """
        vendor = self._find_vendor(vendor_email)
        if vendor is None:
            logger.warning(
                "VendorOnboardingAgent get_status email=%s tenant=%s NOT_FOUND",
                vendor_email,
                tenant_id,
            )
            return self._not_found_record(vendor_email)

        logger.info(
            "VendorOnboardingAgent get_status email=%s tenant=%s stage=%s",
            vendor_email,
            tenant_id,
            vendor["stage"],
        )
        return self._build_record(vendor)

    def initiate_onboarding(
        self,
        vendor_name: str,
        vendor_email: str,
        entity_type: str,
        tenant_id: str,
        db,
    ) -> VendorOnboardingRecord:
        """
        Initiate a new vendor onboarding workflow.

        Creates a new vendor record at stage=initiated. In production this
        would persist to the DB. For demo, returns a constructed record.
        """
        logger.info(
            "VendorOnboardingAgent initiate email=%s entity=%s tenant=%s",
            vendor_email,
            entity_type,
            tenant_id,
        )

        today = date.today().isoformat()
        new_vendor = {
            "vendor_id": f"VND-NEW-{vendor_email[:8].upper()}",
            "vendor_name": vendor_name,
            "vendor_email": vendor_email,
            "stage": "initiated",
            "entity_type": entity_type or "unknown",
            "ein": None,
            "bank_info": None,
            "hold_reason": None,
            "submitted_date": today,
            "completed_date": None,
        }
        return self._build_record(new_vendor)

    def get_all_in_progress(self, tenant_id: str, db) -> list[VendorOnboardingRecord]:
        """
        Return all vendors not yet active and not on hold.

        Covers stages: initiated, w9_requested, w9_received, banking_requested,
        banking_received, erp_setup.
        """
        logger.info(
            "VendorOnboardingAgent get_all_in_progress tenant=%s",
            tenant_id,
        )
        in_progress_stages = {
            "initiated", "w9_requested", "w9_received",
            "banking_requested", "banking_received", "erp_setup",
        }
        vendors = [v for v in self._MOCK_VENDORS if v["stage"] in in_progress_stages]
        return [self._build_record(v) for v in vendors]

    def get_blocked(self, tenant_id: str, db) -> list[VendorOnboardingRecord]:
        """
        Return all on_hold vendors plus any stalled vendors (> 14 days in process,
        not yet active or on_hold).

        Stall detection: stage NOT in (active, on_hold) AND days_in_process > 14.
        """
        logger.info(
            "VendorOnboardingAgent get_blocked tenant=%s",
            tenant_id,
        )
        terminal_stages = {"active"}
        records = []
        for vendor in self._MOCK_VENDORS:
            stage = vendor["stage"]
            if stage == "on_hold":
                records.append(self._build_record(vendor))
                continue
            if stage not in terminal_stages:
                days = self._compute_days(vendor)
                if days > 14:
                    records.append(self._build_record(vendor))
        return records

    # ── Record builder ─────────────────────────────────────────────────────────

    def _build_record(self, vendor: dict) -> VendorOnboardingRecord:
        """Build a fully hydrated VendorOnboardingRecord from a raw vendor dict."""
        stage = vendor["stage"]
        vendor_id = vendor["vendor_id"]
        hold_reason = vendor.get("hold_reason")

        checklist = list(self._CHECKLISTS.get(stage, []))
        if stage == "on_hold" and hold_reason:
            checklist = [f"Resolve: {hold_reason}", "Contact procurement@company.com"]

        # Build confirmation message
        msg_template = self._CONFIRMATION_MESSAGES.get(
            stage,
            "Please contact procurement@company.com for your onboarding status.",
        )
        if stage == "on_hold" and hold_reason:
            confirmation_message = msg_template.replace("{hold_reason}", hold_reason)
        else:
            confirmation_message = msg_template

        # For w9_requested, include email in message
        if stage == "w9_requested":
            confirmation_message = (
                f"We have sent a W9 request to {vendor['vendor_email']}. "
                "Please complete and return it to complete the verification step."
            )

        contact = self._CONTACTS.get(vendor_id, self._DEFAULT_CONTACT)
        days = self._compute_days(vendor)
        is_stalled = stage not in ("active", "on_hold") and days > 14

        return VendorOnboardingRecord(
            vendor_id=vendor_id,
            vendor_name=vendor["vendor_name"],
            vendor_email=vendor["vendor_email"],
            stage=stage,
            entity_type=vendor.get("entity_type", "unknown") or "unknown",
            ein=vendor.get("ein"),
            bank_info=vendor.get("bank_info"),
            hold_reason=hold_reason,
            submitted_date=vendor.get("submitted_date"),
            completed_date=vendor.get("completed_date"),
            days_in_process=days,
            checklist=checklist,
            next_step=self._NEXT_STEPS.get(stage, "Contact procurement@company.com"),
            internal_contact=contact,
            confirmation_message=confirmation_message,
            is_stalled=is_stalled,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _find_vendor(self, email: str) -> dict | None:
        """Look up a vendor by email (case-insensitive). Returns None if not found."""
        target = email.lower().strip()
        for v in self._MOCK_VENDORS:
            if v["vendor_email"].lower() == target:
                return v
        return None

    def _compute_days(self, vendor: dict) -> int:
        """
        Compute days in process.

        For active vendors: completed_date - submitted_date.
        For all others: today - submitted_date.
        Returns 0 if dates are missing or unparseable.
        """
        submitted_str = vendor.get("submitted_date")
        if not submitted_str:
            return 0

        try:
            submitted = datetime.strptime(submitted_str, "%Y-%m-%d").date()
        except ValueError:
            return 0

        if vendor["stage"] == "active" and vendor.get("completed_date"):
            try:
                completed = datetime.strptime(vendor["completed_date"], "%Y-%m-%d").date()
                return max(0, (completed - submitted).days)
            except ValueError:
                pass

        return max(0, (date.today() - submitted).days)

    def _not_found_record(self, vendor_email: str) -> VendorOnboardingRecord:
        """Return a graceful not-found record rather than raising."""
        return VendorOnboardingRecord(
            vendor_id="NOT_FOUND",
            vendor_name="Unknown Vendor",
            vendor_email=vendor_email,
            stage="initiated",
            entity_type="unknown",
            ein=None,
            bank_info=None,
            hold_reason=None,
            submitted_date=None,
            completed_date=None,
            days_in_process=0,
            checklist=["Submit W9 form", "Provide banking information", "Confirm entity type"],
            next_step="No vendor found for this email. Contact procurement@company.com.",
            internal_contact=self._DEFAULT_CONTACT,
            confirmation_message=(
                f"No vendor onboarding record was found for {vendor_email}. "
                "Please contact procurement@company.com if you believe this is an error."
            ),
            is_stalled=False,
        )
