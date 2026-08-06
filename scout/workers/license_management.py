"""
scout/workers/license_management.py — SaaS License Lifecycle Management Worker

Manages the SaaS license lifecycle: identifies zombie licenses (vendors with
spend but likely unused), upcoming contract renewals that need attention,
license cost benchmarks, and over-licensed categories.

Complements SaasLicenseWorker (Sprint 5) which focused on spend-per-head and
zombie detection. This worker focuses on lifecycle events and renewal planning:
what is expiring, when, at what cost, and what negotiation strategy applies.

The renewal window is where most SaaS savings are captured — or lost. A vendor
with a contract expiring in 30 days has maximum leverage; a vendor auto-renewing
tomorrow with no prepared alternative has maximum leverage over you. Identifying
the renewal calendar 90 days in advance and preparing negotiation strategies
(multi-year commit discounts, competitive alternatives, volume pricing) is the
difference between a 15% price increase and a 15% price decrease.

Data source: Vendor nodes in Neo4j. No live vendor API calls are made here.
"""

import logging
from collections import defaultdict
from datetime import date, datetime

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
RENEWAL_WARNING_DAYS  = 90    # contracts ending within 90 days need attention
RENEWAL_CRITICAL_DAYS = 30    # contracts ending within 30 days = urgent
HIGH_SPEND_LICENSE    = 50_000  # annual spend above this warrants negotiation
ZOMBIE_MONTHLY_COST   = 150   # estimated cost per unused license/month

# Multi-year commit discount assumption: 15% savings on 2-year commit
MULTI_YEAR_DISCOUNT = 0.15
OVERLAP_VENDOR_MIN   = 3      # 3+ vendors in same category = overlap concern


