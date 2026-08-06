"""
scout/workers/expansion_revenue.py — Expansion Revenue Worker (Layer 3)

Identifies upsell and cross-sell opportunities within the existing
customer base. Expansion revenue is the highest-ROI growth lever in
B2B SaaS — existing customers are 3-5x cheaper to expand than
acquiring new logos, and NRR above 100% is what PE firms underwrite.

Layer 3 upgrade (Schema Intelligence):
  - Business model awareness: for subscription companies, absence of
    renewal pipeline is a critical finding (not medium); for transactional
    models, it's expected behavior and should not fire
  - Expansion opportunity sizing is explicit: each finding states the
    specific ARR expansion target (5% of account revenue = conservative,
    10% = aggressive) so the CSM knows what "success" looks like
  - Fragmented buying analysis cross-references deal composition —
    multiple small deals in the same department = consolidation opportunity,
    multiple deals across different departments = platform expansion signal
  - Each finding names the specific accounts, their ARR, and the
    rep/CSM responsible — not just a count

What this worker finds:
  1. Customers with won deals but no expansion pipeline
     (prime upsell targets — they trust you, just haven't been asked)
  2. Fragmented buyers — multiple separate won deals in the same account
     (opportunity to consolidate into a platform/enterprise agreement)
  3. High-value customers in under-penetrated segments
     (reference accounts for adjacent market expansion)
  4. Stagnant prospects — long-standing pipeline with no conversion
     (decide: re-engage with a different approach, or clean the pipe)
"""

import logging
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# ── Hardcoded defaults ─────────────────────────────────────────────────────
MIN_EXPANSION_VALUE   = 50_000
HIGH_REVENUE_CUSTOMER = 100_000
FRAGMENTED_DEAL_COUNT = 2

# Conservative expansion target: 5% of account ARR
EXPANSION_TARGET_PCT  = 0.05


