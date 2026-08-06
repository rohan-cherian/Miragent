"""
scout/workers/hire_to_retire.py — Hire-to-Retire Process Mining Worker

Mines the Hire-to-Retire (H2R) process using the organisational graph stored
in the digital twin. H2R is the end-to-end lifecycle of an employee from
onboarding through offboarding, and it governs a company's largest cost line:
people.

Because exact hire and termination dates are not yet available in the CRM
connector data, this worker uses proxy signals that are present in the graph:
  - is_active = false  →  attrition proxy (person has left the company)
  - MANAGES relationship counts  →  span-of-control / workload proxy
  - Department composition  →  org health and key-person risk proxy
  - IC-to-manager ratio  →  management layer efficiency proxy

These proxies are industry-standard substitutes when HRIS data isn't wired in.
PE firms use the same signals during due diligence when they only have a
headcount export and an org chart.

Sprint 12 upgrade:
  When the HRIS connector (Workday or BambooHR) goes live in Sprint 12,
  this worker will be upgraded to consume the full hire-to-retire event log:
  offer-accepted date, start date, promotion history, and termination date.
  At that point we will compute true time-to-productivity, average tenure,
  voluntary vs. involuntary attrition split, and regrettable-loss rate.

Data source: Person nodes and MANAGES relationships in Neo4j.
No live HRIS calls are made here — all analysis runs against the digital twin.
"""

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from scout.db.clickhouse import ClickHouseClientBase
from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Legacy module-level defaults (still used as fallbacks by ThresholdConfig) ─
INACTIVE_RATE_HIGH        = 0.20
INACTIVE_RATE_MEDIUM      = 0.10
HIGH_SPAN                 = 10
SINGLE_PERSON_DEPT_RISK   = True
MIN_HEADCOUNT             = 5
IC_MGMT_HEAVY_RATIO       = 4
IC_MGMT_THIN_RATIO        = 12


