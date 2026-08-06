"""
scout/workers/ap_processing.py — Accounts Payable Process Optimization Worker

Optimizes the Accounts Payable process by identifying batching opportunities,
early payment discount potential, and AP workflow inefficiencies. Goes deeper
than ProcureToPayWorker (which focuses on terms) by analyzing the overall AP
cycle efficiency, vendor payment concentration, and cash flow timing.

The core insight: AP is not just a payment function — it is a cash management
function. Two companies with identical vendor spend can have $500k differences
in working capital depending purely on how their AP cycle is structured.
Batching small vendor payments, capturing early payment discounts selectively,
and eliminating concentration risk are the three highest-leverage AP levers
for a mid-market PE-backed business.

Sprint 12 connects to NetSuite/QuickBooks for invoice-level AP mining: true
Days Payable Outstanding (DPO), early payment discount capture rate,
duplicate payment detection, and three-way match exception rates.
"""

import logging
from collections import defaultdict

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
EARLY_PAY_DISCOUNT_RATE = 0.02   # typical 2/10 net 30 discount = 2% if paid in 10 days
HIGH_CONCENTRATION_PCT  = 0.40   # one vendor = 40%+ of AP spend = concentration risk
BATCHING_THRESHOLD      = 5      # 5+ small vendors in same category = batching opportunity
SMALL_VENDOR_SPEND      = 10_000 # vendors under $10k/year = candidate for batching/elimination
AP_BENCHMARK_DAYS       = 30     # benchmark AP cycle = 30 days

# Net-30 or longer terms = eligible for early payment discount consideration
NET_30_OR_LONGER = {"Net 30", "Net30", "net30", "net 30",
                    "Net 60", "Net 90", "Net60", "Net90", "net60", "net90",
                    "net 60", "net 90"}


