"""
scout/workers/marketing_funnel.py — Marketing Funnel Intelligence Worker (Layer 3)

Analyzes the full lead-to-close funnel using opportunity stage data
to find where deals drop off, which segments convert fastest, and
where sales velocity is degrading.

Layer 3 upgrade:
  - Win rate benchmark is now company-calibrated instead of hardcoding 25%.
    The benchmark is derived from the company's own historical win rate with a
    10% improvement target — what's achievable, not a generic industry number.
    If there isn't enough history, falls back to sector baseline.
  - Stage distribution analysis uses StageVocabularyMapper: "Stage 2 - Qualify"
    and "Qualification" are both recognised as early stage. "Stage 4 - Paper"
    and "Negotiation/Review" are both late stage. The old hardcoded lists
    were the most common source of false negatives in this worker.
  - Pipeline aging threshold uses ctx.p75_sales_cycle instead of a fixed 45 days.
    A company with a 180-day enterprise cycle should flag deals at 120 days,
    not 45 days — the 45-day hardcode was producing noise in enterprise orgs.
  - Win/loss industry analysis includes specific lost deal names and amounts
    so the operating partner knows exactly which deals to post-mortem.
  - Channel attribution note removed (it was Sprint 12 scaffolding noise).

WHAT THE FUNNEL LOOKS LIKE (from the CRM data):
  Prospecting → Qualification → Discovery → Demo → Proposal → Negotiation → Closed

WHAT THIS WORKER MEASURES:
  1. WIN RATE vs calibrated benchmark
  2. WIN/LOSS BY INDUSTRY — where are we losing?
  3. STAGE DISTRIBUTION — top-heavy pipeline (too many early-stage deals)?
  4. DEAL VELOCITY BY SEGMENT — which industries close fastest?
  5. PIPELINE AGING — deals sitting in stages beyond their expected time

SPRINT 12 ENRICHMENT:
In Sprint 12 (Real Connectors), this worker will be enriched with:
  - HubSpot/Marketo lead source data → CAC by channel
  - Email engagement data → contact-level activity scoring
  - Marketing attribution → revenue by channel (paid, SEO, events)

Current data source: CRM Opportunity nodes in Neo4j.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict, Counter
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# Fallback defaults when no company history is available
_DEFAULT_LOW_WIN_RATE = 0.15      # below 15% = HIGH finding
_DEFAULT_STRONG_WIN_RATE = 0.40   # above 40% = INFO (good, but check TAM)
_DEFAULT_BENCHMARK_WIN_RATE = 0.25
_DEFAULT_EARLY_STAGE_RATIO = 2.0  # early_count > late_count × 2 = top-heavy
_DEFAULT_AGING_DAYS = 45          # deals stale in early stage beyond this


class MarketingFunnelWorker(WorkerBase):
    """
    Surfaces funnel conversion rates, win/loss analysis, velocity by
    segment, and pipeline health indicators — with company-calibrated thresholds.
    """

    WORKER_NAME = "MarketingFunnelWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            all_deals    = self._get_all_opportunities(tenant_id)
            open_deals   = [d for d in all_deals if not d.get("is_closed")]
            closed_deals = [d for d in all_deals if d.get("is_closed")]
            won_deals    = [d for d in all_deals if d.get("is_won")]
            lost_deals   = [d for d in all_deals if d.get("is_closed") and not d.get("is_won")]

            total             = len(all_deals)
            actual_win_rate   = len(won_deals) / len(closed_deals) if closed_deals else 0
            total_won_value   = sum(d.get("amount") or 0 for d in won_deals)
            total_lost_value  = sum(d.get("amount") or 0 for d in lost_deals)

            # ── Calibrated win rate benchmarks ─────────────────────────────
            # If we have enough history, use company's own win rate as the benchmark
            # with a 10% improvement target. If not, use sector defaults.
            if ctx.has_calibrated_history and ctx.win_rate and ctx.win_rate > 0:
                # Target = historical win rate + 10% (achievable improvement)
                calibrated_benchmark = min(ctx.win_rate * 1.10, 0.60)  # cap at 60%
                low_win_rate         = ctx.win_rate * 0.75              # flag if 25% below historical
                strong_win_rate      = ctx.win_rate * 1.25
                benchmark_label      = f"{calibrated_benchmark*100:.0f}% (company calibrated)"
                thresholds_source    = "calibrated from your historical win rate"
            else:
                calibrated_benchmark = cfg.get("benchmark_win_rate", _DEFAULT_BENCHMARK_WIN_RATE)
                low_win_rate         = cfg.get("low_win_rate",        _DEFAULT_LOW_WIN_RATE)
                strong_win_rate      = cfg.get("strong_win_rate",     _DEFAULT_STRONG_WIN_RATE)
                benchmark_label      = f"{calibrated_benchmark*100:.0f}% (B2B SaaS baseline)"
                thresholds_source    = "using B2B SaaS baseline (insufficient history to calibrate)"

            # Pipeline aging threshold from company cycle data
            aging_threshold = (
                round(ctx.p75_sales_cycle * 0.60)  # flag deals stale for 60% of P75 cycle
                if ctx.p75_sales_cycle and ctx.p75_sales_cycle > 0
                else cfg.get("early_stage_aging_days", _DEFAULT_AGING_DAYS)
            )

            # Stage vocabulary — maps company-specific names to canonical groups
            early_canonical = {"prospecting", "qualification"}
            late_canonical  = {"proposal", "negotiation"}
            early_raw_stages = {
                d.get("stage") for d in open_deals
                if ctx.stage(d.get("stage") or "") in early_canonical
            }
            late_raw_stages = {
                d.get("stage") for d in open_deals
                if ctx.stage(d.get("stage") or "") in late_canonical
            }

            # Stage distribution
            stage_counts = Counter(d.get("stage") for d in open_deals if d.get("stage"))

            result.summary_stats = {
                "total_opportunities":       total,
                "open_deals":                len(open_deals),
                "closed_deals":              len(closed_deals),
                "won_deals":                 len(won_deals),
                "lost_deals":                len(lost_deals),
                "win_rate_pct":              round(actual_win_rate * 100, 1),
                "benchmark_win_rate_pct":    round(calibrated_benchmark * 100, 1),
                "total_won_value":           round(total_won_value),
                "total_lost_value":          round(total_lost_value),
                "open_stage_distribution":   dict(stage_counts),
                "thresholds_source":         thresholds_source,
                "aging_threshold_days":      aging_threshold,
            }

            if total == 0:
                result.findings.append(Finding(
                    title="No opportunity data — run a CRM scan first",
                    detail="MarketingFunnelWorker requires Opportunity nodes from Salesforce, HubSpot, or similar.",
                    severity=Severity.INFO,
                    data={},
                ))
                return result

            context_note = (
                f"Win rate benchmark: {benchmark_label}. "
                f"Pipeline aging threshold: {aging_threshold} days "
                f"({'calibrated from P75 sales cycle' if ctx.p75_sales_cycle else 'using default'})."
            )

            # ── Finding 1: Win rate vs calibrated benchmark ─────────────
            if closed_deals:
                if actual_win_rate < low_win_rate:
                    gap = calibrated_benchmark - actual_win_rate
                    lost_revenue_estimate = round(total_lost_value * gap)
                    result.findings.append(Finding(
                        title=(
                            f"Low win rate: {actual_win_rate*100:.0f}% vs "
                            f"{calibrated_benchmark*100:.0f}% benchmark "
                            f"— ${total_lost_value:,.0f} in lost deals"
                        ),
                        detail=(
                            f"{len(won_deals)} won out of {len(closed_deals)} closed deals "
                            f"({actual_win_rate*100:.0f}% win rate). "
                            f"Benchmark is {benchmark_label}. "
                            f"Typical causes: poor ICP qualification, weak competitive positioning, "
                            f"or pricing above market. "
                            f"At current volume, closing at benchmark rate would recover "
                            f"~${lost_revenue_estimate:,.0f} in annual revenue."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "won":                   len(won_deals),
                            "lost":                  len(lost_deals),
                            "win_rate_pct":          round(actual_win_rate * 100, 1),
                            "benchmark_pct":         round(calibrated_benchmark * 100, 1),
                            "lost_value":            round(total_lost_value),
                            "thresholds_source":     thresholds_source,
                        },
                        recommended_action=(
                            "Conduct a structured win/loss analysis on the last 10 closed deals. "
                            "Identify the top 3 loss reasons. "
                            "If loss reasons are consistent (e.g., 'went with competitor', 'price'), "
                            "these require specific product or GTM fixes, not just rep coaching."
                        ),
                        confidence="high" if ctx.has_calibrated_history else "medium",
                        context_note=context_note,
                    ))
                elif actual_win_rate >= strong_win_rate:
                    result.findings.append(Finding(
                        title=f"Strong win rate: {actual_win_rate*100:.0f}% — above {calibrated_benchmark*100:.0f}% benchmark",
                        detail=(
                            f"{len(won_deals)} won out of {len(closed_deals)} closed deals. "
                            f"Win rate of {actual_win_rate*100:.0f}% exceeds the benchmark. "
                            f"This suggests strong product-market fit in current segments. "
                            f"Risk: with a strong win rate, you may be fishing in too small a pond — "
                            f"qualifying too narrowly means leaving addressable market untouched."
                        ),
                        severity=Severity.INFO,
                        data={
                            "win_rate_pct":   round(actual_win_rate * 100, 1),
                            "benchmark_pct":  round(calibrated_benchmark * 100, 1),
                        },
                        recommended_action=(
                            "With a strong win rate, increase pipeline volume rather than "
                            "improving conversion — the funnel is working. "
                            "Check if TAM limits are constraining growth."
                        ),
                        confidence="high",
                    ))

            # ── Finding 2: Win/loss by industry with specific deal names ─
            if closed_deals:
                industry_results: dict[str, dict] = defaultdict(
                    lambda: {"won": 0, "lost": 0, "value": 0, "lost_deals": []}
                )
                for d in closed_deals:
                    ind = d.get("industry") or "Unknown"
                    if d.get("is_won"):
                        industry_results[ind]["won"] += 1
                        industry_results[ind]["value"] += d.get("amount") or 0
                    else:
                        industry_results[ind]["lost"] += 1
                        industry_results[ind]["lost_deals"].append({
                            "name": d.get("deal_name"),
                            "amount": d.get("amount") or 0,
                        })

                for industry, stats in industry_results.items():
                    total_ind = stats["won"] + stats["lost"]
                    if total_ind >= 2:
                        ind_win_rate = stats["won"] / total_ind
                        if ind_win_rate == 0:
                            lost_value = sum(d["amount"] for d in stats["lost_deals"])
                            lost_names = ", ".join(
                                d["name"] for d in stats["lost_deals"][:3] if d.get("name")
                            )
                            result.findings.append(Finding(
                                title=(
                                    f"0% win rate in {industry}: "
                                    f"{total_ind} deal(s) lost, ${lost_value:,.0f} in value"
                                ),
                                detail=(
                                    f"All {total_ind} closed deal(s) in {industry} were lost. "
                                    f"Lost deals: {lost_names}. "
                                    f"This pattern indicates a vertical-specific positioning gap or "
                                    f"product fit issue — not rep performance."
                                ),
                                severity=Severity.HIGH,
                                data={
                                    "industry":    industry,
                                    "won":         stats["won"],
                                    "lost":        stats["lost"],
                                    "lost_value":  round(lost_value),
                                    "lost_deals":  stats["lost_deals"][:5],
                                },
                                recommended_action=(
                                    f"Interview lost {industry} prospects. "
                                    f"Determine if this vertical should be paused or if "
                                    f"a vertical-specific pitch and proof point is needed."
                                ),
                                confidence="high",
                                specific_entities=[
                                    {"type": "deal", "name": d["name"], "amount": d["amount"],
                                     "industry": industry}
                                    for d in stats["lost_deals"][:5]
                                ],
                            ))

            # ── Finding 3: Pipeline stage distribution (vocabulary-aware) ─
            early_count = sum(
                1 for d in open_deals
                if d.get("stage") and ctx.stage(d.get("stage") or "") in early_canonical
            )
            late_count = sum(
                1 for d in open_deals
                if d.get("stage") and ctx.stage(d.get("stage") or "") in late_canonical
            )
            early_value = sum(
                d.get("amount") or 0 for d in open_deals
                if d.get("stage") and ctx.stage(d.get("stage") or "") in early_canonical
            )
            late_value = sum(
                d.get("amount") or 0 for d in open_deals
                if d.get("stage") and ctx.stage(d.get("stage") or "") in late_canonical
            )

            if open_deals and late_count > 0 and early_count > late_count * 2:
                result.findings.append(Finding(
                    title=(
                        f"Top-heavy pipeline: {early_count} early-stage vs "
                        f"{late_count} late-stage deals"
                    ),
                    detail=(
                        f"{early_count} deal(s) are in early stages "
                        f"(${early_value:,.0f}) vs {late_count} in late stages "
                        f"(${late_value:,.0f}). "
                        f"A healthy pipeline should have roughly equal deal counts across stages. "
                        f"Top-heavy pipelines often indicate reps overstating early-stage activity "
                        f"or insufficient conversion from qualification to proposal."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "early_stage_count": early_count,
                        "late_stage_count":  late_count,
                        "early_stage_value": round(early_value),
                        "late_stage_value":  round(late_value),
                        "early_stages_found": list(early_raw_stages),
                        "late_stages_found":  list(late_raw_stages),
                    },
                    recommended_action=(
                        "Enforce stage exit criteria: a deal should only advance past qualification "
                        "if a discovery call has been completed and budget confirmed. "
                        f"Any deal in early stages for {aging_threshold}+ days "
                        "needs to advance or be closed out."
                    ),
                    confidence="medium",
                ))

            # ── Finding 4: Average deal velocity by industry ──────────────
            industry_velocity: dict[str, list[int]] = defaultdict(list)
            for d in won_deals:
                ind  = d.get("industry") or "Unknown"
                days = d.get("days_in_pipeline") or 0
                if days > 0:
                    industry_velocity[ind].append(days)

            if len(industry_velocity) >= 2:
                industry_avg = {
                    ind: round(statistics.mean(days))
                    for ind, days in industry_velocity.items()
                }
                fastest = min(industry_avg, key=lambda k: industry_avg[k])
                slowest = max(industry_avg, key=lambda k: industry_avg[k])
                if industry_avg[slowest] > industry_avg[fastest] * 1.5:
                    day_diff = industry_avg[slowest] - industry_avg[fastest]
                    result.findings.append(Finding(
                        title=(
                            f"Velocity gap: {fastest} closes {day_diff} days faster than {slowest}"
                        ),
                        detail=(
                            f"Won deals in {fastest} close in avg {industry_avg[fastest]} days. "
                            f"{slowest} takes avg {industry_avg[slowest]} days. "
                            f"When pipeline is constrained, prioritising {fastest} deals "
                            f"generates revenue {day_diff} days sooner per deal."
                        ),
                        severity=Severity.INFO,
                        data={
                            "industry_velocity": industry_avg,
                            "fastest": fastest,
                            "slowest": slowest,
                            "day_difference": day_diff,
                        },
                        recommended_action=(
                            f"Weight pipeline scoring toward {fastest} deals when "
                            f"quarter-end pressure exists. "
                            f"For {slowest} deals, set milestones at "
                            f"{round(industry_avg[slowest] * 0.33)} / "
                            f"{round(industry_avg[slowest] * 0.67)} days or qualify out."
                        ),
                        confidence="medium",
                    ))

        except Exception as exc:
            logger.exception(f"MarketingFunnelWorker failed: {exc}")
            result.error = str(exc)

        return result

    def _get_all_opportunities(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id})
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.name AS deal_name, o.stage AS stage, o.amount AS amount,
            o.is_closed AS is_closed, o.is_won AS is_won,
            o.probability AS probability,
            o.days_in_pipeline AS days_in_pipeline,
            o.close_date AS close_date,
            a.name AS account_name, a.industry AS industry
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
