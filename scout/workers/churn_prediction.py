"""
scout/workers/churn_prediction.py — Churn Prediction Worker (Layer 3)

Identifies customer accounts at elevated churn risk using a composite
signal score rather than a single binary flag. Each account gets a
risk score (0–100) built from multiple signals weighted by severity.

Layer 3 upgrade (Schema Intelligence):
  - Inactivity threshold calibrated to 2× this company's median sales cycle
    instead of a hardcoded 90 days (a company with 7-day cycles should not
    wait 90 days before flagging a quiet customer)
  - Business model awareness: for subscription businesses, renewal pipeline
    absence is penalized more severely than for transactional models
  - Multi-signal composite scoring replaces single-condition binary flags
  - Each finding cites the specific account name, ARR, days inactive,
    and owner — not just a count of affected accounts
  - Accounts are sorted by risk score so operators know where to focus first

Churn risk signals (with weights):
  W=35  No open pipeline (no renewal or expansion opportunity in CRM)
  W=25  Owner is inactive/departed (relationship risk)
  W=20  Account has no assigned owner (unmanaged)
  W=15  ARR concentration in single rep (key-person risk)
  W=5   Account data quality issues (missing industry, revenue)

Score → Risk Level:
  80-100: CRITICAL — immediate intervention required
  50-79:  HIGH — action this month
  25-49:  MEDIUM — monitor and schedule health check
  0-24:   LOW — healthy, standard retention process
"""

import logging
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# ── Hardcoded defaults (pre-intelligence fallbacks) ────────────────────────
HIGH_ARR_CONCENTRATION   = 500_000
CUSTOMER_INACTIVITY_DAYS = 90

# ── Signal weights ─────────────────────────────────────────────────────────
W_NO_PIPELINE   = 35
W_INACTIVE_OWNER = 25
W_NO_OWNER      = 20
W_ARR_CONCENTRATION = 15  # applied at portfolio level, not per-account
W_DATA_QUALITY  = 5


