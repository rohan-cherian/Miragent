"""
scout/workers/lead_to_cash.py — Lead-to-Cash Process Mining Worker

Traces the complete Lead → Opportunity → Revenue lifecycle using CRM stage
data stored in the digital twin. This is one of the highest-signal process
intelligence plays for a PE operating partner: a company's L2C cycle time
and stage conversion health directly govern revenue predictability and rep
efficiency.

What this worker measures:
  1. L2C cycle time — average days from deal creation to close (won deals)
     benchmarked against B2B SaaS norm of 90 days. Deals averaging >180
     days signal a broken process or misaligned ICP, not a pipeline problem.
  2. Bottleneck stage — which stage kills the most deals. The highest-loss
     stage is where your process, messaging, or economics fail prospects.
     This is where coaching and process redesign dollars should go first.
  3. Rep velocity gap — fastest vs. slowest rep deal-cycle comparison.
     A >50% spread signals that top performers have cracked a method the
     rest of the team hasn't learned. This is a training ROI opportunity.
  4. Revenue recognition rate — closed-won / total deals. A rate below 20%
     means you're generating pipeline you can't convert — a sign of ICP
     drift, qualification failure, or pricing misalignment.

Roadmap:
  Sprint 12 will add MQL/SQL tracking via HubSpot and Marketo connectors,
  enabling full lead-funnel visibility from first touch through closed-won.
  At that point this worker will report MQL→SQL conversion rate, SQL→
  Opportunity conversion rate, and true end-to-end L2C cycle time including
  the marketing pipeline phase.

Data source: Opportunity nodes (with OWNS_DEAL and IN_ACCOUNT edges) in Neo4j.
No live CRM calls are made here — all analysis runs against the digital twin.
"""

import logging
import statistics
from collections import defaultdict

from scout.db.clickhouse import ClickHouseClientBase
from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
L2C_BENCHMARK_DAYS   = 90    # B2B SaaS industry norm for closed-won cycle time
L2C_SLOW_DAYS        = 180   # anything above this is a process failure signal
RECOGNITION_RATE_LOW = 0.20  # won/total < 20% = qualification or ICP problem
MIN_REP_DEALS        = 1     # minimum won deals for a rep to be included in velocity


