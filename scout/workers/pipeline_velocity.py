"""
scout/workers/pipeline_velocity.py — Pipeline Velocity Worker (Layer 3)

Analyzes the open sales pipeline to find stalled deals, at-risk closes,
and coverage gaps. This is the first thing a PE operating partner looks
at when they want to understand revenue momentum.

Layer 3 upgrade (Schema Intelligence):
  - Stall thresholds are calibrated to THIS company's historical sales cycle
    (P75 × 0.5 for high-value, P75 × 0.6 for standard) rather than hardcoded
    21/30 day defaults that may be meaningless for this business
  - Stage names are translated via StageVocabularyMapper — no hardcoded
    {"Negotiation/Review", "Proposal/Price Quote"} that miss every
    customized Salesforce implementation
  - Findings cite the specific deal name, rep name, days stalled, and how
    that compares to this company's typical cycle (not generic advice)
  - Overdue close date logic respects field trust — if close_date has high
    null rate, findings are marked uncertain rather than asserted confidently
  - Context note appended to every finding when data confidence is not high

What this worker finds:
  1. Stalled deals — deals that haven't progressed in longer than the
     company's calibrated stall threshold (or hardcoded fallback)
  2. Overdue close dates — open deals with close dates in the past
  3. Pipeline concentration risk — one deal or one rep owns too much
  4. Late-stage low-probability deals — deals in proposal/negotiation
     with probability below 50% (qualification issue or stalling)
"""

import logging
from datetime import date
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (used when no WorkerContext is available) ───────────
# These match pre-intelligence behavior exactly for backward compatibility.
STALLED_DAYS_HIGH_VALUE = 21
STALLED_DAYS_STANDARD   = 30
HIGH_VALUE_THRESHOLD    = 100_000
CONCENTRATION_PCT       = 40


