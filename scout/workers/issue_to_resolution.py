"""
scout/workers/issue_to_resolution.py — Issue-to-Resolution Process Mining Worker

Mines the Issue-to-Resolution (I2R) process — the lifecycle of a problem
from identification through closure. In a mature tech stack, this worker
would read directly from Zendesk (customer support tickets), Jira (engineering
and ops issues), and PagerDuty (incident data). Until those connectors are
live (Sprint 12), this worker uses CRM data as a structured proxy:

  Proxy signal mapping:
    Open deal stalled >N days      →  Unresolved sales issue
    Account with no won deals      →  Potential service or onboarding issue
    High % of pipeline in early    →  Qualification bottleneck / resolution backlog
    Low closed-to-open ratio       →  More issues entering than being resolved

These proxies are not perfect substitutes for a real ticketing system, but
they are directionally valid and actionable. A deal that has sat in
"Qualification" for 90+ days is, by any definition, an unresolved issue in
the sales process — whether it's a pricing mismatch, a stakeholder blocker,
or a qualification failure.

Why this matters for PE operating partners:
  Issue resolution velocity is a leading indicator of customer satisfaction,
  rep effectiveness, and operational scalability. Companies with low resolution
  rates and high stall rates are burning cash on pipeline they will never close
  and creating churn risk in their customer base. This worker quantifies
  the severity of that problem in terms PE partners can act on.

Roadmap:
  Sprint 12 will add Zendesk and Jira connectors for real I2R process mining:
  ticket volume, first-response time, resolution time, escalation rate, and
  reopening rate. At that point this worker will be upgraded to use ground-truth
  issue data instead of CRM proxies.

Data source: Opportunity and Account nodes in Neo4j. No live CRM or
ticketing-system calls are made here — all analysis runs against the digital twin.
"""

import logging
from collections import Counter
from typing import TYPE_CHECKING

from scout.db.clickhouse import ClickHouseClientBase
from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────────
STALL_DAYS            = 45     # deal in same stage with days_in_pipeline > this = stalled issue
OLD_DEAL_DAYS         = 90     # open deal older than this = stale / unresolved
LOW_STAGE_DEAL        = ["Qualification", "Needs Analysis"]  # early stages where deals linger
EARLY_STAGE_PCT       = 50     # if >50% of open pipeline is in early stages = bottleneck signal
RESOLUTION_RATE_LOW   = 0.5    # closed/open ratio < 0.5 = more issues than resolutions
OVERDUE_THRESHOLD     = 0      # any is_closed=false deal = open issue (threshold in days)


