"""
scout/workers/vendor.py — Vendor Intelligence Worker.

Analyses the vendor/contract side of the digital twin:
  - Renewal urgency (contracts expiring soon)
  - Spend concentration (too much with one vendor = negotiation leverage lost)
  - Category consolidation (5 vendors doing the same thing = duplication)
  - Inactive vendor spend (paying for tools nobody uses)
  - Total spend benchmarking

This is the "CFO intelligence" layer that transforms raw NetSuite data
into PE-relevant findings about vendor costs and contract risk.

Rule of 40 connection:
  Vendor spend is SaaS subscriptions, professional services, cloud infra.
  In PE-backed mid-market companies, 15-25% of revenue goes to vendors.
  A $5M ARR company spending $1.5M on vendors has enormous consolidation
  potential — often $200-500k of savings in year 1 post-acquisition.
  This worker surfaces those savings opportunities.
"""

import logging
from datetime import date, datetime

from scout.data.vendor_intelligence import lookup_vendor
from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# Thresholds are managed in threshold_registry.py (VendorWorker)


class VendorWorker(WorkerBase):
    """
    Analyses vendor spend and contract risk from the digital twin.
    All data comes from :Vendor nodes in Neo4j.
    """

    WORKER_NAME = "VendorWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        try:
            self._analyse(tenant_id, result)
        except Exception as exc:
            logger.error(f"VendorWorker failed for {tenant_id}: {exc}", exc_info=True)
            result.error = str(exc)
        return result

    def _analyse(self, tenant_id: str, result: WorkerResult) -> None:
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        with self.driver.session() as session:
            self._spend_summary(session, tenant_id, result)
            self._renewal_urgency(session, tenant_id, result, cfg)
            self._spend_concentration(session, tenant_id, result, cfg)
            self._category_consolidation(session, tenant_id, result, cfg)
        # Additive catalog enrichment — appends metadata to existing findings
        self._enrich_with_catalog(result.findings)

    # ── Analysis methods ───────────────────────────────────────────────────────

    def _spend_summary(self, session, tenant_id: str, result: WorkerResult) -> None:
        """Total vendor spend and vendor count."""
        row = session.run("""
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            RETURN
                count(v) AS vendor_count,
                sum(v.annual_spend) AS total_annual_spend,
                avg(v.annual_spend) AS avg_spend,
                max(v.annual_spend) AS max_spend
        """, tid=tenant_id).single()

        if not row or row["vendor_count"] == 0:
            return

        total = row["total_annual_spend"] or 0.0
        count = row["vendor_count"]
        avg = round(row["avg_spend"] or 0.0, 0)
        result.summary_stats["active_vendor_count"] = count
        result.summary_stats["total_annual_vendor_spend"] = round(total, 0)
        result.summary_stats["avg_vendor_spend"] = avg
        result.summary_stats["largest_vendor_spend"] = round(row["max_spend"] or 0.0, 0)

        result.findings.append(Finding(
            title=f"Total vendor spend: ${total:,.0f}/year across {count} vendors",
            detail=(
                f"Average contract size: ${avg:,.0f}/year. "
                f"Largest single vendor: ${row['max_spend']:,.0f}/year."
            ),
            severity=Severity.INFO,
            data=dict(row),
        ))

    def _renewal_urgency(self, session, tenant_id: str, result: WorkerResult, cfg: ThresholdConfig) -> None:
        """Find contracts expiring soon — categorised by urgency."""
        rows = session.run("""
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            WHERE v.contract_renewal IS NOT NULL
            WITH v,
                 date(v.contract_renewal) AS renewal_date,
                 date() AS today
            WITH v, renewal_date, today,
                 duration.inDays(today, renewal_date).days AS days_until
            WHERE days_until >= 0
            RETURN
                v.name AS vendor,
                v.annual_spend AS spend,
                toString(renewal_date) AS renewal_date,
                days_until
            ORDER BY days_until ASC
        """, tid=tenant_id).data()

        if not rows:
            return

        renewal_critical_days = cfg.get("renewal_critical_days")
        renewal_high_days = cfg.get("renewal_high_days")
        renewal_medium_days = cfg.get("renewal_medium_days")
        critical = [r for r in rows if r["days_until"] <= renewal_critical_days]
        high = [r for r in rows if renewal_critical_days < r["days_until"] <= renewal_high_days]
        medium = [r for r in rows if renewal_high_days < r["days_until"] <= renewal_medium_days]

        result.summary_stats["renewals_in_30_days"] = len(critical)
        result.summary_stats["renewals_in_90_days"] = len(critical) + len(high)
        result.summary_stats["renewals_in_180_days"] = len(critical) + len(high) + len(medium)

        if critical:
            total_at_risk = sum(r["spend"] or 0 for r in critical)
            vendors = ", ".join(
                f"{r['vendor']} ({r['days_until']}d, ${r['spend']:,.0f})"
                for r in critical
            )
            result.findings.append(Finding(
                title=f"URGENT: {len(critical)} contract(s) renewing in <{renewal_critical_days} days",
                detail=(
                    f"{vendors}. Total at risk: ${total_at_risk:,.0f}/year. "
                    f"Auto-renewal without negotiation typically locks you in "
                    f"at list price for another full term."
                ),
                severity=Severity.CRITICAL,
                data={"critical_renewals": critical, "total_at_risk": total_at_risk},
                recommended_action=(
                    "Contact vendor immediately. "
                    "Request multi-year discount (15-30% typical) or evaluate alternatives. "
                    "Send cancellation notice if unsure — you can reinstate after negotiation."
                ),
            ))

        if high:
            total_at_risk = sum(r["spend"] or 0 for r in high)
            vendors = ", ".join(f"{r['vendor']} ({r['days_until']}d)" for r in high)
            result.findings.append(Finding(
                title=f"{len(high)} contract(s) renewing in 30–90 days: start negotiation now",
                detail=(
                    f"{vendors}. Total: ${total_at_risk:,.0f}/year. "
                    f"90 days is the minimum lead time for meaningful vendor negotiations."
                ),
                severity=Severity.HIGH,
                data={"high_renewals": high, "total_at_risk": total_at_risk},
                recommended_action=(
                    "Schedule vendor reviews. Benchmark pricing vs. alternatives. "
                    "Prepare consolidation case if applicable."
                ),
            ))

        if medium:
            total = sum(r["spend"] or 0 for r in medium)
            result.findings.append(Finding(
                title=f"{len(medium)} contract(s) renewing in 90–180 days (${total:,.0f})",
                detail=(
                    f"Upcoming renewals worth ${total:,.0f}/year. "
                    f"Enough lead time to evaluate, benchmark, and negotiate."
                ),
                severity=Severity.MEDIUM,
                data={"medium_renewals": medium, "total": total},
                recommended_action="Add renewal reviews to CFO calendar.",
            ))

    def _spend_concentration(self, session, tenant_id: str, result: WorkerResult, cfg: ThresholdConfig) -> None:
        """
        Flag if a single vendor represents too large a share of total spend.
        High concentration = negotiation leverage lost + business continuity risk.
        """
        rows = session.run("""
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            WITH sum(v.annual_spend) AS total_spend
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            WITH v, total_spend,
                 round(v.annual_spend / total_spend * 100, 1) AS pct
            WHERE pct >= $threshold
            RETURN v.name AS vendor, v.annual_spend AS spend,
                   v.category AS category, pct
            ORDER BY pct DESC
        """, tid=tenant_id, threshold=cfg.get("spend_concentration_pct")).data()

        if rows:
            for r in rows:
                result.findings.append(Finding(
                    title=(
                        f"Spend concentration: {r['vendor']} = "
                        f"{r['pct']}% of total vendor budget"
                    ),
                    detail=(
                        f"{r['vendor']} ({r['category']}) represents ${r['spend']:,.0f}/year "
                        f"— {r['pct']}% of total vendor spend. "
                        f"This concentration limits negotiation leverage and "
                        f"creates business continuity risk."
                    ),
                    severity=Severity.HIGH,
                    data=r,
                    recommended_action=(
                        f"Evaluate alternative vendors for {r['category']}. "
                        f"Use competitive bids to drive pricing down at renewal. "
                        f"Ensure contract has standard termination-for-convenience clause."
                    ),
                ))

    def _enrich_with_catalog(self, findings: list) -> None:
        """
        Additive enrichment — for each finding that mentions a vendor name,
        append catalog metadata (alternatives, negotiation_leverage tips) to
        the finding's data dict. Does not modify any other field.
        """
        for finding in findings:
            vendor_name = finding.data.get("vendor") or finding.data.get("name")
            if not vendor_name:
                continue
            catalog = lookup_vendor(str(vendor_name))
            if catalog:
                finding.data["catalog_alternatives"] = catalog.get("alternatives", [])
                finding.data["catalog_negotiation_tips"] = catalog.get(
                    "negotiation_leverage", []
                )
                finding.data["catalog_typical_discount_pct"] = catalog.get(
                    "typical_discount_pct"
                )

    def _category_consolidation(self, session, tenant_id: str, result: WorkerResult, cfg: ThresholdConfig) -> None:
        """
        Find categories where we have too many vendors doing the same thing.
        Classic PE value-creation lever: consolidate 5 point solutions → 1 platform.
        """
        rows = session.run("""
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            WHERE v.category IS NOT NULL
            WITH v.category AS category,
                 count(v) AS vendor_count,
                 sum(v.annual_spend) AS category_spend,
                 collect(v.name) AS vendors
            WHERE vendor_count >= $min_vendors
            RETURN category, vendor_count, category_spend, vendors
            ORDER BY vendor_count DESC, category_spend DESC
        """, tid=tenant_id, min_vendors=cfg.get("consolidation_min_vendors")).data()

        if rows:
            for r in rows:
                vendor_list = ", ".join(r["vendors"])
                result.findings.append(Finding(
                    title=(
                        f"Consolidation opportunity: {r['vendor_count']} vendors "
                        f"in '{r['category']}' (${r['category_spend']:,.0f}/yr)"
                    ),
                    detail=(
                        f"Vendors: {vendor_list}. "
                        f"Multiple vendors in the same category often indicates "
                        f"shadow IT, departmental silos, or legacy contracts. "
                        f"Consolidation typically saves 20-40% in the category."
                    ),
                    severity=Severity.MEDIUM,
                    data=r,
                    recommended_action=(
                        f"Review all {r['category']} vendors for feature overlap. "
                        f"Issue RFP for a consolidated platform. "
                        f"Target: 1-2 vendors in this category, not {r['vendor_count']}."
                    ),
                ))