class PipelineVelocityWorker(WorkerBase):
    """
    Surfaces stalled deals, pipeline concentration risk, and close date risk.

    With WorkerContext: thresholds calibrated to this company's sales cycle;
    stage names translated from custom vocabulary; findings cite specific entities.

    Without WorkerContext: falls back to hardcoded defaults (pre-intelligence behavior).
    """

    WORKER_NAME = "PipelineVelocityWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        # ── Resolve thresholds (calibrated > config > hardcoded) ──────────
        t_stalled_high  = ctx.threshold(
            self.WORKER_NAME, "stalled_days_high_value",
            cfg.get("stalled_days_high_value", STALLED_DAYS_HIGH_VALUE),
        )
        t_stalled_std   = ctx.threshold(
            self.WORKER_NAME, "stalled_days_standard",
            cfg.get("stalled_days_standard", STALLED_DAYS_STANDARD),
        )
        t_high_value    = ctx.threshold(
            self.WORKER_NAME, "high_value_threshold",
            cfg.get("high_value_threshold", HIGH_VALUE_THRESHOLD),
        )
        t_concentration = cfg.get("concentration_pct", CONCENTRATION_PCT)

        # Whether thresholds were calibrated to real company data
        calibrated = ctx.has_calibrated_history

        try:
            deals = self._get_open_pipeline(tenant_id)

            if not deals:
                result.findings.append(Finding(
                    title="No open pipeline found in the graph",
                    detail="Either no CRM connector has been scanned or no open opportunities exist.",
                    severity=Severity.INFO,
                    data={},
                    recommended_action="Run a scan with Salesforce or HubSpot connector enabled.",
                ))
                result.summary_stats = {"open_deals": 0, "total_pipeline_value": 0}
                return result

            # ── Summary stats ──────────────────────────────────────────────
            total_value    = sum(d.get("amount") or 0 for d in deals)
            weighted_value = sum(
                (d.get("amount") or 0) * (d.get("probability") or 0) / 100
                for d in deals
            )
            avg_days = (
                sum(d.get("days_in_pipeline") or 0 for d in deals) / len(deals)
                if deals else 0
            )
            result.summary_stats = {
                "open_deals":            len(deals),
                "total_pipeline_value":  total_value,
                "weighted_pipeline_value": round(weighted_value),
                "avg_days_in_pipeline":  round(avg_days),
                "stall_threshold_high_value": t_stalled_high,
                "stall_threshold_standard":   t_stalled_std,
                "thresholds_calibrated":  calibrated,
            }

            # ── Finding 1: Stalled deals ───────────────────────────────────
            stalled = []
            for d in deals:
                threshold = t_stalled_high if (d.get("amount") or 0) >= t_high_value else t_stalled_std
                if (d.get("days_in_pipeline") or 0) >= threshold:
                    stalled.append({**d, "_stall_threshold": threshold})

            if stalled:
                total_stalled_value = sum(d.get("amount") or 0 for d in stalled)
                severity = Severity.HIGH if total_stalled_value > 200_000 else Severity.MEDIUM

                detail = self._build_stall_detail(stalled, ctx, t_stalled_high, t_stalled_std, t_high_value)
                action = self._build_stall_action(stalled, ctx, t_high_value)
                context_note = (
                    f"Stall thresholds calibrated to this company's P75 sales cycle "
                    f"({ctx.p75_sales_cycle} days)."
                    if calibrated
                    else "Using default stall thresholds (21/30 days). "
                         "Thresholds will calibrate automatically after 5+ closed-won deals are available."
                )

                result.findings.append(Finding(
                    title=f"{len(stalled)} stalled deal{'s' if len(stalled) > 1 else ''} "
                          f"— ${total_stalled_value:,.0f} at risk",
                    detail=detail,
                    severity=severity,
                    data={
                        "stalled_count":     len(stalled),
                        "stalled_value":     total_stalled_value,
                        "stall_threshold_days_high": t_stalled_high,
                        "stall_threshold_days_std":  t_stalled_std,
                        "deals": [
                            {
                                "name":         d.get("deal_name"),
                                "owner":        d.get("owner"),
                                "amount":       d.get("amount"),
                                "days_stalled": d.get("days_in_pipeline"),
                                "stage":        d.get("stage"),
                                "canonical_stage": ctx.stage(d.get("stage") or ""),
                            }
                            for d in stalled
                        ],
                    },
                    recommended_action=action,
                    confidence="high" if ctx.field_trusted("opportunity.days_in_pipeline") else "medium",
                    specific_entities=[
                        {
                            "type":         "opportunity",
                            "name":         d.get("deal_name"),
                            "id":           d.get("deal_id"),
                            "owner":        d.get("owner"),
                            "owner_id":     d.get("owner_id"),
                            "amount":       d.get("amount"),
                            "days_stalled": d.get("days_in_pipeline"),
                            "stage":        d.get("stage"),
                            "account":      d.get("account_name"),
                        }
                        for d in stalled
                    ],
                    context_note=context_note,
                ))

            # ── Finding 2: Overdue close dates ─────────────────────────────
            close_date_trusted = ctx.field_trusted("opportunity.close_date")
            today = date.today().isoformat()
            overdue = [
                d for d in deals
                if d.get("close_date") and d["close_date"] < today
            ]
            if overdue:
                overdue_value = sum(d.get("amount") or 0 for d in overdue)
                overdue_detail = self._build_overdue_detail(overdue)
                result.findings.append(Finding(
                    title=f"{len(overdue)} deal{'s' if len(overdue) > 1 else ''} past close date "
                          f"— ${overdue_value:,.0f}",
                    detail=overdue_detail,
                    severity=Severity.HIGH,
                    data={
                        "overdue_count": len(overdue),
                        "overdue_value": overdue_value,
                        "deals": [
                            {"name": d.get("deal_name"), "close_date": d.get("close_date"),
                             "amount": d.get("amount"), "owner": d.get("owner")}
                            for d in overdue
                        ],
                    },
                    recommended_action=(
                        "Update close dates or move to Closed Lost this week. "
                        "Stale close dates inflate pipeline coverage ratios and distort "
                        "forecast accuracy — your operating partner will flag this in the next board call."
                    ),
                    confidence="high" if close_date_trusted else "medium",
                    specific_entities=[
                        {
                            "type":       "opportunity",
                            "name":       d.get("deal_name"),
                            "id":         d.get("deal_id"),
                            "owner":      d.get("owner"),
                            "amount":     d.get("amount"),
                            "close_date": d.get("close_date"),
                        }
                        for d in overdue
                    ],
                    context_note=ctx.field_trust_note("opportunity.close_date"),
                ))

            # ── Finding 3: Pipeline concentration risk ─────────────────────
            if total_value > 0:
                for d in deals:
                    pct = ((d.get("amount") or 0) / total_value) * 100
                    if pct >= t_concentration:
                        result.findings.append(Finding(
                            title=f"Pipeline concentration: '{d.get('deal_name')}' is "
                                  f"{pct:.0f}% of total pipeline",
                            detail=(
                                f"${d.get('amount', 0):,.0f} deal owned by {d.get('owner', 'Unknown')} "
                                f"represents {pct:.0f}% of all open pipeline "
                                f"(${total_value:,.0f} total). "
                                f"If this deal slips, the quarter is at risk — "
                                f"a single deal should not define a period's outcome."
                            ),
                            severity=Severity.HIGH,
                            data={
                                "deal_name":        d.get("deal_name"),
                                "deal_amount":      d.get("amount"),
                                "pct_of_pipeline":  round(pct, 1),
                                "total_pipeline":   total_value,
                                "owner":            d.get("owner"),
                            },
                            recommended_action=(
                                f"Accelerate 2-3 other deals to reduce concentration below 30%. "
                                f"Assign a second relationship point of contact to "
                                f"'{d.get('deal_name')}' — if the primary rep leaves, "
                                f"this deal is at immediate risk."
                            ),
                            specific_entities=[{
                                "type":   "opportunity",
                                "name":   d.get("deal_name"),
                                "id":     d.get("deal_id"),
                                "owner":  d.get("owner"),
                                "amount": d.get("amount"),
                                "pct_of_total_pipeline": round(pct, 1),
                            }],
                        ))

            # ── Finding 4: Late-stage low-probability deals ────────────────
            # Use stage mapper to find what "late stage" means for THIS company
            late_stage_names = ctx.late_stage_names()

            # Fallback if mapper has no late stages mapped (sparse data)
            if not late_stage_names:
                late_stage_names = {"Negotiation/Review", "Proposal/Price Quote"}

            low_prob_late = [
                d for d in deals
                if (d.get("stage") in late_stage_names
                    and (d.get("probability") or 0) < 50)
            ]
            if low_prob_late:
                lp_value = sum(d.get("amount") or 0 for d in low_prob_late)
                lp_detail = self._build_low_prob_detail(low_prob_late, ctx)
                result.findings.append(Finding(
                    title=f"{len(low_prob_late)} late-stage deal{'s' if len(low_prob_late) > 1 else ''} "
                          f"with low confidence — ${lp_value:,.0f}",
                    detail=lp_detail,
                    severity=Severity.MEDIUM,
                    data={
                        "count":       len(low_prob_late),
                        "total_value": lp_value,
                        "deals": [
                            {
                                "name":        d.get("deal_name"),
                                "stage":       d.get("stage"),
                                "probability": d.get("probability"),
                                "owner":       d.get("owner"),
                                "amount":      d.get("amount"),
                            }
                            for d in low_prob_late
                        ],
                    },
                    recommended_action=(
                        "Review each of these deals in your next 1:1 with the rep. "
                        "Deals in proposal/negotiation at <50% probability either have "
                        "a qualification problem (wrong buyer, no budget) or stalled momentum "
                        "(champion went quiet). Each needs a clear next step set within 48 hours "
                        "or should be marked Closed Lost to clean the pipeline."
                    ),
                    specific_entities=[
                        {
                            "type":        "opportunity",
                            "name":        d.get("deal_name"),
                            "id":          d.get("deal_id"),
                            "owner":       d.get("owner"),
                            "amount":      d.get("amount"),
                            "stage":       d.get("stage"),
                            "probability": d.get("probability"),
                        }
                        for d in low_prob_late
                    ],
                ))

        except Exception as exc:
            logger.exception("PipelineVelocityWorker failed: %s", exc)
            result.error = str(exc)

        return result

    # ── Detail builders ────────────────────────────────────────────────────

    def _build_stall_detail(
        self,
        stalled: list[dict],
        ctx: "WorkerContext",
        t_high: int,
        t_std: int,
        high_value_threshold: float,
    ) -> str:
        """
        Build a specific, entity-citing detail for stalled deals.
        Names the deal, the rep, days stalled, and compares to company's cycle.
        """
        lines = []
        for d in stalled[:4]:  # cite up to 4 deals specifically
            name    = d.get("deal_name", "Unknown Deal")
            owner   = d.get("owner", "Unassigned")
            amount  = d.get("amount") or 0
            days    = d.get("days_in_pipeline") or 0
            stage   = d.get("stage", "")
            canonical = ctx.stage(stage)

            # Compare to company median if we have it
            if ctx.median_sales_cycle and ctx.median_sales_cycle > 0:
                cycle_comparison = (
                    f"{days / ctx.median_sales_cycle:.1f}x your median sales cycle"
                )
            else:
                threshold = t_high if amount >= high_value_threshold else t_std
                cycle_comparison = f"{days - threshold} days past the stall threshold"

            lines.append(
                f"• {name} (${amount:,.0f}, {owner}) — {days} days in {stage or 'pipeline'} "
                f"({cycle_comparison})"
            )

        if len(stalled) > 4:
            lines.append(f"• …and {len(stalled) - 4} more stalled deal(s)")

        context_note = ctx.confidence_note()
        return "\n".join(lines) + (f"\n{context_note}" if context_note else "")

    def _build_stall_action(
        self,
        stalled: list[dict],
        ctx: "WorkerContext",
        high_value_threshold: float,
    ) -> str:
        """Build specific, prioritized recommended actions for stalled deals."""
        high_value = [d for d in stalled if (d.get("amount") or 0) >= high_value_threshold]
        standard   = [d for d in stalled if (d.get("amount") or 0) < high_value_threshold]

        actions = []
        if high_value:
            names = ", ".join(d.get("deal_name", "?") for d in high_value[:2])
            actions.append(
                f"Priority: schedule exec sponsor call for {names} this week "
                f"(high-value deals warrant escalation above rep level)."
            )
        if standard:
            names = ", ".join(d.get("deal_name", "?") for d in standard[:2])
            actions.append(
                f"Review {names} in next 1:1s — determine if deals should be "
                f"re-qualified, escalated, or cleaned from the pipeline."
            )
        if not actions:
            actions.append(
                "Schedule deal reviews this week. For each: confirm buyer is still engaged, "
                "set a specific next step with a date, or move to Closed Lost."
            )
        return " ".join(actions)

    def _build_overdue_detail(self, overdue: list[dict]) -> str:
        """Build specific detail for overdue close dates."""
        lines = []
        for d in overdue[:4]:
            name      = d.get("deal_name", "Unknown")
            owner     = d.get("owner", "Unassigned")
            amount    = d.get("amount") or 0
            close_dt  = d.get("close_date", "unknown date")
            lines.append(f"• {name} (${amount:,.0f}, {owner}) — close date was {close_dt}")

        if len(overdue) > 4:
            lines.append(f"• …and {len(overdue) - 4} more overdue deal(s)")

        lines.append(
            "Overdue close dates inflate pipeline coverage ratios and "
            "signal CRM hygiene issues that PE operating partners flag in board prep."
        )
        return "\n".join(lines)

    def _build_low_prob_detail(self, deals: list[dict], ctx: "WorkerContext") -> str:
        """Build specific detail for late-stage low-probability deals."""
        lines = []
        for d in deals[:4]:
            name    = d.get("deal_name", "Unknown")
            owner   = d.get("owner", "Unassigned")
            amount  = d.get("amount") or 0
            prob    = d.get("probability") or 0
            stage   = d.get("stage", "")
            lines.append(
                f"• {name} (${amount:,.0f}, {owner}) — {prob}% probability in {stage}"
            )

        if len(deals) > 4:
            lines.append(f"• …and {len(deals) - 4} more")

        lines.append(
            "Late-stage deals below 50% probability indicate either qualification "
            "gaps (wrong ICP, no budget authority) or stalled momentum (champion disengaged)."
        )
        return "\n".join(lines)

    # ── Data queries ───────────────────────────────────────────────────────

    def _get_open_pipeline(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        OPTIONAL MATCH (p:Person)-[:OWNS_DEAL]->(o)
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.name              AS deal_name,
            o.canonical_id      AS deal_id,
            o.stage             AS stage,
            o.amount            AS amount,
            o.close_date        AS close_date,
            o.probability       AS probability,
            o.days_in_pipeline  AS days_in_pipeline,
            p.full_name         AS owner,
            p.canonical_id      AS owner_id,
            a.name              AS account_name
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            result = session.run(query, tenant_id=tenant_id)
            return [dict(row) for row in result]
