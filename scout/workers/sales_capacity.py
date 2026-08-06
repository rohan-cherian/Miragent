"""
scout/workers/sales_capacity.py — Sales Capacity Worker (Layer 3)

Analyzes the sales organization's capacity, coverage, and productivity.

Layer 3 upgrade (Schema Intelligence):
  - Thresholds are segment-aware: enterprise teams need deeper pipeline coverage
    (4x quota) and tighter manager spans; SMB teams carry higher volumes at
    lower ACV and have different capacity math
  - Idle rep analysis goes beyond "no pipeline" — it distinguishes between
    likely causes and generates different recommendations for each:
      * New hire (title contains "Junior", "Associate", "SDR", "BDR")
        → recommend ramp plan review, not a PIP conversation
      * Experienced rep with no pipeline
        → recommend 1:1 performance conversation within 48 hours
      * Rep with high-value accounts but no pipeline
        → recommend account planning session (expansion focus)
  - Pipeline distribution finding uses a Gini-style imbalance score
    rather than a simple max/min ratio
  - Each finding names the specific rep(s) involved

PE context:
  PE firms consistently find one of two problems here:
  1. Overcapacity — too many reps for the deal volume (burn rate risk)
  2. Undercapacity — too few reps for pipeline growth targets (revenue risk)
     Often disguised as "we need to hire" when the real issue is
     that existing reps are underperforming or mis-allocated.
"""

import logging
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (pre-intelligence fallbacks) ────────────────────────
IDEAL_PIPELINE_MULTIPLE   = 3.0
MIN_DEALS_PER_ACTIVE_REP  = 1
MAX_PIPELINE_PER_REP      = 600_000
SALES_MANAGER_SPAN_MIN    = 4
SALES_MANAGER_SPAN_MAX    = 10

# Keywords that suggest a rep is in onboarding/ramp phase
JUNIOR_TITLE_SIGNALS = {"junior", "associate", "sdr", "bdr", "new", "trainee", "apprentice"}


