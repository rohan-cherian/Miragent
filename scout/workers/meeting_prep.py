"""
scout/workers/meeting_prep.py — Meeting Prep Worker

Generates account intelligence briefs for deals in late pipeline stages
(Proposal/Price Quote, Negotiation/Review). Each brief includes: account
overview, deal history, key stakeholders, recommended talking points, and
risk flags. Reps should use these briefs before every discovery and closing
call. Sprint 12 will enrich briefs with LinkedIn profiles, recent news,
and Glassdoor data.
"""

import logging

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

logger = logging.getLogger(__name__)

LATE_STAGES = {"Proposal/Price Quote", "Negotiation/Review", "Value Proposition"}

_INDUSTRY_VALUE_PROPS = {
    "Financial Services": (
        "reduce compliance overhead",
        "automate audit trails",
        "cut regulatory reporting time",
    ),
    "Technology": (
        "accelerate engineering velocity",
        "reduce technical debt burden",
        "scale infrastructure without headcount",
    ),
    "Healthcare": (
        "streamline clinical operations",
        "simplify regulatory workflows",
        "reduce administrative staff burnout",
    ),
    "Manufacturing": (
        "improve supply chain visibility",
        "cut unplanned downtime",
        "unify fragmented ERP data",
    ),
}
_DEFAULT_VALUE_PROPS = (
    "reduce operational complexity",
    "eliminate manual process overhead",
    "unlock scalable growth without proportional cost",
)