class IssueToResolutionWorker(WorkerBase):
    """
    Surfaces sales-process issue signals: stalled deals, orphaned customers,
    pipeline concentration at bottleneck stages, and resolution velocity proxy —
    all derived from CRM data until Zendesk/Jira connectors are live in Sprint 12.

    All findings clearly document that they are CRM-based proxies, not
    ground-truth issue-tracking data.
    """

    WORKER_NAME = "IssueToResolutionWorker"

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
                title="IssueToResolutionWorker is disabled for this tenant",
                detail="Re-enable this worker in the Admin Portal.",
                severity=Severity.INFO, data={}, recommended_action=None,
            ))
            return result

        try:
            # ── ClickHouse: run regardless of Neo4j state ──────────────────
            if ch_client is not None:
                # P1 SLA: 4 hours
                p1_breaches = ch_client.query_sla_breaches(
                    tenant_id, "ticket", "resolved", sla_hours=4.0
                )
                # All-ticket cycle time
                resolution = ch_client.query_cycle_times(
                    tenant_id, "ticket", "created", "resolved"
                )
                if resolution.count >= 10:
                    median_hours = round(resolution.median_days * 24, 1)
                    p95_hours = round(resolution.p95_days * 24, 1)
                    result.findings.append(Finding(
                        title=(
                            f"Ticket resolution: {median_hours}h median "
                            f"({resolution.count} tickets), {p1_breaches} P1 SLA breaches"
                        ),
                        detail=(
                            f"From ClickHouse event log: {resolution.count} resolved tickets. "
                            f"Median resolution: {median_hours}h, p95: {p95_hours}h. "
                            f"P1 (4-hour SLA) breaches: {p1_breaches}. "
                            + ("P1 SLA breaches indicate critical support process failure." if p1_breaches > 0 else "No P1 SLA breaches detected.")
                        ),
                        severity=(
                            Severity.CRITICAL if p1_breaches > 5 else
                            Severity.HIGH if p1_breaches > 0 or median_hours > 48 else
                            Severity.MEDIUM if median_hours > 24 else
                            Severity.INFO
                        ),
                        data={
                            "process": "Issue-to-Resolution",
                            "median_hours": median_hours,
                            "p95_hours": p95_hours,
                            "p1_sla_breaches": p1_breaches,
                            "sample_size": resolution.count,
                            "p1_sla_hours": 4,
                            "source": "clickhouse_event_log",
                        },
                        recommended_action=(
                            f"Review P1 escalation path. {p1_breaches} breaches in the last 90 days "
                            "suggest either under-staffing on call, unclear escalation criteria, "
                            "or insufficient on-call coverage."
                        ) if p1_breaches > 0 else None,
                    ))
                    result.summary_stats["clickhouse_median_resolution_hours"] = median_hours
                    result.summary_stats["clickhouse_p1_breaches"] = p1_breaches
                    result.summary_stats["clickhouse_event_log"] = True

            open_opps   = self._get_open_opportunities(tenant_id)
            opp_summary = self._get_all_opportunities_summary(tenant_id)

            # ── Load thresholds from config ────────────────────────────────
            t_old_days     = cfg.get("old_deal_days",       OLD_DEAL_DAYS)
            t_stall_days   = cfg.get("stall_days",          STALL_DAYS)
            t_early_pct    = cfg.get("early_stage_pct",     EARLY_STAGE_PCT) / 100
            t_res_low      = cfg.get("resolution_rate_low", RESOLUTION_RATE_LOW)

            if not open_opps and opp_summary.get("total", 0) == 0:
                result.findings.append(Finding(
                    title="No opportunity data found — run a CRM scan first",
                    detail=(
                        "IssueToResolutionWorker uses Opportunity and Account nodes as "
                        "I2R proxies. Connect a Salesforce or HubSpot connector and run a scan."
                    ),
                    severity=Severity.INFO,
                    data={},
                    recommended_action="Enable a CRM connector and trigger a full scan.",
                ))
                result.summary_stats.update({
                    "open_issues_proxy": 0,
                    "stalled_deals": 0,
                    "orphaned_customers": 0,
                    "closed_resolved_proxy": 0,
                    "resolution_rate_proxy": None,
                    "sprint12_upgrade": True,
                })
                return result

            # ── Partition open opportunities ───────────────────────────────
            stalled_deals = [
                o for o in open_opps
                if (o.get("days_in_pipeline") or 0) > t_old_days
            ]
            early_stage_open = [
                o for o in open_opps
                if o.get("stage") in LOW_STAGE_DEAL
            ]

            total_open   = len(open_opps)
            total_closed = opp_summary.get("closed", 0)
            total_won    = opp_summary.get("won", 0)

            resolution_rate = (
                total_closed / total_open if total_open > 0 else None
            )

            # ── Orphaned customers ────────────────────────────────────────
            orphaned = self._get_orphaned_customers(tenant_id)

            result.summary_stats = {
                "open_issues_proxy": total_open,
                "stalled_deals": len(stalled_deals),
                "orphaned_customers": len(orphaned),
                "closed_resolved_proxy": total_closed,
                "resolution_rate_proxy": (
                    round(resolution_rate, 2) if resolution_rate is not None else None
                ),
                "sprint12_upgrade": True,
            }

            # ── Finding 1: Stalled deals (open issues proxy) ───────────────
            if stalled_deals:
                stalled_value = sum(o.get("amount") or 0 for o in stalled_deals)
                severity = (
                    Severity.HIGH
                    if len(stalled_deals) >= 5 or stalled_value >= 250_000
                    else Severity.MEDIUM
                )
                top_stalled = sorted(
                    stalled_deals, key=lambda o: -(o.get("days_in_pipeline") or 0)
                )[:5]
                top_names = ", ".join(
                    f"'{o.get('name')}' ({o.get('days_in_pipeline')} days"
                    + (f", ${o.get('amount'):,.0f}" if o.get("amount") else "")
                    + ")"
                    for o in top_stalled
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(stalled_deals)} stalled deal"
                        f"{'s' if len(stalled_deals) != 1 else ''} — "
                        f"open >{t_old_days} days without closing "
                        f"(${stalled_value:,.0f} at risk)"
                    ),
                    detail=(
                        f"{len(stalled_deals)} open deal"
                        f"{'s have' if len(stalled_deals) != 1 else ' has'} "
                        f"been in the pipeline for more than {t_old_days} days without "
                        f"progressing to closed. These are unresolved sales issues: "
                        f"each represents a prospect stuck in a decision process with no resolution. "
                        f"Longest-stalled: {top_names}. "
                        f"Stalled deals consume rep bandwidth, distort pipeline coverage ratios, "
                        f"and almost never close without active intervention."
                    ),
                    severity=severity,
                    data={
                        "stalled_count": len(stalled_deals),
                        "stalled_value": round(stalled_value),
                        "stall_threshold_days": t_old_days,
                        "stalled_deals": [
                            {
                                "name": o.get("name"),
                                "stage": o.get("stage"),
                                "days_in_pipeline": o.get("days_in_pipeline"),
                                "amount": o.get("amount"),
                                "account_name": o.get("account_name"),
                            }
                            for o in top_stalled
                        ],
                    },
                    recommended_action=(
                        f"Force a push-or-close review for all {len(stalled_deals)} stalled deals "
                        f"in the next sales team meeting. Each deal should be: "
                        f"(1) accelerated with an executive sponsor, (2) repriced or restructured, "
                        f"or (3) marked Closed Lost. Remove stale pipeline — it is worse than "
                        f"no pipeline because it masks the real coverage gap."
                    ),
                ))
            else:
                result.findings.append(Finding(
                    title=(
                        f"No stalled deals detected (threshold: >{t_old_days} days open)"
                    ),
                    detail=(
                        f"All {total_open} open deals have been in the pipeline fewer than "
                        f"{OLD_DEAL_DAYS} days. This is a healthy signal — either deals are "
                        f"moving or stale ones have already been cleaned out."
                    ),
                    severity=Severity.INFO,
                    data={
                        "open_deals": total_open,
                        "stall_threshold_days": t_old_days,
                    },
                    recommended_action=(
                        "Maintain this discipline. Set up a weekly automated flag "
                        "for any deal crossing the {t_stall_days}-day mark without a stage change."
                    ),
                ))

            # ── Finding 2: Orphaned customers (accounts with no won deals) ─
            if orphaned:
                result.findings.append(Finding(
                    title=(
                        f"{len(orphaned)} Customer account"
                        f"{'s' if len(orphaned) != 1 else ''} "
                        f"with zero won deals — potential service or onboarding issue"
                    ),
                    detail=(
                        f"{len(orphaned)} account"
                        f"{'s are' if len(orphaned) != 1 else ' is'} "
                        f"classified as 'Customer' in the CRM but have no closed-won "
                        f"opportunities linked to them. This is an I2R proxy for a "
                        f"service or onboarding issue: either the deal was closed outside "
                        f"the CRM (data gap), the account was miscategorised, or the customer "
                        f"is live but their history wasn't captured. "
                        f"Top orphaned accounts: "
                        f"{', '.join(o.get('account_name', 'Unknown') for o in orphaned[:5])}."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "orphaned_customer_count": len(orphaned),
                        "orphaned_accounts": [
                            {
                                "account_name": o.get("account_name"),
                                "industry": o.get("industry"),
                                "annual_revenue": o.get("annual_revenue"),
                                "employee_count": o.get("employee_count"),
                            }
                            for o in orphaned[:10]
                        ],
                    },
                    recommended_action=(
                        "Audit each orphaned customer account: verify whether a won deal "
                        "exists in the CRM under a different account record, or whether "
                        "the account type is miscategorised. Update records in the CRM. "
                        "If these are genuine customers with no CRM history, back-populate "
                        "the won deal to preserve revenue attribution."
                    ),
                ))

            # ── Finding 3: Early-stage pipeline concentration ──────────────
            if total_open > 0:
                early_stage_pct = (len(early_stage_open) / total_open) * 100
                early_stage_threshold = t_early_pct * 100

                if early_stage_pct > early_stage_threshold:
                    stage_counts = Counter(
                        o.get("stage") or "Unknown" for o in open_opps
                    )
                    result.findings.append(Finding(
                        title=(
                            f"Pipeline bottleneck: {early_stage_pct:.0f}% of open deals "
                            f"are stuck in early stages "
                            f"({', '.join(LOW_STAGE_DEAL)})"
                        ),
                        detail=(
                            f"{len(early_stage_open)} of {total_open} open deals "
                            f"({early_stage_pct:.0f}%) are in {' or '.join(LOW_STAGE_DEAL)}. "
                            f"A pipeline weighted this heavily in early stages is a "
                            f"resolution backlog signal: issues (prospects) are entering "
                            f"the funnel faster than they are being advanced or resolved. "
                            f"This compresses late-stage pipeline and forecasting accuracy. "
                            f"Stage distribution: "
                            + ", ".join(
                                f"{stage}: {count}"
                                for stage, count in stage_counts.most_common(5)
                            )
                            + "."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "early_stage_count": len(early_stage_open),
                            "total_open": total_open,
                            "early_stage_pct": round(early_stage_pct, 1),
                            "early_stage_threshold_pct": early_stage_threshold,
                            "early_stage_names": LOW_STAGE_DEAL,
                            "stage_distribution": dict(stage_counts),
                        },
                        recommended_action=(
                            "Introduce a qualification SLA: any deal in Qualification or "
                            "Needs Analysis for more than 21 days must be reviewed in the "
                            "weekly pipeline call. Either advance it with a defined next step "
                            "or mark it Closed Lost. "
                            "Consider adding a mandatory 'discovery call completed' field "
                            "as an exit criterion for the Qualification stage."
                        ),
                    ))
                else:
                    result.findings.append(Finding(
                        title=(
                            f"Pipeline stage distribution is healthy: "
                            f"{early_stage_pct:.0f}% in early stages "
                            f"(threshold: {early_stage_threshold:.0f}%)"
                        ),
                        detail=(
                            f"Only {len(early_stage_open)} of {total_open} open deals "
                            f"({early_stage_pct:.0f}%) are in early stages "
                            f"({', '.join(LOW_STAGE_DEAL)}), below the {EARLY_STAGE_PCT}% "
                            f"concentration risk threshold. Pipeline is flowing through stages "
                            f"at a healthy rate."
                        ),
                        severity=Severity.INFO,
                        data={
                            "early_stage_count": len(early_stage_open),
                            "total_open": total_open,
                            "early_stage_pct": round(early_stage_pct, 1),
                        },
                        recommended_action=(
                            "Maintain stage progression discipline. "
                            "Review stage distribution weekly in the pipeline call to "
                            "catch any drift before it becomes a bottleneck."
                        ),
                    ))

            # ── Finding 4: Resolution velocity proxy ──────────────────────
            if resolution_rate is not None:
                if resolution_rate < t_res_low:
                    result.findings.append(Finding(
                        title=(
                            f"Low resolution velocity: {total_closed} closed deals "
                            f"vs {total_open} open — ratio {resolution_rate:.2f} "
                            f"(threshold: {RESOLUTION_RATE_LOW})"
                        ),
                        detail=(
                            f"The closed-to-open deal ratio is {resolution_rate:.2f}, "
                            f"meaning there are more unresolved issues (open deals) than "
                            f"resolved ones (closed deals). In a healthy pipeline, closed deals "
                            f"should match or exceed open deals over time as the funnel matures. "
                            f"A ratio below {RESOLUTION_RATE_LOW} signals either a very young "
                            f"pipeline, poor conversion discipline, or a process that creates "
                            f"issues faster than it resolves them. "
                            f"Current: {total_won} won, {total_closed - total_won} lost, "
                            f"{total_open} open."
                        ),
                        severity=Severity.MEDIUM,
                        data={
                            "open_deals": total_open,
                            "closed_deals": total_closed,
                            "won_deals": total_won,
                            "lost_deals": total_closed - total_won,
                            "resolution_rate": round(resolution_rate, 3),
                            "resolution_rate_threshold": t_res_low,
                        },
                        recommended_action=(
                            "Set a target of closing (won or lost) at least as many deals "
                            "each month as are created. Run a monthly 'stale deal amnesty': "
                            "force all deals >60 days old to be pushed to a next stage or "
                            "marked Closed Lost. A clean pipeline is better than a large one."
                        ),
                    ))
                else:
                    result.findings.append(Finding(
                        title=(
                            f"Resolution velocity proxy is healthy: "
                            f"ratio {resolution_rate:.2f} "
                            f"({total_closed} closed vs {total_open} open)"
                        ),
                        detail=(
                            f"The closed-to-open deal ratio is {resolution_rate:.2f}, "
                            f"at or above the {t_res_low} threshold. "
                            f"Closed deals ({total_closed}) are keeping pace with or "
                            f"outpacing open ones ({total_open}), which suggests the "
                            f"sales process is resolving issues at a healthy rate. "
                            f"Won: {total_won}, Lost: {total_closed - total_won}."
                        ),
                        severity=Severity.INFO,
                        data={
                            "open_deals": total_open,
                            "closed_deals": total_closed,
                            "won_deals": total_won,
                            "resolution_rate": round(resolution_rate, 3),
                        },
                        recommended_action=(
                            "Maintain the closed-deal cadence. Track the ratio monthly "
                            "and alert if it drops below {t_res_low} — that is the leading indicator "
                            "of a pipeline health problem before it shows up in revenue."
                        ),
                    ))

            # ── Sprint 26: Emit follow-up actions for stalled deals ────────
            if db is not None and stalled_deals:
                self._emit_stalled_deal_actions(
                    db, tenant_id, stalled_deals, result
                )

        except Exception as exc:
            logger.exception(
                f"IssueToResolutionWorker failed for tenant {tenant_id}: {exc}"
            )
            result.error = str(exc)

        return result

    # ── Helper methods ──────────────────────────────────────────────────────

    def _emit_stalled_deal_actions(
        self,
        db: "Session",
        tenant_id: str,
        stalled_deals: list[dict],
        result: WorkerResult,
    ) -> None:
        """
        Emit a log_activity ActionSpec for each stalled deal so the executor
        can automatically log a follow-up task in SFDC and notify the owner.
        """
        from scout.actions.factory import ActionFactory, stalled_deal_followup

        factory = ActionFactory(db, tenant_id)
        actions_emitted = 0

        for deal in stalled_deals:
            opp_id = deal.get("canonical_id") or ""
            opp_name = deal.get("name") or "Unknown Opportunity"
            account_id = deal.get("account_canonical_id") or opp_id
            days_stalled = deal.get("days_in_pipeline") or 0
            amount = deal.get("amount")
            owner_email = deal.get("owner_email")

            if not opp_id:
                continue

            finding_hash = f"i2r-stalled-{tenant_id}-{opp_id}"

            factory.emit(stalled_deal_followup(
                finding_hash=finding_hash,
                worker_name=self.WORKER_NAME,
                opportunity_name=opp_name,
                opportunity_id=opp_id,
                account_id=account_id,
                days_stalled=days_stalled,
                owner_email=owner_email,
                arr_at_risk=float(amount) if amount else None,
            ))
            actions_emitted += 1

        created = factory.flush()
        result.summary_stats["actions_emitted"] = actions_emitted
        result.summary_stats["action_ids_created"] = len(created)
        logger.info(
            f"IssueToResolutionWorker: emitted {actions_emitted} stalled-deal action specs "
            f"→ {len(created)} new actions for tenant {tenant_id}"
        )

    def _get_open_opportunities(self, tenant_id: str) -> list[dict]:
        """
        Fetch all open (is_closed=false) opportunities with pipeline age and account context.

        Uses OPTIONAL MATCH for account so that deals without an account link
        are still returned — they may represent the most stale/orphaned issues.
        """
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.canonical_id      AS canonical_id,
            o.name              AS name,
            o.stage             AS stage,
            o.amount            AS amount,
            o.days_in_pipeline  AS days_in_pipeline,
            o.is_closed         AS is_closed,
            a.name              AS account_name
        ORDER BY o.days_in_pipeline DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_orphaned_customers(self, tenant_id: str) -> list[dict]:
        """
        Return Customer-type accounts that have no closed-won opportunities linked to them.

        An 'orphaned customer' is an account classified as Customer in the CRM
        but with no evidence of a closed deal — a data quality gap or a service
        issue proxy. This is the same query pattern as CrossSellIntelligenceWorker's
        dormant customer detection.
        """
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: "Customer"})
        WHERE NOT EXISTS {
            MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: true, is_won: true})
                  -[:IN_ACCOUNT]->(a)
        }
        RETURN
            a.canonical_id      AS canonical_id,
            a.name              AS account_name,
            a.industry          AS industry,
            a.annual_revenue    AS annual_revenue,
            a.employee_count    AS employee_count
        ORDER BY a.annual_revenue DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_all_opportunities_summary(self, tenant_id: str) -> dict:
        """
        Return aggregate counts across all opportunities for the tenant.

        Provides the total, closed, and won counts needed for resolution
        rate calculation without pulling every opportunity into memory.
        """
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id})
        RETURN
            count(o)                                                        AS total,
            count(CASE WHEN o.is_closed = true THEN 1 END)                 AS closed,
            count(CASE WHEN o.is_closed = true AND o.is_won = true THEN 1 END) AS won
        """
        with self.driver.session() as session:
            row = session.run(query, tenant_id=tenant_id).single()
            if row:
                return dict(row)
            return {"total": 0, "closed": 0, "won": 0}
