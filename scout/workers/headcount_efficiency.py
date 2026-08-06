"""
scout/workers/headcount_efficiency.py — Headcount Efficiency Worker (Layer 3)

Analyzes the organizational structure for headcount efficiency signals:
G&A ratio, management overhead, contractor concentration, and department
balance. These are among the first things a PE operating partner reviews
in the first 100 days.

Layer 3 upgrade:
  - G&A and management overhead benchmarks are now segment-aware.
    Enterprise companies should be at 15% G&A; SMB companies at 25% is
    normal. The old single benchmark (20%) was flagging small-company G&A
    as a problem when it's structurally expected.
  - Management overhead threshold also varies: enterprise companies
    with mature HR practices typically have 18-22%; early-stage SMB
    companies may have 30%+ because founders are player-coaches.
  - All benchmarks sourced from context_note so the AI memo can explain
    which benchmark applies and why.
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

# ── Department classification sets ────────────────────────────────────────
GA_DEPARTMENTS = {"Finance", "HR", "Human Resources", "Legal", "IT", "Operations", "Admin", "G&A"}
REVENUE_DEPARTMENTS = {"Sales", "Marketing", "Business Development", "Revenue"}
PRODUCT_DEPARTMENTS = {"Engineering", "Product", "Design", "R&D", "Technology"}

# ── Segment-aware benchmarks ───────────────────────────────────────────────
GA_BENCHMARKS: dict[str, dict] = {
    "enterprise": {"benchmark": 0.15, "high": 0.22, "label": "enterprise (target: 15%)"},
    "mid_market": {"benchmark": 0.20, "high": 0.27, "label": "mid-market (target: 20%)"},
    "smb":        {"benchmark": 0.25, "high": 0.35, "label": "SMB (target: 25%)"},
}
MGMT_BENCHMARKS: dict[str, dict] = {
    "enterprise": {"high": 0.25, "label": "enterprise"},
    "mid_market": {"high": 0.28, "label": "mid-market"},
    "smb":        {"high": 0.35, "label": "SMB"},  # founders as player-coaches inflate this
}


class HeadcountEfficiencyWorker(WorkerBase):
    """
    Surfaces G&A bloat, management overhead, contractor risk, and
    department imbalance — with segment-calibrated benchmarks.
    """

    WORKER_NAME = "HeadcountEfficiencyWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        # Segment-aware benchmark selection
        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
        ga_spec   = GA_BENCHMARKS.get(segment,   GA_BENCHMARKS["mid_market"])
        mgmt_spec = MGMT_BENCHMARKS.get(segment, MGMT_BENCHMARKS["mid_market"])

        ga_benchmark = cfg.get("ga_ratio_benchmark", ga_spec["benchmark"])
        ga_high      = cfg.get("ga_ratio_high",       ga_spec["high"])
        mgmt_high    = cfg.get("mgmt_overhead_high",  mgmt_spec["high"])

        context_note = (
            f"Benchmarks calibrated for {ga_spec['label']} segment. "
            f"G&A target: {ga_benchmark*100:.0f}%, flag threshold: {ga_high*100:.0f}%. "
            f"Management overhead flag threshold: {mgmt_high*100:.0f}%."
        )
        result.summary_stats["segment"] = segment

        try:
            persons = self._get_all_persons(tenant_id)
            dept_breakdown = self._get_department_breakdown(tenant_id)
            managers = self._get_managers_with_span(tenant_id)

            if not persons:
                result.findings.append(Finding(
                    title="No headcount data found — run an HCM scan first",
                    detail="HeadcountEfficiencyWorker requires data from Workday, BambooHR, or similar.",
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats.update({"total_headcount": 0})
                return result

            active = [p for p in persons if p.get("is_active")]
            total = len(active)
            contractors = [p for p in active if (p.get("employment_type") or "").lower() in ("contractor", "consultant", "temp")]
            managers_list = [p for p in active if p.get("is_manager")]

            ga_count      = sum(1 for p in active if self._is_ga(p.get("department")))
            revenue_count = sum(1 for p in active if self._is_revenue(p.get("department")))
            product_count = sum(1 for p in active if self._is_product(p.get("department")))

            ga_ratio       = ga_count / total if total > 0 else 0
            contractor_ratio = len(contractors) / total if total > 0 else 0
            mgmt_ratio     = len(managers_list) / total if total > 0 else 0

            result.summary_stats.update({
                "total_headcount":               total,
                "active_headcount":              total,
                "contractor_count":              len(contractors),
                "contractor_pct":                round(contractor_ratio * 100, 1),
                "ga_headcount":                  ga_count,
                "ga_ratio_pct":                  round(ga_ratio * 100, 1),
                "ga_benchmark_pct":              round(ga_benchmark * 100, 1),
                "revenue_generating_headcount":  revenue_count + product_count,
                "manager_count":                 len(managers_list),
                "management_overhead_pct":       round(mgmt_ratio * 100, 1),
            })

            # ── Finding 1: G&A ratio (segment-calibrated) ─────────────
            if ga_ratio > ga_high:
                overstaffed_by = ga_count - int(total * ga_benchmark)
                overage_pp = round((ga_ratio - ga_benchmark) * 100, 1)
                result.findings.append(Finding(
                    title=(
                        f"G&A is {ga_ratio*100:.0f}% of headcount — "
                        f"{overstaffed_by} head{'s' if overstaffed_by != 1 else ''} above "
                        f"{ga_benchmark*100:.0f}% {ga_spec['label']} benchmark"
                    ),
                    detail=(
                        f"{ga_count} of {total} employees are in G&A functions "
                        f"(Finance, HR, Legal, IT, Operations). "
                        f"Segment benchmark ({ga_spec['label']}): {ga_benchmark*100:.0f}%. "
                        f"At benchmark, you'd have ~{int(total * ga_benchmark)} G&A heads — "
                        f"approximately {overstaffed_by} above target. "
                        f"Each excess G&A seat is roughly $80-120k fully-loaded cost."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "ga_headcount":        ga_count,
                        "total_headcount":     total,
                        "ga_ratio_pct":        round(ga_ratio * 100, 1),
                        "benchmark_pct":       round(ga_benchmark * 100, 1),
                        "heads_above_benchmark": overstaffed_by,
                        "segment":             segment,
                        "overage_pp":          overage_pp,
                    },
                    recommended_action=(
                        "Conduct a function-by-function G&A review. "
                        "Identify roles that can be automated (AP processing, expense audit, "
                        "license management) vs. roles requiring headcount reduction or "
                        "attrition management. Target: reach benchmark within 12-18 months."
                    ),
                    confidence="medium",
                    context_note=context_note,
                ))
            elif ga_ratio < 0.08:
                result.findings.append(Finding(
                    title=f"G&A appears understaffed at {ga_ratio*100:.0f}% of headcount",
                    detail=(
                        f"Only {ga_count} G&A employees for {total} total headcount. "
                        f"This may indicate G&A work is being done by revenue-generating "
                        f"employees (hidden cost) or outsourced to expensive consultants."
                    ),
                    severity=Severity.MEDIUM,
                    data={"ga_headcount": ga_count, "total_headcount": total,
                          "ga_ratio_pct": round(ga_ratio * 100, 1)},
                    recommended_action=(
                        "Audit whether G&A work is being absorbed by non-G&A employees. "
                        "Hidden G&A work reduces sales and engineering productivity."
                    ),
                    confidence="medium",
                ))

            # ── Finding 2: Contractor concentration ───────────────────
            if contractor_ratio > cfg.get("contractor_high", 0.20):
                contractor_cost_premium_est = len(contractors) * 20_000
                result.findings.append(Finding(
                    title=(
                        f"{len(contractors)} contractors ({contractor_ratio*100:.0f}% of workforce) "
                        f"— ~${contractor_cost_premium_est:,.0f}/yr premium vs FTE"
                    ),
                    detail=(
                        f"{len(contractors)} contractors represent {contractor_ratio*100:.0f}% of the workforce. "
                        f"Above 20%, this typically indicates permanent work being done at a "
                        f"30-40% cost premium vs converting to FTE. "
                        f"It may also indicate misclassification risk (contractors acting as employees)."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "contractor_count":        len(contractors),
                        "contractor_pct":          round(contractor_ratio * 100, 1),
                        "estimated_cost_premium":  contractor_cost_premium_est,
                    },
                    recommended_action=(
                        "Audit each contractor role: (a) is this truly project-based work "
                        "or permanent? (b) is conversion to FTE cheaper at scale? "
                        "(c) are there any misclassification risks? "
                        "Target: contractors < 15% of workforce."
                    ),
                    confidence="medium",
                ))

            # ── Finding 3: Management overhead (segment-calibrated) ───
            if mgmt_ratio > mgmt_high:
                result.findings.append(Finding(
                    title=(
                        f"Management overhead at {mgmt_ratio*100:.0f}% — above "
                        f"{mgmt_high*100:.0f}% {mgmt_spec['label']} threshold"
                    ),
                    detail=(
                        f"{len(managers_list)} of {total} employees are people managers "
                        f"({mgmt_ratio*100:.0f}%). "
                        f"For a {mgmt_spec['label']} company, above {mgmt_high*100:.0f}% indicates "
                        f"organizational complexity — too many managers means long decision cycles "
                        f"and high overhead cost."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "manager_count":           len(managers_list),
                        "total_headcount":         total,
                        "management_overhead_pct": round(mgmt_ratio * 100, 1),
                        "segment_threshold_pct":   round(mgmt_high * 100, 1),
                        "segment":                 segment,
                    },
                    recommended_action=(
                        "Map the management layers. If any chain exceeds 5 layers from IC to CEO, "
                        "consider collapsing. Promote strong ICs to player-coaches rather than "
                        "pure managers. Target: 18-22% management overhead for mature orgs."
                    ),
                    confidence="medium",
                    context_note=context_note,
                ))

            # ── Finding 4: Department concentration ───────────────────
            for dept_row in dept_breakdown:
                dept = dept_row.get("department") or "Unknown"
                count = dept_row.get("count") or 0
                pct = count / total if total > 0 else 0
                if pct >= cfg.get("dept_imbalance") and count > 5:
                    result.findings.append(Finding(
                        title=f"{dept} is {pct*100:.0f}% of headcount — organizational concentration risk",
                        detail=(
                            f"{count} of {total} employees are in {dept}. "
                            f"Single-department concentration above 40% can indicate "
                            f"functional imbalance — under-investment in other areas "
                            f"or over-indexing that may not match revenue stage."
                        ),
                        severity=Severity.LOW,
                        data={"department": dept, "count": count, "pct_of_total": round(pct * 100, 1)},
                        recommended_action=f"Review whether {dept} headcount matches the company's current growth priorities. Compare to industry benchmarks for this revenue stage.",
                    ))

        except Exception as exc:
            logger.exception(f"HeadcountEfficiencyWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _is_ga(self, dept: str | None) -> bool:
        if not dept:
            return False
        return any(g.lower() in dept.lower() for g in GA_DEPARTMENTS)

    def _is_revenue(self, dept: str | None) -> bool:
        if not dept:
            return False
        return any(r.lower() in dept.lower() for r in REVENUE_DEPARTMENTS)

    def _is_product(self, dept: str | None) -> bool:
        if not dept:
            return False
        return any(p.lower() in dept.lower() for p in PRODUCT_DEPARTMENTS)

    def _get_all_persons(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id})
        OPTIONAL MATCH (p)-[:MANAGES]->(r:Person)
        WITH p, count(r) AS direct_reports
        RETURN
            p.full_name AS full_name,
            p.department AS department,
            p.is_active AS is_active,
            p.employment_type AS employment_type,
            p.job_title AS job_title,
            direct_reports > 0 AS is_manager
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_department_breakdown(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
        WHERE p.department IS NOT NULL
        RETURN p.department AS department, count(p) AS count
        ORDER BY count DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_managers_with_span(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id})-[:MANAGES]->(rep:Person)
        WITH mgr, count(rep) AS direct_reports
        RETURN mgr.full_name AS manager, mgr.department AS department,
               mgr.job_title AS title, direct_reports
        ORDER BY direct_reports DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
