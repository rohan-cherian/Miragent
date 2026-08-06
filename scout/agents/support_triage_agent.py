"""
SupportTriageAgent — Sprint 64

Classifies inbound support tickets, pulls CRM account context, assigns
priority, routes to the correct team, and drafts a professional first response.

Why this matters:
  - Support teams spend 20-30% of their time on triage before actual resolution
  - High-ARR accounts getting P4 treatment because the agent didn't check CRM
  - Tickets landing in the wrong queue, bounced 2-3 times before resolution

What it does:
  1. Classify ticket into one of 8 categories using keyword + pattern matching
  2. Pull account context from CRM (ARR, health score, open deals, prior tickets)
  3. Compute priority score: base from category + modifiers from account data
  4. Assign to correct team queue
  5. Draft a professional first response using category-specific templates
  6. Flag escalation-worthy tickets (high ARR + critical category)

Categories:
  portal_access     → KeyRound  → customer-success + L1 IT
  billing_dispute   → Receipt   → billing
  technical_bug     → Bug       → engineering
  feature_request   → Lightbulb → product
  account_mgmt      → User      → customer-success
  security_concern  → Shield    → security (always P1)
  data_question     → Database  → engineering or customer-success
  general_inquiry   → HelpCircle → general
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class AccountContext:
    customer_email: str
    company_name: str
    arr: float                    # Annual Recurring Revenue
    health_score: int             # 0-100
    account_status: str           # "healthy" / "at_risk" / "churned" / "new"
    open_deals: int
    open_deal_value: float
    prior_tickets_30d: int        # tickets in last 30 days
    csm_name: str                 # Customer Success Manager
    csm_email: str
    is_enterprise: bool           # ARR > $100k
    contract_tier: str            # "enterprise" / "growth" / "starter"
    source: str                   # "crm" / "mock"


@dataclass
class TriageResult:
    ticket_id: str
    customer_email: str
    subject: str
    category: str
    category_label: str
    priority_score: int           # 0-100
    priority_label: str           # "P1-Critical" / "P2-High" / "P3-Medium" / "P4-Low"
    assigned_queue: str
    drafted_response: str
    account_context: AccountContext
    escalation_reason: Optional[str]  # None if no escalation needed
    routing_explanation: str      # why it was routed this way
    completed_at: datetime


# ── Agent class ────────────────────────────────────────────────────────────────


class SupportTriageAgent:
    """
    Autonomous support ticket classification, prioritization, and routing agent.

    Keyword matching classifies tickets into 8 categories. Account context
    (from Neo4j CRM or mock) modifies the base priority score. Enterprise,
    at-risk, and security tickets receive priority boosts. Draft responses
    use category-specific professional templates.
    """

    CATEGORIES: dict[str, dict] = {
        "portal_access":    {"label": "Portal Access",     "base_priority": 60, "queue": "customer-success"},
        "billing_dispute":  {"label": "Billing Dispute",   "base_priority": 55, "queue": "billing"},
        "technical_bug":    {"label": "Technical Bug",     "base_priority": 65, "queue": "engineering"},
        "feature_request":  {"label": "Feature Request",   "base_priority": 20, "queue": "product"},
        "account_mgmt":     {"label": "Account Management","base_priority": 45, "queue": "customer-success"},
        "security_concern": {"label": "Security Concern",  "base_priority": 95, "queue": "security"},
        "data_question":    {"label": "Data Question",     "base_priority": 40, "queue": "engineering"},
        "general_inquiry":  {"label": "General Inquiry",   "base_priority": 25, "queue": "general"},
    }

    CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "portal_access":    [
            "can't log in", "cannot login", "access denied", "password", "locked out",
            "login", "sign in", "portal", "authentication", "mfa", "two factor", "sso",
        ],
        "billing_dispute":  [
            "invoice", "charge", "billing", "payment", "refund", "overcharge", "credit",
            "subscription", "renewal", "price", "cost", "fee",
        ],
        "technical_bug":    [
            "error", "bug", "broken", "not working", "crash", "fail", "issue",
            "problem", "500", "404", "exception", "timeout", "slow",
        ],
        "feature_request":  [
            "feature", "request", "suggest", "would be great", "enhancement",
            "add", "improve", "wish", "could you", "can you add",
        ],
        "account_mgmt":     [
            "account", "user", "seat", "license", "team", "onboard", "offboard",
            "admin", "permission", "role",
        ],
        "security_concern": [
            "security", "breach", "hack", "unauthorized", "suspicious", "phishing",
            "vulnerability", "data leak", "gdpr", "compliance",
        ],
        "data_question":    [
            "data", "export", "report", "analytics", "api", "integration",
            "sync", "import", "csv", "webhook",
        ],
        "general_inquiry":  [],  # catch-all
    }

    # ── Public API ─────────────────────────────────────────────────────────────

    def run(
        self,
        customer_email: str,
        subject: str,
        body: str,
        tenant_id: str,
        ticket_id: str,
        customer_name: Optional[str] = None,
    ) -> TriageResult:
        """
        Triage a single inbound support ticket end-to-end.

        Returns a TriageResult with category, priority, queue, drafted response,
        and optional escalation reason.
        """
        try:
            category = self._classify(subject, body)
            account = self._get_account_context(customer_email, tenant_id)
            priority_score = self._compute_priority(category, account)
            priority_label = self._priority_label(priority_score)
            queue = self._assign_queue(category, account)
            response = self._draft_response(category, account, subject, priority_label, customer_name)
            escalation = self._check_escalation(category, account, priority_score)
            routing_explanation = self._explain_routing(category, account, priority_score, queue, subject, body)

            status_str = "escalated" if escalation else "draft_ready"

            logger.info(
                "SupportTriageAgent ticket=%s email=%s category=%s priority=%s queue=%s escalated=%s",
                ticket_id, customer_email, category, priority_label, queue, escalation is not None,
            )

            return TriageResult(
                ticket_id=ticket_id,
                customer_email=customer_email,
                subject=subject,
                category=category,
                category_label=self.CATEGORIES[category]["label"],
                priority_score=priority_score,
                priority_label=priority_label,
                assigned_queue=queue,
                drafted_response=response,
                account_context=account,
                escalation_reason=escalation,
                routing_explanation=routing_explanation,
                completed_at=datetime.now(timezone.utc),
            )

        except Exception as exc:
            logger.error("SupportTriageAgent error for ticket=%s: %s", ticket_id, exc)
            # Return a safe fallback result on error
            mock_account = self._mock_account(customer_email)
            return TriageResult(
                ticket_id=ticket_id,
                customer_email=customer_email,
                subject=subject,
                category="general_inquiry",
                category_label="General Inquiry",
                priority_score=25,
                priority_label="P4-Low",
                assigned_queue="general",
                drafted_response=self._draft_response("general_inquiry", mock_account, subject, "P4-Low", customer_name),
                account_context=mock_account,
                escalation_reason=None,
                routing_explanation=f"Error during triage: {exc}. Defaulted to general queue.",
                completed_at=datetime.now(timezone.utc),
            )

    # ── Classification ─────────────────────────────────────────────────────────

    def _classify(self, subject: str, body: str) -> str:
        """
        Classify a ticket into one of 8 categories via keyword matching.

        Subject is weighted 2x relative to body. Returns the category with the
        highest match count; ties or zero-match cases default to general_inquiry.
        """
        # Combine subject (2x weight) and body, lowercase
        text = (subject.lower() + " " + subject.lower() + " " + body.lower())

        scores: dict[str, int] = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            count = 0
            for kw in keywords:
                if kw in text:
                    count += 1
            if count > 0:
                scores[category] = count

        if not scores:
            return "general_inquiry"

        # Return the category with the highest score; tie-break: first insertion order wins
        return max(scores, key=lambda c: scores[c])

    # ── Account context ────────────────────────────────────────────────────────

    def _get_account_context(self, email: str, tenant_id: str) -> AccountContext:
        """
        Try Neo4j Account node by email/domain; fall back to mock.

        In production this would query the CRM connector (Salesforce, HubSpot)
        via the tenant's configured integration. The mock returns varied accounts
        based on email domain for demo diversity.
        """
        try:
            from scout.config import settings
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            with driver.session() as session:
                result = session.run(
                    """
                    MATCH (a:Account)
                    WHERE a.email = $email OR a.domain = $domain
                    RETURN a.company_name AS company_name,
                           a.arr AS arr,
                           a.health_score AS health_score,
                           a.account_status AS account_status,
                           a.open_deals AS open_deals,
                           a.open_deal_value AS open_deal_value,
                           a.prior_tickets_30d AS prior_tickets_30d,
                           a.csm_name AS csm_name,
                           a.csm_email AS csm_email,
                           a.contract_tier AS contract_tier
                    LIMIT 1
                    """,
                    email=email,
                    domain=email.split("@")[-1] if "@" in email else "",
                )
                record = result.single()
                if record and record["company_name"]:
                    arr = float(record["arr"] or 0)
                    driver.close()
                    return AccountContext(
                        customer_email=email,
                        company_name=record["company_name"],
                        arr=arr,
                        health_score=int(record["health_score"] or 75),
                        account_status=record["account_status"] or "healthy",
                        open_deals=int(record["open_deals"] or 0),
                        open_deal_value=float(record["open_deal_value"] or 0),
                        prior_tickets_30d=int(record["prior_tickets_30d"] or 0),
                        csm_name=record["csm_name"] or "Support Team",
                        csm_email=record["csm_email"] or "support@miragent.io",
                        is_enterprise=arr > 100_000,
                        contract_tier=record["contract_tier"] or "growth",
                        source="crm",
                    )
            driver.close()
        except Exception:
            pass  # Fall through to mock

        return self._mock_account(email)

    def _mock_account(self, email: str) -> AccountContext:
        """
        Return varied demo accounts based on email domain for smoke-test diversity.

        Domain patterns:
          @enterprise.com / @bigcorp.com → enterprise, $250k ARR, at_risk, health 72
          @startup.io / @techco.com      → growth, $45k ARR, healthy, health 85
          @smallbiz.com                  → starter, $8k ARR, healthy, health 90
          @company.com / @security.*     → growth, $65k ARR, healthy, health 78
          default                        → growth, $65k ARR, healthy, health 78
        """
        domain = email.split("@")[-1].lower() if "@" in email else ""

        if domain in ("enterprise.com", "bigcorp.com"):
            return AccountContext(
                customer_email=email,
                company_name="Enterprise Corp",
                arr=250_000.0,
                health_score=72,
                account_status="at_risk",
                open_deals=2,
                open_deal_value=85_000.0,
                prior_tickets_30d=4,
                csm_name="Jordan Reeves",
                csm_email="jordan.reeves@miragent.io",
                is_enterprise=True,
                contract_tier="enterprise",
                source="mock",
            )

        if domain in ("startup.io", "techco.com"):
            return AccountContext(
                customer_email=email,
                company_name="TechCo Startup",
                arr=45_000.0,
                health_score=85,
                account_status="healthy",
                open_deals=1,
                open_deal_value=25_000.0,
                prior_tickets_30d=1,
                csm_name="Sarah Mitchell",
                csm_email="sarah.mitchell@miragent.io",
                is_enterprise=False,
                contract_tier="growth",
                source="mock",
            )

        if domain == "smallbiz.com":
            return AccountContext(
                customer_email=email,
                company_name="Small Biz LLC",
                arr=8_000.0,
                health_score=90,
                account_status="healthy",
                open_deals=0,
                open_deal_value=0.0,
                prior_tickets_30d=1,
                csm_name="Priya Sharma",
                csm_email="priya.sharma@miragent.io",
                is_enterprise=False,
                contract_tier="starter",
                source="mock",
            )

        # Default: mid-market growth account
        # Use domain to derive a company name for display variety
        company = domain.split(".")[0].title() + " Inc." if domain else "Unknown Company"
        return AccountContext(
            customer_email=email,
            company_name=company,
            arr=65_000.0,
            health_score=78,
            account_status="healthy",
            open_deals=1,
            open_deal_value=30_000.0,
            prior_tickets_30d=2,
            csm_name="Jordan Reeves",
            csm_email="jordan.reeves@miragent.io",
            is_enterprise=False,
            contract_tier="growth",
            source="mock",
        )

    # ── Priority computation ───────────────────────────────────────────────────

    def _compute_priority(self, category: str, account: AccountContext) -> int:
        """
        Compute a 0-100 priority score.

        Base score comes from category configuration.  Account-aware modifiers
        boost (or lower) the score before clamping to [0, 100].

        Modifiers:
          +20  security_concern (on top of already-high base)
          +15  enterprise account (ARR > $100k)
          +10  health score < 60 (at-risk)
          +10  ARR > $100k (same customer, belt-and-suspenders)
          +5   prior_tickets_30d >= 3 (repeat contact — unresolved root cause?)
          +5   open_deal_value > $50k (active deal at risk)
          -10  feature_request (always deprioritize relative to issues)
        """
        score = self.CATEGORIES[category]["base_priority"]

        if category == "security_concern":
            score += 20
        if account.is_enterprise:
            score += 15
        if account.health_score < 60:
            score += 10
        if account.arr > 100_000:
            score += 10
        if account.prior_tickets_30d >= 3:
            score += 5
        if account.open_deal_value > 50_000:
            score += 5
        if category == "feature_request":
            score -= 10

        return max(0, min(100, score))

    def _priority_label(self, score: int) -> str:
        if score >= 80:
            return "P1-Critical"
        if score >= 60:
            return "P2-High"
        if score >= 40:
            return "P3-Medium"
        return "P4-Low"

    # ── Queue assignment ───────────────────────────────────────────────────────

    def _assign_queue(self, category: str, account: AccountContext) -> str:
        """
        Assign ticket to the correct team queue.

        Base queue comes from CATEGORIES. Overrides for special cases:
          - security_concern always routes to "security" regardless of tier
          - enterprise + technical_bug bypasses L1 → "engineering" directly
          - enterprise + billing_dispute → "billing" (already correct, but flagged)
        """
        # Security always overrides everything
        if category == "security_concern":
            return "security"

        base_queue = self.CATEGORIES[category]["queue"]

        # Enterprise bugs go directly to engineering — skip L1/customer-success
        if account.is_enterprise and category == "technical_bug":
            return "engineering"

        return base_queue

    # ── Draft response ─────────────────────────────────────────────────────────

    def _draft_response(
        self,
        category: str,
        account: AccountContext,
        subject: str,
        priority_label: str,
        customer_name: Optional[str] = None,
    ) -> str:
        """
        Generate a professional, empathetic first response using category templates.

        Enterprise accounts get a CSM sign-off. Response timelines scale with
        priority label.
        """
        name = customer_name or account.company_name or "there"
        sign_off = account.csm_name if account.is_enterprise else "Support Team"

        # Timeline lookup by priority
        timelines = {
            "P1-Critical": "1 hour",
            "P2-High": "4 hours",
            "P3-Medium": "1 business day",
            "P4-Low": "2 business days",
        }
        timeline = timelines.get(priority_label, "1 business day")

        if category == "portal_access":
            return (
                f"Hi {name},\n\n"
                "Thank you for reaching out. I can see you're having trouble accessing your account, "
                "and I want to get this resolved for you right away.\n\n"
                f"Our team is looking into this now and will have an update for you within {timeline}. "
                "In the meantime, you can try clearing your browser cache and using an incognito window — "
                "this resolves the issue in many cases.\n\n"
                "I'll follow up shortly.\n\n"
                f"— {sign_off}"
            )

        if category == "billing_dispute":
            return (
                f"Hi {name},\n\n"
                "Thank you for bringing this billing matter to our attention. "
                "I've flagged your inquiry to our billing team, who will review your account carefully "
                f"and respond within {timeline}.\n\n"
                "If this is time-sensitive or requires urgent resolution, please don't hesitate to let me know "
                "and we'll prioritize accordingly.\n\n"
                f"— {sign_off}"
            )

        if category == "technical_bug":
            return (
                f"Hi {name},\n\n"
                "Thank you for reporting this. Our engineering team has been notified and is investigating the issue.\n\n"
                f"You can expect a status update within {timeline}. "
                "In the meantime, if you're able to share any error messages, screenshots, or steps to reproduce "
                "the issue, that will help us resolve this faster.\n\n"
                "We'll keep you posted.\n\n"
                f"— {sign_off}"
            )

        if category == "security_concern":
            return (
                f"Hi {name},\n\n"
                "Thank you for bringing this to our attention immediately. "
                "We take security matters extremely seriously.\n\n"
                "Our security team has been alerted and will contact you within 1 hour. "
                "Please do not share further details over email — someone from our team will reach out "
                "via a secure channel to follow up.\n\n"
                "Thank you for your vigilance.\n\n"
                "— Security Team"
            )

        if category == "feature_request":
            return (
                f"Hi {name},\n\n"
                "Thank you for this suggestion — we love hearing how we can make the product better for you.\n\n"
                "I've logged this as a feature request and shared it with our product team for consideration. "
                "While I can't commit to a specific timeline, we review all requests as part of our quarterly "
                "roadmap planning process.\n\n"
                "We appreciate your feedback!\n\n"
                "— Product Team"
            )

        if category == "account_mgmt":
            return (
                f"Hi {name},\n\n"
                "Thank you for reaching out about your account. "
                f"Our customer success team will review your request and follow up within {timeline}.\n\n"
                "If you need anything in the meantime, feel free to reply to this message.\n\n"
                f"— {sign_off}"
            )

        if category == "data_question":
            return (
                f"Hi {name},\n\n"
                "Thank you for your question about your data. "
                f"I've routed this to our engineering team, who will review and respond within {timeline}.\n\n"
                "If you can share more details about the specific data or integration you're asking about, "
                "that will help us get you a precise answer faster.\n\n"
                f"— {sign_off}"
            )

        # general_inquiry (default)
        return (
            f"Hi {name},\n\n"
            "Thank you for reaching out. I've received your message and will get back to you "
            f"within {timeline}.\n\n"
            "If this is urgent, please let us know and we'll prioritize accordingly.\n\n"
            f"— {sign_off}"
        )

    # ── Escalation check ───────────────────────────────────────────────────────

    def _check_escalation(
        self,
        category: str,
        account: AccountContext,
        score: int,
    ) -> Optional[str]:
        """
        Determine if a ticket warrants immediate escalation.

        Returns a human-readable escalation reason, or None if no escalation needed.

        Rules (evaluated in priority order — first match wins):
          1. security_concern: always escalate
          2. enterprise + score >= 80: critical issue for high-value account
          3. at_risk + score >= 60: churn risk
          4. prior_tickets >= 5: chronic issue — unresolved root cause likely
        """
        arr_display = f"${account.arr / 1_000:.0f}k ARR" if account.arr < 1_000_000 else f"${account.arr / 1_000_000:.1f}M ARR"

        if category == "security_concern":
            return (
                f"Security concern from {account.contract_tier} customer ({arr_display}) — "
                "immediate review required by security team"
            )

        if account.is_enterprise and score >= 80:
            return (
                f"Enterprise customer ({arr_display}) with critical-priority issue — "
                f"escalate to senior {self.CATEGORIES[category]['queue']} team"
            )

        if account.account_status == "at_risk" and score >= 60:
            return (
                f"At-risk account ({arr_display}, health score {account.health_score}) with "
                "high-priority issue — churn risk, flag for CSM"
            )

        if account.prior_tickets_30d >= 5:
            return (
                f"Repeat contactor — {account.prior_tickets_30d} tickets in last 30 days. "
                "Possible unresolved root cause — schedule a call"
            )

        return None

    # ── Routing explanation ────────────────────────────────────────────────────

    def _explain_routing(
        self,
        category: str,
        account: AccountContext,
        score: int,
        queue: str,
        subject: str,
        body: str,
    ) -> str:
        """
        Generate a human-readable explanation of the triage decision.

        Surfaces which keywords matched, account factors that influenced priority,
        and the final routing decision. Used in the UI for transparency.
        """
        # Find matched keywords for the classified category
        text = (subject.lower() + " " + body.lower())
        matched = [kw for kw in self.CATEGORY_KEYWORDS.get(category, []) if kw in text]
        matched_display = ", ".join(f'"{k}"' for k in matched[:5]) if matched else "no keywords (catch-all)"

        parts = [
            f'Classified as {self.CATEGORIES[category]["label"]} (matched: {matched_display}).',
        ]

        arr_display = f"${account.arr / 1_000:.0f}k ARR" if account.arr < 1_000_000 else f"${account.arr / 1_000_000:.1f}M ARR"
        tier_label = account.contract_tier.title()
        parts.append(
            f"{tier_label} account — {account.company_name} ({arr_display}, "
            f"health score {account.health_score}, status: {account.account_status})."
        )

        priority_label = self._priority_label(score)
        parts.append(f"Priority computed as {priority_label} (score {score}/100).")

        if queue != self.CATEGORIES[category]["queue"]:
            parts.append(
                f"Routed to {queue} queue (override from default "
                f"{self.CATEGORIES[category]['queue']} — enterprise fast-track)."
            )
        else:
            parts.append(f"Routed to {queue} queue.")

        return " ".join(parts)
