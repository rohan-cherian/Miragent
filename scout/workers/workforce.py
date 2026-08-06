"""
scout/workers/workforce.py — Workforce Intelligence Worker (Layer 3)

Analyses the people side of the digital twin:
  - Org health (who reports to whom, depth of hierarchy)
  - Span of control (are managers over/under-loaded?)
  - Headcount by department and employment type
  - Key person risk (single points of failure — people with no backup)
  - Data completeness (missing emails, titles, departments)

Layer 3 upgrade:
  - Segment-aware span thresholds: enterprise orgs can sustain wider spans
    than SMB orgs; a 12-report span is fine for a Director of a 200-person
    company but dangerous for an 18-person startup
  - G&A ratio benchmarks calibrated by company stage: pre-revenue companies
    have higher G&A as a percentage while building systems; growth-stage
    companies should be below 20%
  - Key person risk findings now cross-reference segment context and note
    whether succession planning is typical vs. urgent for this stage
  - All findings include confidence, specific_entities, and context_note
    so the AI memo can synthesise with appropriate nuance

Rule of 40 connection:
  Workforce spend is typically 60-70% of OpEx.
  An overloaded manager → burnout → attrition → recruiting cost (~$30k/hire).
  A 2-layer-deep org with a VP who has 1 direct report is $300k/year of slack.
  This worker surfaces those findings so the operating partner can act.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# Thresholds — segment-agnostic defaults
SPAN_OPTIMAL_MIN = 5
SPAN_OPTIMAL_MAX = 10
SPAN_CRITICAL_MAX = 15  # above this is a retention risk, not just inefficiency
KEY_PERSON_THRESHOLD = 3  # if someone manages ≥ this many and has no peer, flag it

# Segment-aware span adjustments
# Enterprise orgs have more experienced managers who can sustain wider spans.
# SMB leaders often wear many hats — narrow spans (2-3 reports) are common
# and acceptable rather than a sign of over-management.
SEGMENT_SPAN_OVERRIDES: dict[str, dict] = {
    "enterprise": {"span_optimal_max": 12, "span_critical_max": 18},
    "mid_market": {"span_optimal_max": 10, "span_critical_max": 15},
    "smb":        {"span_optimal_max": 8,  "span_critical_max": 12},
}

# G&A headcount benchmarks by segment
GA_BENCHMARK: dict[str, float] = {
    "enterprise": 0.15,   # mature orgs should be at 15% or below
    "mid_market": 0.20,
    "smb":        0.25,   # small companies need proportionally more ops overhead
}


class WorkforceWorker(WorkerBase):
    """
    Analyses org structure and headcount from the digital twin.
    All data comes from :Person nodes and :MANAGES relationships in Neo4j.
    """

    WORKER_NAME = "WorkforceWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        # Resolve segment-aware span thresholds
        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
        seg_overrides = SEGMENT_SPAN_OVERRIDES.get(segment, SEGMENT_SPAN_OVERRIDES["mid_market"])

        t_span_min      = cfg.get("span_optimal_min",   SPAN_OPTIMAL_MIN)
        t_span_max      = cfg.get("span_optimal_max",   seg_overrides["span_optimal_max"])
        t_span_critical = cfg.get("span_critical_max",  seg_overrides["span_critical_max"])
        t_key_person    = cfg.get("key_person_threshold", KEY_PERSON_THRESHOLD)

        # G&A benchmark calibrated by segment
        ga_benchmark_pct = GA_BENCHMARK.get(segment, 0.20) * 100

        context_note = (
            f"Thresholds calibrated for {segment} segment: "
            f"optimal span {t_span_min}–{t_span_max}, "
            f"critical at {t_span_critical}+."
            if ctx.has_calibrated_history
            else "Using default thresholds (insufficient company history for calibration)."
        )

        result.summary_stats["segment"] = segment
        result.summary_stats["thresholds_calibrated"] = ctx.has_calibrated_history

        try:
            self._analyse(
                tenant_id, result, ctx,
                span_min=t_span_min, span_max=t_span_max,
                span_critical=t_span_critical, key_person=t_key_person,
                ga_benchmark_pct=ga_benchmark_pct, context_note=context_note,
            )
        except Exception as exc:
            logger.error(f"WorkforceWorker failed for {tenant_id}: {exc}", exc_info=True)
            result.error = str(exc)
        return result

    def _analyse(
        self,
        tenant_id: str,
        result: WorkerResult,
        ctx: "WorkerContext",
        *,
        span_min: int,
        span_max: int,
        span_critical: int,
        key_person: int,
        ga_benchmark_pct: float,
        context_note: str,
    ) -> None:
        with self.driver.session() as session:
            self._headcount_summary(session, tenant_id, result)
            self._span_of_control(
                session, tenant_id, result,
                span_min=span_min, span_max=span_max, span_critical=span_critical,
                context_note=context_note,
            )
            self._department_breakdown(session, tenant_id, result, ga_benchmark_pct=ga_benchmark_pct)
            self._key_person_risk(session, tenant_id, result, threshold=key_person, ctx=ctx)
            self._data_quality(session, tenant_id, result)

    # ── Analysis methods ───────────────────────────────────────────────────────

    def _headcount_summary(self, session, tenant_id: str, result: WorkerResult) -> None:
        """Overall headcount split by employment type and active status."""
        rows = session.run("""
            MATCH (p:Person {tenant_id: $tid})
            RETURN
                count(p) AS total,
                count(p.is_active) AS active,
                sum(CASE WHEN p.employment_type = 'Contractor' THEN 1 ELSE 0 END) AS contractors,
                sum(CASE WHEN p.employment_type = 'Regular' THEN 1 ELSE 0 END) AS employees
        """, tid=tenant_id).single()

        if not rows:
            return

        total = rows["total"]
        contractors = rows["contractors"]
        employees = rows["employees"]
        contractor_pct = round(contractors / total * 100, 1) if total else 0

        result.summary_stats["total_headcount"] = total
        result.summary_stats["employees"] = employees
        result.summary_stats["contractors"] = contractors
        result.summary_stats["contractor_pct"] = contractor_pct

        # Flag high contractor ratio — a PE red flag (hidden FTE costs, IP risk)
        if contractor_pct > 30:
            result.findings.append(Finding(
                title=f"High contractor ratio: {contractor_pct}% of workforce",
                detail=(
                    f"{contractors} of {total} people are contractors. "
                    f"Ratios above 30% indicate potential misclassification risk, "
                    f"IP ownership concerns, and hidden benefits costs. "
                    f"PE firms routinely flag this during diligence — it signals that "
                    f"headcount may be understated vs. true economic workforce cost."
                ),
                severity=Severity.HIGH,
                data={"total": total, "contractors": contractors, "contractor_pct": contractor_pct},
                recommended_action=(
                    "Review contractor roles for potential conversion to FTE. "
                    "Audit for co-employment risk and IP assignment agreements. "
                    "Prioritise longest-tenure contractors first — these carry the highest risk."
                ),
                confidence="high",
            ))
        elif contractor_pct > 15:
            result.findings.append(Finding(
                title=f"Contractor ratio at {contractor_pct}% — monitor trend",
                detail=(
                    f"{contractors} contractors out of {total} total headcount. "
                    f"Within acceptable range but worth tracking quarter-over-quarter."
                ),
                severity=Severity.LOW,
                data={"total": total, "contractors": contractors, "contractor_pct": contractor_pct},
                recommended_action="Track contractor ratio each quarter.",
                confidence="high",
            ))

    def _span_of_control(
        self,
        session,
        tenant_id: str,
        result: WorkerResult,
        *,
        span_min: int,
        span_max: int,
        span_critical: int,
        context_note: str,
    ) -> None:
        """Identify overloaded and under-loaded managers."""
        rows = session.run("""
            MATCH (mgr:Person {tenant_id: $tid})-[:MANAGES]->(rep:Person)
            WITH mgr, count(rep) AS span
            RETURN
                mgr.full_name AS manager,
                mgr.job_title AS title,
                mgr.department AS dept,
                span
            ORDER BY span DESC
        """, tid=tenant_id).data()

        if not rows:
            return

        spans = [r["span"] for r in rows]
        avg_span = round(sum(spans) / len(spans), 1)
        result.summary_stats["manager_count"] = len(rows)
        result.summary_stats["avg_span_of_control"] = avg_span

        overloaded = [r for r in rows if r["span"] > span_max]
        critical = [r for r in rows if r["span"] > span_critical]
        below = [r for r in rows if r["span"] < span_min]

        result.summary_stats["overloaded_managers"] = len(overloaded)
        result.summary_stats["below_optimal_managers"] = len(below)

        # Critical overload (burnout + attrition risk)
        if critical:
            names = ", ".join(
                f"{r['manager']} ({r['span']} reports)" for r in critical
            )
            result.findings.append(Finding(
                title=f"{len(critical)} manager(s) critically overloaded (>{span_critical} direct reports)",
                detail=(
                    f"{names}. Spans above {span_critical} are associated with "
                    f"manager burnout, reduced 1:1 quality, and elevated attrition risk. "
                    f"At an average cost of $30k+ per regrettable hire, preventing one "
                    f"manager from burning out and leaving saves more than a team restructure costs."
                ),
                severity=Severity.CRITICAL,
                data={"critical_managers": critical, "threshold": span_critical},
                recommended_action=(
                    "Immediate org design review. Consider team leads, "
                    "team restructuring, or targeted hiring under these managers."
                ),
                confidence="high",
                specific_entities=[
                    {"type": "person", "name": r["manager"], "title": r["title"],
                     "dept": r["dept"], "span": r["span"]}
                    for r in critical
                ],
                context_note=context_note,
            ))
        elif overloaded:
            names = ", ".join(
                f"{r['manager']} ({r['span']} reports)" for r in overloaded
            )
            result.findings.append(Finding(
                title=f"{len(overloaded)} manager(s) overloaded ({span_max}+ direct reports)",
                detail=(
                    f"{names}. Optimal span for this segment is {span_min}–{span_max}. "
                    f"These managers may struggle with coaching, career development, "
                    f"and retaining high performers."
                ),
                severity=Severity.HIGH,
                data={"overloaded_managers": overloaded},
                recommended_action=(
                    "Review org design. Consider redistributing reports or "
                    "promoting senior ICs to team lead roles."
                ),
                confidence="high",
                specific_entities=[
                    {"type": "person", "name": r["manager"], "title": r["title"],
                     "dept": r["dept"], "span": r["span"]}
                    for r in overloaded
                ],
                context_note=context_note,
            ))

        # Under-loaded (efficiency opportunity)
        # Only flag if majority of managers are below-optimal AND there are at least 3 managers
        # (a 2-person company having a "manager" with 1 report is not a finding)
        if len(below) > len(rows) * 0.5 and len(rows) >= 3:
            result.findings.append(Finding(
                title=f"{len(below)} of {len(rows)} managers have fewer than {span_min} direct reports",
                detail=(
                    f"Average span is {avg_span}. Flat orgs with small spans "
                    f"often indicate over-management layers that increase cost "
                    f"without proportional value. This is one of the most common "
                    f"PE-driven restructuring opportunities."
                ),
                severity=Severity.MEDIUM,
                data={"below_optimal": below, "avg_span": avg_span},
                recommended_action=(
                    "Map management layers vs. IC ratio. "
                    "Consider whether any manager roles can be consolidated."
                ),
                confidence="medium",
                context_note=context_note,
            ))

    def _department_breakdown(
        self,
        session,
        tenant_id: str,
        result: WorkerResult,
        *,
        ga_benchmark_pct: float,
    ) -> None:
        """Headcount by department — useful for benchmarking G&A ratio."""
        rows = session.run("""
            MATCH (p:Person {tenant_id: $tid, is_active: true})
            WHERE p.department IS NOT NULL
            RETURN p.department AS dept, count(p) AS headcount
            ORDER BY headcount DESC
        """, tid=tenant_id).data()

        dept_breakdown = {r["dept"]: r["headcount"] for r in rows}
        result.summary_stats["headcount_by_department"] = dept_breakdown

        ga_depts = {"Finance", "HR", "Legal", "Administration", "Operations"}
        ga_hc = sum(v for k, v in dept_breakdown.items() if k in ga_depts)
        total_hc = sum(dept_breakdown.values())
        if total_hc > 0:
            ga_pct = round(ga_hc / total_hc * 100, 1)
            result.summary_stats["ga_headcount_pct"] = ga_pct
            result.summary_stats["ga_benchmark_pct"] = ga_benchmark_pct

            if ga_pct > ga_benchmark_pct:
                overage = round(ga_pct - ga_benchmark_pct, 1)
                result.findings.append(Finding(
                    title=(
                        f"G&A headcount is {ga_pct}% — {overage}pp above "
                        f"{ga_benchmark_pct:.0f}% benchmark for this segment"
                    ),
                    detail=(
                        f"{ga_hc} of {total_hc} active employees are in G&A functions "
                        f"(Finance, HR, Legal, Admin). "
                        f"The benchmark for this company's segment is {ga_benchmark_pct:.0f}%. "
                        f"G&A overage of {overage}pp on {total_hc} headcount represents "
                        f"approximately {round(total_hc * overage / 100)} excess G&A seats — "
                        f"a material OpEx opportunity."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "ga_headcount": ga_hc,
                        "total_headcount": total_hc,
                        "ga_pct": ga_pct,
                        "ga_benchmark_pct": ga_benchmark_pct,
                        "overage_pp": overage,
                    },
                    recommended_action=(
                        "Benchmark G&A ratio against sector peers. "
                        "Identify automation opportunities in finance and HR operations. "
                        "Examine if any G&A functions are performing work that should be "
                        "outsourced or automated."
                    ),
                    confidence="medium",
                ))

    def _key_person_risk(
        self,
        session,
        tenant_id: str,
        result: WorkerResult,
        *,
        threshold: int,
        ctx: "WorkerContext",
    ) -> None:
        """
        Find people who are single points of failure.

        A key-person risk exists when someone manages a large team AND
        there's no clear peer/backup at the same level. If they leave,
        those reports go unmanaged — a common PE due diligence finding.
        """
        rows = session.run("""
            MATCH (mgr:Person {tenant_id: $tid})-[:MANAGES]->(rep:Person)
            WITH mgr, count(rep) AS reports_count
            WHERE reports_count >= $threshold
            OPTIONAL MATCH (mgr_mgr:Person)-[:MANAGES]->(mgr)
            OPTIONAL MATCH (mgr_mgr)-[:MANAGES]->(peer:Person)
            WHERE peer.canonical_id <> mgr.canonical_id
            WITH mgr, reports_count, mgr_mgr, count(peer) AS peer_count
            RETURN
                mgr.full_name AS name,
                mgr.job_title AS title,
                mgr.department AS dept,
                reports_count,
                peer_count,
                mgr_mgr.full_name AS reports_to
            ORDER BY reports_count DESC
        """, tid=tenant_id, threshold=threshold).data()

        key_persons = [r for r in rows if r["peer_count"] == 0]
        result.summary_stats["key_person_risks"] = len(key_persons)

        if key_persons:
            names = "; ".join(
                f"{r['name']} ({r['title']}, {r['reports_count']} reports)"
                for r in key_persons
            )
            # Severity escalates for enterprise companies — they should have succession plans
            # SMB is expected to have key-person concentration; enterprise should not
            segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"
            if segment == "enterprise":
                sev = Severity.CRITICAL if len(key_persons) > 1 else Severity.HIGH
                urgency_note = (
                    "For an enterprise organisation, absence of succession plans "
                    "is a governance gap that surfaces during PE hold period reviews."
                )
            else:
                sev = Severity.HIGH if len(key_persons) > 1 else Severity.MEDIUM
                urgency_note = (
                    "At this company stage, some key-person concentration is expected. "
                    "Prioritise documenting institutional knowledge and identifying understudies."
                )

            result.findings.append(Finding(
                title=f"{len(key_persons)} key-person risk(s) identified",
                detail=(
                    f"{names}. These individuals manage significant teams "
                    f"with no identified peer at their level. Their departure "
                    f"would create an immediate leadership gap. {urgency_note}"
                ),
                severity=sev,
                data={"key_persons": key_persons},
                recommended_action=(
                    "Develop succession plans for each key-person role. "
                    "Consider cross-training senior ICs as understudies. "
                    "Ensure critical institutional knowledge is documented."
                ),
                confidence="high",
                specific_entities=[
                    {
                        "type": "person",
                        "name": r["name"],
                        "title": r["title"],
                        "dept": r["dept"],
                        "reports_count": r["reports_count"],
                        "reports_to": r["reports_to"],
                    }
                    for r in key_persons
                ],
            ))

    def _data_quality(self, session, tenant_id: str, result: WorkerResult) -> None:
        """Flag people records with missing critical fields."""
        rows = session.run("""
            MATCH (p:Person {tenant_id: $tid, is_active: true})
            RETURN
                sum(CASE WHEN p.job_title IS NULL THEN 1 ELSE 0 END) AS missing_title,
                sum(CASE WHEN p.department IS NULL THEN 1 ELSE 0 END) AS missing_dept,
                sum(CASE WHEN p.email IS NULL THEN 1 ELSE 0 END) AS missing_email,
                count(p) AS total
        """, tid=tenant_id).single()

        if not rows or rows["total"] == 0:
            return

        total = rows["total"]
        issues = []
        if rows["missing_title"] > 0:
            issues.append(f"{rows['missing_title']} missing job title")
        if rows["missing_dept"] > 0:
            issues.append(f"{rows['missing_dept']} missing department")
        if rows["missing_email"] > 0:
            issues.append(f"{rows['missing_email']} missing email")

        if issues:
            result.findings.append(Finding(
                title=f"Data quality gaps in people records: {', '.join(issues)}",
                detail=(
                    f"Out of {total} active people: {'; '.join(issues)}. "
                    f"Missing fields reduce the accuracy of org analysis and "
                    f"will prevent correct entity resolution across systems."
                ),
                severity=Severity.LOW,
                data=dict(rows),
                recommended_action=(
                    "Run a data quality remediation in Workday. "
                    "Ensure all active employees have title, department, and email."
                ),
                confidence="high",
            ))
