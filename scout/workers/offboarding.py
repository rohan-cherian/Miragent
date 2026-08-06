"""
scout/workers/offboarding.py — Offboarding Impact Assessment Worker

Identifies operational risk from employee departures (inactive persons) and
generates offboarding impact assessments. Key risks: accounts with only one
owner who is now inactive, open deals owned by inactive reps, and manager
vacancies created when a departing employee had direct reports.

Revenue risk from unmanaged offboarding is consistently underestimated:
a single AE departure can put $500k+ of pipeline at risk within 30 days
if deals are not reassigned. Customer accounts owned by a departed rep are
at elevated churn risk — relationships go cold without active ownership.

Sprint 12 will trigger automated HRIS offboarding via Workday and revoke
system access via Okta within minutes of the is_active flag changing, rather
than relying on manual IT tickets that typically take 3-5 business days.
"""

import logging

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)


class OffboardingWorker(WorkerBase):
    """
    Surfaces revenue and relationship risk created by inactive (departed)
    employees. Identifies accounts at churn risk, pipeline in limbo, and
    management vacuums left by departing people managers.
    """

    WORKER_NAME = "OffboardingWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            inactive_persons = self._get_inactive_persons(tenant_id)
            at_risk_accounts = self._get_accounts_by_inactive_owners(tenant_id)
            at_risk_deals = self._get_deals_by_inactive_owners(tenant_id)
            orphaned_manager_rows = self._get_orphaned_reports(tenant_id)

            # Derived metrics
            total_arr_at_risk = sum(
                (row.get("total_won") or 0) for row in at_risk_accounts
            )
            total_pipeline_at_risk = sum(
                (row.get("amount") or 0) for row in at_risk_deals
            )
            orphaned_reports: list[str] = []
            for row in orphaned_manager_rows:
                for name in (row.get("reports") or []):
                    orphaned_reports.append(name)

            result.summary_stats = {
                "inactive_persons": len(inactive_persons),
                "accounts_at_risk": len(at_risk_accounts),
                "deals_at_risk": len(at_risk_deals),
                "total_arr_at_risk": round(total_arr_at_risk),
                "total_pipeline_at_risk": round(total_pipeline_at_risk),
                "orphaned_reports": len(orphaned_reports),
            }

            # ── Finding 1: Accounts owned by inactive reps ────────────────
            if at_risk_accounts:
                critical_accounts = [
                    row for row in at_risk_accounts
                    if (row.get("total_won") or 0) > cfg.get("high_arr_risk")
                ]
                high_accounts = [
                    row for row in at_risk_accounts
                    if (row.get("total_won") or 0) <= cfg.get("high_arr_risk")
                ]

                if critical_accounts:
                    top_critical = sorted(
                        critical_accounts, key=lambda r: -(r.get("total_won") or 0)
                    )[:4]
                    top_names = ", ".join(
                        f"{r.get('account_name')} (${r.get('total_won') or 0:,.0f} ARR, "
                        f"owner: {r.get('owner')})"
                        for r in top_critical
                    )
                    result.findings.append(Finding(
                        title=(
                            f"{len(critical_accounts)} high-ARR account"
                            f"{'s' if len(critical_accounts) != 1 else ''} owned by inactive reps "
                            f"— CRITICAL churn risk"
                        ),
                        detail=(
                            f"{len(critical_accounts)} customer account"
                            f"{'s have' if len(critical_accounts) != 1 else ' has'} "
                            f"total won ARR above ${cfg.get('high_arr_risk'):,.0f} and are owned "
                            f"by departed employees. These accounts have no active relationship "
                            f"owner and are at high churn risk. "
                            f"Examples: {top_names}."
                        ),
                        severity=Severity.CRITICAL,
                        data={
                            "account_count": len(critical_accounts),
                            "arr_threshold": cfg.get("high_arr_risk"),
                            "accounts": [
                                {
                                    "account_name": r.get("account_name"),
                                    "account_type": r.get("account_type"),
                                    "owner": r.get("owner"),
                                    "total_won": r.get("total_won"),
                                }
                                for r in critical_accounts
                            ],
                        },
                        recommended_action=(
                            "Reassign each critical account to an active CSM or AE today. "
                            "Send a personal introduction email from the new owner within 48 hours. "
                            "Schedule an EBR within 30 days to re-establish the relationship. "
                            "Flag these accounts in the CRM as 'At-Risk: Owner Departed'."
                        ),
                    ))

                if high_accounts:
                    top_names = ", ".join(
                        f"{r.get('account_name')} (owner: {r.get('owner')})"
                        for r in high_accounts[:4]
                    )
                    result.findings.append(Finding(
                        title=(
                            f"{len(high_accounts)} account"
                            f"{'s' if len(high_accounts) != 1 else ''} owned by inactive reps "
                            f"— relationship coverage gap"
                        ),
                        detail=(
                            f"{len(high_accounts)} account"
                            f"{'s have' if len(high_accounts) != 1 else ' has'} "
                            f"a departed employee as owner with lower ARR (≤${cfg.get('high_arr_risk'):,.0f}). "
                            f"These require reassignment to prevent relationship decay. "
                            f"Examples: {top_names}."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "account_count": len(high_accounts),
                            "accounts": [
                                {
                                    "account_name": r.get("account_name"),
                                    "account_type": r.get("account_type"),
                                    "owner": r.get("owner"),
                                    "total_won": r.get("total_won"),
                                }
                                for r in high_accounts
                            ],
                        },
                        recommended_action=(
                            "Reassign all accounts owned by inactive reps within this week. "
                            "Prioritise by ARR. For Prospect accounts, ensure the new owner "
                            "reviews the deal history before the next touchpoint."
                        ),
                    ))

            # ── Finding 2: Open deals owned by inactive reps ──────────────
            if at_risk_deals:
                top_deals = sorted(
                    at_risk_deals, key=lambda r: -(r.get("amount") or 0)
                )
                top_names = ", ".join(
                    f"{r.get('deal_name')} (${r.get('amount') or 0:,.0f}, "
                    f"{r.get('stage')}, owner: {r.get('owner')})"
                    for r in top_deals[:4]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(at_risk_deals)} open deal"
                        f"{'s' if len(at_risk_deals) != 1 else ''} owned by inactive reps "
                        f"— ${total_pipeline_at_risk:,.0f} pipeline at risk"
                    ),
                    detail=(
                        f"{len(at_risk_deals)} open opportunit"
                        f"{'ies' if len(at_risk_deals) != 1 else 'y'} "
                        f"(${total_pipeline_at_risk:,.0f} total) are owned by departed employees. "
                        f"Without an active rep, these deals will stall and ultimately be lost. "
                        f"Top deals: {top_names}."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "deal_count": len(at_risk_deals),
                        "total_pipeline": round(total_pipeline_at_risk),
                        "high_risk_threshold": cfg.get("high_deal_risk"),
                        "deals": [
                            {
                                "deal_name": r.get("deal_name"),
                                "amount": r.get("amount"),
                                "stage": r.get("stage"),
                                "owner": r.get("owner"),
                            }
                            for r in top_deals
                        ],
                    },
                    recommended_action=(
                        "Reassign all open deals from departed reps within 24 hours. "
                        "For deals >$50k, the sales manager should personally brief the "
                        "incoming rep and introduce them to the prospect via email. "
                        "Check deal notes and email history before the first outreach call."
                    ),
                ))

            # ── Finding 3: Manager vacancies ──────────────────────────────
            if orphaned_manager_rows:
                vacancy_items = []
                for row in orphaned_manager_rows:
                    reports_list = row.get("reports") or []
                    vacancy_items.append({
                        "departed_manager": row.get("manager"),
                        "orphaned_reports": reports_list,
                        "orphaned_count": len(reports_list),
                    })

                total_orphaned = sum(v["orphaned_count"] for v in vacancy_items)
                manager_names = ", ".join(v["departed_manager"] for v in vacancy_items[:4])

                result.findings.append(Finding(
                    title=(
                        f"{len(orphaned_manager_rows)} manager vacanc"
                        f"{'ies' if len(orphaned_manager_rows) != 1 else 'y'} "
                        f"— {total_orphaned} direct report"
                        f"{'s' if total_orphaned != 1 else ''} without a manager"
                    ),
                    detail=(
                        f"{len(orphaned_manager_rows)} departed employee"
                        f"{'s were' if len(orphaned_manager_rows) != 1 else ' was'} "
                        f"managing direct reports via MANAGES relationships. "
                        f"Their {total_orphaned} report"
                        f"{'s are' if total_orphaned != 1 else ' is'} now without an active manager. "
                        f"Departed managers: {manager_names}. "
                        f"Orphaned reports have no performance feedback loop, no escalation path, "
                        f"and are at elevated attrition risk."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "manager_vacancy_count": len(orphaned_manager_rows),
                        "total_orphaned_reports": total_orphaned,
                        "vacancies": vacancy_items,
                    },
                    recommended_action=(
                        "Assign an interim manager to each orphaned report today — "
                        "even a temporary reporting line is better than none. "
                        "The CHRO should schedule 1:1s with orphaned reports within 5 business days. "
                        "Open a backfill requisition immediately for any manager vacancy."
                    ),
                ))

            # ── Finding 4: Offboarding impact summary ─────────────────────
            result.findings.append(Finding(
                title=(
                    f"Offboarding impact summary: ${total_arr_at_risk:,.0f} ARR at risk, "
                    f"${total_pipeline_at_risk:,.0f} pipeline at risk, "
                    f"{len(orphaned_reports)} orphaned report"
                    f"{'s' if len(orphaned_reports) != 1 else ''}"
                ),
                detail=(
                    f"Across {len(inactive_persons)} inactive employee"
                    f"{'s' if len(inactive_persons) != 1 else ''}: "
                    f"${total_arr_at_risk:,.0f} of won ARR sits in accounts with no active owner; "
                    f"${total_pipeline_at_risk:,.0f} of open pipeline is orphaned; "
                    f"{len(orphaned_reports)} direct report"
                    f"{'s have' if len(orphaned_reports) != 1 else ' has'} no manager. "
                    f"This is the cost of unmanaged offboarding — it is recoverable if acted on "
                    f"within the first week of departure."
                ),
                severity=Severity.INFO,
                data={
                    "inactive_person_count": len(inactive_persons),
                    "total_arr_at_risk": round(total_arr_at_risk),
                    "total_pipeline_at_risk": round(total_pipeline_at_risk),
                    "orphaned_reports_count": len(orphaned_reports),
                    "accounts_at_risk_count": len(at_risk_accounts),
                    "deals_at_risk_count": len(at_risk_deals),
                },
                recommended_action=(
                    "Use this summary as the offboarding impact brief for the CEO and CRO. "
                    "Act on account and deal reassignment within 24-48 hours of departure. "
                    "Track recovery rate (% of at-risk ARR that did not churn) as a quarterly KPI."
                ),
            ))

        except Exception as exc:
            logger.exception(f"OffboardingWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Query helpers ───────────────────────────────────────────────────────

    def _get_inactive_persons(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: false})
        RETURN p.canonical_id AS canonical_id, p.full_name AS full_name,
               p.department AS department, p.title AS title
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_accounts_by_inactive_owners(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: false})-[:OWNS]->(a:Account {tenant_id: $tenant_id})
        OPTIONAL MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WITH p, a, coalesce(sum(o.amount), 0) AS total_won
        RETURN p.full_name AS owner, a.name AS account_name,
               a.account_type AS account_type, total_won
        ORDER BY total_won DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_deals_by_inactive_owners(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: false})-[:OWNS_DEAL]->(o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        RETURN p.full_name AS owner, o.name AS deal_name,
               o.amount AS amount, o.stage AS stage
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_orphaned_reports(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (mgr:Person {tenant_id: $tenant_id, is_active: false})<-[:MANAGES]-(report:Person {tenant_id: $tenant_id, is_active: true})
        RETURN mgr.full_name AS manager, collect(report.full_name) AS reports
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
