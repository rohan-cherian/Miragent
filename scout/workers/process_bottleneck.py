"""
scout/workers/process_bottleneck.py — Process Bottleneck Worker

Surfaces process fragmentation and operational inefficiency signals
using the data already in the digital twin.

In Sprint 7 (PM4Py), this worker will be rebuilt on actual event log
data to produce empirical process flow maps with bottleneck detection.
For Sprint 5, it uses proxy signals from the graph:

PROXY SIGNAL LOGIC:
The digital twin contains rich structural data that correlates strongly
with process dysfunction. We don't need event logs to identify these
signals — they're visible in the org and vendor data:

  1. TOOL FRAGMENTATION — multiple vendors in the same category
     indicates process fragmentation. Three project management tools
     means three different ways to run a project. This creates
     coordination overhead, training costs, and integration debt.
     Each additional tool in a category adds ~2 hours/employee/week
     of friction (Forrester, 2022).

  2. ITSM SPRAWL — having both ServiceNow AND Jira AND Zendesk AND
     Freshservice means tickets fall through the cracks. Each handoff
     between systems is a delay. In PE-backed companies, ITSM sprawl
     is almost always acquired through M&A and never rationalized.

  3. ORG DESIGN SIGNALS — departments with very high span of control
     (>12 direct reports) indicate managers who cannot run structured
     processes. They're too busy firefighting to implement repeatable
     workflows.

  4. VENDOR-PROCESS MISMATCH — companies spending heavily on ERP but
     with low headcount in Finance/Operations signals that ERP
     adoption may be poor (paying for the tool, not using the process).

In Sprint 7, PM4Py will replace proxy signals with empirical cycle
time measurement across Lead-to-Cash, Hire-to-Retire, Procure-to-Pay,
and Issue-to-Resolution.
"""

import logging
from collections import defaultdict

from scout.db.clickhouse import ClickHouseClientBase
from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# ── Tool category taxonomy ─────────────────────────────────────────────────
PROCESS_CATEGORIES = {
    "Project Management": ["Jira", "Asana", "Monday", "Trello", "ClickUp", "Basecamp", "Linear"],
    "ITSM / Ticketing": ["ServiceNow", "Jira", "Zendesk", "Freshservice", "Intercom", "Help Scout"],
    "CRM": ["Salesforce", "HubSpot", "Dynamics CRM", "Pipedrive", "Zoho"],
    "HRIS": ["Workday", "BambooHR", "ADP", "Rippling", "UKG", "Gusto"],
    "Finance / ERP": ["NetSuite", "QuickBooks", "SAP", "Dynamics Finance", "Sage Intacct", "Acumatica", "Epicor"],
    "Identity / SSO": ["Okta", "Azure AD", "Google Workspace", "JumpCloud"],
    "Expense Management": ["Concur", "Ramp", "Brex", "Expensify", "Bill.com"],
}
FRAGMENTATION_THRESHOLD = 2   # 2+ tools in one process area = fragmentation
HIGH_SPAN_THRESHOLD     = 12  # managers with >12 reports signal process chaos