class ExpansionRevenueWorker(WorkerBase):
    """
    Surfaces expansion and upsell opportunities with business-model-aware logic
    and specific account-level sizing.
    """

    WORKER_NAME = "ExpansionRevenueWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        t_min_expansion = cfg.get("min_expansion_value", MIN_EXPANSION_VALUE)
        t_high_revenue  = cfg.get("high_revenue_customer", HIGH_REVENUE_CUSTOMER)

        try:
            customers           = self._get_customers_with_won_deals(tenant_id)
            expansion_candidates = self._get_expansion_candidates(tenant_id)
            fragmented          = self._get_fragmented_buyers(tenant_id)
            pipeline_by_acct    = self._get_open_pipeline_by_account(tenant_id)

            # Build pipeline lookup
            pipeline_lookup = {
                r["account_name"]: r["open_pipeline"] or 0
                for r in pipeline_by_acct if r.get("account_name")
            }

            total_won_arr = sum(c.get("total_won") or 0 for c in customers)
            total_expansion_opportunity = sum(
                (e.get("total_won") or 0) * EXPANSION_TARGET_PCT
                for e in expansion_candidates
            )

            result.summary_stats = {
                "total_customers_with_won_deals": len(customers),
                "total_won_arr":                  round(total_won_arr),
                "expansion_candidates":           len(expansion_candidates),
                "fragmented_accounts":            len(fragmented),
                "expansion_opportunity_5pct":     round(total_expansion_opportunity),
                "business_model":                 ctx.company_profile.business_model if ctx.company_profile else "unknown",
                "thresholds_calibrated":          ctx.has_calibrated_history,
            }

            if not customers:
                result.findings.append(Finding(
                    title="No closed-won opportunities found — expansion analysis requires win history",
                    detail="Run a CRM scan after some deals have been closed won.",
                    severity=Severity.INFO,
                ))
                return result

            # ── Finding 1: No expansion pipeline ─────────────────────────
            if expansion_candidates:
                # Severity depends on business model
                # Subscription: CRITICAL — these accounts are churning silently
                # Transactional: HIGH — missed upsell, but expected that not all have open deals
                # Unknown: HIGH — default
                if ctx.is_subscription():
                    sev = Severity.HIGH
                    model_note = (
                        "For a subscription business, customers with no active pipeline "
                        "are renewal risks — they have no reason to re-engage with your team. "
                        "NRR above 100% requires active expansion pipeline in every account."
                    )
                else:
                    sev = Severity.MEDIUM
                    model_note = (
                        "Customers with existing won deals are your highest-probability "
                        "upsell targets. A 10% expansion on existing ARR is 5x cheaper "
                        "than acquiring a new logo."
                    )

                detail = self._build_expansion_detail(
                    expansion_candidates, pipeline_lookup, model_note
                )
                action = self._build_expansion_action(expansion_candidates, ctx)

                result.findings.append(Finding(
                    title=f"{len(expansion_candidates)} customer{'s' if len(expansion_candidates) > 1 else ''} "
                          f"with no open expansion pipeline "
                          f"(${total_expansion_opportunity:,.0f} in untapped opportunity at 5% target)",
                    detail=detail,
                    severity=sev,
                    data={
                        "count":                     len(expansion_candidates),
                        "expansion_opportunity_5pct": round(total_expansion_opportunity),
                        "business_model":             ctx.company_profile.business_model if ctx.company_profile else "unknown",
                        "accounts": [
                            {
                                "name":      e.get("account_name"),
                                "industry":  e.get("industry"),
                                "total_won": e.get("total_won"),
                                "won_deals": e.get("won_deals"),
                                "expansion_target_5pct": round((e.get("total_won") or 0) * EXPANSION_TARGET_PCT),
                            }
                            for e in expansion_candidates
                        ],
                    },
                    recommended_action=action,
                    confidence="high",
                    specific_entities=[
                        {
                            "type":        "account",
                            "name":        e.get("account_name"),
                            "total_won":   e.get("total_won"),
                            "expansion_target": round((e.get("total_won") or 0) * EXPANSION_TARGET_PCT),
                            "won_deals":   e.get("won_deals"),
                        }
                        for e in expansion_candidates
                    ],
                ))

            # ── Finding 2: Fragmented buyers — consolidation opportunity ──
            if fragmented:
                frag_total = sum(f.get("total_won") or 0 for f in fragmented)
                # Consolidation opportunity: if they've bought twice, they'll buy a platform deal
                consolidation_value = frag_total * 0.15  # typical 15% premium for enterprise bundle

                detail_lines = [
                    f"These accounts have {FRAGMENTED_DEAL_COUNT}+ separate won deals, "
                    f"suggesting department-by-department buying (not enterprise agreements):"
                ]
                for f in fragmented[:4]:
                    name = f.get("account_name", "Unknown")
                    deals = f.get("won_deals", 0)
                    value = f.get("total_won") or 0
                    detail_lines.append(
                        f"  • {name}: {deals} won deals, ${value:,.0f} total — "
                        f"consolidation target: ${value * 1.15:,.0f}"
                    )
                if len(fragmented) > 4:
                    detail_lines.append(f"  • …and {len(fragmented) - 4} more")

                result.findings.append(Finding(
                    title=f"{len(fragmented)} account{'s' if len(fragmented) > 1 else ''} "
                          f"with fragmented buying — ${consolidation_value:,.0f} consolidation opportunity",
                    detail="\n".join(detail_lines),
                    severity=Severity.MEDIUM,
                    data={
                        "count":                len(fragmented),
                        "total_fragmented_value": frag_total,
                        "consolidation_value_15pct": round(consolidation_value),
                        "accounts": [
                            {
                                "name":        f.get("account_name"),
                                "deal_count":  f.get("won_deals"),
                                "total_value": f.get("total_won"),
                            }
                            for f in fragmented
                        ],
                    },
                    recommended_action=(
                        "Present an enterprise consolidation proposal to the top accounts "
                        "by total value. Frame it as: bundle all existing modules into one "
                        "agreement at a 10-15% total premium — they pay slightly more, "
                        "you get longer contract term, bigger logo, and simpler renewal. "
                        "This is one of the highest-ROI plays in SaaS sales motion."
                    ),
                    specific_entities=[
                        {
                            "type":       "account",
                            "name":       f.get("account_name"),
                            "won_deals":  f.get("won_deals"),
                            "total_value": f.get("total_won"),
                        }
                        for f in fragmented
                    ],
                ))

            # ── Finding 3: Industry penetration — reference account leverage ──
            if customers:
                industry_counts: dict[str, list] = {}
                for c in customers:
                    ind = c.get("industry") or "Unknown"
                    industry_counts.setdefault(ind, []).append(c)

                if len(industry_counts) >= 2:
                    by_count = sorted(industry_counts.items(), key=lambda x: len(x[1]), reverse=True)
                    dominant_ind, dominant_accts = by_count[0]
                    thin_inds = [(ind, accts) for ind, accts in by_count[1:] if len(accts) == 1]

                    if len(dominant_accts) >= 3 and thin_inds:
                        dominant_arr = sum(a.get("total_won") or 0 for a in dominant_accts)
                        result.findings.append(Finding(
                            title=f"Strong {dominant_ind} vertical "
                                  f"({len(dominant_accts)} customers, ${dominant_arr:,.0f} ARR) "
                                  f"— use as reference for adjacent expansion",
                            detail=(
                                f"You have {len(dominant_accts)} customers in {dominant_ind} "
                                f"vs. only 1 customer each in "
                                f"{', '.join(ind for ind, _ in thin_inds[:3])}. "
                                f"A dominant vertical is both a sales asset (case studies, referrals) "
                                f"and a concentration risk if that sector hits headwinds."
                            ),
                            severity=Severity.INFO,
                            data={
                                "dominant_industry":    dominant_ind,
                                "dominant_count":       len(dominant_accts),
                                "dominant_arr":         round(dominant_arr),
                                "industry_distribution": {
                                    ind: len(accts) for ind, accts in industry_counts.items()
                                },
                            },
                            recommended_action=(
                                f"Use {dominant_ind} case studies and referrals to accelerate "
                                f"deals in adjacent verticals "
                                f"({', '.join(ind for ind, _ in thin_inds[:2])}). "
                                f"Target accounts with similar profiles to your best "
                                f"{dominant_ind} customers — they have the highest conversion probability."
                            ),
                        ))

        except Exception as exc:
            logger.exception("ExpansionRevenueWorker failed: %s", exc)
            result.error = str(exc)

        return result

    # ── Detail builders ────────────────────────────────────────────────────

    def _build_expansion_detail(
        self,
        candidates: list[dict],
        pipeline_lookup: dict,
        model_note: str,
    ) -> str:
        """Build specific per-account expansion detail."""
        lines = [model_note, ""]
        for e in candidates[:5]:
            name    = e.get("account_name", "Unknown")
            won     = e.get("total_won") or 0
            deals   = e.get("won_deals", 0)
            target  = round(won * EXPANSION_TARGET_PCT)
            pipeline = pipeline_lookup.get(name, 0)

            lines.append(
                f"• {name}: ${won:,.0f} in {deals} won deal(s) — "
                f"expansion target ${target:,.0f} (5%). "
                f"{'No open pipeline.' if pipeline == 0 else f'${pipeline:,.0f} open pipeline (partial).'}"
            )
        if len(candidates) > 5:
            lines.append(f"• …and {len(candidates) - 5} more accounts")
        return "\n".join(lines)

    def _build_expansion_action(
        self,
        candidates: list[dict],
        ctx: "WorkerContext",
    ) -> str:
        """Build an action with specific account names and targets."""
        top = candidates[:3]
        names_with_targets = ", ".join(
            f"{e.get('account_name', '?')} (target: ${round((e.get('total_won') or 0) * EXPANSION_TARGET_PCT):,.0f})"
            for e in top
        )
        subscription_note = (
            " For a subscription model, this is also a renewal risk — "
            "accounts without active pipeline have no reason to re-engage."
        ) if ctx.is_subscription() else ""

        return (
            f"Create expansion opportunities in CRM for: {names_with_targets}. "
            f"Each needs a next step (EBR, upsell call, or usage review) set within 2 weeks."
            f"{subscription_note}"
        )

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_customers_with_won_deals(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WITH a, count(o) AS won_deals, sum(o.amount) AS total_won
        RETURN
            a.name AS account_name,
            a.industry AS industry,
            a.annual_revenue AS annual_revenue,
            won_deals,
            total_won
        ORDER BY total_won DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_expansion_candidates(self, tenant_id: str) -> list[dict]:
        """Customers with won deals but NO open pipeline of any kind."""
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WHERE NOT EXISTS {
            MATCH (open_o:Opportunity {tenant_id: $tenant_id, is_closed: false})-[:IN_ACCOUNT]->(a)
        }
        WITH a, count(o) AS won_deals, sum(o.amount) AS total_won
        RETURN
            a.name AS account_name,
            a.industry AS industry,
            won_deals,
            total_won
        ORDER BY total_won DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_fragmented_buyers(self, tenant_id: str) -> list[dict]:
        """Accounts with 2+ separate won deals — consolidation opportunity."""
        query = """
        MATCH (a:Account {tenant_id: $tenant_id})
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WITH a, count(o) AS won_deals, sum(o.amount) AS total_won
        WHERE won_deals >= $min_deals
        RETURN
            a.name AS account_name,
            a.industry AS industry,
            won_deals,
            total_won
        ORDER BY won_deals DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(
                query, tenant_id=tenant_id, min_deals=FRAGMENTED_DEAL_COUNT
            )]

    def _get_open_pipeline_by_account(self, tenant_id: str) -> list[dict]:
        """Open pipeline value per account — for the 'partial pipeline' note."""
        query = """
        MATCH (a:Account {tenant_id: $tenant_id})
        OPTIONAL MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})-[:IN_ACCOUNT]->(a)
        WITH a.name AS account_name, coalesce(sum(o.amount), 0) AS open_pipeline
        WHERE open_pipeline > 0
        RETURN account_name, open_pipeline
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