class APProcessingWorker(WorkerBase):
    """
    Surfaces AP concentration risk, batching opportunities, early payment
    discount potential, and vendors with undefined payment timing.

    Complements ProcureToPayWorker by focusing on AP cycle efficiency and
    cash flow timing rather than individual vendor payment term renegotiation.
    """

    WORKER_NAME = "APProcessingWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_discount_rate  = cfg.get("early_pay_discount_rate",  EARLY_PAY_DISCOUNT_RATE)
        t_concentration  = cfg.get("high_concentration_pct",   HIGH_CONCENTRATION_PCT)
        t_batching       = cfg.get("batching_threshold",        BATCHING_THRESHOLD)
        t_small_spend    = cfg.get("small_vendor_spend",        SMALL_VENDOR_SPEND)
        t_benchmark_days = cfg.get("ap_benchmark_days",         AP_BENCHMARK_DAYS)

        try:
            vendors = self._get_vendors(tenant_id)

            if not vendors:
                result.findings.append(Finding(
                    title="No vendor data found — run an ERP or procurement scan first",
                    detail=(
                        "APProcessingWorker requires Vendor nodes in the graph. "
                        "Connect a NetSuite, QuickBooks, or procurement connector "
                        "and run a scan to populate vendor data."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action=(
                        "Enable an ERP connector (NetSuite or QuickBooks) and trigger a scan. "
                        "Alternatively, upload a vendor export CSV via the manual ingestion endpoint."
                    ),
                ))
                result.summary_stats = {
                    "total_vendors": 0,
                    "total_annual_spend": 0,
                    "largest_vendor_pct": 0.0,
                    "vendors_no_terms": 0,
                    "batching_candidates": 0,
                    "early_pay_savings_opportunity": 0,
                }
                return result

            total_spend = sum((v.get("annual_spend") or 0) for v in vendors)

            # ── Category bucketing for batching analysis ───────────────────
            category_map: dict[str, list[dict]] = defaultdict(list)
            for v in vendors:
                cat = v.get("category") or "Uncategorized"
                category_map[cat].append(v)

            # Small vendors (<$10k) per category
            small_vendor_categories: dict[str, list[dict]] = {}
            for cat, cat_vendors in category_map.items():
                small = [v for v in cat_vendors if (v.get("annual_spend") or 0) < t_small_spend]
                if len(small) >= t_batching:
                    small_vendor_categories[cat] = small

            vendors_no_terms = [v for v in vendors if not v.get("payment_terms")]

            # Eligible for early pay discount: Net 30 or longer terms
            early_pay_eligible = [
                v for v in vendors
                if v.get("payment_terms") in NET_30_OR_LONGER
            ]
            eligible_spend = sum((v.get("annual_spend") or 0) for v in early_pay_eligible)
            early_pay_savings = round(eligible_spend * t_discount_rate)

            # Largest single vendor
            largest_vendor = max(vendors, key=lambda v: v.get("annual_spend") or 0) if vendors else None
            largest_vendor_spend = (largest_vendor.get("annual_spend") or 0) if largest_vendor else 0
            largest_vendor_pct = (largest_vendor_spend / total_spend) if total_spend > 0 else 0.0

            result.summary_stats = {
                "total_vendors": len(vendors),
                "total_annual_spend": round(total_spend),
                "largest_vendor_pct": round(largest_vendor_pct * 100, 1),
                "vendors_no_terms": len(vendors_no_terms),
                "batching_candidates": sum(len(v) for v in small_vendor_categories.values()),
                "early_pay_savings_opportunity": early_pay_savings,
            }

            # ── Finding 1: AP concentration risk ──────────────────────────
            if largest_vendor and total_spend > 0 and largest_vendor_pct >= t_concentration:
                result.findings.append(Finding(
                    title=(
                        f"AP concentration risk: {largest_vendor.get('name')} is "
                        f"{largest_vendor_pct * 100:.1f}% of total spend "
                        f"(${largest_vendor_spend:,.0f})"
                    ),
                    detail=(
                        f"{largest_vendor.get('name')} represents "
                        f"{largest_vendor_pct * 100:.1f}% of total annual vendor spend "
                        f"(${largest_vendor_spend:,.0f} of ${total_spend:,.0f}). "
                        f"A single vendor exceeding {t_concentration * 100:.0f}% of AP "
                        f"creates payment timing concentration risk: any dispute, service issue, "
                        f"or unilateral term change by this vendor has outsized P&L impact. "
                        f"It also eliminates negotiating leverage — you cannot credibly threaten "
                        f"to switch a vendor that holds 40%+ of your spend."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "vendor_name": largest_vendor.get("name"),
                        "vendor_spend": round(largest_vendor_spend),
                        "vendor_pct_of_total": round(largest_vendor_pct * 100, 1),
                        "total_spend": round(total_spend),
                        "concentration_threshold_pct": t_concentration * 100,
                        "vendor_category": largest_vendor.get("category"),
                        "vendor_payment_terms": largest_vendor.get("payment_terms"),
                    },
                    recommended_action=(
                        "Develop a dual-source strategy for this vendor's category. "
                        "Pilot a secondary vendor for at least 15% of volume to restore "
                        "credible switch threat. Brief the CFO on this concentration before "
                        "the next renewal negotiation — leverage is highest when alternatives exist."
                    ),
                ))

            # ── Finding 2: Batching opportunity ───────────────────────────
            if small_vendor_categories:
                total_batch_vendors = sum(
                    len(v) for v in small_vendor_categories.values()
                )
                total_batch_spend = sum(
                    sum(v.get("annual_spend") or 0 for v in vlist)
                    for vlist in small_vendor_categories.values()
                )
                cats_summary = "; ".join(
                    f"{cat} ({len(vlist)} vendors, ${sum(v.get('annual_spend') or 0 for v in vlist):,.0f}/yr)"
                    for cat, vlist in list(small_vendor_categories.items())[:4]
                )
                ap_overhead_savings_pct = 0.60  # consolidation reduces AP overhead by 60%
                result.findings.append(Finding(
                    title=(
                        f"AP batching opportunity: {total_batch_vendors} small vendors "
                        f"across {len(small_vendor_categories)} categor"
                        f"{'ies' if len(small_vendor_categories) != 1 else 'y'} "
                        f"— ${total_batch_spend:,.0f}/yr"
                    ),
                    detail=(
                        f"{total_batch_vendors} vendors each with <${t_small_spend:,.0f}/yr spend "
                        f"are spread across {len(small_vendor_categories)} categories with "
                        f"{t_batching}+ vendors each. "
                        f"Each small vendor requires an individual AP workflow: "
                        f"invoice processing, approval routing, payment scheduling, and reconciliation. "
                        f"Consolidating to 1-2 preferred vendors per category reduces AP processing "
                        f"overhead by approximately {ap_overhead_savings_pct * 100:.0f}%. "
                        f"Categories: {cats_summary}."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "total_small_vendors": total_batch_vendors,
                        "batching_categories": len(small_vendor_categories),
                        "total_small_vendor_spend": round(total_batch_spend),
                        "small_vendor_threshold": t_small_spend,
                        "batching_threshold": t_batching,
                        "ap_overhead_reduction_pct": int(ap_overhead_savings_pct * 100),
                        "categories": {
                            cat: [
                                {"name": v.get("name"), "annual_spend": v.get("annual_spend")}
                                for v in vlist
                            ]
                            for cat, vlist in small_vendor_categories.items()
                        },
                    },
                    recommended_action=(
                        "For each affected category, identify 1-2 preferred vendors and "
                        "consolidate all small-vendor spend to them over the next quarter. "
                        "Issue a preferred vendor policy memo: no new vendors under $10k/yr "
                        "without procurement approval. "
                        "This typically reduces AP processing costs by $500-$2,000 per eliminated vendor."
                    ),
                ))

            # ── Finding 3: Vendors with no payment terms ───────────────────
            if vendors_no_terms:
                no_terms_spend = sum((v.get("annual_spend") or 0) for v in vendors_no_terms)
                top_no_terms = sorted(
                    vendors_no_terms, key=lambda v: -(v.get("annual_spend") or 0)
                )[:5]
                names = ", ".join(
                    f"{v.get('name')} (${v.get('annual_spend') or 0:,.0f}/yr)"
                    for v in top_no_terms
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(vendors_no_terms)} vendor"
                        f"{'s' if len(vendors_no_terms) != 1 else ''} with no payment terms "
                        f"— ${no_terms_spend:,.0f}/yr cash flow uncertainty"
                    ),
                    detail=(
                        f"{len(vendors_no_terms)} vendor"
                        f"{'s have' if len(vendors_no_terms) != 1 else ' has'} "
                        f"no payment terms recorded, representing ${no_terms_spend:,.0f}/yr "
                        f"of spend with undefined payment timing. "
                        f"Without documented terms, the AP team cannot build an accurate "
                        f"cash flow forecast — payments may be made ad hoc on whatever schedule "
                        f"the vendor requests. "
                        f"Examples: {names}."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "vendor_count": len(vendors_no_terms),
                        "total_spend": round(no_terms_spend),
                        "vendors": [
                            {"name": v.get("name"), "category": v.get("category"),
                             "annual_spend": v.get("annual_spend")}
                            for v in top_no_terms
                        ],
                    },
                    recommended_action=(
                        "Pull invoices and contracts for all vendors with no payment terms. "
                        "Document actual terms in the vendor management system this week. "
                        "For vendors above $25k/yr, negotiate formal written payment terms "
                        "as a condition of the next purchase order or renewal."
                    ),
                ))

            # ── Finding 4: Early payment discount opportunity ──────────────
            if early_pay_eligible and early_pay_savings > 0:
                result.findings.append(Finding(
                    title=(
                        f"Early payment discount opportunity: ~${early_pay_savings:,.0f}/yr "
                        f"available from {len(early_pay_eligible)} vendor"
                        f"{'s' if len(early_pay_eligible) != 1 else ''} on Net-30+ terms"
                    ),
                    detail=(
                        f"{len(early_pay_eligible)} vendor"
                        f"{'s are' if len(early_pay_eligible) != 1 else ' is'} on Net-30 or "
                        f"longer payment terms (${eligible_spend:,.0f}/yr combined). "
                        f"A standard 2/10 Net-30 early payment discount — pay in 10 days, "
                        f"take {t_discount_rate * 100:.0f}% off the invoice — "
                        f"would yield approximately ${early_pay_savings:,.0f}/yr in savings. "
                        f"This is only worthwhile when the company's cost of capital is below "
                        f"{t_discount_rate * 100:.0f}% on a 20-day basis (~{t_discount_rate * 365 / 20 * 100:.0f}% annualized). "
                        f"Selectively capture discounts for the highest-spend vendors first."
                    ),
                    severity=Severity.INFO,
                    data={
                        "eligible_vendor_count": len(early_pay_eligible),
                        "eligible_spend": round(eligible_spend),
                        "discount_rate": t_discount_rate,
                        "estimated_annual_savings": early_pay_savings,
                        "annualized_equivalent_rate": round(
                            t_discount_rate * 365 / 20 * 100, 1
                        ),
                        "top_eligible_vendors": [
                            {"name": v.get("name"), "annual_spend": v.get("annual_spend"),
                             "payment_terms": v.get("payment_terms")}
                            for v in sorted(
                                early_pay_eligible, key=lambda v: -(v.get("annual_spend") or 0)
                            )[:5]
                        ],
                    },
                    recommended_action=(
                        "Ask the CFO whether the company's cost of capital justifies early "
                        "payment discount capture at current cash balances. "
                        "If yes, negotiate 2/10 Net-30 terms with the top 5 vendors by spend."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"APProcessingWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Query helpers ───────────────────────────────────────────────────────

    def _get_vendors(self, tenant_id: str) -> list[dict]:
        """
        Fetch all Vendor nodes with spend, category, and payment terms data.
        """
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id})
        RETURN v.name           AS name,
               v.category       AS category,
               v.annual_spend   AS annual_spend,
               v.payment_terms  AS payment_terms
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