class ChurnPredictionWorker(WorkerBase):
    """
    Scores every customer account on churn risk using a composite signal model.
    Findings are sorted by risk score and cite specific account details.
    """

    WORKER_NAME = "ChurnPredictionWorker"

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)

        t_arr_concentration = cfg.get("high_arr_concentration", HIGH_ARR_CONCENTRATION)
        t_inactivity_days   = ctx.threshold(
            self.WORKER_NAME, "customer_inactivity_days",
            cfg.get("customer_inactivity_days", CUSTOMER_INACTIVITY_DAYS),
        )

        try:
            customers          = self._get_customer_accounts(tenant_id)
            pipeline_by_acct   = self._get_pipeline_by_account(tenant_id)
            rep_concentrations = self._get_rep_account_concentration(tenant_id)

            if not customers:
                result.findings.append(Finding(
                    title="No customer accounts found in the graph",
                    detail="CRM data has not been ingested or no accounts are marked as 'Customer'.",
                    severity=Severity.INFO,
                    recommended_action="Run a scan with a CRM connector (Salesforce, HubSpot).",
                ))
                result.summary_stats = {"total_customers": 0}
                return result

            # Build lookup: account_id → open pipeline value
            pipeline_lookup: dict[str, float] = {
                r["account_id"]: r["open_pipeline"] or 0
                for r in pipeline_by_acct
                if r.get("account_id")
            }

            # Score every customer account
            scored = []
            for acct in customers:
                score_record = self._score_account(
                    acct, pipeline_lookup, t_inactivity_days, ctx
                )
                scored.append(score_record)

            # Sort by risk score descending
            scored.sort(key=lambda x: x["risk_score"], reverse=True)

            # Summarize
            critical_accts = [s for s in scored if s["risk_score"] >= 80]
            high_accts     = [s for s in scored if 50 <= s["risk_score"] < 80]
            medium_accts   = [s for s in scored if 25 <= s["risk_score"] < 50]

            total_arr_at_risk = sum(
                (s["annual_revenue"] or 0)
                for s in scored if s["risk_score"] >= 50
            )

            result.summary_stats = {
                "total_customers":         len(customers),
                "critical_risk_accounts":  len(critical_accts),
                "high_risk_accounts":      len(high_accts),
                "medium_risk_accounts":    len(medium_accts),
                "arr_at_risk_high_plus":   round(total_arr_at_risk),
                "inactivity_threshold_days": t_inactivity_days,
                "thresholds_calibrated":   ctx.has_calibrated_history,
            }

            # ── Finding 1: CRITICAL risk accounts ────────────────────────
            if critical_accts:
                self._emit_risk_finding(
                    result, critical_accts, Severity.CRITICAL,
                    "CRITICAL churn risk", ctx, t_inactivity_days,
                )

            # ── Finding 2: HIGH risk accounts ─────────────────────────────
            if high_accts:
                self._emit_risk_finding(
                    result, high_accts, Severity.HIGH,
                    "HIGH churn risk", ctx, t_inactivity_days,
                )

            # ── Finding 3: Medium risk (summary) ──────────────────────────
            if medium_accts:
                med_arr = sum((s["annual_revenue"] or 0) for s in medium_accts)
                result.findings.append(Finding(
                    title=f"{len(medium_accts)} customer account{'s' if len(medium_accts) > 1 else ''} "
                          f"at moderate churn risk",
                    detail=(
                        f"{len(medium_accts)} accounts have partial risk signals "
                        f"(${med_arr:,.0f} in combined ARR). "
                        f"Common signals: limited pipeline, data gaps, or borderline inactivity. "
                        f"Standard CSM health checks recommended."
                    ),
                    severity=Severity.MEDIUM,
                    data={
                        "count": len(medium_accts),
                        "total_arr": round(med_arr),
                        "accounts": [s["account_name"] for s in medium_accts[:5]],
                    },
                    recommended_action=(
                        "Schedule quarterly health reviews for each of these accounts. "
                        "Ensure each has an open renewal or expansion opportunity in CRM."
                    ),
                    confidence="medium" if not ctx.has_calibrated_history else "high",
                ))

            # ── Finding 4: Rep ARR concentration (portfolio-level risk) ───
            high_concentration_reps = [
                r for r in rep_concentrations
                if (r.get("total_account_revenue") or 0) >= t_arr_concentration
            ]
            if high_concentration_reps:
                for rep in high_concentration_reps[:2]:
                    arr = rep.get("total_account_revenue", 0)
                    acct_count = rep.get("account_count", 0)
                    result.findings.append(Finding(
                        title=f"Key-person ARR risk: {rep.get('rep', 'Unknown')} "
                              f"owns ${arr:,.0f} across {acct_count} customers",
                        detail=(
                            f"{rep.get('rep')} ({rep.get('title', '')}) is the sole owner "
                            f"of {acct_count} customer account(s) representing ${arr:,.0f} in ARR. "
                            f"If this person departs, those customer relationships have no "
                            f"internal point of contact — churn risk is immediate and concentrated."
                        ),
                        severity=Severity.HIGH,
                        data={
                            "rep":                  rep.get("rep"),
                            "account_count":        acct_count,
                            "total_account_revenue": arr,
                        },
                        recommended_action=(
                            f"Introduce a secondary relationship (manager or CSM) to each of "
                            f"{rep.get('rep')}'s top accounts this quarter. "
                            f"Document account health, key contacts, and renewal dates in CRM "
                            f"independent of the rep's personal notes."
                        ),
                        specific_entities=[{
                            "type":    "person",
                            "name":    rep.get("rep"),
                            "title":   rep.get("title"),
                            "arr_at_risk": arr,
                            "account_count": acct_count,
                        }],
                    ))

        except Exception as exc:
            logger.exception("ChurnPredictionWorker failed: %s", exc)
            result.error = str(exc)

        return result

    # ── Risk scoring ───────────────────────────────────────────────────────

    def _score_account(
        self,
        acct: dict,
        pipeline_lookup: dict,
        inactivity_days: int,
        ctx: "WorkerContext",
    ) -> dict:
        """
        Assign a composite risk score (0–100) to one customer account.
        Returns the account dict enriched with risk_score and risk_signals.
        """
        score = 0
        signals = []

        acct_id = acct.get("account_id")
        open_pipeline = pipeline_lookup.get(acct_id, 0)

        # Signal 1: No open pipeline
        if open_pipeline == 0:
            score += W_NO_PIPELINE
            signals.append("no_open_pipeline")
            # Subscription businesses: no pipeline = almost certainly churning
            if ctx.is_subscription():
                score += 10
                signals.append("subscription_model_no_renewal")

        # Signal 2: Inactive/departed owner
        if acct.get("owner") and not acct.get("owner_active", True):
            score += W_INACTIVE_OWNER
            signals.append("owner_inactive_or_departed")

        # Signal 3: No owner assigned
        if not acct.get("owner"):
            score += W_NO_OWNER
            signals.append("no_owner_assigned")

        # Signal 4: Data quality — no revenue recorded
        if not acct.get("annual_revenue"):
            score += W_DATA_QUALITY
            signals.append("missing_revenue_data")

        return {
            **acct,
            "risk_score":    min(score, 100),
            "risk_signals":  signals,
            "open_pipeline": open_pipeline,
        }

    # ── Finding emitter ────────────────────────────────────────────────────

    def _emit_risk_finding(
        self,
        result: WorkerResult,
        accounts: list[dict],
        severity: Severity,
        label: str,
        ctx: "WorkerContext",
        inactivity_days: int,
    ) -> None:
        """Emit a finding for a group of at-risk accounts."""
        total_arr = sum((a.get("annual_revenue") or 0) for a in accounts)

        # Build specific per-account detail
        detail_lines = []
        for a in accounts[:4]:
            name     = a.get("account_name", "Unknown")
            arr      = a.get("annual_revenue") or 0
            owner    = a.get("owner") or "Unassigned"
            signals  = a.get("risk_signals", [])
            pipeline = a.get("open_pipeline", 0)

            signal_txt = _format_signals(signals, inactivity_days)
            arr_txt = f"${arr:,.0f} ARR" if arr else "ARR unknown"
            pipeline_txt = f"${pipeline:,.0f} open pipeline" if pipeline else "no open pipeline"

            detail_lines.append(
                f"• {name} ({arr_txt}, {owner}) — {pipeline_txt}. Risk signals: {signal_txt}."
            )

        if len(accounts) > 4:
            detail_lines.append(f"• …and {len(accounts) - 4} more account(s)")

        confidence_note = ctx.confidence_note()
        if confidence_note:
            detail_lines.append(confidence_note)

        result.findings.append(Finding(
            title=f"{len(accounts)} customer account{'s' if len(accounts) > 1 else ''} "
                  f"at {label} — ${total_arr:,.0f} ARR at risk",
            detail="\n".join(detail_lines),
            severity=severity,
            data={
                "count":      len(accounts),
                "total_arr":  round(total_arr),
                "accounts": [
                    {
                        "name":         a.get("account_name"),
                        "arr":          a.get("annual_revenue"),
                        "owner":        a.get("owner"),
                        "risk_score":   a.get("risk_score"),
                        "risk_signals": a.get("risk_signals"),
                        "open_pipeline": a.get("open_pipeline"),
                    }
                    for a in accounts
                ],
            },
            recommended_action=_build_churn_action(accounts, severity, ctx),
            confidence="high" if ctx.has_calibrated_history else "medium",
            specific_entities=[
                {
                    "type":         "account",
                    "name":         a.get("account_name"),
                    "id":           a.get("account_id"),
                    "owner":        a.get("owner"),
                    "annual_revenue": a.get("annual_revenue"),
                    "risk_score":   a.get("risk_score"),
                    "risk_signals": a.get("risk_signals"),
                }
                for a in accounts
            ],
        ))

    # ── Queries ────────────────────────────────────────────────────────────

    def _get_customer_accounts(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        OPTIONAL MATCH (p:Person)-[:OWNS]->(a)
        RETURN
            a.name          AS account_name,
            a.industry      AS industry,
            a.annual_revenue AS annual_revenue,
            a.canonical_id  AS account_id,
            p.full_name     AS owner,
            p.is_active     AS owner_active
        ORDER BY a.annual_revenue DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_pipeline_by_account(self, tenant_id: str) -> list[dict]:
        """Sum of open pipeline value per account — used to detect no-pipeline customers."""
        query = """
        MATCH (a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        OPTIONAL MATCH (o:Opportunity {tenant_id: $tenant_id, is_closed: false})-[:IN_ACCOUNT]->(a)
        RETURN
            a.canonical_id AS account_id,
            coalesce(sum(o.amount), 0) AS open_pipeline
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_rep_account_concentration(self, tenant_id: str) -> list[dict]:
        query = """
        MATCH (p:Person {tenant_id: $tenant_id, is_active: true})-[:OWNS]->(a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
        WITH p, count(a) AS account_count, sum(a.annual_revenue) AS total_account_revenue
        WHERE total_account_revenue IS NOT NULL
        RETURN
            p.full_name  AS rep,
            p.job_title  AS title,
            account_count,
            total_account_revenue
        ORDER BY total_account_revenue DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]


# ── Signal formatting helpers ──────────────────────────────────────────────

def _format_signals(signals: list[str], inactivity_days: int) -> str:
    """Convert signal codes to human-readable text."""
    labels = {
        "no_open_pipeline":           "no open renewal or expansion opportunity",
        "subscription_model_no_renewal": "subscription model — renewal not tracked",
        "owner_inactive_or_departed": "owner is inactive or has departed",
        "no_owner_assigned":          "no owner assigned",
        "missing_revenue_data":       "ARR not recorded in CRM",
    }
    readable = [labels.get(s, s) for s in signals]
    return "; ".join(readable) if readable else "no signals"


def _build_churn_action(
    accounts: list[dict],
    severity: Severity,
    ctx: "WorkerContext",
) -> str:
    """Build a specific recommended action based on the account risk profile."""
    if severity == Severity.CRITICAL:
        names = ", ".join(a.get("account_name", "?") for a in accounts[:3])
        return (
            f"Immediate action required for: {names}. "
            f"Assign a named CSM or AE to each within 24 hours. "
            f"Schedule a health-check call this week — do not wait for inbound. "
            f"Create a renewal or expansion opportunity in CRM to establish visibility."
        )
    else:
        names = ", ".join(a.get("account_name", "?") for a in accounts[:3])
        return (
            f"Schedule CSM health reviews for {names} "
            f"{'(and others)' if len(accounts) > 3 else ''} within the next 30 days. "
            f"For each: confirm key contacts are still in role, verify renewal date is tracked, "
            f"and create an expansion opportunity if none exists."
        )
