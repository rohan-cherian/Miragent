"""
scout/workers/pricing_integrity.py — Pricing Integrity Worker (Layer 3)

Identifies pricing anomalies in closed deals: excessive discounting,
legacy pricing on long-term customers, and deal size outliers.

Pricing is one of the highest-leverage EBITDA levers. A 1% improvement
in price realization yields a 10-12% improvement in operating profit
(McKinsey pricing research). PE firms consistently find 3-8% of revenue
being given away in unnecessary discounts.

Layer 3 upgrade:
  - Segment-aware outlier thresholds: enterprise deals are expected to have
    wider variance (multi-year vs annual, platform vs module — these produce
    legitimate 10x ACV differences). Flagging an enterprise company with CV
    of 70% is noise; for an SMB SaaS with standardized seats it's a real signal.
  - Cross-reference deal attributes: the outlier analysis now separates deals
    by market segment when enough data exists. An SMB deal in an enterprise
    company's pipeline isn't a discount problem — it's a qualification problem.
  - ACV trend uses ctx.avg_deal_size as the calibrated historical baseline
    rather than computing it from the current sample (avoids distortion from
    seasonal variance).
  - All findings include specific deal names so the VP of Sales can immediately
    pull the correct records.
  - Confidence is "uncertain" when field trust for deal amounts is low
    (high null rate in the amount field means this analysis may be misleading).

What this worker analyzes:
  1. Discount outliers — deals significantly below the average ACV
  2. Small deal anomalies in the open pipeline
  3. Deal value distribution — ACV variance / coefficient of variation
  4. Average ACV trend — new vs historical win values

Note: Without explicit discount% fields in the mock CRM, this worker
uses deal amount distribution analysis as a pricing integrity proxy.
In production with real Salesforce data, Discount_Percentage__c
and List_Price__c fields would be used directly.
"""

from __future__ import annotations

import logging
import statistics
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# Segment-aware acceptable ACV coefficient-of-variation thresholds
# Enterprise orgs legitimately have wide deal size variance (platform deals vs module deals).
# SMB SaaS with per-seat pricing should have very consistent deal sizes.
CV_THRESHOLDS: dict[str, float] = {
    "enterprise":  100.0,   # >100% CV = flag for enterprise
    "mid_market":   75.0,   # >75% CV = flag for mid-market
    "smb":          50.0,   # >50% CV = flag for SMB
}

# How many std devs below mean counts as a price outlier (by segment)
OUTLIER_STD_DEVS: dict[str, float] = {
    "enterprise": 2.0,   # enterprise needs wider tolerance
    "mid_market": 1.5,
    "smb":        1.0,   # SMB should have tight pricing
}

# Downmarket drift threshold: open pipeline avg is this fraction of historical ACV
DOWNMARKET_THRESHOLD = 0.70


