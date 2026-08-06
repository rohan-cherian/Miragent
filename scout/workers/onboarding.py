"""
scout/workers/onboarding.py — Onboarding Checklist and Coverage Gap Worker

Generates structured onboarding checklists and risk assessments for new team
members and for accounts that need relationship coverage. Identifies gaps in
account ownership (accounts with no owner), deals with no assigned rep, and
departments with no leadership coverage.

Sprint 12 will trigger real HRIS onboarding workflows via Workday/BambooHR,
automatically provisioning system access, scheduling orientation sessions, and
routing onboarding tasks to the right stakeholders based on role and department.
"""

import logging

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

CHECKLIST_ITEMS_SALES = [
    "Set up CRM access and complete Salesforce training",
    "Shadow 3 discovery calls with top-performing AE",
    "Study the ICP definition and 5 customer case studies",
    "Complete product certification (demo environment)",
    "Shadow a CSM on a customer QBR",
    "Build a list of 50 target accounts in your territory",
    "Complete first solo discovery call with manager review",
]

CHECKLIST_ITEMS_OPS = [
    "Complete system access requests (Neo4j, AWS, GitHub)",
    "Review runbook and on-call documentation",
    "Shadow existing team member for first 2 weeks",
    "Complete security training and sign security policy",
    "Set up monitoring dashboards and alerting",
]

CHECKLIST_ITEMS_DEFAULT = [
    "Complete company onboarding (HR systems, benefits, equipment)",
    "Review org chart and schedule 1:1s with direct team",
    "Shadow your manager for the first week",
    "Read the company strategy document",
    "Set 30/60/90 day goals with your manager",
]