class LicenseManagementWorker(WorkerBase):
    """
    Surfaces contract renewal urgency, high-spend negotiation targets,
    category overlap, and lifecycle optimization savings from Vendor nodes.
    """

    WORKER_NAME = "LicenseManagementWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_warn_days  = cfg.get("renewal_warning_days",  RENEWAL_WARNING_DAYS)
        t_crit_days  = cfg.get("renewal_critical_days", RENEWAL_CRITICAL_DAYS)
        t_high_spend = cfg.get("high_spend_license",    HIGH_SPEND_LICENSE)
        t_zombie_cost = cfg.get("zombie_monthly_cost",  ZOMBIE_MONTHLY_COST)
        t_overlap_min = cfg.get("overlap_vendor_min",   OVERLAP_VENDOR_MIN)

        try:
            vendors = self._get_vendors(tenant_id)
            today = date.today()

            if not vendors:
                result.findings.append(Finding(
                    title="No vendor data found — run a procurement or ERP scan first",
                    detail=(
                        "LicenseManagementWorker requires Vendor nodes in the graph. "
                        "Connect a procurement or ERP connector and run a scan."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action=(
                        "Enable a vendor data connector (NetSuite, QuickBooks, or a manual "
                        "CSV upload) and trigger a scan to populate Vendor nodes."
                    ),
                ))
                result.summary_stats = {
                    "total_licenses": 0,
                    "critical_renewals": 0,
                    "upcoming_renewals": 0,
                    "total_renewal_spend": 0,
                    "high_spend_count": 0,
                    "potential_savings_multi_year": 0,
                }
                return result

            # ── Parse renewal dates ────────────────────────────────────────
            # Each vendor gets a parsed_days_to_renewal: int | None
            enriched: list[dict] = []
            for v in vendors:
                days_to_renewal = self._days_to_renewal(v.get("contract_end_date"), today)
                enriched.append({**v, "days_to_renewal": days_to_renewal})

            critical_renewals = [
                v for v in enriched
                if v["days_to_renewal"] is not None
                and 0 <= v["days_to_renewal"] <= t_crit_days
            ]
            upcoming_renewals = [
                v for v in enriched
                if v["days_to_renewal"] is not None
                and t_crit_days < v["days_to_renewal"] <= t_warn_days
            ]
            high_spend_vendors = [
                v for v in enriched
                if (v.get("annual_spend") or 0) > t_high_spend
            ]

            total_renewal_spend = sum(
                (v.get("annual_spend") or 0)
                for v in critical_renewals + upcoming_renewals
            )

            # Potential savings: multi-year commit on all renewal-window vendors
            potential_savings = round(total_renewal_spend * MULTI_YEAR_DISCOUNT)

            # Category overlap
            category_map: dict[str, list[dict]] = defaultdict(list)
            for v in enriched:
                cat = v.get("category") or "Uncategorized"
                category_map[cat].append(v)
            overlapping_categories = {
                cat: vlist
                for cat, vlist in category_map.items()
                if len(vlist) >= t_overlap_min
            }

            result.summary_stats = {
                "total_licenses": len(vendors),
                "critical_renewals": len(critical_renewals),
                "upcoming_renewals": len(upcoming_renewals),
                "total_renewal_spend": round(total_renewal_spend),
                "high_spend_count": len(high_spend_vendors),
                "potential_savings_multi_year": potential_savings,
            }

            # ── Finding 1: Critical renewal window (≤30 days) ─────────────
            if critical_renewals:
                top_critical = sorted(
                    critical_renewals, key=lambda v: v["days_to_renewal"]
                )
                top_names = ", ".join(
                    f"{v.get('name')} ({v['days_to_renewal']}d, ${v.get('annual_spend') or 0:,.0f}/yr)"
                    for v in top_critical[:4]
                )
                critical_spend = sum((v.get("annual_spend") or 0) for v in critical_renewals)
                result.findings.append(Finding(
                    title=(
                        f"CRITICAL: {len(critical_renewals)} contract"
                        f"{'s' if len(critical_renewals) != 1 else ''} expiring within "
                        f"{t_crit_days} days — ${critical_spend:,.0f}/yr"
                    ),
                    detail=(
                        f"{len(critical_renewals)} vendor contract"
                        f"{'s expire' if len(critical_renewals) != 1 else ' expires'} "
                        f"within {t_crit_days} days. "
                        f"At this stage, you have minimal negotiating leverage — the vendor knows "
                        f"there is no time to evaluate alternatives. Auto-renewal clauses may "
                        f"already be triggering. "
                        f"Examples: {top_names}."
                    ),
                    severity=Severity.CRITICAL,
                    data={
                        "critical_count": len(critical_renewals),
                        "total_critical_spend": round(critical_spend),
                        "renewal_critical_days": t_crit_days,
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "annual_spend": v.get("annual_spend"),
                                "days_to_renewal": v["days_to_renewal"],
                                "contract_end_date": v.get("contract_end_date"),
                                "category": v.get("category"),
                            }
                            for v in top_critical
                        ],
                    },
                    recommended_action=(
                        "Escalate each critical renewal to the CFO and relevant department head today. "
                        "Contact the vendor within 24 hours to confirm renewal terms and check for "
                        "auto-renewal clauses that may have already triggered. "
                        "Even at this stage, push for a short-term extension (30-60 days) to allow "
                        "proper evaluation — vendors often grant this to protect the relationship."
                    ),
                ))

            # ── Finding 2: Upcoming renewal window (31-90 days) ───────────
            if upcoming_renewals:
                top_upcoming = sorted(
                    upcoming_renewals, key=lambda v: v["days_to_renewal"]
                )
                top_names = ", ".join(
                    f"{v.get('name')} ({v['days_to_renewal']}d, ${v.get('annual_spend') or 0:,.0f}/yr)"
                    for v in top_upcoming[:4]
                )
                upcoming_spend = sum((v.get("annual_spend") or 0) for v in upcoming_renewals)
                result.findings.append(Finding(
                    title=(
                        f"{len(upcoming_renewals)} contract"
                        f"{'s' if len(upcoming_renewals) != 1 else ''} renewing in "
                        f"{t_crit_days + 1}-{t_warn_days} days "
                        f"— ${upcoming_spend:,.0f}/yr"
                    ),
                    detail=(
                        f"{len(upcoming_renewals)} vendor contract"
                        f"{'s renew' if len(upcoming_renewals) != 1 else ' renews'} "
                        f"in the {t_crit_days + 1}-{t_warn_days} day window. "
                        f"This is the optimal negotiation window — enough time to evaluate "
                        f"alternatives and apply competitive pressure, but close enough for "
                        f"vendors to take the renewal seriously. "
                        f"Examples: {top_names}."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "upcoming_count": len(upcoming_renewals),
                        "total_upcoming_spend": round(upcoming_spend),
                        "renewal_warning_days": t_warn_days,
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "annual_spend": v.get("annual_spend"),
                                "days_to_renewal": v["days_to_renewal"],
                                "contract_end_date": v.get("contract_end_date"),
                                "category": v.get("category"),
                                "payment_terms": v.get("payment_terms"),
                            }
                            for v in top_upcoming
                        ],
                    },
                    recommended_action=(
                        "Begin renewal negotiations for all upcoming contracts now. "
                        "Request at least one competitive quote per category to establish "
                        "pricing benchmarks. "
                        "Explore multi-year commits (2-year) for any vendor where the "
                        "relationship is strong — typical savings are 15-20% over annual pricing."
                    ),
                ))

            # ── Finding 3: High-spend licenses needing renewal strategy ────
            if high_spend_vendors:
                no_date_high_spend = [
                    v for v in high_spend_vendors if v["days_to_renewal"] is None
                ]
                total_high_spend = sum(
                    (v.get("annual_spend") or 0) for v in high_spend_vendors
                )
                top_names = ", ".join(
                    f"{v.get('name')} (${v.get('annual_spend') or 0:,.0f}/yr, "
                    f"{'no renewal date' if v['days_to_renewal'] is None else str(v['days_to_renewal']) + 'd'})"
                    for v in sorted(high_spend_vendors, key=lambda v: -(v.get("annual_spend") or 0))[:4]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(high_spend_vendors)} high-spend license"
                        f"{'s' if len(high_spend_vendors) != 1 else ''} "
                        f"(>${t_high_spend:,.0f}/yr) warrant multi-year negotiation strategy"
                    ),
                    detail=(
                        f"{len(high_spend_vendors)} vendor"
                        f"{'s have' if len(high_spend_vendors) != 1 else ' has'} "
                        f"annual spend above ${t_high_spend:,.0f} "
                        f"(total: ${total_high_spend:,.0f}/yr). "
                        f"At this spend level, a structured 2-year commit negotiation "
                        f"typically yields 15-20% savings versus annual pricing. "
                        f"{len(no_date_high_spend)} of these have no contract end date recorded — "
                        f"a data quality risk that must be fixed before renewal season. "
                        f"Examples: {top_names}."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "high_spend_count": len(high_spend_vendors),
                        "total_high_spend": round(total_high_spend),
                        "no_date_count": len(no_date_high_spend),
                        "spend_threshold": t_high_spend,
                        "vendors": [
                            {
                                "name": v.get("name"),
                                "annual_spend": v.get("annual_spend"),
                                "days_to_renewal": v["days_to_renewal"],
                                "category": v.get("category"),
                            }
                            for v in sorted(
                                high_spend_vendors, key=lambda v: -(v.get("annual_spend") or 0)
                            )
                        ],
                    },
                    recommended_action=(
                        "For each high-spend vendor, assign a business owner responsible for "
                        "the renewal negotiation. Document contract end dates for all vendors "
                        "with missing dates this week. "
                        "Prepare a multi-year commit proposal for the top 3 vendors by spend — "
                        "start 6 months before expiry for maximum leverage."
                    ),
                ))

            # ── Finding 4: License category overlap ────────────────────────
            if overlapping_categories:
                for cat, cat_vendors in list(overlapping_categories.items())[:3]:
                    cat_spend = sum((v.get("annual_spend") or 0) for v in cat_vendors)
                    names = ", ".join(v.get("name") for v in cat_vendors)
                    savings_est = round(cat_spend * 0.25)
                    result.findings.append(Finding(
                        title=(
                            f"{len(cat_vendors)} vendors in {cat} category "
                            f"— ${cat_spend:,.0f}/yr, consolidation opportunity"
                        ),
                        detail=(
                            f"You have {len(cat_vendors)} vendors in the {cat} category: "
                            f"{names}. "
                            f"Having {t_overlap_min}+ vendors serving the same function "
                            f"splits negotiating leverage, creates user confusion, and generates "
                            f"redundant AP processing overhead. "
                            f"Consolidating to 1-2 preferred vendors typically saves 20-30% "
                            f"through volume discounts (estimated ~${savings_est:,.0f}/yr)."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "category": cat,
                            "vendor_count": len(cat_vendors),
                            "total_category_spend": round(cat_spend),
                            "estimated_consolidation_savings": savings_est,
                            "vendors": [
                                {
                                    "name": v.get("name"),
                                    "annual_spend": v.get("annual_spend"),
                                    "days_to_renewal": v["days_to_renewal"],
                                    "contract_end_date": v.get("contract_end_date"),
                                }
                                for v in cat_vendors
                            ],
                        },
                        recommended_action=(
                            f"Evaluate consolidating {cat} tools. Align consolidation timing "
                            f"with the nearest contract renewal in this category — "
                            f"consolidation is cheapest when you are already renegotiating. "
                            f"Issue an RFP with current usage data across all {len(cat_vendors)} vendors."
                        ),
                    ))

            # ── Finding 5: Lifecycle optimization summary ──────────────────
            result.findings.append(Finding(
                title=(
                    f"License lifecycle summary: ${total_renewal_spend:,.0f} up for renewal, "
                    f"~${potential_savings:,.0f} potential multi-year savings"
                ),
                detail=(
                    f"${total_renewal_spend:,.0f} of annual spend is in contracts expiring "
                    f"within {t_warn_days} days "
                    f"({len(critical_renewals)} critical, {len(upcoming_renewals)} upcoming). "
                    f"If multi-year commits (2-year) are negotiated for these renewals, "
                    f"estimated savings are ~${potential_savings:,.0f}/yr "
                    f"({MULTI_YEAR_DISCOUNT * 100:.0f}% average discount). "
                    f"This analysis uses contract-level data only — Sprint 12 will add "
                    f"seat utilization data from Okta for precise zombie license detection."
                ),
                severity=Severity.INFO,
                data={
                    "total_renewal_spend": round(total_renewal_spend),
                    "critical_renewal_count": len(critical_renewals),
                    "upcoming_renewal_count": len(upcoming_renewals),
                    "multi_year_discount_assumption": MULTI_YEAR_DISCOUNT,
                    "potential_savings_multi_year": potential_savings,
                    "high_spend_vendor_count": len(high_spend_vendors),
                    "overlapping_category_count": len(overlapping_categories),
                },
                recommended_action=(
                    "Present this renewal calendar to the CFO and IT procurement lead. "
                    "Build a 12-month license renewal calendar with assigned owners for "
                    "each renewal. "
                    "Target: zero auto-renewals above $10k without CFO sign-off."
                ),
            ))

        except Exception as exc:
            logger.exception(f"LicenseManagementWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Query helpers ───────────────────────────────────────────────────────

    def _get_vendors(self, tenant_id: str) -> list[dict]:
        """
        Fetch all Vendor nodes with spend, category, contract date, and terms.
        """
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id})
        RETURN v.name              AS name,
               v.category          AS category,
               v.annual_spend      AS annual_spend,
               v.contract_end_date AS contract_end_date,
               v.payment_terms     AS payment_terms
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _days_to_renewal(self, date_str, today: date) -> int | None:
        """
        Parse a contract_end_date string and return days until that date.

        Returns None if the date is missing, empty, or unparseable.
        Negative values indicate the contract has already expired.
        """
        if not date_str:
            return None
        try:
            end_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
            return (end_date - today).days
        except (ValueError, TypeError):
            return None
