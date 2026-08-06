"""
scout/workers/outreach_sequence.py — Outreach Sequence Worker

Generates personalized 5-touch outreach sequences for top ICP-qualified
prospects. Uses account data (industry, size, revenue) to select the most
relevant messaging angle. In Sprint 9, sequences are template-based with
account-specific personalization. Sprint 12 will enable AI-generated
sequences via Claude when the API key is configured.
"""

import logging

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

ICP_INDUSTRIES = {"Financial Services", "Technology", "Healthcare", "Manufacturing"}

_INDUSTRY_PAIN = {
    "Financial Services": (
        "compliance burden",
        "audit trail complexity",
        "regulatory reporting overhead",
    ),
    "Technology": (
        "engineering velocity",
        "technical debt",
        "scaling infrastructure costs",
    ),
    "Healthcare": (
        "clinical operations efficiency",
        "regulatory complexity",
        "staff burnout",
    ),
    "Manufacturing": (
        "supply chain visibility",
        "operational downtime",
        "ERP fragmentation",
    ),
}
_DEFAULT_PAIN = (
    "operational complexity",
    "scaling inefficiencies",
    "manual process overhead",
)

_SIMILAR_COMPANY = {
    "Financial Services": "financial services",
    "Technology": "high-growth SaaS",
    "Healthcare": "healthcare",
    "Manufacturing": "manufacturing",
}


