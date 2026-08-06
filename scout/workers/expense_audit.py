"""
scout/workers/expense_audit.py — Vendor Expense Audit Worker

Audits vendor expenses for anomalies, duplicates, and policy violations.
Uses statistical analysis of vendor spend to identify outliers within
categories, vendors with spend far exceeding category peers, categories
where spend per employee exceeds industry benchmarks, and audit blind spots
(vendors with zero or missing spend data).

This worker answers the question every CFO asks in a PE-backed company's
first 100 days: "Where is the money going and can we trust the data?" A
spend audit is typically the first step in any cost reduction programme —
you cannot eliminate what you cannot see.

Statistical approach: within each category with 3+ vendors, flag any vendor
whose spend exceeds mean + 1.5σ as an outlier warranting manual review.
This is conservative enough to avoid false positives while catching true
anomalies. Category benchmarks are applied at the company level using
total active headcount as the denominator.

Sprint 12 connects to Concur/Ramp/Brex for transaction-level expense auditing:
receipt matching, policy violation detection, duplicate transaction flagging,
and merchant-level spend categorization.
"""

import logging
import statistics
from collections import defaultdict

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
OUTLIER_STD_DEVS           = 1.5    # spend > mean + 1.5σ = outlier
MIN_VENDORS_FOR_STATS      = 3      # need 3+ vendors per category for stats
DUPLICATE_NAME_SIMILARITY  = True   # flag vendors in same category with similar names
HIGH_SPEND_AUDIT_THRESHOLD = 75_000 # flag any single vendor above this for audit

# Per-employee annual spend benchmarks by category
CATEGORY_BENCHMARK: dict[str, int] = {
    "Software & SaaS": 4_000,
    "Cloud Infrastructure": 2_000,
    "Professional Services": 5_000,
    "Marketing": 3_000,
}


