"""
scout/workers/cross_sell_campaign.py — Cross-Sell Campaign Worker

Generates targeted expansion campaign briefs for the highest-scoring
cross-sell accounts (building on CrossSellIntelligenceWorker's scoring).
Produces campaign blueprints: objective, audience, messaging angles, channel
mix, timing recommendations, and success metrics. These briefs are ready for
an AE or CSM to execute or hand off to a campaign manager. Sprint 12 will
auto-launch these campaigns via Outreach/Salesloft when the connector is live.
"""

import logging

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

CAMPAIGN_DURATION_DAYS = 30

_INDUSTRY_ANGLES = {
    "Financial Services": (
        "Compliance-driven ROI: show how peers reduced audit prep time by 40% post-expansion"
    ),
    "Technology": (
        "Engineering velocity angle: expanded customers ship 30% faster with the full platform"
    ),
    "Healthcare": (
        "Regulatory simplification: expanded healthcare customers cut compliance workload in half"
    ),
    "Manufacturing": (
        "Supply chain visibility: expanded manufacturing customers reduced downtime by 25%"
    ),
}
_DEFAULT_INDUSTRY_ANGLE = (
    "Proven operational ROI: expanded customers report 30%+ efficiency gains within 90 days"
)


class CrossSellCampaignWorker(WorkerBase):
    """
    Generates ready-to-execute expansion campaign briefs for the highest-value
    customer accounts, including objectives, messaging angles, channel mix,
    timing, and success metrics.
    """

    WORKER_NAME = "CrossSellCampaignWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            customers = self._get_customers_with_deal_history(tenant_id)

            if not customers:
                result.findings.append(Finding(
                    title="No customer accounts with won deal history — campaign briefs require closed-won data",
                    detail=(
                        "Ensure closed-won opportunities are linked to Customer accounts in the CRM "
                        "to enable expansion campaign brief generation."
                    ),
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats = {
                    "eligible_accounts": 0,
                    "campaigns_generated": 0,
                    "total_expansion_opportunity": 0,
                    "avg_expansion_target": 0,
                }
                return result

            # Score accounts using simplified expansion readiness
            scored = []
            for customer in customers:
                score = self._compute_simple_score(customer)
                if score >= cfg.get("priority_score_threshold"):
                    expansion_target = self._compute_expansion_target(customer, cfg)
                    scored.append({
                        **customer,
                        "expansion_score": score,
                        "expansion_target": expansion_target,
                    })

            scored.sort(key=lambda a: a["expansion_score"], reverse=True)
            eligible = scored
            top_accounts = scored[:cfg.get("max_campaigns")]

            total_expansion_opportunity = sum(a["expansion_target"] for a in top_accounts)
            campaigns_generated = 0
            multi_product_accounts = []

            # ── Finding 1: Summary ─────────────────────────────────────────
            if top_accounts:
                result.findings.append(Finding(
                    title=(
                        f"Expansion campaigns ready for {len(top_accounts)} account"
                        f"{'s' if len(top_accounts) > 1 else ''} — "
                        f"${total_expansion_opportunity:,.0f} in play"
                    ),
                    detail=(
                        f"{len(eligible)} customer account(s) scored above the "
                        f"{cfg.get('priority_score_threshold')}-point expansion threshold. "
                        f"Campaign briefs have been generated for the top {len(top_accounts)} "
                        f"by expansion readiness score. "
                        f"Total expansion opportunity across these accounts: "
                        f"${total_expansion_opportunity:,.0f}."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "eligible_accounts": len(eligible),
                        "campaigns_generated": len(top_accounts),
                        "total_expansion_opportunity": total_expansion_opportunity,
                        "accounts": [
                            {
                                "name": a.get("account_name"),
                                "score": a["expansion_score"],
                                "expansion_target": a["expansion_target"],
                            }
                            for a in top_accounts
                        ],
                    },
                    recommended_action=(
                        "Assign the top account to an AE or CSM today. "
                        "Review each campaign brief and launch within 7 days."
                    ),
                ))

            # ── Finding 2: Individual campaign briefs ──────────────────────
            for account in top_accounts:
                brief = self._generate_campaign_brief(account)
                account_name = account.get("account_name") or "Unknown Account"
                won_deals = account.get("won_deal_count") or 0
                expansion_target = account["expansion_target"]

                if won_deals >= 2:
                    multi_product_accounts.append(account)

                result.findings.append(Finding(
                    title=f"Expansion campaign brief — {account_name} (Score: {account['expansion_score']}/100)",
                    detail=(
                        f"Campaign objective: {brief.get('objective')}. "
                        f"Audience: {brief.get('audience')}. "
                        f"{CAMPAIGN_DURATION_DAYS}-day campaign with {len(brief.get('channel_mix', []))} "
                        f"channel touch points. "
                        f"Success target: ${expansion_target:,.0f} expansion pipeline within 30 days."
                    ),
                    severity=Severity.HIGH,
                    data=brief,
                    recommended_action=(
                        f"Review the messaging angles for {account_name} and assign an AE or CSM "
                        f"to execute. Personalize touch 1 with a specific outcome from their "
                        f"initial purchase before launching."
                    ),
                ))
                campaigns_generated += 1

            # ── Finding 3: Multi-product account callout ───────────────────
            if multi_product_accounts:
                mp_names = [a.get("account_name") or "Unknown" for a in multi_product_accounts]
                result.findings.append(Finding(
                    title=(
                        f"{len(multi_product_accounts)} multi-product buyer"
                        f"{'s' if len(multi_product_accounts) > 1 else ''} in campaign list — "
                        f"lead with product expansion roadmap"
                    ),
                    detail=(
                        f"{', '.join(mp_names)} have 2 or more closed-won deals. "
                        f"Multi-product buyers have an established expansion pattern — "
                        f"they have already demonstrated willingness to grow the relationship. "
                        f"These accounts should receive the product expansion roadmap angle "
                        f"in their campaign messaging rather than a standard ROI pitch."
                    ),
                    severity=Severity.INFO,
                    data={
                        "multi_product_accounts": [
                            {
                                "name": a.get("account_name"),
                                "won_deal_count": a.get("won_deal_count"),
                                "total_won_value": a.get("total_won_value"),
                            }
                            for a in multi_product_accounts
                        ],
                    },
                    recommended_action=(
                        "For multi-product buyers, open with: 'Based on how you're using "
                        "[Product A], here's what teams like yours are adding next.' "
                        "Reference their specific use case before proposing expansion."
                    ),
                ))

            avg_expansion_target = (
                round(total_expansion_opportunity / len(top_accounts))
                if top_accounts else 0
            )

            result.summary_stats = {
                "eligible_accounts": len(eligible),
                "campaigns_generated": campaigns_generated,
                "total_expansion_opportunity": round(total_expansion_opportunity),
                "avg_expansion_target": avg_expansion_target,
            }

        except Exception as exc:
            logger.exception(f"CrossSellCampaignWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Scoring ────────────────────────────────────────────────────────────

    def _compute_simple_score(self, customer: dict) -> int:
        """
        Simplified expansion readiness score: penetration depth + deal history.
        0-55 pts. Thresholds intentionally below CrossSellIntelligenceWorker's
        full 0-100 scale so that campaign briefs target a focused subset.
        """
        score = 0

        # Penetration depth (0-30 pts)
        total_won = customer.get("total_won_value") or 0
        annual_rev = customer.get("annual_revenue") or 0
        if annual_rev > 0:
            penetration = total_won / annual_rev
            if penetration < 0.025:
                score += 30  # very low penetration = large whitespace
            elif penetration < 0.05:
                score += 20
            else:
                score += 10
        else:
            score += 15  # unknown revenue = neutral

        # Deal history (0-25 pts)
        deal_count = customer.get("won_deal_count") or 0
        if deal_count >= 2:
            score += 25
        elif deal_count == 1:
            score += 10

        return min(score, 55)

    def _compute_expansion_target(self, customer: dict, cfg) -> float:
        """
        Compute the expansion ARR target for the campaign brief.
        Primary: 5% of annual revenue.
        Fallback: 30% of total won value.
        """
        annual_revenue = customer.get("annual_revenue") or 0
        total_won = customer.get("total_won_value") or 0
        if annual_revenue:
            return annual_revenue * cfg.get("expansion_arr_target_pct")
        return total_won * 0.3

    # ── Campaign brief generation ──────────────────────────────────────────

    def _generate_campaign_brief(self, account: dict) -> dict:
        """
        Build a structured expansion campaign brief for a single account.
        Pure Python — no DB calls.
        """
        account_name = account.get("account_name") or "the account"
        industry = account.get("industry") or ""
        annual_revenue = account.get("annual_revenue") or 0
        total_won = account.get("total_won_value") or 0
        won_deals = account.get("won_deal_count") or 0
        expansion_target = account["expansion_target"]

        objective = (
            f"Expand {account_name} from ${total_won:,.0f} to "
            f"${total_won + expansion_target:,.0f} ARR"
        )

        audience = (
            f"Decision maker and economic buyer at {account_name}"
            f"{' (' + industry + ')' if industry else ''}"
        )

        messaging_angles = [
            "Proven ROI: reference their specific outcomes from the initial purchase "
            "and anchor the expansion conversation in documented results.",
        ]
        if won_deals >= 2:
            messaging_angles.append(
                "Established buyer relationship — lead with the product expansion roadmap "
                "and position the next module as the natural next step, not a new sale."
            )
        industry_angle = _INDUSTRY_ANGLES.get(industry, _DEFAULT_INDUSTRY_ANGLE)
        messaging_angles.append(industry_angle)

        channel_mix = [
            "Executive email sequence (Touch 1-3)",
            "CSM-led expansion conversation (Touch 2)",
            "EBR (Executive Business Review) (Touch 4)",
        ]

        timing = (
            f"Launch within 7 days. {CAMPAIGN_DURATION_DAYS}-day campaign. "
            f"Decision checkpoint at Day 15."
        )

        success_metrics = [
            "Expansion opportunity created in CRM",
            f"${expansion_target:,.0f} in pipeline within {CAMPAIGN_DURATION_DAYS} days",
            f"Stage 2+ by Day {CAMPAIGN_DURATION_DAYS}",
        ]

        return {
            "account_name": account_name,
            "industry": industry,
            "annual_revenue": annual_revenue,
            "total_won_value": total_won,
            "won_deal_count": won_deals,
            "expansion_target": expansion_target,
            "expansion_score": account.get("expansion_score"),
            "objective": objective,
            "audience": audience,
            "messaging_angles": messaging_angles,
            "channel_mix": channel_mix,
            "timing": timing,
            "success_metrics": success_metrics,
        }

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_customers_with_deal_history(self, tenant_id: str) -> list[dict]:
        """
        Return Customer accounts with at least one closed-won opportunity,
        including aggregated deal stats and account firmographics.
        """
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        OPTIONAL MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WITH
            a,
            count(o) AS won_deal_count,
            coalesce(sum(o.amount), 0) AS total_won_value
        WHERE won_deal_count > 0
        RETURN
            a.canonical_id AS account_id,
            a.name AS account_name,
            a.industry AS industry,
            a.annual_revenue AS annual_revenue,
            a.employee_count AS employee_count,
            won_deal_count,
            total_won_value
        ORDER BY total_won_value DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