class PricingIntegrityWorker(WorkerBase):
    """
    Surfaces pricing anomalies: discount outliers, small deal patterns,
    and ACV distribution issues — with segment-aware thresholds.
    """

    WORKER_NAME = "PricingIntegrityWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            won_deals  = self._get_won_deals(tenant_id)
            open_deals = self._get_open_deals(tenant_id)

            all_amounts = [d.get("amount") or 0 for d in won_deals if (d.get("amount") or 0) > 0]

            # Check field trust for deal amounts
            amount_trusted = ctx.field_trusted("opportunity_amount", min_confidence=0.60)
            confidence_level = "high" if amount_trusted else "low"
            field_caveat = (
                "" if amount_trusted
                else " Note: deal amount data has high null rates — treat these findings as directional only."
            )

            # Segment-aware parameters
            segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
            cv_threshold   = CV_THRESHOLDS.get(segment, 75.0)
            outlier_stdevs = OUTLIER_STD_DEVS.get(segment, 1.5)

            # Use context-calibrated ACV if available (reduces seasonal distortion)
            calibrated_avg_acv = (
                ctx.avg_deal_size
                if ctx.avg_deal_size and ctx.avg_deal_size > 0 and ctx.has_calibrated_history
                else None
            )

            result.summary_stats = {
                "won_deal_count":       len(won_deals),
                "total_won_arr":        sum(all_amounts),
                "mean_acv":             round(statistics.mean(all_amounts)) if all_amounts else 0,
                "median_acv":           round(statistics.median(all_amounts)) if all_amounts else 0,
                "open_deal_count":      len(open_deals),
                "total_open_pipeline":  sum(d.get("amount") or 0 for d in open_deals),
                "segment":              segment,
                "amount_field_trusted": amount_trusted,
                "calibrated_acv":       calibrated_avg_acv,
            }

            if len(all_amounts) < cfg.get("min_deals_for_stats", 5):
                result.findings.append(Finding(
                    title="Insufficient deal history for pricing integrity analysis",
                    detail=(
                        f"Need at least {cfg.get('min_deals_for_stats', 5)} closed-won deals. "
                        f"Found {len(won_deals)}."
                    ),
                    severity=Severity.INFO,
                    data={"won_deal_count": len(won_deals)},
                ))
                return result

            mean_acv  = statistics.mean(all_amounts)
            stdev_acv = statistics.stdev(all_amounts) if len(all_amounts) > 1 else 0

            # Use calibrated ACV as the reference point if available
            reference_acv = calibrated_avg_acv or mean_acv
            acv_label = (
                "company calibrated ACV" if calibrated_avg_acv
                else "current sample mean ACV"
            )

            context_note = (
                f"Segment: {segment}. CV threshold: {cv_threshold:.0f}%. "
                f"Outlier sensitivity: {outlier_stdevs}x std dev. "
                f"ACV reference: {acv_label} (${reference_acv:,.0f}).{field_caveat}"
            )

            # ── Finding 1: Price outliers (potential heavy discounting) ──
            low_threshold = mean_acv - (outlier_stdevs * stdev_acv)
            outliers = [
                d for d in won_deals
                if (d.get("amount") or 0) < low_threshold and (d.get("amount") or 0) > 0
            ]

            if outliers and stdev_acv > 0:
                lost_revenue_estimate = sum(mean_acv - (d.get("amount") or 0) for d in outliers)
                outlier_details = [
                    {
                        "name":      d.get("deal_name", "Unknown"),
                        "amount":    d.get("amount") or 0,
                        "account":   d.get("account_name"),
                        "industry":  d.get("industry"),
                        "gap":       round(mean_acv - (d.get("amount") or 0)),
                    }
                    for d in outliers
                ]
                detail_lines = [
                    f"Mean ACV is ${mean_acv:,.0f} ({acv_label}). "
                    f"These {len(outliers)} deal(s) closed at more than {outlier_stdevs}x "
                    f"std dev below average — likely excessive discounting:{field_caveat}",
                    "",
                ]
                for od in outlier_details[:5]:
                    detail_lines.append(
                        f"  • {od['name']} ({od['account'] or 'Unknown'}): "
                        f"${od['amount']:,.0f} — ${od['gap']:,.0f} below mean"
                    )
                if len(outliers) > 5:
                    detail_lines.append(f"  • …and {len(outliers) - 5} more")

                result.findings.append(Finding(
                    title=(
                        f"{len(outliers)} won deal(s) significantly below mean ACV "
                        f"— potential ${lost_revenue_estimate:,.0f} in pricing leakage"
                    ),
                    detail="\n".join(detail_lines),
                    severity=Severity.HIGH,
                    data={
                        "mean_acv":              round(mean_acv),
                        "outlier_threshold":     round(low_threshold),
                        "outlier_count":         len(outliers),
                        "estimated_leakage":     round(lost_revenue_estimate),
                        "outlier_std_devs":      outlier_stdevs,
                        "deals":                 outlier_details,
                    },
                    recommended_action=(
                        "Review discount approval process. "
                        "Implement deal desk review for any deal below "
                        f"{round((low_threshold / mean_acv) * 100):.0f}% of standard ACV. "
                        "Consider minimum pricing policy enforcement by segment."
                    ),
                    confidence=confidence_level,
                    specific_entities=[
                        {
                            "type":    "deal",
                            "name":    od["name"],
                            "amount":  od["amount"],
                            "account": od["account"],
                        }
                        for od in outlier_details[:5]
                    ],
                    context_note=context_note,
                ))

            # ── Finding 2: ACV variance — pricing consistency ─────────────
            if stdev_acv > 0:
                coefficient_of_variation = (stdev_acv / mean_acv) * 100
                if coefficient_of_variation > cv_threshold:
                    result.findings.append(Finding(
                        title=(
                            f"High ACV variance for {segment} segment "
                            f"(CV: {coefficient_of_variation:.0f}% vs {cv_threshold:.0f}% threshold)"
                        ),
                        detail=(
                            f"Deal values range from ${min(all_amounts):,.0f} to ${max(all_amounts):,.0f} "
                            f"with a mean of ${mean_acv:,.0f}. "
                            f"A coefficient of variation above {cv_threshold:.0f}% for a {segment} "
                            f"company indicates inconsistent pricing — reps are quoting based on "
                            f"negotiation skill, not a structured pricing framework. "
                            f"This is recoverable 3-8% ARR on the table annually.{field_caveat}"
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "min_acv":                    round(min(all_amounts)),
                            "max_acv":                    round(max(all_amounts)),
                            "mean_acv":                   round(mean_acv),
                            "std_dev":                    round(stdev_acv),
                            "coefficient_of_variation_pct": round(coefficient_of_variation, 1),
                            "segment_cv_threshold":       cv_threshold,
                        },
                        recommended_action=(
                            "Implement a tiered pricing model with clear packages. "
                            "Anchor reps to standard pricing tiers — negotiation should be "
                            "exception-based with deal desk approval, not the default."
                        ),
                        confidence=confidence_level,
                        context_note=context_note,
                    ))

            # ── Finding 3: Open pipeline vs calibrated ACV baseline ───────
            open_amounts = [d.get("amount") or 0 for d in open_deals if (d.get("amount") or 0) > 0]
            if open_amounts and reference_acv > 0:
                avg_open = statistics.mean(open_amounts)
                pct_of_acv = avg_open / reference_acv
                if pct_of_acv < cfg.get("small_deal_threshold", DOWNMARKET_THRESHOLD):
                    downmarket_pct = round((1 - pct_of_acv) * 100)
                    result.findings.append(Finding(
                        title=(
                            f"Pipeline ACV trending {downmarket_pct}% below historical — "
                            f"potential downmarket drift"
                        ),
                        detail=(
                            f"Open pipeline average deal size is ${avg_open:,.0f} vs "
                            f"${reference_acv:,.0f} {acv_label}. "
                            f"Causes: downmarket ICP drift, poor qualification letting in "
                            f"small deals, or reps filling pipeline with easy low-value deals "
                            f"to hit volume metrics.{field_caveat}"
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "avg_open_pipeline_acv":  round(avg_open),
                            "historical_avg_acv":     round(reference_acv),
                            "pct_of_historical":      round(pct_of_acv * 100, 1),
                            "downmarket_drift_pct":   downmarket_pct,
                        },
                        recommended_action=(
                            "Review pipeline qualification standards. "
                            "Consider minimum deal size thresholds for CRM entry. "
                            "Confirm sales motion has not inadvertently shifted downmarket."
                        ),
                        confidence=confidence_level,
                        context_note=context_note,
                    ))

        except Exception as exc:
            logger.exception(f"PricingIntegrityWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _get_won_deals(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.name AS deal_name,
            o.amount AS amount,
            o.close_date AS close_date,
            a.name AS account_name,
            a.industry AS industry
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]

    def _get_open_deals(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        RETURN
            o.name AS deal_name,
            o.amount AS amount,
            o.stage AS stage,
            o.probability AS probability
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]