class LeadToCashWorker(WorkerBase):
    """
    Mines the Lead-to-Cash process using CRM stage data in the digital twin.

    Surfaces cycle time vs. benchmark, stage conversion bottlenecks, rep
    velocity spread, and revenue recognition rate — the four levers PE
    operating partners pull first when diagnosing a stalled revenue engine.
    """

    WORKER_NAME = "LeadToCashWorker"

    def run(  # type: ignore[override]
        self,
        tenant_id: str,
        ch_client: ClickHouseClientBase | None = None,
    ) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_recognition_rate = cfg.get("recognition_rate_low", RECOGNITION_RATE_LOW)
        t_min_deals        = cfg.get("min_rep_deals",        MIN_REP_DEALS)

        try:
            # ── ClickHouse: run regardless of Neo4j state ─────────────────
            # Event log data is independent of graph state — gather it first
            # so it appears even if Neo4j is empty (e.g. before first scan).
            if ch_client is not None:
                dist = ch_client.query_stage_distribution(tenant_id, "opportunity")
                if dist:
                    total_events = sum(dist.values())
                    won_events = dist.get("closed_won", 0)
                    lost_events = dist.get("closed_lost", 0)
                    empirical_win_rate = (
                        won_events / (won_events + lost_events)
                        if (won_events + lost_events) > 0 else 0.0
                    )
                    result.findings.append(Finding(
                        title=(
                            f"Empirical win rate: {empirical_win_rate:.0%} "
                            f"({won_events} closed-won / {won_events + lost_events} decided) "
                            f"— from event log"
                        ),
                        detail=(
                            f"ClickHouse event log: {total_events} opportunity events. "
                            f"Win rate {empirical_win_rate:.0%} "
                            + ("is below the 30% B2B SaaS benchmark." if empirical_win_rate < 0.30 else "is at or above the 30% B2B SaaS benchmark.")
                            + f" Stage distribution: {', '.join(f'{k}={v}' for k, v in sorted(dist.items(), key=lambda x: -x[1])[:5])}."
                        ),
                        severity=(
                            Severity.HIGH if empirical_win_rate < 0.20 else
                            Severity.MEDIUM if empirical_win_rate < 0.30 else
                            Severity.INFO
                        ),
                        data={
                            "stage_distribution": dist,
                            "empirical_win_rate": round(empirical_win_rate, 3),
                            "total_events": total_events,
                            "source": "clickhouse_event_log",
                        },
                    ))
                    result.summary_stats["clickhouse_win_rate"] = round(empirical_win_rate, 3)
                    result.summary_stats["clickhouse_event_log"] = True

            opps = self._get_opportunities_with_stages(tenant_id)

            if not opps:
                result.findings.append(Finding(
                    title="No opportunity data found — run a CRM scan first",
                    detail=(
                        "LeadToCashWorker requires Opportunity nodes in the graph. "
                        "Connect a Salesforce or HubSpot connector and run a scan."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action="Enable a CRM connector and trigger a full scan.",
                ))
                result.summary_stats.update({
                    "total_pipeline_deals": 0,
                    "won_deals": 0,
                    "lost_deals": 0,
                    "open_deals": 0,
                    "revenue_recognized": 0,
                    "recognition_rate_pct": 0.0,
                    "l2c_benchmark_days": L2C_BENCHMARK_DAYS,
                })
                return result

            # ── Partition deals ────────────────────────────────────────────
            won_opps  = [o for o in opps if o.get("is_closed") and o.get("is_won")]
            lost_opps = [o for o in opps if o.get("is_closed") and not o.get("is_won")]
            open_opps = [o for o in opps if not o.get("is_closed")]

            total   = len(opps)
            n_won   = len(won_opps)
            n_lost  = len(lost_opps)
            n_open  = len(open_opps)

            revenue_recognized = sum(o.get("amount") or 0 for o in won_opps)
            recognition_rate   = n_won / total if total > 0 else 0.0

            result.summary_stats = {
                "total_pipeline_deals": total,
                "won_deals": n_won,
                "lost_deals": n_lost,
                "open_deals": n_open,
                "revenue_recognized": round(revenue_recognized),
                "recognition_rate_pct": round(recognition_rate * 100, 1),
                "l2c_benchmark_days": L2C_BENCHMARK_DAYS,
            }

            # ── Finding 1: L2C cycle time vs benchmark ─────────────────────
            if won_opps:
                days_list = [
                    o["days_in_pipeline"]
                    for o in won_opps
                    if o.get("days_in_pipeline") is not None
                ]
                if days_list:
                    avg_days = round(statistics.mean(days_list), 1)
                    median_days = round(statistics.median(days_list), 1)

                    if avg_days > L2C_SLOW_DAYS:
                        severity = Severity.HIGH
                        headline = (
                            f"L2C cycle time is {avg_days} days — "
                            f"{avg_days - L2C_BENCHMARK_DAYS:.0f} days above the 90-day B2B SaaS benchmark"
                        )
                        detail = (
                            f"Won deals average {avg_days} days in pipeline (median {median_days} days), "
                            f"more than double the {L2C_BENCHMARK_DAYS}-day industry benchmark. "
                            f"Cycle times this long typically reflect ICP misalignment, "
                            f"multi-stakeholder buying committees, or stalled qualification. "
                            f"Each additional 30 days of cycle time reduces annual quota capacity by ~8%."
                        )
                    elif avg_days > L2C_BENCHMARK_DAYS:
                        severity = Severity.MEDIUM
                        headline = (
                            f"L2C cycle time is {avg_days} days — "
                            f"{avg_days - L2C_BENCHMARK_DAYS:.0f} days above benchmark"
                        )
                        detail = (
                            f"Won deals average {avg_days} days in pipeline (median {median_days} days), "
                            f"above the {L2C_BENCHMARK_DAYS}-day B2B SaaS benchmark. "
                            f"This is worth investigating but not yet a crisis. "
                            f"Focus on the bottleneck stage (see next finding) to compress the cycle."
                        )
                    else:
                        severity = Severity.INFO
                        headline = (
                            f"L2C cycle time is healthy at {avg_days} days "
                            f"(benchmark: {L2C_BENCHMARK_DAYS} days)"
                        )
                        detail = (
                            f"Won deals average {avg_days} days in pipeline (median {median_days} days), "
                            f"within the {L2C_BENCHMARK_DAYS}-day B2B SaaS benchmark. "
                            f"Maintain current qualification and stage progression discipline."
                        )

                    result.findings.append(Finding(
                        title=headline,
                        detail=detail,
                        severity=severity,
                        data={
                            "avg_days_won": avg_days,
                            "median_days_won": median_days,
                            "won_deal_count": len(days_list),
                            "l2c_benchmark_days": L2C_BENCHMARK_DAYS,
                            "l2c_slow_threshold_days": L2C_SLOW_DAYS,
                        },
                        recommended_action=(
                            "Break the average cycle time down by deal size and industry segment. "
                            "Enterprise deals >$100k naturally run longer — ensure benchmark "
                            "comparisons are like-for-like by segment."
                        ),
                    ))

            # ── Finding 2: Bottleneck stage ────────────────────────────────
            stage_stats = self._analyze_stage_conversion(opps)
            if stage_stats:
                # Stage with the highest loss count among closed deals
                bottleneck = max(
                    stage_stats.items(),
                    key=lambda kv: kv[1]["loss_count"],
                )
                bn_stage, bn_data = bottleneck
                if bn_data["loss_count"] > 0:
                    result.findings.append(Finding(
                        title=(
                            f"Bottleneck stage: '{bn_stage}' — "
                            f"{bn_data['loss_count']} deal{'s' if bn_data['loss_count'] != 1 else ''} lost here "
                            f"({bn_data['loss_pct']:.0f}% loss rate)"
                        ),
                        detail=(
                            f"'{bn_stage}' is where deals die most often: "
                            f"{bn_data['loss_count']} lost vs {bn_data['won_count']} won "
                            f"out of {bn_data['total']} total deals reaching this stage "
                            f"({bn_data['loss_pct']:.0f}% loss rate). "
                            f"This is where your pitch, pricing, or process is failing prospects. "
                            f"Coaching investment at this stage produces the highest conversion ROI."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "bottleneck_stage": bn_stage,
                            "total_at_stage": bn_data["total"],
                            "lost_at_stage": bn_data["loss_count"],
                            "won_at_stage": bn_data["won_count"],
                            "loss_rate_pct": round(bn_data["loss_pct"], 1),
                            "all_stage_stats": {
                                stage: {
                                    "total": v["total"],
                                    "loss_count": v["loss_count"],
                                    "won_count": v["won_count"],
                                    "loss_pct": round(v["loss_pct"], 1),
                                }
                                for stage, v in stage_stats.items()
                            },
                        },
                        recommended_action=(
                            f"Pull call recordings and deal notes for all '{bn_stage}' losses this quarter. "
                            f"Look for the top 3 objection patterns. "
                            f"Run a targeted enablement session with the sales team to address them."
                        ),
                    ))

            # ── Finding 3: Rep velocity gap ────────────────────────────────
            rep_velocity = self._analyze_rep_velocity(won_opps)
            qualified_reps = {
                rep: data
                for rep, data in rep_velocity.items()
                if data["count"] >= t_min_deals and data["avg_days"] > 0
            }
            if len(qualified_reps) >= 2:
                fastest_rep = min(qualified_reps.items(), key=lambda kv: kv[1]["avg_days"])
                slowest_rep = max(qualified_reps.items(), key=lambda kv: kv[1]["avg_days"])
                fast_name, fast_data = fastest_rep
                slow_name, slow_data = slowest_rep

                if fast_data["avg_days"] > 0:
                    gap_pct = (
                        (slow_data["avg_days"] - fast_data["avg_days"])
                        / fast_data["avg_days"]
                    ) * 100

                    if gap_pct >= 50:
                        result.findings.append(Finding(
                            title=(
                                f"Rep velocity gap: {fast_name} closes {gap_pct:.0f}% faster "
                                f"than {slow_name}"
                            ),
                            detail=(
                                f"{fast_name} averages {fast_data['avg_days']:.0f} days to close "
                                f"({fast_data['count']} deal{'s' if fast_data['count'] != 1 else ''}); "
                                f"{slow_name} averages {slow_data['avg_days']:.0f} days "
                                f"({slow_data['count']} deal{'s' if slow_data['count'] != 1 else ''}). "
                                f"A {gap_pct:.0f}% spread means your fastest rep's playbook "
                                f"is not being transferred to the rest of the team. "
                                f"If the slowest rep adopted the fastest rep's cycle time, "
                                f"annual quota capacity would increase materially."
                            ),
                            severity=Severity.MEDIUM,
                            data={
                                "fastest_rep": fast_name,
                                "fastest_avg_days": round(fast_data["avg_days"], 1),
                                "fastest_deal_count": fast_data["count"],
                                "slowest_rep": slow_name,
                                "slowest_avg_days": round(slow_data["avg_days"], 1),
                                "slowest_deal_count": slow_data["count"],
                                "velocity_gap_pct": round(gap_pct, 1),
                                "all_reps": {
                                    rep: {
                                        "avg_days": round(data["avg_days"], 1),
                                        "count": data["count"],
                                    }
                                    for rep, data in qualified_reps.items()
                                },
                            },
                            recommended_action=(
                                f"Interview {fast_name} to extract their qualification, "
                                f"discovery, and closing playbook. Run a peer coaching session "
                                f"where they walk the team through 2-3 recent wins. "
                                f"Record it for onboarding new reps."
                            ),
                        ))

            # ── Finding 4: Revenue recognition rate ───────────────────────
            if recognition_rate < t_recognition_rate and total >= 5:
                result.findings.append(Finding(
                    title=(
                        f"Revenue recognition rate is {recognition_rate * 100:.1f}% "
                        f"— below the {t_recognition_rate * 100:.0f}% threshold"
                    ),
                    detail=(
                        f"Only {n_won} of {total} deals ({recognition_rate * 100:.1f}%) "
                        f"reached closed-won. A recognition rate below {t_recognition_rate * 100:.0f}% "
                        f"indicates the pipeline contains deals that were never genuinely qualified. "
                        f"You're burning rep time and management attention on phantom pipeline. "
                        f"Common causes: ICP drift, no formal qualification gate, "
                        f"or sandbagging by reps who keep lost deals open."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "total_deals": total,
                        "won_deals": n_won,
                        "lost_deals": n_lost,
                        "open_deals": n_open,
                        "recognition_rate_pct": round(recognition_rate * 100, 1),
                        "recognition_rate_threshold_pct": t_recognition_rate * 100,
                        "revenue_recognized": round(revenue_recognized),
                    },
                    recommended_action=(
                        "Introduce a formal qualification gate (MEDDIC or SPICED framework) "
                        "at Needs Analysis stage. Audit all deals open >90 days and force a "
                        "push-or-close decision. Report win rate weekly in the sales standup."
                    ),
                ))

            # ── ClickHouse: empirical stage-transition distribution ─────────
            if ch_client is not None:
                dist = ch_client.query_stage_distribution(tenant_id, "opportunity")
                if dist:
                    total_events = sum(dist.values())
                    won_events = dist.get("closed_won", 0)
                    lost_events = dist.get("closed_lost", 0)
                    empirical_win_rate = (
                        won_events / (won_events + lost_events)
                        if (won_events + lost_events) > 0 else 0.0
                    )
                    result.findings.append(Finding(
                        title=(
                            f"Empirical win rate: {empirical_win_rate:.0%} "
                            f"({won_events} closed-won / {won_events + lost_events} decided) "
                            f"— from event log"
                        ),
                        detail=(
                            f"ClickHouse event log: {total_events} opportunity events. "
                            f"Win rate {empirical_win_rate:.0%} "
                            + ("is below the 30% B2B SaaS benchmark." if empirical_win_rate < 0.30 else "is at or above the 30% B2B SaaS benchmark.")
                            + f" Stage distribution: {', '.join(f'{k}={v}' for k, v in sorted(dist.items(), key=lambda x: -x[1])[:5])}."
                        ),
                        severity=(
                            Severity.HIGH if empirical_win_rate < 0.20 else
                            Severity.MEDIUM if empirical_win_rate < 0.30 else
                            Severity.INFO
                        ),
                        data={
                            "stage_distribution": dist,
                            "empirical_win_rate": round(empirical_win_rate, 3),
                            "total_events": total_events,
                            "source": "clickhouse_event_log",
                        },
                    ))
                    result.summary_stats["clickhouse_win_rate"] = round(empirical_win_rate, 3)
                    result.summary_stats["clickhouse_event_log"] = True

        except Exception as exc:
            logger.exception(f"LeadToCashWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Helper methods ──────────────────────────────────────────────────────

    def _analyze_stage_conversion(
        self, opps: list[dict]
    ) -> dict[str, dict]:
        """
        Compute per-stage conversion statistics across all closed deals.

        Returns a dict keyed by stage name with:
          total      — number of deals that reached this stage and are now closed
          loss_count — deals that were lost while at this stage
          won_count  — deals that were won while at this stage
          loss_pct   — loss_count / total * 100
        """
        closed = [o for o in opps if o.get("is_closed")]
        stage_data: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "loss_count": 0, "won_count": 0, "loss_pct": 0.0}
        )

        for opp in closed:
            stage = opp.get("stage") or "Unknown"
            stage_data[stage]["total"] += 1
            if opp.get("is_won"):
                stage_data[stage]["won_count"] += 1
            else:
                stage_data[stage]["loss_count"] += 1

        for stage, data in stage_data.items():
            if data["total"] > 0:
                data["loss_pct"] = (data["loss_count"] / data["total"]) * 100

        return dict(stage_data)

    def _analyze_rep_velocity(
        self, won_opps: list[dict]
    ) -> dict[str, dict]:
        """
        Compute average deal cycle time and deal count per rep for won deals.

        Returns a dict keyed by owner_name with:
          avg_days — mean days_in_pipeline for that rep's won deals
          count    — number of won deals included
        """
        rep_days: dict[str, list[float]] = defaultdict(list)

        for opp in won_opps:
            owner = opp.get("owner_name") or "Unassigned"
            days  = opp.get("days_in_pipeline")
            if days is not None:
                rep_days[owner].append(float(days))

        return {
            rep: {
                "avg_days": statistics.mean(days_list),
                "count": len(days_list),
            }
            for rep, days_list in rep_days.items()
            if days_list
        }

    def _get_opportunities_with_stages(self, tenant_id: str) -> list[dict]:
        """
        Fetch all opportunities for the tenant with owner and account context.

        Uses OPTIONAL MATCH for owner (Person via OWNS_DEAL) and account
        (Account via IN_ACCOUNT) so that unowned or unlinked deals are still
        returned — we don't want to silently drop them from the analysis.
        """
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id})
        OPTIONAL MATCH (p:Person)-[:OWNS_DEAL]->(o)
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.canonical_id      AS canonical_id,
            o.name              AS name,
            o.stage             AS stage,
            o.amount            AS amount,
            o.is_closed         AS is_closed,
            o.is_won            AS is_won,
            o.probability       AS probability,
            o.days_in_pipeline  AS days_in_pipeline,
            p.full_name         AS owner_name,
            a.name              AS account_name,
            a.industry          AS industry
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