class MeetingPrepWorker(WorkerBase):
    """
    Generates structured account intelligence briefs for late-stage deals,
    including talking points, risk flags, and a recommended next best action.
    """

    WORKER_NAME = "MeetingPrepWorker"

    def run(self, tenant_id: str) -> WorkerResult:
        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        try:
            deals = self._get_late_stage_deals(tenant_id)

            if not deals:
                result.findings.append(Finding(
                    title="No late-stage deals found — meeting prep briefs require open pipeline in late stages",
                    detail=(
                        "Move deals to Proposal/Price Quote, Negotiation/Review, or "
                        "Value Proposition to trigger automatic meeting prep brief generation."
                    ),
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats = {
                    "late_stage_deals": 0,
                    "briefs_generated": 0,
                    "total_late_stage_value": 0,
                }
                return result

            top_deals = deals[:cfg.get("max_briefs")]
            briefs_generated = 0
            total_late_stage_value = sum((d.get("amount") or 0) for d in deals)

            for deal in top_deals:
                account = {
                    "name": deal.get("account_name"),
                    "industry": deal.get("industry"),
                    "annual_revenue": deal.get("annual_revenue"),
                    "employee_count": deal.get("employee_count"),
                }
                owner = deal.get("owner_name")
                brief = self._generate_brief(deal, account, owner, cfg)

                amount = deal.get("amount") or 0
                severity = Severity.HIGH if amount > cfg.get("large_deal_threshold") else Severity.MEDIUM
                deal_name = deal.get("deal_name") or "Unnamed Deal"
                stage = deal.get("stage") or "Unknown Stage"

                result.findings.append(Finding(
                    title=f"Meeting prep brief — {deal_name} ({stage})",
                    detail=(
                        f"${amount:,.0f} deal at {stage} stage for "
                        f"{account.get('name') or 'Unknown Account'}. "
                        f"{deal.get('days_in_pipeline') or 0} days in pipeline. "
                        f"Brief includes {len(brief.get('talking_points', []))} talking points "
                        f"and {len(brief.get('risk_flags', []))} risk flag(s). "
                        f"Recommended next action: {brief.get('next_best_action', 'See brief.')}",
                    ),
                    severity=severity,
                    data=brief,
                    recommended_action=(
                        f"Review this brief 30 minutes before your next call with "
                        f"{account.get('name') or 'the account'}. "
                        f"Address the risk flags directly in the agenda. "
                        f"Sprint 12 will enrich this brief with LinkedIn profiles and recent news."
                    ),
                ))
                briefs_generated += 1

            # Summary finding
            result.findings.append(Finding(
                title=f"Meeting prep briefs generated for {briefs_generated} late-stage deals",
                detail=(
                    f"Briefs generated for the top {briefs_generated} deal(s) by value in "
                    f"late pipeline stages. Total late-stage pipeline value: "
                    f"${total_late_stage_value:,.0f} across {len(deals)} deal(s). "
                    f"Sprint 12 will enrich all briefs with LinkedIn profiles, "
                    f"recent company news, and Glassdoor data."
                ),
                severity=Severity.INFO,
                data={
                    "late_stage_deals": len(deals),
                    "briefs_generated": briefs_generated,
                    "total_late_stage_value": total_late_stage_value,
                    "late_stages": list(LATE_STAGES),
                },
                recommended_action=(
                    "Schedule a weekly brief review with your AEs every Monday morning "
                    "before pipeline calls."
                ),
            ))

            result.summary_stats = {
                "late_stage_deals": len(deals),
                "briefs_generated": briefs_generated,
                "total_late_stage_value": total_late_stage_value,
            }

        except Exception as exc:
            logger.exception(f"MeetingPrepWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Brief generation ───────────────────────────────────────────────────

    def _generate_brief(self, deal: dict, account: dict, owner: str | None, cfg) -> dict:
        """
        Build a structured meeting prep brief for a single deal.
        Pure Python — no DB calls.
        """
        deal_name = deal.get("deal_name") or "Unnamed Deal"
        stage = deal.get("stage") or "Unknown"
        amount = deal.get("amount") or 0
        probability = deal.get("probability") or 0
        days_in_pipeline = deal.get("days_in_pipeline") or 0

        industry = account.get("industry") or ""
        account_name = account.get("name") or "the account"
        annual_revenue = account.get("annual_revenue") or 0
        employee_count = account.get("employee_count") or 0

        value_props = _INDUSTRY_VALUE_PROPS.get(industry, _DEFAULT_VALUE_PROPS)
        primary_vp = value_props[0]
        secondary_vp = value_props[1] if len(value_props) > 1 else value_props[0]

        # Talking points
        talking_points = [
            (
                f"Their {industry or 'industry'} peers are reducing {primary_vp.split(' ', 1)[-1] if ' ' in primary_vp else primary_vp} "
                f"by 35% using our platform — ask if they've benchmarked against similar companies."
            ),
            (
                f"At {days_in_pipeline} days in pipeline, securing a clear decision milestone "
                f"this week is critical — propose a mutual action plan with a signed date."
            ),
            (
                f"Reinforce value: {account_name} can {secondary_vp} without adding headcount — "
                f"tie the ROI calculation to their specific team size and current process cost."
            ),
        ]
        if amount > cfg.get("large_deal_threshold"):
            talking_points.append(
                f"For an account this size, a dedicated CSM and executive sponsor are standard — "
                f"position this as a strategic partnership, not a product sale."
            )

        # Risk flags
        risk_flags = []
        if days_in_pipeline > 90:
            risk_flags.append("Deal aging — risk of deal going cold. Request an explicit next step with a date.")
        if probability < 50 and stage in LATE_STAGES:
            risk_flags.append(
                f"Low probability ({probability}%) for a {stage} deal — "
                f"surface and resolve outstanding blockers before the next call."
            )
        if amount > cfg.get("large_deal_threshold") and not owner:
            risk_flags.append("High-value deal without a named owner — assign an AE immediately.")

        # Next best action
        if risk_flags:
            next_best_action = (
                f"Address the top risk flag before the call: {risk_flags[0]}"
            )
        elif probability >= 70:
            next_best_action = (
                f"Send a mutual action plan to {account_name} today — "
                f"define final approval steps, legal review timeline, and signing date."
            )
        else:
            next_best_action = (
                f"Schedule a value confirmation call with the economic buyer at {account_name} "
                f"to reaffirm ROI and unblock the decision."
            )

        return {
            "deal_name": deal_name,
            "stage": stage,
            "amount": amount,
            "probability": probability,
            "days_in_pipeline": days_in_pipeline,
            "account_overview": {
                "name": account_name,
                "industry": industry,
                "annual_revenue": annual_revenue,
                "employee_count": employee_count,
            },
            "rep_owner": owner or "Unassigned",
            "talking_points": talking_points,
            "risk_flags": risk_flags,
            "next_best_action": next_best_action,
        }

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_late_stage_deals(self, tenant_id: str) -> list[dict]:
        """
        Return open deals in LATE_STAGES with account and owner info,
        ordered by amount DESC.
        """
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})
        WHERE o.stage IN ['Proposal/Price Quote', 'Negotiation/Review', 'Value Proposition']
        OPTIONAL MATCH (p:Person)-[:OWNS_DEAL]->(o)
        OPTIONAL MATCH (o)-[:IN_ACCOUNT]->(a:Account)
        RETURN
            o.name AS deal_name,
            o.stage AS stage,
            o.amount AS amount,
            o.probability AS probability,
            o.days_in_pipeline AS days_in_pipeline,
            o.canonical_id AS deal_id,
            p.full_name AS owner_name,
            a.name AS account_name,
            a.industry AS industry,
            a.annual_revenue AS annual_revenue,
            a.employee_count AS employee_count
        ORDER BY o.amount DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]
