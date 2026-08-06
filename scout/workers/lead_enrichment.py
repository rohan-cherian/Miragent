"""
scout/workers/lead_enrichment.py — Lead Enrichment Worker

Scores every prospect and customer account on data completeness and
enrichment priority. Identifies data gaps that hurt conversion rates
(missing industry, revenue, or headcount data means the ICP score can't
be computed accurately). Generates an enrichment action list prioritized
by account potential. Sprint 12 will connect to Clearbit/ZoomInfo for
automated enrichment.
"""

import logging

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

ENRICHMENT_FIELDS = ["industry", "annual_revenue", "employee_count"]  # fields that power ICP scoring
COMPLETENESS_SCORE_FULL = 100


class LeadEnrichmentWorker(WorkerBase):
    """
    Audits account data completeness across all Customer and Prospect accounts,
    and produces a prioritized enrichment action list with specific field gaps.
    """

    WORKER_NAME = "LeadEnrichmentWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            accounts = self._get_all_accounts(tenant_id)

            if not accounts:
                result.findings.append(Finding(
                    title="No accounts found — enrichment analysis requires Account nodes",
                    detail=(
                        "Import account records into the CRM graph to enable data quality "
                        "and enrichment scoring."
                    ),
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats = {
                    "total_accounts": 0,
                    "complete_accounts": 0,
                    "incomplete_accounts": 0,
                    "completeness_rate_pct": 0,
                    "customer_missing_count": 0,
                    "high_revenue_missing_count": 0,
                }
                return result

            # Annotate each account with completeness data
            annotated = []
            for acct in accounts:
                missing_fields = [
                    f for f in ENRICHMENT_FIELDS if not acct.get(f)
                ]
                missing_count = len(missing_fields)
                completeness_score = COMPLETENESS_SCORE_FULL - (missing_count * cfg.get("missing_field_penalty"))
                annotated.append({
                    **acct,
                    "missing_fields": missing_fields,
                    "missing_count": missing_count,
                    "completeness_score": completeness_score,
                })

            # Sort: customers first, then high revenue, then worst completeness first
            annotated.sort(
                key=lambda a: (
                    0 if a.get("account_type") == "Customer" else 1,
                    -(a.get("annual_revenue") or 0),
                    a["completeness_score"],
                )
            )

            total_accounts = len(annotated)
            complete_accounts = sum(1 for a in annotated if a["missing_count"] == 0)
            incomplete_accounts = total_accounts - complete_accounts
            completeness_rate = round((complete_accounts / total_accounts) * 100) if total_accounts else 0

            customer_missing = [
                a for a in annotated
                if a.get("account_type") == "Customer" and a["missing_count"] > 0
            ]
            high_revenue_missing = [
                a for a in annotated
                if (a.get("annual_revenue") or 0) > cfg.get("high_revenue_threshold") and a["missing_count"] > 0
            ]
            needs_enrichment = [a for a in annotated if a["missing_count"] > 0]

            result.summary_stats = {
                "total_accounts": total_accounts,
                "complete_accounts": complete_accounts,
                "incomplete_accounts": incomplete_accounts,
                "completeness_rate_pct": completeness_rate,
                "customer_missing_count": len(customer_missing),
                "high_revenue_missing_count": len(high_revenue_missing),
            }

            # ── Finding 1: Overall data quality ───────────────────────────
            if completeness_rate < 50:
                quality_severity = Severity.HIGH
                quality_verdict = "Critical data gap"
            elif completeness_rate < 80:
                quality_severity = Severity.MEDIUM
                quality_verdict = "Moderate data gap"
            else:
                quality_severity = Severity.INFO
                quality_verdict = "Good data coverage"

            result.findings.append(Finding(
                title=(
                    f"{quality_verdict} — {completeness_rate}% of accounts have complete enrichment data"
                ),
                detail=(
                    f"Out of {total_accounts} accounts, {complete_accounts} have all three "
                    f"ICP-scoring fields populated (industry, annual revenue, employee count). "
                    f"{incomplete_accounts} accounts are missing at least one field, "
                    f"which degrades ICP scoring accuracy and slows down targeting decisions."
                ),
                severity=quality_severity,
                data={
                    "total_accounts": total_accounts,
                    "complete_accounts": complete_accounts,
                    "incomplete_accounts": incomplete_accounts,
                    "completeness_rate_pct": completeness_rate,
                },
                recommended_action=(
                    "Prioritize enrichment for customer accounts first (cross-sell risk), "
                    "then high-revenue prospects (largest ICP opportunity). "
                    "See the enrichment action list finding for specific accounts and fields."
                ),
            ))

            # ── Finding 2: Customer accounts with missing data ─────────────
            if customer_missing:
                customer_names = [a.get("name") or "Unknown" for a in customer_missing]
                result.findings.append(Finding(
                    title=(
                        f"{len(customer_missing)} customer account{'s' if len(customer_missing) > 1 else ''} "
                        f"missing enrichment data — cross-sell visibility is blind"
                    ),
                    detail=(
                        f"Customer accounts with missing fields: "
                        f"{', '.join(customer_names)}. "
                        f"Without complete data, the ICP score cannot be computed for these accounts, "
                        f"meaning cross-sell and upsell targeting is effectively guesswork. "
                        f"These are your highest-priority enrichment targets."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "customer_missing": [
                            {
                                "name": a.get("name"),
                                "missing_fields": a["missing_fields"],
                                "completeness_score": a["completeness_score"],
                                "annual_revenue": a.get("annual_revenue"),
                            }
                            for a in customer_missing
                        ],
                    },
                    recommended_action=(
                        "Assign a RevOps resource to manually enrich these customer records "
                        "this week — check LinkedIn, company websites, and press releases."
                    ),
                ))

            # ── Finding 3: High-revenue prospects with incomplete data ─────
            if high_revenue_missing:
                rev_names = [a.get("name") or "Unknown" for a in high_revenue_missing]
                result.findings.append(Finding(
                    title=(
                        f"{len(high_revenue_missing)} high-revenue prospect"
                        f"{'s' if len(high_revenue_missing) > 1 else ''} "
                        f"with incomplete data — ICP score blocked"
                    ),
                    detail=(
                        f"Prospects with annual revenue above "
                        f"${cfg.get('high_revenue_threshold'):,.0f} but missing enrichment fields: "
                        f"{', '.join(rev_names)}. "
                        f"These are your largest addressable opportunities — incomplete data "
                        f"means they cannot be ranked accurately against other ICP targets."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "high_revenue_missing": [
                            {
                                "name": a.get("name"),
                                "annual_revenue": a.get("annual_revenue"),
                                "missing_fields": a["missing_fields"],
                                "completeness_score": a["completeness_score"],
                            }
                            for a in high_revenue_missing
                        ],
                        "threshold": cfg.get("high_revenue_threshold"),
                    },
                    recommended_action=(
                        "Pull firmographic data for these accounts from your data provider "
                        "or assign an SDR to research and update the records before the next "
                        "ICP scoring run."
                    ),
                ))

            # ── Finding 4: Full enrichment action list ─────────────────────
            if needs_enrichment:
                action_list = [
                    {
                        "name": a.get("name"),
                        "account_type": a.get("account_type"),
                        "missing_fields": a["missing_fields"],
                        "completeness_score": a["completeness_score"],
                        "annual_revenue": a.get("annual_revenue"),
                    }
                    for a in needs_enrichment
                ]
                result.findings.append(Finding(
                    title=f"Enrichment action list — {len(needs_enrichment)} accounts need data updates",
                    detail=(
                        f"Full list of accounts requiring enrichment, sorted by priority "
                        f"(customers first, then high-revenue prospects, then worst completeness). "
                        f"Each entry includes the specific fields to fill. "
                        f"Completing all fields unlocks accurate ICP scoring across the entire book of business."
                    ),
                    severity=Severity.INFO,
                    data={
                        "action_list": action_list,
                        "enrichment_fields": ENRICHMENT_FIELDS,
                    },
                    recommended_action=(
                        "Export this list to a CSV and distribute to RevOps or SDRs for "
                        "manual research. Use LinkedIn Sales Navigator, ZoomInfo, or Clearbit "
                        "to source missing fields."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"LeadEnrichmentWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_all_accounts(self, tenant_id: str) -> list[dict]:
        """
        Return all Customer and Prospect accounts with enrichment fields.
        Fields: name, account_type, industry, annual_revenue, employee_count, canonical_id.
        """
        query = """
        MATCH (a:Account {tenant_id: $tenant_id})
        RETURN
            a.canonical_id AS canonical_id,
            a.name AS name,
            a.account_type AS account_type,
            a.industry AS industry,
            a.annual_revenue AS annual_revenue,
            a.employee_count AS employee_count
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
