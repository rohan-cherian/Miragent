"""
scout/workers/renewal_workflow.py — Renewal Workflow Worker (Layer 3)

Identifies customer accounts at renewal risk and triggers renewal workflow
actions. Without explicit contract end dates in all vendor records, uses
proxy signals: time since last won deal, presence of active expansion
pipeline, and account health indicators.

Layer 3 upgrade:
  - Renewal risk thresholds now derived from company sales cycle data.
    A company with a 30-day cycle should flag accounts at 90 days (3×).
    A company with a 6-month cycle should flag at 18 months (3×).
    The old hardcoded 365/270-day thresholds were enterprise-centric and
    produced false negatives for fast-cycle SMB companies.

  - For subscription businesses, the framework is: 1 annual contract = 365 days.
    We use the higher of (median_cycle × 3) or 365 as the high-risk threshold
    so subscription companies always get at least 1-year-based renewal logic.

  - HIGH_ARR_THRESHOLD calibrated from ctx.avg_deal_size instead of a
    hardcoded $100k. A company with a $15k ACV has a very different definition
    of "high-ARR renewal" than one with a $500k ACV.

  - Business model awareness: for transactional models (one-time purchases),
    the renewal framing is replaced with "re-engagement risk" language.
    Flagging a transactional company's customers as "renewal risk" is misleading.

  - Each finding now includes specific_entities with account name, ARR,
    days elapsed, and risk reasons — so the operating partner can act
    without opening the CRM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# Fallback defaults (used when no company history is available)
_DEFAULT_HIGH_DAYS   = 365    # annual contract standard
_DEFAULT_MEDIUM_DAYS = 270    # 90-day warning window before annual renewal
_DEFAULT_HIGH_ARR    = 100_000

# For subscription companies: never flag sooner than 270 days (too noisy)
_SUBSCRIPTION_MIN_HIGH_DAYS = 365
_SUBSCRIPTION_MIN_MEDIUM_DAYS = 270


class RenewalWorkflowWorker(WorkerBase):
    """
    Scores customer accounts on renewal risk using proxy signals and
    surfaces at-risk accounts with recommended workflow actions.
    Thresholds calibrated from company sales cycle and segment data.
    """

    WORKER_NAME = "RenewalWorkflowWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        # ── Calibrate renewal thresholds ──────────────────────────────────
        # High-risk: deal aged beyond 3× median cycle (clearly past renewal window)
        # Medium-risk: deal aged beyond 2× median cycle (entering renewal window)
        is_subscription = ctx.is_subscription()
        median_cycle = ctx.median_sales_cycle or 0

        if median_cycle > 0 and ctx.has_calibrated_history:
            computed_high   = round(median_cycle * 3)
            computed_medium = round(median_cycle * 2)
            # Subscription floor: never flag annual-contract companies before 270/365 days
            if is_subscription:
                t_high_days   = max(computed_high,   _SUBSCRIPTION_MIN_HIGH_DAYS)
                t_medium_days = max(computed_medium, _SUBSCRIPTION_MIN_MEDIUM_DAYS)
            else:
                t_high_days   = computed_high
                t_medium_days = computed_medium
            thresholds_source = (
                f"calibrated from {median_cycle:.0f}-day median sales cycle"
            )
        else:
            t_high_days   = cfg.get("renewal_risk_high_days",   _DEFAULT_HIGH_DAYS)
            t_medium_days = cfg.get("renewal_risk_medium_days", _DEFAULT_MEDIUM_DAYS)
            thresholds_source = "using defaults (insufficient company history)"

        # High-ARR threshold: 2× avg deal size, floored at $50k, capped at $500k
        if ctx.avg_deal_size and ctx.avg_deal_size > 0 and ctx.has_calibrated_history:
            t_high_arr = max(50_000, min(ctx.avg_deal_size * 2, 500_000))
            arr_threshold_source = f"2× avg deal size (${ctx.avg_deal_size:,.0f})"
        else:
            t_high_arr = cfg.get("high_arr_threshold", _DEFAULT_HIGH_ARR)
            arr_threshold_source = "default threshold"

        context_note = (
            f"Renewal risk thresholds: high={t_high_days}d, medium={t_medium_days}d "
            f"({thresholds_source}). "
            f"High-ARR threshold: ${t_high_arr:,.0f} ({arr_threshold_source}). "
            f"Business model: {'subscription' if is_subscription else 'transactional'}."
        )

        # Adjust language for transactional companies
        risk_term = "renewal" if is_subscription else "re-engagement"
        risk_term_cap = risk_term.capitalize()

        result.summary_stats.update({
            "high_risk_threshold_days":  t_high_days,
            "medium_risk_threshold_days": t_medium_days,
            "high_arr_threshold":        round(t_high_arr),
            "business_model":            "subscription" if is_subscription else "transactional",
            "thresholds_source":         thresholds_source,
        })

        try:
            customers               = self._get_customers_with_deal_history(tenant_id)
            accounts_with_pipeline  = self._get_open_pipeline_accounts(tenant_id)

            if not customers:
                result.findings.append(Finding(
                    title=f"No customer accounts found — {risk_term} workflow requires Customer accounts with won deal history",
                    detail=(
                        "Tag accounts as 'Customer' and ensure closed-won opportunities "
                        "are linked to them to enable renewal risk scoring."
                    ),
                    severity=Severity.INFO,
                    data={},
                ))
                result.summary_stats.update({
                    "customer_accounts": 0,
                    "high_risk_count": 0,
                    "medium_risk_count": 0,
                    "total_arr_at_risk": 0,
                    "accounts_with_expansion_pipeline": 0,
                })
                return result

            # ── Score each customer ────────────────────────────────────
            scored = []
            for customer in customers:
                account_id       = customer.get("account_id") or ""
                has_open_pipeline = account_id in accounts_with_pipeline
                last_won_days    = customer.get("max_days_in_pipeline") or 0
                total_won_value  = customer.get("total_won_value") or 0

                base_risk    = 0
                risk_reasons = []

                if last_won_days > t_high_days:
                    base_risk += 40
                    risk_reasons.append(
                        f"Last won deal is {last_won_days} days old "
                        f"(threshold: {t_high_days}d) — likely past {risk_term} window"
                    )
                elif last_won_days > t_medium_days:
                    base_risk += 20
                    risk_reasons.append(
                        f"Last won deal is {last_won_days} days old "
                        f"(threshold: {t_medium_days}d) — approaching {risk_term} window"
                    )

                if not has_open_pipeline:
                    base_risk += 30
                    risk_reasons.append(f"No active expansion pipeline — no ongoing engagement signal")

                # High-ARR flag for executive attention
                risk_label = "Standard"
                if total_won_value > t_high_arr:
                    risk_label = "High-ARR"

                scored.append({
                    **customer,
                    "risk_score":        base_risk,
                    "risk_label":        risk_label,
                    "risk_reasons":      risk_reasons,
                    "has_open_pipeline": has_open_pipeline,
                    "last_won_days":     last_won_days,
                })

            scored.sort(key=lambda a: a["risk_score"], reverse=True)

            high_risk = [
                a for a in scored
                if not a["has_open_pipeline"] and a["last_won_days"] > t_high_days
            ]
            medium_risk = [
                a for a in scored
                if t_medium_days < a["last_won_days"] <= t_high_days
                and a not in high_risk
            ]
            high_arr_no_pipeline = [
                a for a in scored
                if (a.get("total_won_value") or 0) > t_high_arr
                and not a["has_open_pipeline"]
            ]

            # Deduplicate at-risk list for ARR sum
            seen: set = set()
            deduped_at_risk = []
            for a in high_risk + medium_risk:
                key = a.get("account_id")
                if key not in seen:
                    seen.add(key)
                    deduped_at_risk.append(a)
            total_arr_at_risk = sum((a.get("total_won_value") or 0) for a in deduped_at_risk)

            result.summary_stats.update({
                "customer_accounts":              len(customers),
                "high_risk_count":                len(high_risk),
                "medium_risk_count":              len(medium_risk),
                "total_arr_at_risk":              round(total_arr_at_risk),
                "accounts_with_expansion_pipeline": len(accounts_with_pipeline),
            })

            # ── Finding 1: High-risk accounts ────────────────────────────
            if high_risk:
                high_risk_arr = sum((a.get("total_won_value") or 0) for a in high_risk)
                detail_lines = [
                    f"No active pipeline, last won deal aged over {t_high_days} days "
                    f"({thresholds_source}). Total ARR at risk: ${high_risk_arr:,.0f}.",
                    "",
                ]
                for a in high_risk[:5]:
                    detail_lines.append(
                        f"  • {a.get('account_name', 'Unknown')} "
                        f"(${(a.get('total_won_value') or 0):,.0f} ARR, "
                        f"{a['last_won_days']} days since last deal)"
                    )
                if len(high_risk) > 5:
                    detail_lines.append(f"  • …and {len(high_risk) - 5} more")

                result.findings.append(Finding(
                    title=(
                        f"{len(high_risk)} high-{risk_term} risk customer"
                        f"{'s' if len(high_risk) > 1 else ''} "
                        f"— ${high_risk_arr:,.0f} ARR at risk"
                    ),
                    detail="\n".join(detail_lines),
                    severity=Severity.HIGH,
                    data={
                        "high_risk_accounts": [
                            {
                                "name":             a.get("account_name"),
                                "industry":         a.get("industry"),
                                "total_won_value":  a.get("total_won_value"),
                                "last_won_days":    a["last_won_days"],
                                "has_open_pipeline": a["has_open_pipeline"],
                                "risk_label":       a["risk_label"],
                                "risk_reasons":     a["risk_reasons"],
                            }
                            for a in high_risk
                        ],
                        "threshold_days": t_high_days,
                        "total_arr_at_risk": round(high_risk_arr),
                    },
                    recommended_action=(
                        f"Assign a CSM to each of these accounts immediately. "
                        f"Schedule an account health check this week. "
                        f"Create a {risk_term} opportunity in CRM for each account "
                        f"to activate pipeline tracking."
                    ),
                    confidence="high",
                    specific_entities=[
                        {
                            "type":            "account",
                            "name":            a.get("account_name"),
                            "total_won_value": a.get("total_won_value"),
                            "last_won_days":   a["last_won_days"],
                            "risk_score":      a["risk_score"],
                        }
                        for a in high_risk
                    ],
                    context_note=context_note,
                ))

            # ── Finding 2: Medium-risk accounts ──────────────────────────
            if medium_risk:
                med_arr = sum((a.get("total_won_value") or 0) for a in medium_risk)
                detail_lines = [
                    f"Last won deal aged {t_medium_days}–{t_high_days} days "
                    f"— entering the {risk_term} window ({thresholds_source}).",
                    "",
                ]
                for a in medium_risk[:5]:
                    detail_lines.append(
                        f"  • {a.get('account_name', 'Unknown')} "
                        f"(${(a.get('total_won_value') or 0):,.0f} ARR, "
                        f"{a['last_won_days']} days since last deal)"
                    )
                if len(medium_risk) > 5:
                    detail_lines.append(f"  • …and {len(medium_risk) - 5} more")

                result.findings.append(Finding(
                    title=(
                        f"{len(medium_risk)} medium-{risk_term} risk customer"
                        f"{'s' if len(medium_risk) > 1 else ''} "
                        f"— approaching {risk_term} window"
                    ),
                    detail="\n".join(detail_lines),
                    severity=Severity.MEDIUM,
                    data={
                        "medium_risk_accounts": [
                            {
                                "name":             a.get("account_name"),
                                "industry":         a.get("industry"),
                                "total_won_value":  a.get("total_won_value"),
                                "last_won_days":    a["last_won_days"],
                                "has_open_pipeline": a["has_open_pipeline"],
                                "risk_reasons":     a["risk_reasons"],
                            }
                            for a in medium_risk
                        ],
                    },
                    recommended_action=(
                        f"Schedule quarterly business reviews with these accounts in the next 30 days. "
                        f"Use the {risk_term} conversation to surface expansion opportunities."
                    ),
                    confidence="medium" if ctx.has_calibrated_history else "low",
                    specific_entities=[
                        {
                            "type":            "account",
                            "name":            a.get("account_name"),
                            "total_won_value": a.get("total_won_value"),
                            "last_won_days":   a["last_won_days"],
                        }
                        for a in medium_risk
                    ],
                    context_note=context_note,
                ))

            # ── Finding 3: High-ARR customers with no pipeline ───────────
            if high_arr_no_pipeline:
                total_high_arr = sum((a.get("total_won_value") or 0) for a in high_arr_no_pipeline)
                detail_lines = [
                    f"Customers with over ${t_high_arr:,.0f} in won ARR and no active "
                    f"expansion pipeline ({arr_threshold_source}).",
                    "",
                ]
                for a in high_arr_no_pipeline[:5]:
                    detail_lines.append(
                        f"  • {a.get('account_name', 'Unknown')} — "
                        f"${(a.get('total_won_value') or 0):,.0f} ARR, "
                        f"{a['last_won_days']} days since last deal"
                    )
                if len(high_arr_no_pipeline) > 5:
                    detail_lines.append(f"  • …and {len(high_arr_no_pipeline) - 5} more")

                result.findings.append(Finding(
                    title=(
                        f"{len(high_arr_no_pipeline)} high-ARR customer"
                        f"{'s' if len(high_arr_no_pipeline) > 1 else ''} "
                        f"with no expansion pipeline — executive attention required "
                        f"(${total_high_arr:,.0f} at stake)"
                    ),
                    detail="\n".join(detail_lines),
                    severity=Severity.HIGH,
                    data={
                        "high_arr_no_pipeline": [
                            {
                                "name":            a.get("account_name"),
                                "total_won_value": a.get("total_won_value"),
                                "industry":        a.get("industry"),
                                "risk_label":      a["risk_label"],
                                "last_won_days":   a["last_won_days"],
                            }
                            for a in high_arr_no_pipeline
                        ],
                        "total_arr":  total_high_arr,
                        "threshold":  t_high_arr,
                    },
                    recommended_action=(
                        "Assign a named executive sponsor to each of these accounts. "
                        "Schedule an Executive Business Review (EBR) within 14 days. "
                        f"Create a {risk_term} opportunity in CRM to activate the pipeline."
                    ),
                    confidence="high",
                    specific_entities=[
                        {
                            "type":            "account",
                            "name":            a.get("account_name"),
                            "total_won_value": a.get("total_won_value"),
                        }
                        for a in high_arr_no_pipeline
                    ],
                    context_note=context_note,
                ))

            # ── Finding 4: Summary ─────────────────────────────────────────
            if deduped_at_risk:
                result.findings.append(Finding(
                    title=f"Total ARR at {risk_term} risk: ${total_arr_at_risk:,.0f}",
                    detail=(
                        f"{len(deduped_at_risk)} customer account(s) with combined ARR of "
                        f"${total_arr_at_risk:,.0f} are showing {risk_term} risk signals. "
                        f"High-risk: {len(high_risk)}. Medium-risk: {len(medium_risk)}. "
                        f"{len(accounts_with_pipeline)} customer(s) have active expansion pipeline "
                        f"indicating ongoing engagement."
                    ),
                    severity=Severity.INFO,
                    data={
                        "total_arr_at_risk":       total_arr_at_risk,
                        "high_risk_count":         len(high_risk),
                        "medium_risk_count":       len(medium_risk),
                        "accounts_with_pipeline":  len(accounts_with_pipeline),
                    },
                    recommended_action=(
                        f"Review {risk_term} risk weekly in the pipeline call. "
                        "Prioritize accounts by ARR value and days since last engagement."
                    ),
                ))

        except Exception as exc:
            logger.exception(f"RenewalWorkflowWorker failed: {exc}")
            result.error = str(exc)

        return result

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_customers_with_deal_history(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        OPTIONAL MATCH (o:Opportunity {tenant_id: $tenant_id, is_won: true})-[:IN_ACCOUNT]->(a)
        WITH
            a,
            count(o) AS won_deal_count,
            coalesce(sum(o.amount), 0) AS total_won_value,
            coalesce(max(o.days_in_pipeline), 0) AS max_days
        RETURN
            a.canonical_id AS account_id,
            a.name AS account_name,
            a.industry AS industry,
            won_deal_count,
            total_won_value,
            max_days AS max_days_in_pipeline
        ORDER BY total_won_value DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_open_pipeline_accounts(self, tenant_id: str) -> set:
        query = """
        MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})-[:IN_ACCOUNT]->(a:Account)
        RETURN DISTINCT a.canonical_id AS account_id
        """
        with self.driver.session() as session:
            return {
                row["account_id"]
                for row in session.run(query, tenant_id=tenant_id)
                if row["account_id"]
            }
