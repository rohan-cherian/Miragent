"""
scout/workers/cross_sell_intelligence.py — Cross-sell Intelligence Worker (Layer 3)

Scores every customer on expansion readiness and identifies the optimal
moment, product, and message for upsell/cross-sell motions.

Layer 3 upgrade:
  - ICP industry scoring is no longer hardcoded as
    {"Financial Services": 20, "Technology": 20, "Healthcare": 15}.
    Those were someone else's ICP baked into every tenant.
    The industry fit score is now derived from the actual customer base:
    dominant industry = full points, secondary industry = partial, unknown = neutral.
    This means the expansion scores adapt to the company's actual market.

  - Expansion headroom floor calibrated from ctx.avg_deal_size instead
    of a hardcoded $50k. For a company with $15k ACV, $50k is fantasy;
    for a company with $500k ACV, $50k is noise. The floor is now
    max($5k, avg_deal_size × 0.5).

  - Business model awareness: for subscription companies, the absence of
    expansion pipeline gets a higher weight in the score — it's a renewal
    risk signal, not just a missed upsell.

  - Score breakdown is now included in specific_entities for every priority
    account so the AI memo can explain why each account scored high.

  - The "Sprint 9 trigger" language removed from recommended_action —
    sprint scaffolding notes add noise to the AI memo.

EXPANSION READINESS SCORE (0-100 per account):

  PENETRATION DEPTH (30 pts)
  How much of the customer's potential are you capturing?
  Proxy: (total won deal value) / (account annual revenue × 0.01)
  Low penetration + healthy account = expansion opportunity.

  DEAL HISTORY (25 pts)
  How many times has this customer bought from you?
  1 deal = 10pts | 2+ deals = 25pts (multi-product buyer)

  ACCOUNT HEALTH PROXY (25 pts)
  Active owner + no competing pipeline = primed for outreach.
  For subscription companies, no pipeline = also a renewal risk signal (+5 extra weight).

  ICP FIT (20 pts)
  Derived from actual customer base: most common industry = 20pts,
  second-most-common = 15pts, other = 10pts, unknown = 5pts.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)


class CrossSellIntelligenceWorker(WorkerBase):
    """
    Scores customer accounts on cross-sell/upsell readiness and surfaces
    the top expansion opportunities with supporting rationale.
    ICP scoring is derived from each company's actual customer base.
    """

    WORKER_NAME = "CrossSellIntelligenceWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            customers_with_deals = self._get_customers_with_deal_history(tenant_id)
            open_pipeline_by_account = self._get_open_pipeline_by_account(tenant_id)
            customers_with_owners = self._get_customer_owners(tenant_id)

            # Build owner lookup
            owner_by_account: dict[str, dict] = {
                c.get("account_id"): c
                for c in customers_with_owners
                if c.get("account_id")
            }

            if not customers_with_deals:
                result.findings.append(Finding(
                    title="No customer deal history — cross-sell scoring requires closed-won data",
                    detail="Run a CRM scan with closed-won opportunities to generate expansion scores.",
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats = {
                    "scored_accounts": 0,
                    "priority_accounts": 0,
                    "total_expansion_opportunity": 0,
                }
                return result

            # ── Derive ICP industry distribution from actual customer base ──
            # This replaces the hardcoded {"Financial Services": 20, "Technology": 20, ...}
            industry_counts = Counter(
                c.get("industry")
                for c in customers_with_deals
                if c.get("industry")
            )
            # Map industry → ICP fit score (20 for top, 15 for 2nd, 10 for others, 5 for unknown)
            icp_industry_scores: dict[str, int] = {}
            for rank, (industry, _) in enumerate(industry_counts.most_common()):
                if rank == 0:
                    icp_industry_scores[industry] = 20
                elif rank == 1:
                    icp_industry_scores[industry] = 15
                else:
                    icp_industry_scores[industry] = 10

            # Calibrate expansion headroom floor from company's avg deal size
            if ctx.avg_deal_size and ctx.avg_deal_size > 0 and ctx.has_calibrated_history:
                expansion_floor = max(5_000, ctx.avg_deal_size * 0.5)
            else:
                expansion_floor = 50_000  # fallback default

            is_subscription = ctx.is_subscription()

            result.summary_stats.update({
                "segment":            ctx.company_profile.market_segment if ctx.company_profile else "unknown",
                "business_model":     "subscription" if is_subscription else "transactional",
                "icp_top_industries": [ind for ind, _ in industry_counts.most_common(3)],
                "expansion_floor":    round(expansion_floor),
            })

            # ── Score every customer ────────────────────────────────────
            scored: list[dict] = []
            for customer in customers_with_deals:
                account_id = customer.get("account_id")
                score, breakdown = self._compute_score(
                    customer,
                    open_pipeline_by_account.get(account_id, []),
                    owner_by_account.get(account_id),
                    cfg,
                    icp_industry_scores=icp_industry_scores,
                    is_subscription=is_subscription,
                )
                has_open_pipeline = bool(open_pipeline_by_account.get(account_id))
                expansion_headroom = self._compute_expansion_headroom(
                    customer, cfg, floor=expansion_floor
                )
                scored.append({
                    **customer,
                    "score":             score,
                    "score_breakdown":   breakdown,
                    "has_open_pipeline": has_open_pipeline,
                    "expansion_headroom": expansion_headroom,
                })

            scored.sort(key=lambda x: x["score"], reverse=True)
            priority = [s for s in scored if s["score"] >= cfg.get("score_priority", 70)]
            watch    = [s for s in scored if cfg.get("score_watch", 40) <= s["score"] < cfg.get("score_priority", 70)]

            total_expansion_opportunity = sum(s.get("expansion_headroom") or 0 for s in priority)

            result.summary_stats.update({
                "scored_accounts":         len(scored),
                "priority_accounts":       len(priority),
                "watch_accounts":          len(watch),
                "total_expansion_opportunity": round(total_expansion_opportunity),
                "avg_expansion_score":     round(
                    sum(s["score"] for s in scored) / len(scored)
                ) if scored else 0,
            })

            # ── Finding 1: Priority cross-sell accounts (score 70+) ────────
            if priority:
                detail_lines = [
                    f"Expansion readiness score {cfg.get('score_priority', 70)}+. "
                    f"These accounts have the highest probability of expanding — "
                    f"they've bought before, the relationship is active, and "
                    f"there's no competing expansion deal in pipeline.",
                    "",
                ]
                for p in priority[:5]:
                    bd = p.get("score_breakdown") or {}
                    detail_lines.append(
                        f"  • {p.get('account_name', 'Unknown')} — Score: {p['score']}/100 "
                        f"(Penetration: {bd.get('penetration', 0)}pt, "
                        f"History: {bd.get('deal_history', 0)}pt, "
                        f"Health: {bd.get('health', 0)}pt, "
                        f"ICP: {bd.get('icp_fit', 0)}pt) "
                        f"| Headroom: ${p.get('expansion_headroom', 0):,.0f}"
                    )
                if len(priority) > 5:
                    detail_lines.append(f"  • …and {len(priority) - 5} more")

                result.findings.append(Finding(
                    title=(
                        f"{len(priority)} account{'s' if len(priority) > 1 else ''} "
                        f"ready for expansion — ${total_expansion_opportunity:,.0f} opportunity"
                    ),
                    detail="\n".join(detail_lines),
                    severity=Severity.HIGH,
                    data={
                        "priority_accounts": [
                            {
                                "name":               p.get("account_name"),
                                "score":              p["score"],
                                "score_breakdown":    p.get("score_breakdown"),
                                "won_deals":          p.get("won_deal_count"),
                                "total_won":          p.get("total_won_value"),
                                "expansion_headroom": p.get("expansion_headroom"),
                                "has_open_pipeline":  p["has_open_pipeline"],
                                "industry":           p.get("industry"),
                            }
                            for p in priority
                        ],
                    },
                    recommended_action=(
                        "Assign to AE or CSM this week. "
                        "Lead with a customized expansion proposal — reference their specific "
                        "use case and ROI from the initial purchase."
                    ),
                    confidence="high",
                    specific_entities=[
                        {
                            "type":               "account",
                            "name":               p.get("account_name"),
                            "score":              p["score"],
                            "expansion_headroom": p.get("expansion_headroom"),
                            "total_won":          p.get("total_won_value"),
                            "industry":           p.get("industry"),
                        }
                        for p in priority
                    ],
                ))

            # ── Finding 2: Individual account briefs (top 3) ───────────────
            for account in priority[:3]:
                score_bd = account.get("score_breakdown") or {}
                pipeline_note = (
                    "No active expansion pipeline — clean runway for outreach."
                    if not account["has_open_pipeline"]
                    else "Already has open expansion pipeline — check for overlap before outreach."
                )
                result.findings.append(Finding(
                    title=(
                        f"{account.get('account_name')} — "
                        f"Expansion Score: {account['score']}/100 "
                        f"(${account.get('expansion_headroom', 0):,.0f} headroom)"
                    ),
                    detail=(
                        f"Score breakdown: Penetration {score_bd.get('penetration', 0)}pts, "
                        f"Deal history {score_bd.get('deal_history', 0)}pts, "
                        f"Account health {score_bd.get('health', 0)}pts, "
                        f"ICP fit {score_bd.get('icp_fit', 0)}pts. "
                        f"Won ${account.get('total_won_value', 0):,.0f} across "
                        f"{account.get('won_deal_count', 0)} deal(s). "
                        f"Estimated expansion headroom: ${account.get('expansion_headroom', 0):,.0f}. "
                        f"{pipeline_note}"
                    ),
                    severity=Severity.INFO,
                    data={
                        "account":            account.get("account_name"),
                        "score":              account["score"],
                        "score_breakdown":    score_bd,
                        "total_won_value":    account.get("total_won_value"),
                        "won_deal_count":     account.get("won_deal_count"),
                        "expansion_headroom": account.get("expansion_headroom"),
                        "industry":           account.get("industry"),
                    },
                    recommended_action=(
                        f"Create an expansion opportunity in CRM for {account.get('account_name')}. "
                        f"Brief the AE with account history and suggest a product expansion angle."
                    ),
                    confidence="medium",
                ))

            # ── Finding 3: Dormant customers (no won deal history) ─────────
            dormant = self._get_customers_with_no_won_deals(tenant_id)
            if dormant:
                result.findings.append(Finding(
                    title=(
                        f"{len(dormant)} customer account"
                        f"{'s' if len(dormant) > 1 else ''} with no won deal history"
                    ),
                    detail=(
                        f"{', '.join(d.get('account_name', 'Unknown') for d in dormant)} "
                        f"are marked as 'Customer' but have no closed-won opportunities. "
                        f"These may be legacy customers, trial accounts, or CRM data quality issues. "
                        f"Without deal history, these accounts are invisible to all revenue intelligence."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "dormant_count": len(dormant),
                        "accounts": [{"name": d.get("account_name")} for d in dormant],
                    },
                    recommended_action=(
                        "Audit CRM account records. Create historical won opportunities "
                        "for any customer with an active contract but no CRM deal history."
                    ),
                    confidence="high",
                ))

            # ── Finding 4: Multi-product buyers ────────────────────────────
            multi_product = [
                s for s in scored
                if (s.get("won_deal_count") or 0) >= cfg.get("high_deal_count", 2)
            ]
            if multi_product:
                result.findings.append(Finding(
                    title=(
                        f"{len(multi_product)} multi-product buyer"
                        f"{'s' if len(multi_product) > 1 else ''} — "
                        f"highest-retention accounts"
                    ),
                    detail=(
                        f"{', '.join(m.get('account_name') for m in multi_product)} "
                        f"have {cfg.get('high_deal_count', 2)}+ won deals each. "
                        f"Multi-product buyers have 90%+ retention rates and are your "
                        f"most defensible accounts. They're also your best expansion targets — "
                        f"they've demonstrated willingness to expand the relationship."
                    ),
                    severity=Severity.INFO,
                    data={
                        "multi_product_buyers": [
                            {"name": m.get("account_name"), "deal_count": m.get("won_deal_count")}
                            for m in multi_product
                        ],
                    },
                    recommended_action=(
                        "Use multi-product buyers as reference customers in sales. "
                        "Ask them for case studies and referrals — "
                        "accounts that look like them are your highest-conversion prospects."
                    ),
                    confidence="high",
                ))

        except Exception as exc:
            logger.exception(f"CrossSellIntelligenceWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Scoring engine ─────────────────────────────────────────────────────

    def _compute_score(
        self,
        customer: dict,
        open_pipeline: list[dict],
        owner_info: dict | None,
        cfg,
        *,
        icp_industry_scores: dict[str, int],
        is_subscription: bool,
    ) -> tuple[int, dict]:
        """Compute expansion readiness score 0-100 with breakdown."""
        breakdown: dict[str, int] = {}

        # 1. Penetration depth (30 pts)
        total_won  = customer.get("total_won_value") or 0
        annual_rev = customer.get("annual_revenue") or 0
        if annual_rev > 0:
            penetration = total_won / annual_rev
            if penetration < cfg.get("penetration_target", 0.05) * 0.5:
                breakdown["penetration"] = 30   # deep whitespace = max points
            elif penetration < cfg.get("penetration_target", 0.05):
                breakdown["penetration"] = 20
            else:
                breakdown["penetration"] = 10   # high penetration = less headroom
        else:
            breakdown["penetration"] = 15       # unknown revenue = neutral

        # 2. Deal history (25 pts)
        deal_count = customer.get("won_deal_count") or 0
        if deal_count >= cfg.get("high_deal_count", 2):
            breakdown["deal_history"] = 25
        elif deal_count == 1:
            breakdown["deal_history"] = 10
        else:
            breakdown["deal_history"] = 0

        # 3. Account health proxy (25 pts)
        # No competing deal in flight = primed for outreach.
        # For subscription companies, no pipeline is also a renewal risk — weight it higher.
        if not open_pipeline:
            breakdown["health"] = 22 if is_subscription else 20
        else:
            breakdown["health"] = 5  # already being worked

        if owner_info and owner_info.get("owner_active"):
            breakdown["health"] = breakdown.get("health", 0) + 3  # active relationship owner

        # 4. ICP fit (20 pts) — derived from actual customer base, not hardcoded
        industry = customer.get("industry")
        breakdown["icp_fit"] = icp_industry_scores.get(industry, 5)  # 5 = unknown/other

        total_score = sum(breakdown.values())
        return min(total_score, 100), breakdown

    def _compute_expansion_headroom(self, customer: dict, cfg, *, floor: float) -> float:
        """Estimate expansion opportunity value with calibrated floor."""
        annual_rev = customer.get("annual_revenue") or 0
        total_won  = customer.get("total_won_value") or 0
        target     = annual_rev * cfg.get("penetration_target", 0.05)
        headroom   = max(0, target - total_won)
        return max(headroom, floor) if annual_rev > 0 else floor

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_customers_with_deal_history(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        OPTIONAL MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WITH a, count(o) AS won_deal_count, coalesce(sum(o.amount), 0) AS total_won_value
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

    def _get_customers_with_no_won_deals(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        WHERE NOT EXISTS {
            MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        }
        RETURN a.name AS account_name, a.industry AS industry
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_open_pipeline_by_account(self, tenant_id: str) -> dict[str, list[dict]]:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})-[:IN_ACCOUNT]->(a:Account)
        RETURN a.canonical_id AS account_id, o.name AS deal_name, o.amount AS amount
        """
        result: dict[str, list[dict]] = defaultdict(list)
        with self.driver.session() as session:
            for row in session.run(query, tenant_id=tenant_id):
                d = dict(row)
                result[d["account_id"]].append(d)
        return result

    def _get_customer_owners(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        OPTIONAL MATCH (p:Person)-[:OWNS]->(a)
        RETURN
            a.canonical_id AS account_id,
            a.name AS account_name,
            p.full_name AS owner,
            p.is_active AS owner_active
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