class ProcessBottleneckWorker(WorkerBase):
    """
    Surfaces process fragmentation, tooling sprawl, and org design signals
    that predict operational bottlenecks.
    """

    WORKER_NAME = "ProcessBottleneckWorker"

    def run(  # type: ignore[override]
        self,
        tenant_id: str,
        ch_client: ClickHouseClientBase | None = None,
    ) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_fragmentation = cfg.get("fragmentation_threshold", FRAGMENTATION_THRESHOLD)
        t_high_span     = cfg.get("high_span_threshold",     HIGH_SPAN_THRESHOLD)

        try:
            vendors = self._get_vendors(tenant_id)
            overloaded_managers = self._get_overloaded_managers(tenant_id, t_high_span)
            dept_breakdown = self._get_dept_breakdown(tenant_id)

            total_vendor_count = len(vendors)
            vendor_names = {(v.get("name") or "").lower() for v in vendors}

            # Map vendors to process categories
            category_matches = self._categorize_vendors(vendor_names)
            fragmented_categories = {
                cat: tools for cat, tools in category_matches.items()
                if len(tools) >= t_fragmentation
            }
            total_fragmentation_overhead_hrs = sum(
                len(tools) * 2 * 52  # 2 hrs/week/extra tool × 52 weeks
                for tools in fragmented_categories.values()
            )

            result.summary_stats = {
                "total_vendor_count": total_vendor_count,
                "fragmented_process_categories": len(fragmented_categories),
                "overloaded_managers": len(overloaded_managers),
                "estimated_fragmentation_overhead_hrs_yr": round(total_fragmentation_overhead_hrs),
            }

            # ── Finding 1: Tool fragmentation by category ──────────────
            for category, tools in fragmented_categories.items():
                extra_tools = len(tools) - 1  # beyond the first one
                hrs_overhead = extra_tools * 2 * 52
                result.findings.append(Finding(
                    title=f"{len(tools)} {category} tools — fragmented process, ~{hrs_overhead:,} hrs/yr overhead",
                    detail=(
                        f"You appear to have {len(tools)} tools in the {category} space: "
                        f"{', '.join(tools)}. "
                        f"Each additional tool adds context-switching overhead, training cost, "
                        f"and integration complexity. Estimated annual friction: "
                        f"~{hrs_overhead:,} person-hours ({extra_tools} extra tools × 2 hrs/wk × 52 wks)."
                    ),
                    severity=Severity.HIGH if len(tools) >= 3 else Severity.MEDIUM,
                    data={
                        "category": category,
                        "tool_count": len(tools),
                        "tools": list(tools),
                        "estimated_overhead_hours_per_year": hrs_overhead,
                    },
                    recommended_action=(
                        f"Standardize on one {category} tool. "
                        f"Migrate all teams within 90 days. "
                        f"The cost of migration is typically recovered in <6 months "
                        f"through reduced licensing and coordination overhead."
                    ),
                ))

            # ── Finding 2: Overloaded managers (process bottlenecks) ───
            if overloaded_managers:
                for mgr in overloaded_managers[:3]:
                    span = mgr.get("direct_reports") or 0
                    result.findings.append(Finding(
                        title=f"{mgr.get('manager', 'Unknown')} has {span} direct reports — process bottleneck risk",
                        detail=(
                            f"Managers with {span}+ direct reports cannot run structured processes. "
                            f"Every decision, approval, and escalation flows through one person, "
                            f"creating a queue. This is how firefighting cultures develop."
                        ),
                        severity=Severity.HIGH if span >= 15 else Severity.MEDIUM,
                        data={
                            "manager": mgr.get("manager"),
                            "department": mgr.get("department"),
                            "direct_reports": span,
                        },
                        recommended_action=(
                            f"Split the team or promote a senior IC to team lead. "
                            f"In the interim, document and delegate recurring decision types "
                            f"so the manager is not the single point of failure for routine work."
                        ),
                    ))

            # ── Finding 3: Process coverage gaps ───────────────────────
            # Departments with no tooling in their core category
            has_crm = any("salesforce" in (v.get("name") or "").lower()
                          or "hubspot" in (v.get("name") or "").lower()
                          for v in vendors)
            has_hris = any("workday" in (v.get("name") or "").lower()
                           or "bamboohr" in (v.get("name") or "").lower()
                           or "rippling" in (v.get("name") or "").lower()
                           for v in vendors)
            has_erp = any(erp in (v.get("name") or "").lower()
                          for erp in ["netsuite", "quickbooks", "sap", "intacct"]
                          for v in vendors)

            missing_core = []
            if not has_crm:
                missing_core.append("CRM (Salesforce/HubSpot)")
            if not has_hris:
                missing_core.append("HRIS (Workday/BambooHR)")
            if not has_erp:
                missing_core.append("ERP (NetSuite/QuickBooks)")

            if missing_core:
                result.findings.append(Finding(
                    title=f"Missing core process systems: {', '.join(missing_core)}",
                    detail=(
                        f"These foundational systems are not detected in the vendor list: "
                        f"{', '.join(missing_core)}. "
                        f"Without these, key processes are likely running in spreadsheets — "
                        f"a significant operational risk and data quality problem."
                    ),
                    severity=Severity.CRITICAL,
                    data={"missing_systems": missing_core},
                    recommended_action=(
                        "Prioritize implementation of missing core systems. "
                        "Spreadsheet-run finance, HR, or sales processes cannot scale "
                        "and will become audit risks if the company is growing toward an exit."
                    ),
                ))

            # ── Finding 4: ClickHouse cycle time data (Sprint 20) ───────
            if ch_client is not None:
                self._add_cycle_time_findings(tenant_id, ch_client, result)
            else:
                result.findings.append(Finding(
                    title="Empirical cycle time analysis: connect ClickHouse to enable",
                    detail=(
                        "Real cycle time measurement for Lead-to-Cash, Hire-to-Retire, "
                        "Procure-to-Pay, and Issue-to-Resolution requires the ClickHouse "
                        "event log. Current findings are based on structural proxy signals. "
                        "Set USE_MOCK_CONNECTORS=false and provide a ClickHouseClient to "
                        "unlock empirical process analytics."
                    ),
                    severity=Severity.INFO,
                    data={"clickhouse_enabled": False},
                ))

        except Exception as exc:
            logger.exception(f"ProcessBottleneckWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _categorize_vendors(self, vendor_names: set[str]) -> dict[str, list[str]]:
        """Match vendor names to process categories."""
        matches: dict[str, list[str]] = {}
        for category, tools in PROCESS_CATEGORIES.items():
            found = [tool for tool in tools if any(tool.lower() in name for name in vendor_names)]
            if found:
                matches[category] = found
        return matches

    def _get_vendors(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (v:Vendor {tenant_id: $tenant_id, is_active: true})
        RETURN v.name AS name, v.category AS category, v.annual_spend AS annual_spend
        ORDER BY v.annual_spend DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_overloaded_managers(self, tenant_id: str, high_span: int = HIGH_SPAN_THRESHOLD) -> list[dict]:
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id})-[:MANAGES]->(rep:Person)
        WITH mgr, count(rep) AS direct_reports
        WHERE direct_reports >= $threshold
        RETURN mgr.full_name AS manager, mgr.department AS department,
               mgr.job_title AS title, direct_reports
        ORDER BY direct_reports DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id, threshold=high_span)]

    def _get_dept_breakdown(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
        WHERE p.department IS NOT NULL
        RETURN p.department AS department, count(p) AS count
        ORDER BY count DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _add_cycle_time_findings(
        self,
        tenant_id: str,
        ch: ClickHouseClientBase,
        result: WorkerResult,
    ) -> None:
        """Add empirical cycle-time findings sourced from ClickHouse event log."""
        # Lead-to-Cash cycle time
        l2c = ch.query_cycle_times(tenant_id, "opportunity", "created", "closed_won")
        if l2c.count >= 5:
            sev = Severity.CRITICAL if l2c.median_days > 150 else (
                Severity.HIGH if l2c.median_days > 90 else Severity.MEDIUM
            )
            result.findings.append(Finding(
                title=(
                    f"Lead-to-Cash cycle time: {l2c.median_days}d median "
                    f"(p95={l2c.p95_days}d) across {l2c.count} closed deals"
                ),
                detail=(
                    f"Empirical cycle time from ClickHouse event log. "
                    f"Industry benchmark: 90 days. "
                    f"Your median: {l2c.median_days}d, fastest: {l2c.min_days}d, "
                    f"slowest (p95): {l2c.p95_days}d. "
                    + ("Exceeds benchmark — indicates qualification or process failure." if l2c.median_days > 90 else "On or below benchmark.")
                ),
                severity=sev,
                data={
                    "process": "Lead-to-Cash",
                    "median_days": l2c.median_days,
                    "p75_days": l2c.p75_days,
                    "p95_days": l2c.p95_days,
                    "min_days": l2c.min_days,
                    "max_days": l2c.max_days,
                    "sample_size": l2c.count,
                    "benchmark_days": 90,
                    "source": "clickhouse_event_log",
                },
                recommended_action=(
                    "Analyse stage-level drop-off to identify the longest dwell time. "
                    "Compare fastest-rep vs slowest-rep cycle time — the gap is a training ROI opportunity."
                ) if l2c.median_days > 90 else None,
            ))

        # Procure-to-Pay cycle time
        p2p = ch.query_cycle_times(tenant_id, "invoice", "created", "paid")
        if p2p.count >= 10:
            sev = Severity.HIGH if p2p.median_days > 45 else (
                Severity.MEDIUM if p2p.median_days > 30 else Severity.INFO
            )
            result.findings.append(Finding(
                title=(
                    f"Procure-to-Pay: {p2p.median_days}d median payment cycle "
                    f"across {p2p.count} invoices"
                ),
                detail=(
                    f"Invoice creation → payment from ClickHouse event log. "
                    f"Standard net-30 terms assume 30 days. "
                    f"Current median: {p2p.median_days}d, p95: {p2p.p95_days}d. "
                    + ("Late-payment pattern detected — may be incurring penalty APR." if p2p.median_days > 30 else "Within net-30 terms.")
                ),
                severity=sev,
                data={
                    "process": "Procure-to-Pay",
                    "median_days": p2p.median_days,
                    "p95_days": p2p.p95_days,
                    "sample_size": p2p.count,
                    "benchmark_days": 30,
                    "source": "clickhouse_event_log",
                },
                recommended_action=(
                    "Review AP approval workflow. Late payments signal either a process "
                    "bottleneck in the approval chain or a cash-flow management decision."
                ) if p2p.median_days > 30 else None,
            ))

        # Update summary stats
        result.summary_stats["clickhouse_event_log"] = True
        result.summary_stats["l2c_median_days"] = l2c.median_days if l2c.count >= 5 else None
        result.summary_stats["p2p_median_days"] = p2p.median_days if p2p.count >= 10 else None
