"""
scout/workers/working_capital.py — Working Capital Worker

Identifies opportunities to improve free cash flow through smarter
management of vendor payment terms, spend timing, and AP discipline.

Working capital optimization is one of the fastest EBITDA levers
in PE — it doesn't require headcount reductions or price increases.
It's purely financial engineering applied to how and when you pay.

A $30M ARR company typically has $3-5M in vendor spend. Moving from
"pay immediately" to "pay Net 45" across that spend can free up
$350k-$600k of cash that was previously tied up in vendor prepayments —
without spending a dollar less.

What this worker analyzes:

  1. PAYMENT TERM DISTRIBUTION — what percentage of spend is on
     favorable vs unfavorable terms? What's the working capital impact?

  2. HIGH-SPEND VENDORS WITH NO TERMS — these are likely auto-paying
     on invoice with no negotiated terms. Every one is an opportunity.

  3. SPEND TIMING CONCENTRATION — too much spend renewing in Q1
     creates cash flow pressure. Staggering renewals across the year
     smooths the cash flow profile.

  4. ANNUAL UPFRONT VS MONTHLY — vendors where you pay annually upfront
     are tying up cash that could be deployed elsewhere. Converting to
     monthly billing (even at a small premium) often wins on IRR.

In Sprint 9 (Worker Agents), the AP Processing Worker will automate
payment scheduling to always pay on the optimal date within terms —
maximizing float without triggering late fees.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# ── Payment term benchmarks ────────────────────────────────────────────────
FAVORABLE_TERMS    = {"Net 30", "Net 45", "Net 60", "Net 90", "Monthly", "Net 30 Monthly"}
UNFAVORABLE_TERMS  = {"Net 7", "Net 10", "Upfront", "Annual", "Annual Prepaid", "Immediate", "Due on Receipt"}
Q1_CONCENTRATION_THRESHOLD = 0.45   # >45% of renewals in Q1 = cash crunch risk (all segments)

# Segment-aware unmanaged spend threshold.
# Enterprise CFOs care about $50k+ vendors with no terms; SMB CFOs care about $10k+.
UNMANAGED_SPEND_BY_SEGMENT: dict[str, int] = {
    "enterprise": 50_000,
    "mid_market": 25_000,
    "smb":        10_000,
}

# Segment-aware annual billing threshold (above which upfront billing is material).
ANNUAL_BILLING_BY_SEGMENT: dict[str, int] = {
    "enterprise": 100_000,
    "mid_market":  50_000,
    "smb":         20_000,
}

# Minimum working capital improvement to surface the summary finding.
# Scales with company size — $10k is material for SMB, noise for enterprise.
WC_MIN_IMPROVEMENT_BY_SEGMENT: dict[str, int] = {
    "enterprise": 50_000,
    "mid_market": 10_000,
    "smb":         5_000,
}


class WorkingCapitalWorker(WorkerBase):
    """
    Surfaces payment term gaps, cash flow risks, and working capital
    optimization opportunities across the vendor portfolio.
    """

    WORKER_NAME = "WorkingCapitalWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
        t_unmanaged      = cfg.get("unmanaged_spend_threshold", UNMANAGED_SPEND_BY_SEGMENT.get(segment, 25_000))
        t_annual_billing = cfg.get("annual_billing_threshold",  ANNUAL_BILLING_BY_SEGMENT.get(segment, 50_000))
        t_wc_min         = WC_MIN_IMPROVEMENT_BY_SEGMENT.get(segment, 10_000)

        try:
            vendors = self._get_vendors_with_terms(tenant_id)
            renewals = self._get_renewal_timing(tenant_id)

            if not vendors:
                result.findings.append(Finding(
                    title="No vendor payment data — run an ERP scan first",
                    detail="WorkingCapitalWorker requires vendor spend and payment terms from NetSuite or similar.",
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats = {"total_vendor_spend": 0}
                return result

            total_spend = sum(v.get("annual_spend") or 0 for v in vendors)

            # Classify terms
            favorable = [v for v in vendors if v.get("payment_terms") in FAVORABLE_TERMS]
            unfavorable = [v for v in vendors if v.get("payment_terms") in UNFAVORABLE_TERMS]
            unmanaged = [
                v for v in vendors
                if not v.get("payment_terms") and (v.get("annual_spend") or 0) >= t_unmanaged
            ]

            favorable_spend = sum(v.get("annual_spend") or 0 for v in favorable)
            unfavorable_spend = sum(v.get("annual_spend") or 0 for v in unfavorable)
            unmanaged_spend = sum(v.get("annual_spend") or 0 for v in unmanaged)

            # Working capital improvement estimate:
            # Moving unfavorable+unmanaged spend to Net 30 frees up ~30/365 of that spend
            convertible_spend = unfavorable_spend + unmanaged_spend
            wc_improvement_estimate = convertible_spend * (30 / 365)

            # Renewal timing analysis
            q1_renewals = [r for r in renewals if r.get("renewal_month") in (1, 2, 3)]
            q1_renewal_spend = sum(r.get("annual_spend") or 0 for r in q1_renewals)
            total_renewal_spend = sum(r.get("annual_spend") or 0 for r in renewals)
            q1_concentration = q1_renewal_spend / total_renewal_spend if total_renewal_spend > 0 else 0

            result.summary_stats = {
                "total_vendor_spend": round(total_spend),
                "favorable_terms_spend": round(favorable_spend),
                "unfavorable_terms_spend": round(unfavorable_spend),
                "unmanaged_terms_spend": round(unmanaged_spend),
                "favorable_terms_pct": round(favorable_spend / total_spend * 100 if total_spend else 0, 1),
                "estimated_wc_improvement": round(wc_improvement_estimate),
                "q1_renewal_concentration_pct": round(q1_concentration * 100, 1),
                "segment": segment,
                "unmanaged_threshold": t_unmanaged,
            }

            # ── Finding 1: Unmanaged vendor payment terms ───────────────
            if unmanaged:
                unmanaged_names = [v.get("name") for v in unmanaged if v.get("name")]
                result.findings.append(Finding(
                    title=f"{len(unmanaged)} vendor{'s' if len(unmanaged) > 1 else ''} (${unmanaged_spend:,.0f}/yr) with no payment terms — paying on invoice",
                    detail=(
                        f"{len(unmanaged)} vendors totaling ${unmanaged_spend:,.0f}/year have no "
                        f"negotiated payment terms. These are likely paid immediately on invoice — "
                        f"equivalent to giving vendors a free loan each billing cycle. "
                        f"Converting to Net 30 frees up ~${unmanaged_spend * 30/365:,.0f} of cash."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "unmanaged_count": len(unmanaged),
                        "unmanaged_spend": round(unmanaged_spend),
                        "estimated_cash_freed": round(unmanaged_spend * 30 / 365),
                        "vendors": [{"name": v.get("name"), "spend": v.get("annual_spend")} for v in unmanaged[:8]],
                    },
                    recommended_action=(
                        "At next invoice or renewal, request Net 30 terms from each vendor. "
                        "Most vendors will agree — it's standard. "
                        "Document terms in the vendor management system to prevent backslide."
                    ),
                    confidence="high",
                    specific_entities=unmanaged_names[:5],
                    context_note=f"Threshold: vendors with spend > ${t_unmanaged:,} and no terms ({segment} benchmark).",
                ))

            # ── Finding 2: Unfavorable payment terms ────────────────────
            if unfavorable:
                unfavorable_names = [v.get("name") for v in unfavorable if v.get("name")]
                result.findings.append(Finding(
                    title=f"${unfavorable_spend:,.0f}/yr on unfavorable terms (Net 7 / Upfront / Annual)",
                    detail=(
                        f"{len(unfavorable)} vendor(s) totaling ${unfavorable_spend:,.0f}/year "
                        f"are on unfavorable payment terms. "
                        f"Moving these to Net 30 would free up ~${unfavorable_spend * 30/365:,.0f} "
                        f"in working capital — cash that could be deployed in the business."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "unfavorable_count": len(unfavorable),
                        "unfavorable_spend": round(unfavorable_spend),
                        "estimated_cash_freed": round(unfavorable_spend * 30 / 365),
                        "vendors": [{"name": v.get("name"), "spend": v.get("annual_spend"), "terms": v.get("payment_terms")} for v in unfavorable[:5]],
                    },
                    recommended_action=(
                        "Renegotiate payment terms at next renewal for each vendor. "
                        "For annual prepaid vendors: request monthly billing (even at a 3-5% "
                        "premium, the IRR on freed cash typically exceeds the premium)."
                    ),
                    confidence="high",
                    specific_entities=unfavorable_names[:5],
                ))

            # ── Finding 3: Q1 renewal concentration ─────────────────────
            if q1_concentration >= Q1_CONCENTRATION_THRESHOLD:
                result.findings.append(Finding(
                    title=f"{q1_concentration*100:.0f}% of contract renewals fall in Q1 — cash flow crunch risk",
                    detail=(
                        f"${q1_renewal_spend:,.0f} of the ${total_renewal_spend:,.0f} annual "
                        f"renewal portfolio renews in Q1 (Jan-Mar). "
                        f"This creates a predictable cash flow trough at the start of every year — "
                        f"precisely when most companies have the least cash (post-holiday, pre-revenue ramp)."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "q1_renewal_spend": round(q1_renewal_spend),
                        "total_renewal_spend": round(total_renewal_spend),
                        "q1_concentration_pct": round(q1_concentration * 100, 1),
                    },
                    recommended_action=(
                        "At next renewal, negotiate start dates to spread contracts across Q2-Q4. "
                        "Offer vendors a small incentive (faster payment, multi-year commitment) "
                        "in exchange for shifting the billing period."
                    ),
                    confidence="high",
                ))

            # ── Finding 4: Total working capital opportunity summary ─────
            if wc_improvement_estimate > t_wc_min:
                result.findings.append(Finding(
                    title=f"Total working capital improvement opportunity: ${wc_improvement_estimate:,.0f}",
                    detail=(
                        f"By moving ${convertible_spend:,.0f} of vendor spend from immediate/upfront "
                        f"payment to Net 30, the company can free up ~${wc_improvement_estimate:,.0f} "
                        f"in cash float. This is recurring annual improvement — not a one-time benefit."
                    ),
                    severity=Severity.INFO,
                    data={
                        "convertible_spend": round(convertible_spend),
                        "wc_improvement": round(wc_improvement_estimate),
                        "assumption": "Net 30 terms on all convertible spend",
                        "segment": segment,
                    },
                    recommended_action=(
                        "Include payment term targets in the CFO's 100-day plan. "
                        "Track favorable terms % as a KPI — target 70%+ of spend on Net 30+ terms."
                    ),
                    context_note=f"Minimum surfacing threshold: ${t_wc_min:,} ({segment} calibrated).",
                ))

        except Exception as exc:
            logger.exception(f"WorkingCapitalWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _get_vendors_with_terms(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id, is_active: true})
        RETURN v.name AS name, v.category AS category,
               v.annual_spend AS annual_spend, v.payment_terms AS payment_terms
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_renewal_timing(self, tenant_id: str) -> list[dict]:
        """Get renewal month distribution for cash flow analysis."""
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id, is_active: true})
        WHERE v.contract_renewal IS NOT NULL
        RETURN
            v.name AS name,
            v.annual_spend AS annual_spend,
            toInteger(substring(v.contract_renewal, 5, 2)) AS renewal_month
        ORDER BY renewal_month
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
