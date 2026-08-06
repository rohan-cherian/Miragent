"""
PaymentStatusAgent — Sprint 65

Handles vendor payment status inquiries for AP teams. Vendors asking
"where is my invoice?" get a structured response with status, hold reason,
approver routing, and a professional draft reply.

Business scenario:
  A vendor emails AP: "Invoice #4821 was submitted 45 days ago — when will
  it be paid?" The agent looks up the invoice, returns structured status,
  identifies if it's stuck (and why), drafts the vendor response, and routes
  stuck invoices to the right approver.

Invoice lifecycle (in order):
  received → under_review → approved → scheduled → paid | rejected | on_hold

Stuck invoice detection:
  on_hold               → identify hold reason from invoice data
  under_review + >30d   → flag as "overdue review"
  received + >14d       → flag as "stuck in queue"
  approved + no date + >7d → flag as "approval delay"

Hold reason → approver routing:
  missing W9      → vendor_management (procurement@company.com)
  missing PO      → department_head (ops@company.com)
  over budget     → cfo (cfo@company.com)
  over threshold  → board_approval (board@company.com)
  duplicate       → ap_team (ap@company.com)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class PaymentStatusResult:
    invoice_id: str
    vendor_name: str
    vendor_email: str
    amount: float
    status: str           # received/under_review/approved/scheduled/paid/rejected/on_hold
    submitted_date: str   # ISO date string
    payment_date: Optional[str]    # ISO date string or None
    hold_reason: Optional[str]
    is_stuck: bool
    stuck_reason: Optional[str]
    approver: Optional[str]        # email of who needs to act
    approver_role: Optional[str]
    draft_response: str
    days_outstanding: int


@dataclass
class StuckInvoice:
    invoice_id: str
    vendor_name: str
    amount: float
    status: str
    stuck_reason: str
    approver: Optional[str]
    approver_role: Optional[str]
    days_outstanding: int


# ── Agent class ────────────────────────────────────────────────────────────────


class PaymentStatusAgent:
    """
    Autonomous AP invoice status lookup, stuck detection, and vendor response
    drafting agent.

    Uses a mock invoice store (15 invoices) for demo/dev. In production this
    would query the ERP (NetSuite, SAP, QuickBooks) via the tenant connector.
    Stuck invoice logic fires rules deterministically — no LLM needed for
    classification; LLM is only used for free-form response generation if
    enabled.
    """

    # ── Mock invoice data ──────────────────────────────────────────────────────
    #
    # All submitted_date values are set relative to a fixed reference point so
    # stuck-detection thresholds fire correctly in demos regardless of today's
    # actual date. The reference date is 2024-04-15 (mid-sprint demo date).
    # days_outstanding is computed live from today's date.

    _MOCK_INVOICES: list[dict] = [
        {
            "invoice_id": "INV-2024-001",
            "vendor_name": "Acme Cloud",
            "vendor_email": "cloudpeak@acmecorp.com",
            "amount": 12_400.0,
            "status": "paid",
            "submitted_date": "2023-12-31",
            "payment_date": "2024-01-15",
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-002",
            "vendor_name": "DataBridge Pro",
            "vendor_email": "ap@databridgepro.io",
            "amount": 8_750.0,
            "status": "scheduled",
            "submitted_date": "2024-02-01",
            "payment_date": "2024-02-28",
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-003",
            "vendor_name": "NexGen Staffing",
            "vendor_email": "billing@nexgenstaffing.com",
            "amount": 31_200.0,
            "status": "on_hold",
            "submitted_date": "2024-01-10",
            "payment_date": None,
            "hold_reason": "missing W9",
        },
        {
            "invoice_id": "INV-2024-004",
            "vendor_name": "Vertex Analytics",
            "vendor_email": "invoices@vertexanalytics.com",
            "amount": 5_600.0,
            "status": "approved",
            "submitted_date": "2024-03-01",
            "payment_date": None,
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-005",
            "vendor_name": "CloudHost Inc",
            "vendor_email": "ar@cloudhost.io",
            "amount": 18_900.0,
            "status": "under_review",
            "submitted_date": "2024-01-05",
            "payment_date": None,
            "hold_reason": "over budget — needs CFO approval",
        },
        {
            "invoice_id": "INV-2024-006",
            "vendor_name": "TechForce Solutions",
            "vendor_email": "billing@techforce.com",
            "amount": 7_200.0,
            "status": "paid",
            "submitted_date": "2024-01-15",
            "payment_date": "2024-02-01",
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-007",
            "vendor_name": "GlobalLink Media",
            "vendor_email": "ap@globallinkmedia.com",
            "amount": 22_500.0,
            "status": "rejected",
            "submitted_date": "2024-02-10",
            "payment_date": None,
            "hold_reason": "duplicate invoice",
        },
        {
            "invoice_id": "INV-2024-008",
            "vendor_name": "PrimeEdge Consulting",
            "vendor_email": "invoices@primeedge.com",
            "amount": 15_000.0,
            "status": "received",
            "submitted_date": "2024-03-25",
            "payment_date": None,
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-009",
            "vendor_name": "SecureVault IT",
            "vendor_email": "billing@securevault.com",
            "amount": 9_800.0,
            "status": "on_hold",
            "submitted_date": "2024-02-15",
            "payment_date": None,
            "hold_reason": "missing PO number",
        },
        {
            "invoice_id": "INV-2024-010",
            "vendor_name": "Meridian Logistics",
            "vendor_email": "ap@meridianlogistics.com",
            "amount": 4_300.0,
            "status": "paid",
            "submitted_date": "2024-02-20",
            "payment_date": "2024-03-10",
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-011",
            "vendor_name": "BlueSky Marketing",
            "vendor_email": "billing@blueskymarketing.com",
            "amount": 11_600.0,
            "status": "approved",
            "submitted_date": "2024-03-10",
            "payment_date": None,
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-012",
            "vendor_name": "Apex Financial",
            "vendor_email": "invoices@apexfinancial.com",
            "amount": 28_400.0,
            "status": "under_review",
            "submitted_date": "2024-01-20",
            "payment_date": None,
            "hold_reason": "pending department approval",
        },
        {
            "invoice_id": "INV-2024-013",
            "vendor_name": "CoreSystems Ltd",
            "vendor_email": "ap@coresystems.com",
            "amount": 6_700.0,
            "status": "scheduled",
            "submitted_date": "2024-03-01",
            "payment_date": "2024-04-01",
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-014",
            "vendor_name": "Pinnacle HR",
            "vendor_email": "billing@pinnaclehr.com",
            "amount": 3_200.0,
            "status": "received",
            "submitted_date": "2024-04-01",
            "payment_date": None,
            "hold_reason": None,
        },
        {
            "invoice_id": "INV-2024-015",
            "vendor_name": "Frontier Energy",
            "vendor_email": "ap@frontierenergy.com",
            "amount": 45_000.0,
            "status": "on_hold",
            "submitted_date": "2024-01-25",
            "payment_date": None,
            "hold_reason": "over $25k threshold, requires board approval",
        },
    ]

    # ── Hold reason → approver routing ────────────────────────────────────────

    _HOLD_APPROVERS: dict[str, tuple[str, str]] = {
        # keyword substring → (role, email)
        "missing w9":      ("vendor_management", "procurement@company.com"),
        "missing po":      ("department_head",   "ops@company.com"),
        "over budget":     ("cfo",               "cfo@company.com"),
        "over $25k":       ("board_approval",    "board@company.com"),
        "threshold":       ("board_approval",    "board@company.com"),
        "duplicate":       ("ap_team",           "ap@company.com"),
    }

    # ── Public API ─────────────────────────────────────────────────────────────

    def lookup_invoice(
        self, invoice_id: str, tenant_id: str, db
    ) -> PaymentStatusResult:
        """
        Look up a single invoice by ID.

        Falls back to a NOT_FOUND result if the invoice is unknown so the API
        always returns a structured object (never a raw exception).
        """
        raw = self._find_invoice(invoice_id)
        if raw is None:
            logger.warning(
                "PaymentStatusAgent lookup_invoice invoice_id=%s tenant_id=%s NOT_FOUND",
                invoice_id,
                tenant_id,
            )
            return self._not_found_result(invoice_id)

        return self._build_result(raw)

    def lookup_by_vendor(
        self, vendor_email: str, tenant_id: str, db
    ) -> list[PaymentStatusResult]:
        """
        Look up all invoices for a vendor by email address.

        Returns an empty list (not an error) if no invoices match.
        """
        matches = [
            inv for inv in self._MOCK_INVOICES
            if inv["vendor_email"].lower() == vendor_email.lower()
        ]
        logger.info(
            "PaymentStatusAgent lookup_by_vendor email=%s tenant_id=%s found=%d",
            vendor_email,
            tenant_id,
            len(matches),
        )
        return [self._build_result(raw) for raw in matches]

    def draft_response(self, result: PaymentStatusResult) -> str:
        """
        Generate a professional vendor-facing response for the given invoice status.

        This is the same logic used internally during lookup — exposed publicly
        so callers can re-draft after updating invoice state.
        """
        return self._build_draft_response(result.status, result)

    def identify_stuck(
        self, invoices: list[PaymentStatusResult]
    ) -> list[StuckInvoice]:
        """
        Filter a list of PaymentStatusResult objects to those that are stuck.

        Returns StuckInvoice objects (lighter weight, approver-focused) sorted
        by days_outstanding descending so the most overdue items surface first.
        """
        stuck = [
            StuckInvoice(
                invoice_id=inv.invoice_id,
                vendor_name=inv.vendor_name,
                amount=inv.amount,
                status=inv.status,
                stuck_reason=inv.stuck_reason or "",
                approver=inv.approver,
                approver_role=inv.approver_role,
                days_outstanding=inv.days_outstanding,
            )
            for inv in invoices
            if inv.is_stuck
        ]
        return sorted(stuck, key=lambda s: s.days_outstanding, reverse=True)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _find_invoice(self, invoice_id: str) -> dict | None:
        """Return raw mock invoice dict or None."""
        target = invoice_id.upper().strip()
        for inv in self._MOCK_INVOICES:
            if inv["invoice_id"].upper() == target:
                return inv
        return None

    def _build_result(self, raw: dict) -> PaymentStatusResult:
        """
        Construct a full PaymentStatusResult from raw invoice dict.

        Computes days_outstanding, runs stuck detection, resolves approver
        routing, and generates the draft vendor response.
        """
        days = self._days_outstanding(raw["submitted_date"])
        status = raw["status"]
        hold_reason = raw.get("hold_reason")

        is_stuck, stuck_reason = self._detect_stuck(status, hold_reason, days, raw.get("payment_date"))
        approver_role, approver_email = self._resolve_approver(status, hold_reason, is_stuck)

        # Build a partial result first — needed to generate the draft response
        partial = PaymentStatusResult(
            invoice_id=raw["invoice_id"],
            vendor_name=raw["vendor_name"],
            vendor_email=raw["vendor_email"],
            amount=raw["amount"],
            status=status,
            submitted_date=raw["submitted_date"],
            payment_date=raw.get("payment_date"),
            hold_reason=hold_reason,
            is_stuck=is_stuck,
            stuck_reason=stuck_reason,
            approver=approver_email,
            approver_role=approver_role,
            draft_response="",  # filled below
            days_outstanding=days,
        )

        partial.draft_response = self._build_draft_response(status, partial)
        return partial

    def _days_outstanding(self, submitted_date: str) -> int:
        """Compute calendar days from submitted_date to today."""
        try:
            sub = date.fromisoformat(submitted_date)
            return (date.today() - sub).days
        except Exception:
            return 0

    def _detect_stuck(
        self,
        status: str,
        hold_reason: str | None,
        days: int,
        payment_date: str | None,
    ) -> tuple[bool, str | None]:
        """
        Evaluate stuck-invoice rules in priority order.

        Rules:
          1. on_hold → always stuck, reason from hold_reason
          2. under_review + >30d → overdue review
          3. received + >14d → stuck in queue
          4. approved + no payment_date + >7d → approval delay
        """
        if status == "on_hold":
            reason = f"Invoice is on hold: {hold_reason}" if hold_reason else "Invoice is on hold"
            return True, reason

        if status == "under_review" and days > 30:
            return True, f"Under review for {days} days (threshold: 30 days)"

        if status == "received" and days > 14:
            return True, f"Stuck in queue for {days} days (threshold: 14 days)"

        if status == "approved" and not payment_date and days > 7:
            return True, f"Approved {days} days ago but not yet scheduled for payment"

        return False, None

    def _resolve_approver(
        self,
        status: str,
        hold_reason: str | None,
        is_stuck: bool,
    ) -> tuple[str | None, str | None]:
        """
        Map hold_reason to an approver role + email using substring matching.

        Returns (None, None) for non-stuck or non-hold invoices.
        """
        if not is_stuck:
            return None, None

        if status == "on_hold" and hold_reason:
            reason_lower = hold_reason.lower()
            for keyword, (role, email) in self._HOLD_APPROVERS.items():
                if keyword in reason_lower:
                    return role, email
            # Catch-all for unknown hold reasons
            return "ap_team", "ap@company.com"

        # Stuck but not on_hold — route to AP for follow-up
        return "ap_team", "ap@company.com"

    def _build_draft_response(self, status: str, inv: PaymentStatusResult) -> str:
        """
        Generate a professional vendor-facing response based on invoice status.

        Templates follow the AP team's standard communication style:
        specific, factual, with clear next steps and realistic timelines.
        """
        inv_id = inv.invoice_id
        amount = f"${inv.amount:,.2f}"

        if status == "paid":
            pay_date = inv.payment_date or "a recent date"
            return (
                f"Your invoice {inv_id} for {amount} was processed on {pay_date}. "
                "Payment was issued via ACH. Please allow 1-3 business days for funds to appear "
                "in your account. If you have not received funds after 3 business days, "
                "please reply with your banking details for verification."
            )

        if status == "scheduled":
            pay_date = inv.payment_date or "an upcoming payment run"
            return (
                f"Your invoice {inv_id} is approved and scheduled for payment on {pay_date}. "
                "You will receive a payment confirmation email once the transaction is processed. "
                "Please ensure your banking information on file is current."
            )

        if status == "on_hold":
            reason_detail = inv.hold_reason or "a documentation issue"
            return (
                f"Your invoice {inv_id} is currently on hold. {reason_detail.capitalize()}. "
                "We are working to resolve this and will contact you within 2 business days "
                "with the information needed to release your payment. "
                "If you have questions in the meantime, please reference this invoice number."
            )

        if status == "under_review":
            return (
                f"Your invoice {inv_id} for {amount} is currently under review by our "
                "accounts payable team. Expected completion: 3-5 business days. "
                "You will be notified by email once the review is complete and payment is scheduled."
            )

        if status == "approved":
            return (
                f"Your invoice {inv_id} for {amount} has been approved and will be included "
                "in our next payment run. Payment runs are processed bi-weekly. "
                "You will receive a confirmation once payment is issued."
            )

        if status == "received":
            return (
                f"Your invoice {inv_id} was received and is in our processing queue. "
                "Standard processing takes 10-15 business days. "
                "You will be notified once the invoice moves to the review stage. "
                "Please do not resubmit unless you receive a rejection notice."
            )

        if status == "rejected":
            reason = inv.hold_reason or "it did not meet our submission requirements"
            return (
                f"Your invoice {inv_id} was rejected because {reason}. "
                f"Please submit a corrected invoice referencing {inv_id} as the original submission. "
                "Our AP team is available to assist with resubmission questions."
            )

        # Fallback for unknown statuses
        return (
            f"Your invoice {inv_id} for {amount} is currently being processed. "
            "Please contact our AP team at ap@company.com for a status update."
        )

    def _not_found_result(self, invoice_id: str) -> PaymentStatusResult:
        """Return a graceful not-found result rather than raising."""
        return PaymentStatusResult(
            invoice_id=invoice_id,
            vendor_name="Unknown",
            vendor_email="",
            amount=0.0,
            status="not_found",
            submitted_date="",
            payment_date=None,
            hold_reason=None,
            is_stuck=False,
            stuck_reason=None,
            approver=None,
            approver_role=None,
            draft_response=(
                f"Invoice {invoice_id} was not found in our system. "
                "Please verify the invoice number and resubmit, or contact "
                "ap@company.com for assistance."
            ),
            days_outstanding=0,
        )