class OutreachSequenceWorker(WorkerBase):
    """
    Generates personalized 5-touch outreach sequences for top ICP-qualified
    prospect accounts and surfaces them as structured artifacts in findings.
    """

    WORKER_NAME = "OutreachSequenceWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            prospects = self._get_top_prospects(tenant_id)

            if not prospects:
                result.findings.append(Finding(
                    title="No prospect accounts found — outreach sequences require Prospect accounts",
                    detail=(
                        "Add Prospect accounts with industry and revenue data to the CRM "
                        "to enable automated outreach sequence generation."
                    ),
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats = {
                    "prospects_found": 0,
                    "sequences_generated": 0,
                    "total_addressable_contacts_proxy": 0,
                }
                return result

            top_prospects = prospects[:cfg.get("top_prospects_n")]
            sequences_generated = 0
            account_names_with_sequences = []

            for account in top_prospects:
                sequence = self._generate_sequence(account)
                industry = account.get("industry") or ""
                is_icp = industry in ICP_INDUSTRIES
                severity = Severity.HIGH if is_icp else Severity.MEDIUM
                account_name = account.get("name") or "Unknown"
                annual_revenue = account.get("annual_revenue") or 0
                employee_count = account.get("employee_count") or 0

                result.findings.append(Finding(
                    title=f"Outreach sequence generated — {account_name} ({industry or 'Unknown industry'})",
                    detail=(
                        f"{account_name} is a {industry or 'Unknown industry'} prospect with "
                        f"${annual_revenue:,.0f} in annual revenue and approximately "
                        f"{employee_count:,} employees. "
                        f"A {cfg.get('sequence_touches')}-touch sequence spanning 21 days has been generated "
                        f"with messaging anchored to their industry pain points."
                    ),
                    severity=severity,
                    data={
                        "account_name": account_name,
                        "industry": industry,
                        "employee_count": employee_count,
                        "annual_revenue": annual_revenue,
                        "sequence": sequence,
                    },
                    recommended_action=(
                        f"Load this sequence into your outreach tool for {account_name}. "
                        f"Assign to an AE or SDR and launch within 48 hours. "
                        f"Personalize touch 3 with a real reference customer from the "
                        f"{industry or 'relevant'} space before sending."
                    ),
                ))
                sequences_generated += 1
                account_names_with_sequences.append(account_name)

            # Summary finding
            result.findings.append(Finding(
                title=f"Outreach sequences generated for {sequences_generated} prospects",
                detail=(
                    f"{cfg.get('sequence_touches')}-touch, 21-day sequences created for: "
                    f"{', '.join(account_names_with_sequences)}. "
                    f"Sequences use industry-specific pain points and are ready for "
                    f"loading into an outreach tool. Sprint 12 will enable AI-generated "
                    f"sequences via Claude for fully personalized messaging at scale."
                ),
                severity=Severity.INFO,
                data={
                    "accounts": account_names_with_sequences,
                    "touches_per_sequence": cfg.get("sequence_touches"),
                    "sequence_duration_days": 21,
                },
                recommended_action=(
                    "Review each sequence and substitute the placeholder reference company "
                    "with a real named customer before deploying."
                ),
            ))

            total_addressable_contacts_proxy = sum(
                max(1, (a.get("employee_count") or 0) // 50)
                for a in top_prospects
            )

            result.summary_stats = {
                "prospects_found": len(prospects),
                "sequences_generated": sequences_generated,
                "total_addressable_contacts_proxy": total_addressable_contacts_proxy,
            }

        except Exception as exc:
            logger.exception(f"OutreachSequenceWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Sequence generation ────────────────────────────────────────────────

    def _generate_sequence(self, account: dict) -> list[dict]:
        """
        Build a 5-touch sequence for the given account dict.
        Pure Python — no DB calls. Personalizes using name, industry, and size.
        """
        account_name = account.get("name") or "your company"
        industry = account.get("industry") or ""
        employee_count = account.get("employee_count") or 0
        annual_revenue = account.get("annual_revenue") or 0

        pain_points = _INDUSTRY_PAIN.get(industry, _DEFAULT_PAIN)
        primary_pain = pain_points[0]
        secondary_pain = pain_points[1] if len(pain_points) > 1 else pain_points[0]
        similar_type = _SIMILAR_COMPANY.get(industry, "enterprise")

        size_descriptor = (
            "large enterprise" if employee_count > 1000
            else "mid-market" if employee_count > 200
            else "growing"
        )
        revenue_context = (
            f"${annual_revenue / 1_000_000:.1f}M-revenue" if annual_revenue >= 1_000_000
            else f"${annual_revenue:,.0f}-revenue" if annual_revenue > 0
            else ""
        )
        company_descriptor = f"{revenue_context} {size_descriptor}".strip()

        touches = [
            {
                "touch_number": 1,
                "channel": "Email",
                "day": 1,
                "subject": f"Quick question for {account_name}",
                "message_snippet": (
                    f"Hi [First Name], I've been following {account_name}'s growth in the "
                    f"{industry or 'industry'} space and had a quick question about how you're "
                    f"currently handling {primary_pain}. "
                    f"For {company_descriptor} companies like yours, this tends to be a "
                    f"significant lever — would you have 15 minutes this week to compare notes? "
                    f"Happy to share what similar teams are doing differently."
                ),
            },
            {
                "touch_number": 2,
                "channel": "LinkedIn",
                "day": 3,
                "subject": "LinkedIn connection request",
                "message_snippet": (
                    f"Hi [First Name] — I work with {industry or 'enterprise'} leaders on "
                    f"{primary_pain} and {secondary_pain}. "
                    f"I'd love to connect and share some benchmarks I've put together for "
                    f"{similar_type} teams at {account_name}'s scale. "
                    f"No pitch, just useful context."
                ),
            },
            {
                "touch_number": 3,
                "channel": "Email",
                "day": 7,
                "subject": (
                    f"How {similar_type} companies solve {primary_pain}"
                ),
                "message_snippet": (
                    f"Hi [First Name], following up on my earlier note. "
                    f"I recently worked with a {similar_type} company similar to {account_name} "
                    f"that cut their {primary_pain} by 35% in one quarter — "
                    f"the change was surprisingly straightforward. "
                    f"Would it be worth a 15-minute call to walk through the approach? "
                    f"I think there's a direct parallel to what you're doing."
                ),
            },
            {
                "touch_number": 4,
                "channel": "Phone",
                "day": 14,
                "subject": "Phone follow-up",
                "message_snippet": (
                    f"Hi [First Name], this is [Rep Name] — I've sent a couple of emails about "
                    f"{primary_pain} at {account_name}. "
                    f"I wanted to follow up personally because I have one insight specific to the "
                    f"{industry or 'enterprise'} space that I haven't seen many teams take "
                    f"advantage of yet. "
                    f"I'll keep it to 5 minutes — would now or tomorrow work?"
                ),
            },
            {
                "touch_number": 5,
                "channel": "Email",
                "day": 21,
                "subject": "Closing the loop",
                "message_snippet": (
                    f"Hi [First Name], I don't want to keep cluttering your inbox — "
                    f"I'll take your silence as a sign the timing isn't right for {account_name}. "
                    f"I'll close out my notes on my end. "
                    f"If {primary_pain} or {secondary_pain} becomes a priority in a future "
                    f"quarter, I'm happy to reconnect — just reply here and I'll pick up the thread."
                ),
            },
        ]

        return touches

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_top_prospects(self, tenant_id: str) -> list[dict]:
        """
        Return Prospect accounts ordered by annual_revenue DESC.
        Fields: name, industry, annual_revenue, employee_count, account_type.
        """
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Prospect'})
        RETURN
            a.name AS name,
            a.industry AS industry,
            a.annual_revenue AS annual_revenue,
            a.employee_count AS employee_count,
            a.account_type AS account_type
        ORDER BY a.annual_revenue DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