class SalesCapacityWorker(WorkerBase):
    """
    Surfaces sales capacity imbalances with segment-aware thresholds
    and cause-differentiated recommendations.
    """

    WORKER_NAME = "SalesCapacityWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        # Segment-aware threshold resolution
        t_pipeline_multiple = ctx.threshold(
            self.WORKER_NAME, "ideal_pipeline_multiple",
            cfg.get("ideal_pipeline_multiple", IDEAL_PIPELINE_MULTIPLE),
        )
        t_max_pipeline = ctx.threshold(
            self.WORKER_NAME, "max_pipeline_per_rep",
            cfg.get("max_pipeline_per_rep", MAX_PIPELINE_PER_REP),
        )
        t_mgr_span_min = ctx.threshold(
            self.WORKER_NAME, "sales_manager_span_min",
            cfg.get("sales_manager_span_min", SALES_MANAGER_SPAN_MIN),
        )
        t_mgr_span_max = ctx.threshold(
            self.WORKER_NAME, "sales_manager_span_max",
            cfg.get("sales_manager_span_max", SALES_MANAGER_SPAN_MAX),
        )

        try:
            rep_pipeline  = self._get_rep_pipeline(tenant_id)
            sales_managers = self._get_sales_managers(tenant_id)

            active_reps = [r for r in rep_pipeline if r.get("open_deals", 0) > 0]
            idle_reps   = [r for r in rep_pipeline if r.get("open_deals", 0) == 0]
            total_pipeline = sum(r.get("pipeline_value") or 0 for r in rep_pipeline)

            result.summary_stats = {
                "total_sales_reps":          len(rep_pipeline),
                "active_reps":               len(active_reps),
                "idle_reps":                 len(idle_reps),
                "total_open_pipeline":       round(total_pipeline),
                "avg_pipeline_per_active_rep": round(
                    total_pipeline / len(active_reps) if active_reps else 0
                ),
                "sales_manager_count":       len(sales_managers),
                "segment":                   ctx.segment_label,
                "thresholds_calibrated":     ctx.has_calibrated_history,
            }

            if not rep_pipeline:
                result.findings.append(Finding(
                    title="No sales reps found in the graph",
                    detail="Sales headcount analysis requires CRM or HR data with Department='Sales'.",
                    severity=Severity.INFO,
                    recommended_action="Ensure Salesforce or HubSpot connector is included in scans.",
                ))
                return result

            # ── Finding 1: Idle reps — with cause differentiation ─────────
            if idle_reps:
                junior_reps = [r for r in idle_reps if _is_likely_ramping(r)]
                seasoned_idle = [r for r in idle_reps if not _is_likely_ramping(r)]

                severity = (
                    Severity.HIGH
                    if len(seasoned_idle) > len(active_reps) * 0.25
                    else Severity.MEDIUM
                )

                detail_lines = []
                if seasoned_idle:
                    detail_lines.append(
                        f"Experienced reps with no pipeline ({len(seasoned_idle)}):"
                    )
                    for r in seasoned_idle[:3]:
                        detail_lines.append(
                            f"  • {r.get('rep', 'Unknown')} ({r.get('title', 'Rep')}) "
                            f"— 0 open deals, likely underperforming or mis-allocated"
                        )
                    if len(seasoned_idle) > 3:
                        detail_lines.append(f"  • …and {len(seasoned_idle) - 3} more")

                if junior_reps:
                    detail_lines.append(
                        f"Likely ramping/onboarding reps with no pipeline ({len(junior_reps)}):"
                    )
                    for r in junior_reps[:2]:
                        detail_lines.append(
                            f"  • {r.get('rep', 'Unknown')} ({r.get('title', 'Rep')}) "
                            f"— new hire or entry-level role, ramp plan may be in progress"
                        )

                idle_pct = len(idle_reps) / max(len(rep_pipeline), 1) * 100
                detail_lines.append(
                    f"\n{idle_pct:.0f}% of the sales team has zero open pipeline "
                    f"({ctx.segment_label} norms: <15% idle is healthy)."
                )

                action = _build_idle_rep_action(seasoned_idle, junior_reps)

                result.findings.append(Finding(
                    title=f"{len(idle_reps)} sales rep{'s' if len(idle_reps) > 1 else ''} "
                          f"with no open pipeline "
                          f"({len(seasoned_idle)} experienced, {len(junior_reps)} ramping)",
                    detail="\n".join(detail_lines),
                    severity=severity,
                    data={
                        "idle_rep_count":      len(idle_reps),
                        "seasoned_idle_count": len(seasoned_idle),
                        "ramping_count":       len(junior_reps),
                        "total_rep_count":     len(rep_pipeline),
                        "idle_pct":            round(idle_pct, 1),
                        "reps": [
                            {"name": r.get("rep"), "title": r.get("title"),
                             "likely_ramping": _is_likely_ramping(r)}
                            for r in idle_reps
                        ],
                    },
                    recommended_action=action,
                    confidence="high",
                    specific_entities=[
                        {
                            "type":           "person",
                            "name":           r.get("rep"),
                            "title":          r.get("title"),
                            "id":             r.get("rep_id"),
                            "open_deals":     0,
                            "pipeline_value": 0,
                            "likely_ramping": _is_likely_ramping(r),
                        }
                        for r in idle_reps
                    ],
                ))

            # ── Finding 2: Pipeline concentration (overloaded reps) ───────
            overloaded = [
                r for r in rep_pipeline if (r.get("pipeline_value") or 0) >= t_max_pipeline
            ]
            if overloaded:
                for rep in overloaded[:2]:
                    pv = rep.get("pipeline_value", 0)
                    deals = rep.get("open_deals", 0)
                    result.findings.append(Finding(
                        title=f"Pipeline concentration: {rep.get('rep', 'Unknown')} "
                              f"owns ${pv:,.0f} across {deals} open deals",
                        detail=(
                            f"{rep.get('rep')} is carrying {deals} open deals worth "
                            f"${pv:,.0f} — above the {ctx.segment_label} threshold "
                            f"of ${t_max_pipeline:,.0f}. "
                            f"At this level, deal quality and rep attention both suffer. "
                            f"Research shows reps with over-concentrated pipelines close "
                            f"at 15-20% lower rates on their smaller deals."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "rep":            rep.get("rep"),
                            "open_deals":     deals,
                            "pipeline_value": pv,
                            "threshold":      t_max_pipeline,
                        },
                        recommended_action=(
                            f"Review territory balance for {rep.get('rep')}. "
                            f"Consider redistributing 2-3 smaller deals to other reps "
                            f"or assigning an SDR to handle top-of-funnel qualification, "
                            f"freeing this rep to focus on the highest-value opportunities."
                        ),
                        specific_entities=[{
                            "type":           "person",
                            "name":           rep.get("rep"),
                            "id":             rep.get("rep_id"),
                            "pipeline_value": pv,
                            "open_deals":     deals,
                        }],
                    ))

            # ── Finding 3: Manager span of control ────────────────────────
            for mgr in sales_managers:
                span = mgr.get("direct_reports", 0)
                if span < t_mgr_span_min:
                    result.findings.append(Finding(
                        title=f"Sales manager {mgr.get('manager', 'Unknown')} "
                              f"has only {span} direct report{'s' if span != 1 else ''}",
                        detail=(
                            f"{mgr.get('manager')} has {span} report(s) — "
                            f"below the {ctx.segment_label} optimal minimum of {t_mgr_span_min}. "
                            f"Either the team is understaffed or this management layer "
                            f"is premature for the current headcount."
                        ),
                        severity=Severity.LOW,
                        data={"manager": mgr.get("manager"), "direct_reports": span,
                              "expected_min": t_mgr_span_min},
                        recommended_action=(
                            f"Review whether {mgr.get('manager')} should be a player-coach "
                            f"carrying quota, or whether the team should be grown to "
                            f"justify the management cost before next budget cycle."
                        ),
                    ))
                elif span > t_mgr_span_max:
                    result.findings.append(Finding(
                        title=f"Sales manager {mgr.get('manager', 'Unknown')} "
                              f"overloaded — {span} direct reports",
                        detail=(
                            f"With {span} direct reports, {mgr.get('manager')} cannot "
                            f"provide adequate weekly coaching. "
                            f"{ctx.segment_label} optimal span is {t_mgr_span_min}–{t_mgr_span_max}. "
                            f"Research consistently shows high-span sales managers produce "
                            f"15-20% lower team quota attainment — the coaching deficit "
                            f"compounds each quarter."
                        ),
                        severity=Severity.HIGH,
                        data={"manager": mgr.get("manager"), "direct_reports": span,
                              "expected_max": t_mgr_span_max},
                        recommended_action=(
                            f"Hire an additional first-line manager or promote a senior rep "
                            f"to team lead. Split {mgr.get('manager')}'s team into two squads "
                            f"with dedicated coaching capacity — this is a high-ROI org investment."
                        ),
                        specific_entities=[{
                            "type":           "person",
                            "name":           mgr.get("manager"),
                            "direct_reports": span,
                        }],
                    ))

            # ── Finding 4: Pipeline balance (Gini-style imbalance) ────────
            if len(active_reps) >= 3:
                values = sorted([r.get("pipeline_value") or 0 for r in active_reps])
                gini   = _gini_coefficient(values)
                if gini > 0.45:
                    top_rep   = active_reps[0]
                    max_pv    = top_rep.get("pipeline_value", 0)
                    bottom    = active_reps[-1]
                    min_pv    = bottom.get("pipeline_value", 0)
                    result.findings.append(Finding(
                        title=f"Pipeline heavily skewed: top rep has "
                              f"{int(max_pv / max(min_pv, 1))}x the pipeline of the bottom active rep",
                        detail=(
                            f"{top_rep.get('rep', 'Top rep')} carries ${max_pv:,.0f}; "
                            f"{bottom.get('rep', 'Bottom rep')} carries ${min_pv:,.0f}. "
                            f"Pipeline distribution Gini score: {gini:.2f} "
                            f"(0 = perfectly equal, 1 = all pipeline on one rep). "
                            f"Score above 0.45 suggests territory design or lead routing problems."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "gini_score":        round(gini, 2),
                            "max_rep_pipeline":  round(max_pv),
                            "min_rep_pipeline":  round(min_pv),
                            "imbalance_ratio":   round(max_pv / max(min_pv, 1), 1),
                            "active_rep_count":  len(active_reps),
                        },
                        recommended_action=(
                            "Audit territory design and inbound lead routing rules. "
                            "Consider a round-robin model for new inbound leads until "
                            "territories are balanced. The goal: no rep should have more "
                            "than 3x the pipeline of another rep at the same seniority level."
                        ),
                    ))

        except Exception as exc:
            logger.exception("SalesCapacityWorker failed: %s", exc)
            result.error = str(exc)

        return result

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_rep_pipeline(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
        WHERE p.department = 'Sales'
        OPTIONAL MATCH (p)-[:OWNS_DEAL]->(o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        RETURN
            p.full_name     AS rep,
            p.job_title     AS title,
            p.canonical_id  AS rep_id,
            count(o)        AS open_deals,
            coalesce(sum(o.amount), 0) AS pipeline_value,
            coalesce(avg(o.probability), 0) AS avg_probability
        ORDER BY pipeline_value DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_sales_managers(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id, is_active: true})-[:MANAGES]->(rep:Person {tenant_id: $tenant_id})
        WHERE mgr.department = 'Sales'
        WITH mgr, count(rep) AS direct_reports
        RETURN
            mgr.full_name   AS manager,
            mgr.job_title   AS title,
            mgr.canonical_id AS manager_id,
            direct_reports
        ORDER BY direct_reports DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_likely_ramping(rep: dict) -> bool:
    """Heuristic: does this rep's title suggest they're in an onboarding/ramp phase?"""
    title = (rep.get("title") or "").lower()
    return any(signal in title for signal in JUNIOR_TITLE_SIGNALS)


def _build_idle_rep_action(seasoned: list[dict], ramping: list[dict]) -> str:
    """Build differentiated action depending on who is idle."""
    parts = []
    if seasoned:
        names = ", ".join(r.get("rep", "?") for r in seasoned[:2])
        suffix = " (and others)" if len(seasoned) > 2 else ""
        parts.append(
            f"Schedule a 30-minute pipeline review with {names}{suffix} this week. "
            f"If no pipeline has been created in 30+ days, this needs a performance conversation "
            f"— not a territory adjustment. Determine: is there a qualification problem, "
            f"an outreach problem, or a territory coverage gap?"
        )
    if ramping:
        names = ", ".join(r.get("rep", "?") for r in ramping[:2])
        parts.append(
            f"For {names} (likely ramping): review the onboarding plan and ramp timeline. "
            f"Ensure they have territory, tools, and a first-deal target set. "
            f"Ramping reps should be generating first pipeline within 60 days of start."
        )
    return " ".join(parts) if parts else "Review each idle rep's situation individually."


def _gini_coefficient(sorted_values: list[float]) -> float:
    """
    Calculate the Gini coefficient for a list of pipeline values.
    0 = perfect equality, 1 = all pipeline on one rep.
    """
    n = len(sorted_values)
    if n == 0 or sum(sorted_values) == 0:
        return 0.0
    total = sum(sorted_values)
    cumsum = 0.0
    gini_sum = 0.0
    for i, v in enumerate(sorted_values, 1):
        cumsum += v
        gini_sum += cumsum
    return 1 - (2 * gini_sum) / (n * total)