class OnboardingWorker(WorkerBase):
    """
    Surfaces account ownership gaps, unassigned open deals, and department
    coverage thin spots. Generates role-appropriate onboarding checklists
    so new hires have a structured first-90-days plan from day one.
    """

    WORKER_NAME = "OnboardingWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            unowned_accounts = self._get_unowned_accounts(tenant_id)
            unassigned_deals = self._get_unassigned_deals(tenant_id)
            dept_coverage = self._get_department_coverage(tenant_id)

            # Departments with only 1 active person (understaffed)
            understaffed_depts = [
                row for row in dept_coverage if row.get("active_count", 0) < 2
            ]

            result.summary_stats = {
                "unowned_accounts": len(unowned_accounts),
                "unassigned_deals": len(unassigned_deals),
                "understaffed_departments": len(understaffed_depts),
                "checklist_templates_generated": 3,
            }

            # ── Finding 1: Unowned accounts ───────────────────────────────
            if unowned_accounts:
                severity = (
                    Severity.HIGH
                    if len(unowned_accounts) >= cfg.get("unowned_account_risk_high")
                    else Severity.MEDIUM
                )
                account_list = [
                    {"name": row.get("name"), "account_type": row.get("account_type"),
                     "industry": row.get("industry")}
                    for row in unowned_accounts
                ]
                top_names = ", ".join(
                    f"{row.get('name')} ({row.get('account_type')})"
                    for row in unowned_accounts[:5]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(unowned_accounts)} account"
                        f"{'s' if len(unowned_accounts) != 1 else ''} with no assigned owner"
                    ),
                    detail=(
                        f"{len(unowned_accounts)} Customer or Prospect account"
                        f"{'s have' if len(unowned_accounts) != 1 else ' has'} no Person "
                        f"with an OWNS relationship in the graph. These accounts have no named "
                        f"relationship owner — meaning no one is responsible for renewals, "
                        f"expansions, or churn prevention. "
                        f"Examples: {top_names}."
                        + (" This volume of unowned accounts represents a systemic coverage gap." if len(unowned_accounts) >= cfg.get("unowned_account_risk_high") else "")
                    ),
                    severity=severity,
                    data={
                        "unowned_account_count": len(unowned_accounts),
                        "risk_threshold": cfg.get("unowned_account_risk_high"),
                        "accounts": account_list,
                    },
                    recommended_action=(
                        "Assign an account owner to every Customer and Prospect account "
                        "immediately. Use this list to drive the onboarding territory assignment "
                        "for any incoming reps. Unowned accounts with >$100k ARR should be "
                        "escalated to the VP of Sales this week."
                    ),
                ))

            # ── Finding 2: Open deals with no owner ───────────────────────
            if unassigned_deals:
                total_unassigned_value = sum(
                    (row.get("amount") or 0) for row in unassigned_deals
                )
                deal_list = [
                    {"name": row.get("name"), "amount": row.get("amount"),
                     "stage": row.get("stage")}
                    for row in unassigned_deals
                ]
                top_deals = ", ".join(
                    f"{row.get('name')} (${row.get('amount') or 0:,.0f}, {row.get('stage')})"
                    for row in sorted(
                        unassigned_deals, key=lambda r: -(r.get("amount") or 0)
                    )[:4]
                )
                result.findings.append(Finding(
                    title=(
                        f"{len(unassigned_deals)} open deal"
                        f"{'s' if len(unassigned_deals) != 1 else ''} with no assigned rep "
                        f"— ${total_unassigned_value:,.0f} at risk"
                    ),
                    detail=(
                        f"{len(unassigned_deals)} open opportunit"
                        f"{'ies' if len(unassigned_deals) != 1 else 'y'} "
                        f"(total ${total_unassigned_value:,.0f}) have no rep with an OWNS_DEAL "
                        f"relationship. These deals are stalled by definition — nobody is "
                        f"actively moving them forward. "
                        f"Examples: {top_deals}."
                    ),
                    severity=Severity.HIGH,
                    data={
                        "unassigned_deal_count": len(unassigned_deals),
                        "total_unassigned_value": round(total_unassigned_value),
                        "deals": deal_list,
                    },
                    recommended_action=(
                        "Assign each open deal to a rep today. For incoming hires, "
                        "use unassigned deals as a structured ramp exercise — "
                        "new reps inherit a deal and shadow a senior AE on the re-engagement call. "
                        "Any deal >$50k without an owner needs same-day escalation."
                    ),
                ))

            # ── Finding 3: Department coverage gaps ───────────────────────
            if understaffed_depts:
                dept_names = [row.get("department") for row in understaffed_depts]
                result.findings.append(Finding(
                    title=(
                        f"{len(understaffed_depts)} department"
                        f"{'s' if len(understaffed_depts) != 1 else ''} with only 1 active person "
                        f"— coverage risk"
                    ),
                    detail=(
                        f"The following department"
                        f"{'s have' if len(understaffed_depts) != 1 else ' has'} "
                        f"fewer than 2 active team members, creating single-point-of-failure risk: "
                        f"{', '.join(str(d) for d in dept_names)}. "
                        f"If the sole person in a department is out, there is no coverage. "
                        f"These departments should be prioritised for onboarding new hires."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "understaffed_department_count": len(understaffed_depts),
                        "departments": [
                            {"department": row.get("department"),
                             "active_count": row.get("active_count")}
                            for row in understaffed_depts
                        ],
                    },
                    recommended_action=(
                        "Flag each understaffed department in the headcount plan. "
                        "For any department critical to revenue or operations (Sales, Engineering, "
                        "Support), escalate to the CHRO. Use onboarding checklists below to "
                        "accelerate ramp for incoming hires."
                    ),
                ))

            # ── Finding 4a: Onboarding checklist — Sales ──────────────────
            result.findings.append(Finding(
                title="Onboarding checklist generated: Sales department (7 items)",
                detail=(
                    "Structured 30-day onboarding checklist for Sales new hires. "
                    "Covers CRM setup, discovery call shadowing, product certification, "
                    "and first solo call with manager review."
                ),
                severity=Severity.INFO,
                data={
                    "department": "Sales",
                    "checklist": CHECKLIST_ITEMS_SALES,
                    "item_count": len(CHECKLIST_ITEMS_SALES),
                },
                recommended_action=(
                    "Share this checklist with the Sales hiring manager. "
                    "Schedule a 30-day check-in to validate completion. "
                    "Update the checklist quarterly as the product and ICP evolve."
                ),
            ))

            # ── Finding 4b: Onboarding checklist — Operations ─────────────
            result.findings.append(Finding(
                title="Onboarding checklist generated: Operations department (5 items)",
                detail=(
                    "Structured onboarding checklist for Operations and Engineering new hires. "
                    "Covers system access, security training, on-call documentation review, "
                    "and monitoring setup."
                ),
                severity=Severity.INFO,
                data={
                    "department": "Operations",
                    "checklist": CHECKLIST_ITEMS_OPS,
                    "item_count": len(CHECKLIST_ITEMS_OPS),
                },
                recommended_action=(
                    "Share this checklist with the Engineering or Ops hiring manager. "
                    "Ensure the security policy sign-off is completed in week 1 — "
                    "it is typically an audit requirement."
                ),
            ))

            # ── Finding 4c: Onboarding checklist — Default ────────────────
            result.findings.append(Finding(
                title="Onboarding checklist generated: General / cross-functional (5 items)",
                detail=(
                    "Default onboarding checklist for all departments not covered by a "
                    "role-specific template (Finance, Marketing, HR, etc.). "
                    "Covers company onboarding, org chart review, manager shadowing, "
                    "and 30/60/90 day goal-setting."
                ),
                severity=Severity.INFO,
                data={
                    "department": "General",
                    "checklist": CHECKLIST_ITEMS_DEFAULT,
                    "item_count": len(CHECKLIST_ITEMS_DEFAULT),
                },
                recommended_action=(
                    "Assign this checklist to every new hire who does not fall into a "
                    "Sales or Operations role. Review completion at the 30-day mark."
                ),
            ))

        except Exception as exc:
            logger.exception(f"OnboardingWorker failed for tenant {tenant_id}: {exc}")
            result.error = str(exc)

        return result

    # ── Query helpers ───────────────────────────────────────────────────────

    def _get_unowned_accounts(self, tenant_id: str) -> list[dict]:
        """
        Accounts (Customer or Prospect) with no Person OWNS relationship.
        """
        query = """
        MATCH (a:Account {tenant_id: $tenant_id})
        WHERE (a.account_type = 'Customer' OR a.account_type = 'Prospect')
          AND NOT EXISTS {
            MATCH (p:Person)-[:OWNS]->(a)
          }
        RETURN a.name AS name, a.account_type AS account_type, a.industry AS industry
        ORDER BY a.annual_revenue DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_unassigned_deals(self, tenant_id: str) -> list[dict]:
        """
        Open opportunities with no Person OWNS_DEAL relationship.
        """
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        WHERE NOT EXISTS {
            MATCH (p:Person)-[:OWNS_DEAL]->(o)
        }
        RETURN o.name AS name, o.amount AS amount, o.stage AS stage
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_department_coverage(self, tenant_id: str) -> list[dict]:
        """
        Active headcount per department, ordered ascending so thin departments
        appear first.
        """
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})
        RETURN p.department AS department, count(p) AS active_count
        ORDER BY active_count ASC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
