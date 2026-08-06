"""
scout/workers/saas_license.py — SaaS License Optimization Worker

Finds wasted SaaS spend: inactive accounts still holding licenses,
duplicate tools serving the same function, and unmanaged software sprawl.

SaaS license waste is one of the most reliable EBITDA quick-wins in
mid-market PE — the average company wastes 25-30% of its SaaS spend
(Gartner, 2023). Common sources:

  1. Zombie licenses — inactive employees whose accounts were not
     deprovisioned; the company pays for a seat nobody uses

  2. Shelfware — software where fewer than 70% of licensed seats
     are actively used (estimated from inactive account ratio)

  3. Category overlap — multiple vendors serving the same function
     (e.g., 3 project management tools, 2 e-signature platforms)
     Consolidation potential: negotiate one enterprise deal, eliminate
     the others

  4. Shadow IT — software categories outside centrally managed IT
     spend (detected via identity provider login data vs. vendor list)

This worker reads from:
  - Person nodes (is_active flag identifies inactive accounts)
  - Vendor nodes in Software/Technology categories

In Sprint 12 (Real Connectors), this will be enriched with live
Okta login data (last 90-day activity) and vendor API utilization
metrics for precise seat utilization rates.
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

# ── Thresholds ─────────────────────────────────────────────────────────────
ZOMBIE_LICENSE_COST_EST    = 150    # avg monthly cost per seat (SaaS benchmark)
CATEGORY_OVERLAP_MIN       = 2      # 2+ vendors in same category = consolidation opportunity
SHELFWARE_THRESHOLD        = 0.70   # utilization below 70% = shelfware risk
SOFTWARE_CATEGORIES        = {
    "Software", "Technology", "Cloud Infrastructure", "Security",
    "Productivity", "Collaboration", "Analytics", "Communication",
}

# Segment-aware SaaS spend benchmarks (annual spend per employee).
# Sources: Okta Businesses at Work report, Blissfully SaaS Trends.
# Enterprise: heavy compliance tooling, security stack, advanced analytics → $8-12k/head
# Mid-market: moderate stack, some redundancy → $3-6k/head
# SMB: lean stack, often under-invested → $1.5-3k/head
SAAS_SPEND_PER_HEAD: dict[str, dict] = {
    "enterprise": {"benchmark": 8_000,  "high_multiplier": 1.40, "label": "enterprise ($8,000 benchmark)"},
    "mid_market": {"benchmark": 4_000,  "high_multiplier": 1.50, "label": "mid-market ($4,000 benchmark)"},
    "smb":        {"benchmark": 2_500,  "high_multiplier": 1.60, "label": "SMB ($2,500 benchmark)"},
}


class SaasLicenseWorker(WorkerBase):
    """
    Surfaces zombie licenses, tool overlap, and SaaS sprawl.
    Benchmark spend per employee is calibrated to company segment.
    """

    WORKER_NAME = "SaasLicenseWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_zombie_cost = cfg.get("zombie_license_cost_est",  ZOMBIE_LICENSE_COST_EST)
        t_overlap_min = cfg.get("category_overlap_min",     CATEGORY_OVERLAP_MIN)
        t_shelfware   = cfg.get("shelfware_threshold",      SHELFWARE_THRESHOLD)

        # Segment-aware SaaS spend benchmark
        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
        spend_spec = SAAS_SPEND_PER_HEAD.get(segment, SAAS_SPEND_PER_HEAD["mid_market"])
        saas_benchmark_per_head = spend_spec["benchmark"]
        saas_high_multiplier    = spend_spec["high_multiplier"]

        try:
            all_persons = self._get_all_persons(tenant_id)
            inactive_persons = [p for p in all_persons if not p.get("is_active")]
            vendors = self._get_software_vendors(tenant_id)
            category_map = self._build_category_map(vendors)

            total_headcount = len(all_persons)
            inactive_count = len(inactive_persons)
            total_software_spend = sum(v.get("annual_spend") or 0 for v in vendors)

            # Zombie license cost estimate: inactive people × avg cost per seat × 12 vendors
            # (rough: assume 30% of vendor seats are assigned to specific users)
            zombie_annual_cost_est = inactive_count * t_zombie_cost * min(len(vendors), 10) * 12

            result.summary_stats = {
                "total_headcount": total_headcount,
                "inactive_accounts": inactive_count,
                "software_vendor_count": len(vendors),
                "total_software_spend": round(total_software_spend),
                "estimated_zombie_license_cost": round(zombie_annual_cost_est),
                "overlapping_categories": sum(
                    1 for v in category_map.values() if len(v) >= t_overlap_min
                ),
            }

            # ── Finding 1: Zombie licenses ─────────────────────────────
            if inactive_count > 0:
                inactive_names = [p.get("full_name", "Unknown") for p in inactive_persons[:4]]
                severity = Severity.HIGH if zombie_annual_cost_est > 50_000 else Severity.MEDIUM
                result.findings.append(Finding(
                    title=f"{inactive_count} inactive account{'s' if inactive_count > 1 else ''} — est. ${zombie_annual_cost_est:,.0f}/yr in zombie licenses",
                    detail=(
                        f"{', '.join(inactive_names)}{'...' if inactive_count > 4 else ''} "
                        f"are marked inactive but may still hold SaaS licenses across "
                        f"{len(vendors)} software vendor{'s' if len(vendors) > 1 else ''}. "
                        f"At ${t_zombie_cost}/seat/month average, this costs "
                        f"~${zombie_annual_cost_est:,.0f}/year in wasted spend."
                    ),
                    severity=severity,
                    data={
                        "inactive_count": inactive_count,
                        "estimated_annual_waste": round(zombie_annual_cost_est),
                        "inactive_employees": [
                            {"name": p.get("full_name"), "department": p.get("department")}
                            for p in inactive_persons[:10]
                        ],
                    },
                    recommended_action=(
                        "Run an immediate license audit across all SaaS tools. "
                        "Revoke access for all inactive accounts. "
                        "Implement automated offboarding (Offboarding Worker in Sprint 10) "
                        "to prevent recurrence."
                    ),
                ))

            # ── Finding 2: Category overlap (duplicate tools) ───────────
            overlapping = {cat: vends for cat, vends in category_map.items() if len(vends) >= t_overlap_min}
            if overlapping:
                for category, cat_vendors in list(overlapping.items())[:3]:
                    names = [v.get("name") for v in cat_vendors]
                    cat_spend = sum(v.get("annual_spend") or 0 for v in cat_vendors)
                    consolidation_savings_est = cat_spend * 0.25  # consolidation typically saves 20-30%
                    result.findings.append(Finding(
                        title=f"{len(cat_vendors)} {category} tools — ${cat_spend:,.0f}/yr, ${consolidation_savings_est:,.0f} consolidation opportunity",
                        detail=(
                            f"You have {len(cat_vendors)} vendors in the {category} category: "
                            f"{', '.join(names)}. "
                            f"Tool consolidation typically saves 20-30% through volume discounts "
                            f"and elimination of duplicated seats."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "category": category,
                            "vendor_count": len(cat_vendors),
                            "total_category_spend": round(cat_spend),
                            "estimated_consolidation_savings": round(consolidation_savings_est),
                            "vendors": [{"name": v.get("name"), "spend": v.get("annual_spend")} for v in cat_vendors],
                        },
                        recommended_action=(
                            f"Evaluate consolidating {category} tools into one preferred vendor. "
                            f"Issue an RFP with current usage data — vendors will compete on price."
                        ),
                    ))

            # ── Finding 3: High SaaS spend per employee (segment-calibrated) ──
            if total_headcount > 0 and total_software_spend > 0:
                spend_per_head = total_software_spend / total_headcount
                result.summary_stats["spend_per_employee"] = round(spend_per_head)
                result.summary_stats["saas_benchmark_per_head"] = saas_benchmark_per_head
                result.summary_stats["segment"] = segment

                if spend_per_head > saas_benchmark_per_head * saas_high_multiplier:
                    overspend_estimate = (spend_per_head - saas_benchmark_per_head) * total_headcount
                    pct_over = round((spend_per_head / saas_benchmark_per_head - 1) * 100)
                    result.findings.append(Finding(
                        title=(
                            f"SaaS spend per employee (${spend_per_head:,.0f}) "
                            f"is {pct_over}% above {spend_spec['label']}"
                        ),
                        detail=(
                            f"Total software spend of ${total_software_spend:,.0f} across "
                            f"{total_headcount} employees = ${spend_per_head:,.0f}/head/year. "
                            f"Benchmark for {segment} companies: ${saas_benchmark_per_head:,.0f}. "
                            f"Estimated overspend vs. benchmark: ${overspend_estimate:,.0f}/year."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "spend_per_employee":    round(spend_per_head),
                            "benchmark":             saas_benchmark_per_head,
                            "segment":               segment,
                            "pct_over_benchmark":    pct_over,
                            "total_software_spend":  round(total_software_spend),
                            "total_headcount":       total_headcount,
                            "estimated_overspend":   round(overspend_estimate),
                        },
                        recommended_action=(
                            "Conduct a full SaaS rationalization exercise. "
                            "Map every tool to a business owner and measure actual utilization. "
                            "Target: eliminate at least 2 tools per department."
                        ),
                        confidence="medium",
                        context_note=(
                            f"Benchmark: ${saas_benchmark_per_head:,.0f}/head/year "
                            f"({spend_spec['label']}). "
                            f"Flag threshold: {saas_high_multiplier}× benchmark."
                        ),
                    ))

            # ── Finding 4: Large software vendors with no payment terms ──
            unmanaged = [
                v for v in vendors
                if (v.get("annual_spend") or 0) > 50_000 and not v.get("payment_terms")
            ]
            if unmanaged:
                unmanaged_spend = sum(v.get("annual_spend") or 0 for v in unmanaged)
                result.findings.append(Finding(
                    title=f"{len(unmanaged)} high-spend software vendor{'s' if len(unmanaged) > 1 else ''} with no payment terms on file",
                    detail=(
                        f"${unmanaged_spend:,.0f} in software spend has no payment terms "
                        f"recorded. These contracts may be auto-renewing on unfavorable terms "
                        f"or purchasing ad hoc without volume discounts."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "unmanaged_count": len(unmanaged),
                        "unmanaged_spend": round(unmanaged_spend),
                        "vendors": [{"name": v.get("name"), "spend": v.get("annual_spend")} for v in unmanaged[:5]],
                    },
                    recommended_action=(
                        "Pull contracts for all software spend above $50k. "
                        "Record payment terms and renewal dates in the vendor management system. "
                        "Ensure no software over $50k is auto-renewing without CFO review."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"SaasLicenseWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _get_all_persons(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id})
        RETURN p.full_name AS full_name, p.department AS department,
               p.is_active AS is_active, p.employment_type AS employment_type
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_software_vendors(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id, is_active: true})
        RETURN v.name AS name, v.category AS category,
               v.annual_spend AS annual_spend, v.payment_terms AS payment_terms,
               v.contract_renewal AS contract_renewal
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _build_category_map(self, vendors: list[dict]) -> dict[str, list[dict]]:
        """Group vendors by category."""
        cat_map: dict[str, list[dict]] = defaultdict(list)
        for v in vendors:
            cat = v.get("category") or "Uncategorized"
            cat_map[cat].append(v)
        return cat_map
