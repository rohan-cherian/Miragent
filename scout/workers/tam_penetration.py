"""
scout/workers/tam_penetration.py — TAM Penetration & ICP Worker

Defines the Ideal Customer Profile from existing customers, scores
prospects against it, identifies white space, and surfaces market signals.

This is the "top of funnel" intelligence layer introduced in Sprint 6.
Before this worker, Miragent analyzed the pipeline you already have.
This worker answers the prior question: are you chasing the RIGHT market?

WHAT IT DOES:

  1. ICP DEFINITION — reverse-engineers the Ideal Customer Profile
     from existing customers. Analyzes industry, size (headcount),
     revenue, and geography of accounts marked "Customer" to find
     the common profile of your actual buyers.

     "Your best customers are: Financial Services or Healthcare,
      200-2,000 employees, $40M-$300M revenue. 3 of 3 customers
      match this profile."

  2. PROSPECT ICP SCORING — scores every "Prospect" account against
     the derived ICP. Tells you which prospects are worth prioritizing.

     "Vertex Logistics: ICP score 62/100. Size matches, but industry
      (Transportation) is outside your core verticals. Convert with
      a vertical-specific pitch."

  3. WHITE SPACE ANALYSIS — identifies industries with zero current
     penetration that might match your ICP profile.

  4. PIPELINE ICP MATCH — what percentage of your open pipeline is
     chasing ICP-qualified vs. non-ICP accounts?

  5. CUSTOMER CONCENTRATION RISK — flags if too much of your
     current ARR is concentrated in one industry (exit risk for buyers).

SPRINT 12 UPGRADE:
In Sprint 12 (Real Connectors), this worker will be enriched with
external market data via Clearbit (company enrichment), ZoomInfo
(market sizing), Crunchbase (funding signals), and G2 (category signals)
to produce a quantitative TAM estimate and identify specific target companies.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)


class TamPenetrationWorker(WorkerBase):
    """
    Derives ICP from existing customers, scores prospects, and identifies
    white space and pipeline quality signals.
    """

    WORKER_NAME = "TamPenetrationWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()
        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            customers  = self._get_accounts_by_type(tenant_id, "Customer")
            prospects  = self._get_accounts_by_type(tenant_id, "Prospect")
            all_accounts = customers + prospects
            open_pipeline = self._get_open_pipeline_with_accounts(tenant_id)

            result.summary_stats = {
                "customer_count": len(customers),
                "prospect_count": len(prospects),
                "total_accounts": len(all_accounts),
                "open_pipeline_deals": len(open_pipeline),
                "tam_data_source": "internal_crm_only",
                "segment": segment,
            }

            if not customers:
                result.findings.append(Finding(
                    title="No customer accounts found — ICP analysis requires closed-won customers",
                    detail="Run a CRM scan with at least one closed-won deal to define your ICP.",
                    severity=Severity.INFO,
                    data={},
                ))
                return result

            # ── Step 1: Derive ICP from customers ─────────────────────
            icp = self._derive_icp(customers)

            # ── Finding 1: ICP Definition ──────────────────────────────
            result.findings.append(Finding(
                title=f"ICP derived: {icp['top_industries']}, {icp['size_range']} employees, ${icp['revenue_range']}",
                detail=(
                    f"Based on {len(customers)} customer account(s), your Ideal Customer Profile is: "
                    f"Industry: {icp['top_industries']}. "
                    f"Headcount: {icp['size_range']} employees. "
                    f"Revenue: ${icp['revenue_range']}. "
                    f"This is your highest-conversion segment — prioritize pipeline in this profile."
                ),
                severity=Severity.INFO,
                data={
                    "icp": icp,
                    "customer_count": len(customers),
                    "derived_from": "existing_customer_analysis",
                },
                recommended_action=(
                    "Use this ICP definition to qualify inbound leads and prioritize outbound targeting. "
                    "Leads outside the ICP require a 2-3x longer sales cycle on average."
                ),
            ))

            # ── Finding 2: Customer industry concentration risk ────────
            industry_counts = Counter(c.get("industry") or "Unknown" for c in customers)
            top_industry = industry_counts.most_common(1)[0]
            top_pct = top_industry[1] / len(customers) * 100
            if top_pct >= cfg.get("concentration_risk_pct"):
                result.findings.append(Finding(
                    title=f"Customer concentration: {top_pct:.0f}% of customers in {top_industry[0]}",
                    detail=(
                        f"{top_industry[1]} of {len(customers)} customers are in {top_industry[0]}. "
                        f"High industry concentration is a revenue risk at exit — "
                        f"strategic acquirers discount companies overly dependent on one vertical. "
                        f"Target: no single industry above 40% of ARR by exit."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "top_industry": top_industry[0],
                        "top_industry_pct": round(top_pct, 1),
                        "industry_distribution": dict(industry_counts),
                    },
                    recommended_action=(
                        f"Build a targeted expansion campaign in 2 adjacent verticals. "
                        f"Use {top_industry[0]} case studies to establish credibility — "
                        f"buyers in adjacent industries respond to proven ROI in similar sectors."
                    ),
                ))

            # ── Finding 3: Prospect ICP scoring ───────────────────────
            if prospects:
                scored_prospects = []
                for prospect in prospects:
                    score = self._score_against_icp(prospect, icp)
                    scored_prospects.append({**prospect, "icp_score": score})

                scored_prospects.sort(key=lambda x: x["icp_score"], reverse=True)
                strong = [p for p in scored_prospects if p["icp_score"] >= cfg.get("icp_score_strong")]
                weak   = [p for p in scored_prospects if p["icp_score"] < cfg.get("icp_score_moderate")]

                if strong:
                    strong_names = [p.get("name", "Unknown") for p in strong]
                    result.findings.append(Finding(
                        title=f"{len(strong)} high-ICP prospect{'s' if len(strong) > 1 else ''} — prioritize immediately",
                        detail=(
                            f"{', '.join(strong_names)} "
                            f"score{'s' if len(strong) == 1 else ''} {cfg.get('icp_score_strong')}+ on your ICP. "
                            f"These prospects look like your existing customers — "
                            f"highest conversion probability, shortest sales cycle."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "strong_icp_prospects": [
                                {"name": p.get("name"), "industry": p.get("industry"),
                                 "employees": p.get("employee_count"), "icp_score": p["icp_score"]}
                                for p in strong
                            ],
                        },
                        recommended_action=(
                            "Assign your most experienced AE to these prospects. "
                            "Lead with case studies from your most similar existing customers."
                        ),
                        confidence="medium",
                        specific_entities=strong_names[:6],
                    ))

                if weak:
                    weak_names = [p.get("name", "Unknown") for p in weak]
                    result.findings.append(Finding(
                        title=f"{len(weak)} low-ICP prospect{'s' if len(weak) > 1 else ''} in pipeline — review qualification",
                        detail=(
                            f"{', '.join(weak_names)} "
                            f"score below {cfg.get('icp_score_moderate')} on your ICP. "
                            f"These deals will take longer, cost more to close, and churn earlier. "
                            f"Low-ICP deals consume 40% more rep time for 30% lower LTV."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "low_icp_prospects": [
                                {"name": p.get("name"), "industry": p.get("industry"), "icp_score": p["icp_score"]}
                                for p in weak
                            ],
                        },
                        recommended_action=(
                            f"Require VP approval to continue pursuing sub-{cfg.get('icp_score_moderate')} ICP prospects. "
                            "If they must be worked, assign to a junior AE and set "
                            "explicit go/no-go milestones to prevent pipeline contamination."
                        ),
                        confidence="medium",
                        specific_entities=weak_names[:6],
                    ))

            # ── Finding 4: Pipeline ICP match ─────────────────────────
            if open_pipeline:
                customer_ids = {c.get("account_id") for c in customers if c.get("account_id")}
                icp_pipeline = [d for d in open_pipeline if d.get("account_id") in customer_ids]
                icp_pipeline_pct = len(icp_pipeline) / len(open_pipeline) if open_pipeline else 0
                icp_pipeline_value = sum(d.get("amount") or 0 for d in icp_pipeline)
                total_pipeline_value = sum(d.get("amount") or 0 for d in open_pipeline)

                if icp_pipeline_pct < cfg.get("pipeline_icp_low"):
                    result.findings.append(Finding(
                        title=f"Only {icp_pipeline_pct*100:.0f}% of open pipeline is with ICP accounts",
                        detail=(
                            f"{len(icp_pipeline)} of {len(open_pipeline)} open deals "
                            f"(${icp_pipeline_value:,.0f} of ${total_pipeline_value:,.0f}) "
                            f"are with existing customer accounts. "
                            f"Pipeline heavily weighted toward new prospects increases "
                            f"cycle time and reduces win rate."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "icp_pipeline_deals": len(icp_pipeline),
                            "total_pipeline_deals": len(open_pipeline),
                            "icp_pipeline_pct": round(icp_pipeline_pct * 100, 1),
                            "icp_pipeline_value": round(icp_pipeline_value),
                            "total_pipeline_value": round(total_pipeline_value),
                        },
                        recommended_action=(
                            "Rebalance pipeline: target 60%+ of ARR pipeline from existing "
                            "customer expansions (faster, cheaper, higher win rate) "
                            "and 40% from ICP-qualified new logos."
                        ),
                    ))

            # ── Finding 5: White space preview ────────────────────────
            represented_industries = {c.get("industry") for c in customers if c.get("industry")}
            all_known_industries = {
                "Financial Services", "Technology", "Healthcare",
                "Manufacturing", "Professional Services", "Education",
                "Retail", "Real Estate", "Transportation", "Energy",
            }
            white_space = all_known_industries - represented_industries
            if white_space:
                result.findings.append(Finding(
                    title=f"White space: {len(white_space)} adjacent industries with no current penetration",
                    detail=(
                        f"Industries not yet in your customer base: {', '.join(sorted(white_space)[:5])}. "
                        f"Adjacent industries to your ICP verticals are the fastest to enter — "
                        f"buyers respond to case studies from similar sectors."
                    ),
                    severity=Severity.INFO,
                    data={
                        "white_space_industries": sorted(white_space),
                        "current_industries": sorted(represented_industries),
                    },
                    recommended_action=(
                        "Select 2 white space industries adjacent to your strongest vertical. "
                        "Run a 90-day pilot outbound campaign. Measure conversion vs. core vertical."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"TamPenetrationWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Helpers ────────────────────────────────────────────────────────────

    def _derive_icp(self, customers: list[dict]) -> dict:
        """Derive ICP attributes from existing customers."""
        industries = [c.get("industry") for c in customers if c.get("industry")]
        industry_counts = Counter(industries)
        top_industries = ", ".join(ind for ind, _ in industry_counts.most_common(2))

        sizes = [c.get("employee_count") for c in customers if c.get("employee_count")]
        revenues = [c.get("annual_revenue") for c in customers if c.get("annual_revenue")]

        if sizes:
            size_min, size_max = int(min(sizes)), int(max(sizes))
            size_range = f"{size_min:,}–{size_max:,}"
        else:
            size_range = "unknown"

        if revenues:
            rev_min = min(revenues) / 1e6
            rev_max = max(revenues) / 1e6
            revenue_range = f"${rev_min:.0f}M–${rev_max:.0f}M"
        else:
            revenue_range = "unknown"

        return {
            "top_industries": top_industries,
            "industry_distribution": dict(industry_counts),
            "size_range": size_range,
            "revenue_range": revenue_range,
            "min_employees": min(sizes) if sizes else None,
            "max_employees": max(sizes) if sizes else None,
            "min_revenue": min(revenues) if revenues else None,
            "max_revenue": max(revenues) if revenues else None,
        }

    def _score_against_icp(self, prospect: dict, icp: dict) -> int:
        """Score a prospect 0-100 against the derived ICP."""
        score = 0

        # Industry match (40 points)
        industry_dist = icp.get("industry_distribution") or {}
        if prospect.get("industry") in industry_dist:
            # Proportional: most common industry = full points
            max_count = max(industry_dist.values()) if industry_dist else 1
            pct = industry_dist.get(prospect.get("industry"), 0) / max_count
            score += int(40 * pct)

        # Size match (30 points)
        emp = prospect.get("employee_count")
        min_emp = icp.get("min_employees")
        max_emp = icp.get("max_employees")
        if emp and min_emp and max_emp:
            if min_emp <= emp <= max_emp:
                score += 30
            elif emp < min_emp * 0.5 or emp > max_emp * 2:
                score += 0
            else:
                score += 15

        # Revenue match (30 points)
        rev = prospect.get("annual_revenue")
        min_rev = icp.get("min_revenue")
        max_rev = icp.get("max_revenue")
        if rev and min_rev and max_rev:
            if min_rev <= rev <= max_rev:
                score += 30
            elif rev < min_rev * 0.5 or rev > max_rev * 2:
                score += 0
            else:
                score += 15

        return min(score, 100)

    def _get_accounts_by_type(self, tenant_id: str, account_type: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: $account_type})
        RETURN a.name AS name, a.industry AS industry,
               a.annual_revenue AS annual_revenue,
               a.employee_count AS employee_count,
               a.canonical_id AS account_id
        ORDER BY a.annual_revenue DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id, account_type=account_type)]

    def _get_open_pipeline_with_accounts(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN o.name AS deal_name, o.amount AS amount,
               a.canonical_id AS account_id, a.name AS account_name,
               a.industry AS industry
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