class ExpenseAuditWorker(WorkerBase):
    """
    Statistical spend anomaly detection, policy compliance checks, and
    benchmark comparisons across vendor expense data.

    Answers: where is spend concentrated, what looks anomalous, and what
    categories are over- or under-benchmarked for this company's size?
    """

    WORKER_NAME = "ExpenseAuditWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_outlier_std = cfg.get("outlier_std_devs",           OUTLIER_STD_DEVS)
        t_min_vendors = cfg.get("min_vendors_for_stats",      MIN_VENDORS_FOR_STATS)
        t_high_spend  = cfg.get("high_spend_audit_threshold", HIGH_SPEND_AUDIT_THRESHOLD)

        try:
            vendors = self._get_vendors(tenant_id)
            employee_count = self._get_employee_count(tenant_id)

            if not vendors:
                result.findings.append(Finding(
                    title="No vendor data found — run a procurement or ERP scan first",
                    detail=(
                        "ExpenseAuditWorker requires Vendor nodes in the graph. "
                        "Connect a NetSuite, QuickBooks, Ramp, or Brex connector "
                        "and run a scan to populate vendor expense data."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action=(
                        "Enable a vendor or expense data connector and trigger a scan. "
                        "Alternatively, upload a vendor export CSV via the manual ingestion endpoint."
                    ),
                ))
                result.summary_stats = {
                    "total_vendors": 0,
                    "total_spend_audited": 0,
                    "outlier_vendors": 0,
                    "high_spend_flagged": 0,
                    "missing_spend_vendors": 0,
                    "audit_coverage_pct": 0.0,
                }
                return result

            # ── Partition vendors ──────────────────────────────────────────
            vendors_with_spend = [
                v for v in vendors if (v.get("annual_spend") or 0) > 0
            ]
            vendors_missing_spend = [
                v for v in vendors if not v.get("annual_spend") or v.get("annual_spend") == 0
            ]
            total_spend_audited = sum((v.get("annual_spend") or 0) for v in vendors_with_spend)
            audit_coverage_pct = (
                round(len(vendors_with_spend) / len(vendors) * 100, 1)
                if vendors else 0.0
            )

            # ── Category grouping for outlier detection ────────────────────
            category_map: dict[str, list[dict]] = defaultdict(list)
            for v in vendors_with_spend:
                cat = v.get("category") or "Uncategorized"
                category_map[cat].append(v)

            # Outlier detection: mean + OUTLIER_STD_DEVS × stdev per category
            outlier_findings: list[dict] = []
            for cat, cat_vendors in category_map.items():
                if len(cat_vendors) < t_min_vendors:
                    continue
                spends = [v.get("annual_spend") or 0 for v in cat_vendors]
                try:
                    cat_mean = statistics.mean(spends)
                    cat_stdev = statistics.stdev(spends)
                except statistics.StatisticsError:
                    continue
                threshold = cat_mean + t_outlier_std * cat_stdev
                for v in cat_vendors:
                    spend = v.get("annual_spend") or 0
                    if spend > threshold:
                        outlier_findings.append({
                            "name": v.get("name"),
                            "category": cat,
                            "annual_spend": spend,
                            "category_mean": round(cat_mean),
                            "category_stdev": round(cat_stdev),
                            "outlier_threshold": round(threshold),
                            "deviation_from_mean": round(spend - cat_mean),
                            "std_devs_above_mean": round((spend - cat_mean) / cat_stdev, 2)
                            if cat_stdev > 0 else None,
                        })

            # High-spend vendors above audit threshold
            high_spend_vendors = [
                v for v in vendors_with_spend
                if (v.get("annual_spend") or 0) > t_high_spend
            ]

            result.summary_stats = {
                "total_vendors": len(vendors),
                "total_spend_audited": round(total_spend_audited),
                "outlier_vendors": len(outlier_findings),
                "high_spend_flagged": len(high_spend_vendors),
                "missing_spend_vendors": len(vendors_missing_spend),
                "audit_coverage_pct": audit_coverage_pct,
            }

            # ── Finding 1: Spend outliers within category ──────────────────
            if outlier_findings:
                top_outliers = sorted(
                    outlier_findings, key=lambda o: -(o["annual_spend"])
                )
                top_names = "; ".join(
                    f"{o['name']} (${o['annual_spend']:,.0f} vs. "
                    f"${o['category_mean']:,.0f} category avg, "
                    f"{o['std_devs_above_mean']}σ above mean)"
                    for o in top_outliers[:3]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(outlier_findings)} spend outlier"
                        f"{'s' if len(outlier_findings) != 1 else ''} detected "
                        f"(>{t_outlier_std}σ above category mean)"
                    ),
                    detail=(
                        f"{len(outlier_findings)} vendor"
                        f"{'s have' if len(outlier_findings) != 1 else ' has'} "
                        f"spend more than {t_outlier_std}σ above their category mean, "
                        f"indicating potential pricing anomalies, scope creep, or unapproved "
                        f"spend expansion. Each warrants a manual audit to confirm the spend "
                        f"is legitimate and properly approved. "
                        f"Top outliers: {top_names}."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "outlier_count": len(outlier_findings),
                        "std_dev_threshold": t_outlier_std,
                        "min_vendors_for_stats": t_min_vendors,
                        "outliers": top_outliers,
                    },
                    recommended_action=(
                        "Pull invoices and contracts for each outlier vendor and verify "
                        "that spend is within contracted scope. "
                        "Check for unauthorized statement-of-work expansions or usage overruns. "
                        "Flag for CFO review any outlier above $50k with no documented "
                        "business justification."
                    ),
                ))

            # ── Finding 2: High-spend vendors requiring audit ──────────────
            if high_spend_vendors:
                total_high_spend = sum(
                    (v.get("annual_spend") or 0) for v in high_spend_vendors
                )
                top_hs = sorted(
                    high_spend_vendors, key=lambda v: -(v.get("annual_spend") or 0)
                )[:5]
                names = ", ".join(
                    f"{v.get('name')} (${v.get('annual_spend') or 0:,.0f}/yr, {v.get('category')})"
                    for v in top_hs
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(high_spend_vendors)} vendor"
                        f"{'s' if len(high_spend_vendors) != 1 else ''} above "
                        f"${t_high_spend:,.0f}/yr require formal audit approval"
                    ),
                    detail=(
                        f"{len(high_spend_vendors)} vendor"
                        f"{'s exceed' if len(high_spend_vendors) != 1 else ' exceeds'} "
                        f"${t_high_spend:,.0f}/yr "
                        f"(${total_high_spend:,.0f} combined). "
                        f"Vendors at this spend level should have a signed contract, an assigned "
                        f"business owner, formal procurement approval, and documented renewal dates. "
                        f"Without these controls, spend is effectively unmanaged. "
                        f"Examples: {names}."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "high_spend_count": len(high_spend_vendors),
                        "total_high_spend": round(total_high_spend),
                        "audit_threshold": t_high_spend,
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "category": v.get("category"),
                                "annual_spend": v.get("annual_spend"),
                                "payment_terms": v.get("payment_terms"),
                            }
                            for v in top_hs
                        ],
                    },
                    recommended_action=(
                        "For each vendor above the audit threshold, confirm: "
                        "(1) signed contract on file, "
                        "(2) named business owner, "
                        "(3) formal procurement approval on record, "
                        "(4) renewal date documented. "
                        "Any missing item should be remediated before next quarter-close."
                    ),
                ))

            # ── Finding 3: Category spend vs. benchmark ────────────────────
            if employee_count > 0:
                benchmark_exceedances: list[dict] = []
                for benchmark_cat, benchmark_per_head in CATEGORY_BENCHMARK.items():
                    cat_vendors = category_map.get(benchmark_cat, [])
                    if not cat_vendors:
                        continue
                    cat_total = sum((v.get("annual_spend") or 0) for v in cat_vendors)
                    actual_per_head = cat_total / employee_count
                    if actual_per_head > benchmark_per_head:
                        benchmark_exceedances.append({
                            "category": benchmark_cat,
                            "total_category_spend": round(cat_total),
                            "actual_per_head": round(actual_per_head),
                            "benchmark_per_head": benchmark_per_head,
                            "overspend_per_head": round(actual_per_head - benchmark_per_head),
                            "total_overspend": round(
                                (actual_per_head - benchmark_per_head) * employee_count
                            ),
                            "pct_above_benchmark": round(
                                (actual_per_head / benchmark_per_head - 1) * 100, 1
                            ),
                        })

                if benchmark_exceedances:
                    total_benchmark_overspend = sum(
                        e["total_overspend"] for e in benchmark_exceedances
                    )
                    top_exc = sorted(
                        benchmark_exceedances, key=lambda e: -e["total_overspend"]
                    )
                    summary = "; ".join(
                        f"{e['category']} (${e['actual_per_head']:,.0f}/head vs. "
                        f"${e['benchmark_per_head']:,.0f} benchmark, "
                        f"{e['pct_above_benchmark']}% over)"
                        for e in top_exc[:3]
                    )
                    result.findings.append(Finding(
                        title=(
                            f"{len(benchmark_exceedances)} categor"
                            f"{'ies' if len(benchmark_exceedances) != 1 else 'y'} "
                            f"exceed per-employee spend benchmark "
                            f"— ~${total_benchmark_overspend:,.0f} overspend"
                        ),
                        detail=(
                            f"{len(benchmark_exceedances)} spend categor"
                            f"{'ies exceed' if len(benchmark_exceedances) != 1 else 'y exceeds'} "
                            f"industry per-employee benchmarks based on {employee_count} active "
                            f"employees. "
                            f"Overspend categories: {summary}. "
                            f"Total estimated overspend vs. benchmarks: ~${total_benchmark_overspend:,.0f}/yr."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "employee_count": employee_count,
                            "exceedance_count": len(benchmark_exceedances),
                            "total_estimated_overspend": total_benchmark_overspend,
                            "exceedances": benchmark_exceedances,
                            "benchmarks_used": CATEGORY_BENCHMARK,
                        },
                        recommended_action=(
                            "Review vendor contracts in each over-benchmark category. "
                            "Benchmark data should be the opening position in the next "
                            "vendor negotiation — 'our peers spend $X/head; we need to "
                            "reach that level by renewal.' "
                            "Engage a procurement specialist for any category >30% over benchmark."
                        ),
                    ))

            # ── Finding 4: Vendors with zero or missing spend data ─────────
            if vendors_missing_spend:
                names = ", ".join(
                    v.get("name") for v in vendors_missing_spend[:6]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(vendors_missing_spend)} vendor"
                        f"{'s' if len(vendors_missing_spend) != 1 else ''} "
                        f"with no spend data — audit blind spot"
                    ),
                    detail=(
                        f"{len(vendors_missing_spend)} vendor record"
                        f"{'s have' if len(vendors_missing_spend) != 1 else ' has'} "
                        f"zero or missing annual_spend. "
                        f"These vendors exist in the system but their costs are invisible — "
                        f"they cannot be included in AP analysis, outlier detection, "
                        f"or benchmark comparisons. "
                        f"How can you control what you can't see? "
                        f"Examples: {names}."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "missing_spend_count": len(vendors_missing_spend),
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "category": v.get("category"),
                                "payment_terms": v.get("payment_terms"),
                            }
                            for v in vendors_missing_spend
                        ],
                    },
                    recommended_action=(
                        "Pull invoices or contracts for every vendor with missing spend data "
                        "and record the annual spend in the vendor management system. "
                        "If any of these vendors has zero actual spend, consider archiving "
                        "the vendor record to reduce AP overhead. "
                        "This data quality fix unlocks more accurate future audits."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"ExpenseAuditWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Query helpers ───────────────────────────────────────────────────────

    def _get_vendors(self, tenant_id: str) -> list[dict]:
        """
        Fetch all Vendor nodes with spend, category, and payment terms.
        """
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id})
        RETURN v.name          AS name,
               v.category      AS category,
               v.annual_spend  AS annual_spend,
               v.payment_terms AS payment_terms
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_employee_count(self, tenant_id: str) -> int:
        """
        Count active Person nodes for per-employee benchmark calculations.
        Returns 0 if no data is found.
        """
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
        RETURN count(p) AS cnt
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            record = result.single()
            return int(record["cnt"]) if record else 0