class HireToRetireWorker(WorkerBase):
    """
    Surfaces attrition risk, overloaded managers, key-person risk, and
    org-shape inefficiency using proxy signals from Person nodes and MANAGES
    relationships in the digital twin.

    All findings are clearly labelled as proxy-based until the Sprint 12
    HRIS connector provides ground-truth hire/termination event data.
    """

    WORKER_NAME = "HireToRetireWorker"

    def run(  # type: ignore[override]
        self,
        tenant_id: str,
        ch_client: ClickHouseClientBase | None = None,
        config: dict | None = None,
        db: "Session | None" = None,
    ) -> WorkerResult:
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME, config)
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)

        if not cfg.enabled:
            result.findings.append(Finding(
                title="HireToRetireWorker is disabled for this tenant",
                detail="Re-enable this worker in the Admin Portal under Worker Configuration.",
                severity=Severity.INFO, data={}, recommended_action=None,
            ))
            return result

        try:
            # ── ClickHouse: run regardless of Neo4j state ──────────────────
            if ch_client is not None:
                onboard = ch_client.query_cycle_times(
                    tenant_id, "person", "hired", "onboarding_complete"
                )
                if onboard.count >= 5:
                    sev = (
                        Severity.HIGH if onboard.median_days > 30 else
                        Severity.MEDIUM if onboard.median_days > 14 else
                        Severity.INFO
                    )
                    result.findings.append(Finding(
                        title=(
                            f"Onboarding cycle time: {onboard.median_days}d median "
                            f"across {onboard.count} hires (event log)"
                        ),
                        detail=(
                            f"Time from hire event to onboarding_complete from ClickHouse. "
                            f"Median: {onboard.median_days}d, p75: {onboard.p75_days}d, "
                            f"p95: {onboard.p95_days}d. "
                            f"Industry target: 14 days for full productivity. "
                            + (f"Exceeds target — delayed ramp costs ${round(onboard.median_days * 800):,} per hire in lost productivity." if onboard.median_days > 14 else "Within 14-day benchmark.")
                        ),
                        severity=sev,
                        data={
                            "process": "Hire-to-Onboarding-Complete",
                            "median_days": onboard.median_days,
                            "p75_days": onboard.p75_days,
                            "p95_days": onboard.p95_days,
                            "sample_size": onboard.count,
                            "benchmark_days": 14,
                            "source": "clickhouse_event_log",
                        },
                        recommended_action=(
                            "Audit onboarding checklist completion rates. Delays typically "
                            "originate in IT provisioning, equipment, or manager readiness — "
                            "not the new hire."
                        ) if onboard.median_days > 14 else None,
                    ))
                    result.summary_stats["clickhouse_onboarding_median_days"] = onboard.median_days
                    result.summary_stats["clickhouse_event_log"] = True

            persons = self._get_all_persons(tenant_id)

            if not persons:
                result.findings.append(Finding(
                    title="No people data found — run a CRM or HRIS scan first",
                    detail=(
                        "HireToRetireWorker requires Person nodes in the graph. "
                        "Connect a Salesforce, HubSpot, or Workday connector and run a scan."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action="Enable a CRM connector and trigger a full scan.",
                ))
                result.summary_stats.update({
                    "total_headcount": 0,
                    "active_headcount": 0,
                    "inactive_headcount": 0,
                    "inactive_rate_pct": 0.0,
                    "manager_count": 0,
                    "ic_count": 0,
                    "ic_to_manager_ratio": None,
                    "department_count": 0,
                })
                return result

            # ── Partition headcount ────────────────────────────────────────
            active_persons   = [p for p in persons if p.get("is_active")]
            inactive_persons = [p for p in persons if not p.get("is_active")]

            total_headcount    = len(persons)
            active_headcount   = len(active_persons)
            inactive_headcount = len(inactive_persons)
            inactive_rate      = inactive_headcount / total_headcount if total_headcount > 0 else 0.0

            # ── Load thresholds from config ────────────────────────────────
            t_high   = cfg.get("inactive_rate_high",   INACTIVE_RATE_HIGH)
            t_medium = cfg.get("inactive_rate_medium",  INACTIVE_RATE_MEDIUM)
            t_span   = cfg.get("high_span",             HIGH_SPAN)
            t_min_hc = cfg.get("min_headcount",         MIN_HEADCOUNT)
            t_heavy  = cfg.get("ic_mgmt_heavy_ratio",   IC_MGMT_HEAVY_RATIO)
            t_thin   = cfg.get("ic_mgmt_thin_ratio",    IC_MGMT_THIN_RATIO)

            # ── Manager spans ──────────────────────────────────────────────
            manager_spans = self._get_manager_spans(tenant_id)

            # A "manager" is anyone with at least one direct report
            manager_names = set(manager_spans.keys())
            manager_count = len(manager_names)

            # ICs = active persons who are not managers
            ic_count = sum(
                1 for p in active_persons
                if p.get("full_name") not in manager_names
            )
            ic_to_manager_ratio = (
                round(ic_count / manager_count, 1)
                if manager_count > 0 else None
            )

            # ── Department composition ─────────────────────────────────────
            dept_composition = self._get_department_composition(persons)
            department_count = len(dept_composition)

            result.summary_stats = {
                "total_headcount": total_headcount,
                "active_headcount": active_headcount,
                "inactive_headcount": inactive_headcount,
                "inactive_rate_pct": round(inactive_rate * 100, 1),
                "manager_count": manager_count,
                "ic_count": ic_count,
                "ic_to_manager_ratio": ic_to_manager_ratio,
                "department_count": department_count,
            }

            # ── Finding 1: Attrition signal ────────────────────────────────
            if inactive_rate > t_high:
                severity = Severity.HIGH
                headline = (
                    f"High attrition signal: {inactive_rate * 100:.1f}% of headcount "
                    f"is inactive ({inactive_headcount} of {total_headcount} people)"
                )
                detail = (
                    f"{inactive_headcount} of {total_headcount} people in the CRM are marked "
                    f"inactive — a {inactive_rate * 100:.1f}% rate, above the {t_high * 100:.0f}% "
                    f"risk threshold. Note: 'inactive' is a proxy for attrition derived from "
                    f"CRM active-status flags. Until the HRIS connector is live (Sprint 12), "
                    f"this signal may include deactivated service accounts and role changes. "
                    f"Even with that caveat, a rate this high warrants investigation."
                )
            elif inactive_rate > t_medium:
                severity = Severity.MEDIUM
                headline = (
                    f"Attrition proxy signal: {inactive_rate * 100:.1f}% inactive headcount "
                    f"({inactive_headcount} of {total_headcount})"
                )
                detail = (
                    f"{inactive_headcount} of {total_headcount} people are marked inactive "
                    f"— a {inactive_rate * 100:.1f}% rate, above the monitoring threshold "
                    f"of {t_medium * 100:.0f}%. This is a leading indicator of attrition "
                    f"pressure. Replacing an employee costs 0.5–2x their annual salary in "
                    f"recruiting, onboarding, and lost productivity — so trend direction matters."
                )
            else:
                severity = Severity.INFO
                headline = (
                    f"Attrition proxy looks healthy: {inactive_rate * 100:.1f}% inactive "
                    f"({inactive_headcount} of {total_headcount})"
                )
                detail = (
                    f"{inactive_headcount} of {total_headcount} people are marked inactive, "
                    f"a {inactive_rate * 100:.1f}% rate. This is below the {t_medium * 100:.0f}% "
                    f"monitoring threshold. Continue tracking quarterly. "
                    f"Sprint 12 HRIS integration will provide verified attrition rates."
                )

            result.findings.append(Finding(
                title=headline,
                detail=detail,
                severity=severity,
                data={
                    "total_headcount": total_headcount,
                    "active_headcount": active_headcount,
                    "inactive_headcount": inactive_headcount,
                    "inactive_rate_pct": round(inactive_rate * 100, 1),
                    "inactive_threshold_high_pct": t_high * 100,
                    "inactive_threshold_medium_pct": t_medium * 100,
                    "inactive_names": [
                        p.get("full_name") for p in inactive_persons[:10]
                    ],
                },
                recommended_action=(
                    "Cross-reference inactive records with HR. Classify each as: "
                    "voluntary resign, involuntary term, or role change/deactivation. "
                    "This classification is required before Sprint 12 HRIS data is live."
                ),
            ))

            # ── Finding 2: Overloaded managers ────────────────────────────
            overloaded = {
                mgr: reports
                for mgr, reports in manager_spans.items()
                if len(reports) >= t_span
            }
            if overloaded:
                overloaded_details = [
                    {"manager": mgr, "direct_reports": len(reports), "reports": reports[:5]}
                    for mgr, reports in sorted(
                        overloaded.items(), key=lambda kv: -len(kv[1])
                    )
                ]
                top_names = ", ".join(
                    f"{d['manager']} ({d['direct_reports']} reports)"
                    for d in overloaded_details[:3]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(overloaded)} manager{'s' if len(overloaded) != 1 else ''} "
                        f"overloaded with {HIGH_SPAN}+ direct reports: {top_names}"
                    ),
                    detail=(
                        f"{len(overloaded)} manager{'s are' if len(overloaded) != 1 else ' is'} "
                        f"carrying {HIGH_SPAN}+ direct reports. At this span, 1:1 quality drops, "
                        f"coaching time evaporates, and team attrition rises. "
                        f"Research shows managers with >10 reports spend <20 minutes per week "
                        f"per direct report — below the threshold for meaningful development. "
                        f"Each overloaded manager is a retention risk for their entire team."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "overloaded_manager_count": len(overloaded),
                        "high_span_threshold": t_span,
                        "overloaded_managers": overloaded_details,
                    },
                    recommended_action=(
                        "Immediately review team structures for the {count} overloaded manager(s). "
                        "Options: promote a senior IC to team lead, re-distribute reports to "
                        "peer managers, or open a targeted manager hire. "
                        "Prioritise the manager with the highest report count first.".format(
                            count=len(overloaded)
                        )
                    ),
                ))

            # ── Finding 3: Key-person risk (single-person departments) ─────
            single_person_depts = {
                dept: data
                for dept, data in dept_composition.items()
                if data["active"] == 1
            }
            if single_person_depts and SINGLE_PERSON_DEPT_RISK:
                dept_list = list(single_person_depts.keys())
                # Find the name of the active person in each single-person dept
                dept_person_map: dict[str, str] = {}
                for p in active_persons:
                    dept = p.get("department") or "Unknown"
                    if dept in single_person_depts:
                        dept_person_map[dept] = p.get("full_name") or "Unknown"

                detail_parts = [
                    f"{dept} ({dept_person_map.get(dept, 'unknown')})"
                    for dept in dept_list[:5]
                ]
                result.findings.append(Finding(
                    title=(
                        f"Key-person risk: {len(single_person_depts)} department"
                        f"{'s have' if len(single_person_depts) != 1 else ' has'} "
                        f"only 1 active person"
                    ),
                    detail=(
                        f"Departments with a single active person represent critical "
                        f"single points of failure. If that person leaves, institutional "
                        f"knowledge, vendor relationships, and operational continuity are at risk. "
                        f"Affected departments: {', '.join(detail_parts)}"
                        f"{'...' if len(dept_list) > 5 else ''}. "
                        f"In a PE context, key-person risk in Finance, Legal, or Engineering "
                        f"can affect deal close timelines and post-close integration."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "single_person_dept_count": len(single_person_depts),
                        "departments": [
                            {
                                "department": dept,
                                "active_person": dept_person_map.get(dept, "unknown"),
                            }
                            for dept in dept_list
                        ],
                    },
                    recommended_action=(
                        "Document processes and tribal knowledge for each single-person department. "
                        "Create succession plans or cross-training programs. "
                        "For mission-critical functions, consider a fractional hire or backup contractor."
                    ),
                ))

            # ── Finding 4: IC-to-manager ratio (org shape) ────────────────
            if (
                ic_to_manager_ratio is not None
                and total_headcount >= MIN_HEADCOUNT
                and manager_count > 0
            ):
                if ic_to_manager_ratio < t_heavy:
                    result.findings.append(Finding(
                        title=(
                            f"Management-heavy org: IC-to-manager ratio is "
                            f"{ic_to_manager_ratio:.1f}:1 (healthy range: 6–8:1)"
                        ),
                        detail=(
                            f"With {ic_count} individual contributors and {manager_count} managers, "
                            f"the IC-to-manager ratio is {ic_to_manager_ratio:.1f}:1, "
                            f"well below the healthy 6:1–8:1 range. "
                            f"Over-management inflates people costs, slows decision-making, "
                            f"and often signals an org that promoted too many people into management "
                            f"without growing the IC base proportionally. "
                            f"At a {ic_to_manager_ratio:.1f}:1 ratio, management layer cost "
                            f"per revenue dollar is likely above sector benchmarks."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "ic_count": ic_count,
                            "manager_count": manager_count,
                            "ic_to_manager_ratio": ic_to_manager_ratio,
                            "healthy_min_ratio": 6,
                            "healthy_max_ratio": 8,
                            "threshold_management_heavy": t_heavy,
                        },
                        recommended_action=(
                            "Map the management layer against value delivered per manager. "
                            "Consider flattening the org by converting low-span managers to "
                            "senior IC roles ('principal' or 'staff' tracks). "
                            "Target 6:1–8:1 IC-to-manager ratio within two quarters."
                        ),
                    ))
                elif ic_to_manager_ratio > t_thin:
                    result.findings.append(Finding(
                        title=(
                            f"Management-thin org: IC-to-manager ratio is "
                            f"{ic_to_manager_ratio:.1f}:1 (healthy range: 6–8:1)"
                        ),
                        detail=(
                            f"With {ic_count} individual contributors and {manager_count} managers, "
                            f"the IC-to-manager ratio is {ic_to_manager_ratio:.1f}:1, "
                            f"above the healthy 6:1–8:1 range. "
                            f"At this ratio, managers are over-stretched — each manager is "
                            f"responsible for too many ICs to provide adequate coaching, "
                            f"career development, and performance management. "
                            f"This is a leading indicator of attrition in high-performing IC roles."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "ic_count": ic_count,
                            "manager_count": manager_count,
                            "ic_to_manager_ratio": ic_to_manager_ratio,
                            "healthy_min_ratio": 6,
                            "healthy_max_ratio": 8,
                            "threshold_management_thin": t_thin,
                        },
                        recommended_action=(
                            "Identify which teams are most understaffed on management. "
                            "Promote senior ICs into team-lead roles or open manager headcount "
                            "in the next hiring cycle. Prioritise teams with the highest "
                            "attrition risk or the most complex work."
                        ),
                    ))
                else:
                    result.findings.append(Finding(
                        title=(
                            f"Org shape is healthy: IC-to-manager ratio is "
                            f"{ic_to_manager_ratio:.1f}:1"
                        ),
                        detail=(
                            f"{ic_count} ICs and {manager_count} managers gives a "
                            f"{ic_to_manager_ratio:.1f}:1 ratio, within the healthy 6:1–8:1 range. "
                            f"This indicates a well-balanced org where managers have "
                            f"enough reports to stay engaged but not so many that coaching quality drops."
                        ),
                        severity=Severity.INFO,
                        data={
                            "ic_count": ic_count,
                            "manager_count": manager_count,
                            "ic_to_manager_ratio": ic_to_manager_ratio,
                        },
                        recommended_action=(
                            "Maintain ratio discipline as the company scales. "
                            "Revisit quarterly — ratios degrade quickly during rapid hiring phases."
                        ),
                    ))

            # ── Sprint 26: Emit autonomous actions for inactive persons ───
            if db is not None and inactive_persons:
                self._emit_offboarding_actions(
                    db, tenant_id, inactive_persons, result
                )

        except Exception as exc:
            logger.exception(f"HireToRetireWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Helper methods ──────────────────────────────────────────────────────

    def _get_all_persons(self, tenant_id: str) -> list[dict]:
        """
        Fetch all Person nodes for the tenant regardless of active status.

        We pull both active and inactive so attrition proxy can be computed
        against total headcount, not just the active slice.
        """
        query = """
        MATCH (p:Person {tenant_id: $tenant_id})
        RETURN
            p.canonical_id  AS canonical_id,
            p.full_name     AS full_name,
            p.department    AS department,
            p.title         AS title,
            p.is_active     AS is_active
        ORDER BY p.full_name
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_manager_spans(self, tenant_id: str) -> dict[str, list[str]]:
        """
        Return a dict mapping manager full_name → list of direct report full_names.

        Query direction: (mgr)<-[:MANAGES]-(report) matches the relationship
        semantics where a MANAGES edge points from report to manager.

        Note: the direction is (report)-[:MANAGES]->(mgr) per the schema
        definition — a person MANAGES their manager, i.e. the edge goes
        from the subordinate to the superior. The MATCH below follows
        that convention.
        """
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id})<-[:MANAGES]-(report:Person {tenant_id: $tenant_id})
        RETURN mgr.full_name AS manager_name, collect(report.full_name) AS report_names
        """
        with self.driver.session() as session:
            rows = [dict(row) for row in session.run(query, tenant_id=tenant_id)]

        return {
            row["manager_name"]: list(row["report_names"])
            for row in rows
            if row.get("manager_name")
        }

    def _emit_offboarding_actions(
        self,
        db: "Session",
        tenant_id: str,
        inactive_persons: list[dict],
        result: WorkerResult,
    ) -> None:
        """
        Emit ActionFactory specs for each inactive person:
          - deprovision_access   (Workday offboarding)
          - reassign_accounts    (SFDC account redistribution, if person had accounts)

        Uses canonical_id as the source-system proxy ID until Workday connector
        provides real worker IDs. The execution_payload is pre-populated so the
        executor can act without guessing.
        """
        from scout.actions.factory import (
            ActionFactory,
            departed_rep_reassignment,
            deprovision_departed_employee,
        )

        factory = ActionFactory(db, tenant_id)
        actions_emitted = 0

        for person in inactive_persons:
            person_id = person.get("canonical_id") or ""
            person_name = person.get("full_name") or "Unknown"
            if not person_id:
                continue

            # Use a stable hash so re-runs are idempotent
            finding_hash = f"h2r-offboard-{tenant_id}-{person_id}"

            # 1. Deprovision access (always emit for inactive persons)
            factory.emit(deprovision_departed_employee(
                finding_hash=f"{finding_hash}-deprov",
                worker_name=self.WORKER_NAME,
                employee_name=person_name,
                workday_id=person_id,
            ))
            actions_emitted += 1

        created = factory.flush()
        result.summary_stats["actions_emitted"] = actions_emitted
        result.summary_stats["action_ids_created"] = len(created)
        logger.info(
            f"HireToRetireWorker: emitted {actions_emitted} action specs "
            f"→ {len(created)} new actions for tenant {tenant_id}"
        )

    def _get_department_composition(
        self, persons: list[dict]
    ) -> dict[str, dict]:
        """
        Compute active/inactive headcount per department from in-memory person list.

        Returns a dict keyed by department name with:
          total    — all persons in the department
          active   — is_active = True
          inactive — is_active = False or None
        """
        composition: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "active": 0, "inactive": 0}
        )

        for p in persons:
            dept = p.get("department") or "Unknown"
            composition[dept]["total"] += 1
            if p.get("is_active"):
                composition[dept]["active"] += 1
            else:
                composition[dept]["inactive"] += 1

        return dict(composition)
