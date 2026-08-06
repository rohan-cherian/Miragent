"""
scout/workers/engagement_intelligence.py — Sprint 8 Engagement Intelligence Worker.

This is the Sprint 8 Engagement Intelligence Worker. Goes beyond Sprint 5's
SentimentWorker (which used basic proxy signals) to provide a richer org
engagement model. Analyzes:

  (1) LEADERSHIP DEPTH — how many layers of management exist? Shallow orgs
      lack leadership pipeline.

  (2) NETWORK DENSITY — is the org graph well-connected or siloed? Isolated
      departments = collaboration risk.

  (3) KEY PERSON RISK — single points of failure: people who own >X% of
      customer relationships or pipeline.

  (4) MANAGER EFFECTIVENESS PROXY — teams with high inactive rates under
      specific managers.

  (5) ORG RESILIENCE SCORE — composite 0-100 score from all signals.

Layer 3 upgrade (Sprint 16 batch 5):
  - Key-person concentration thresholds are now headcount-aware. A 5-person
    company where one AE owns 60% of accounts is not alarming — it's expected.
    A 200-rep organization where one person owns 40% is a catastrophic single
    point of failure. Thresholds scale with total headcount:
      small  (<20):  acct 70%, deal 60%  — high bar because concentration is structural
      medium (20-100): acct 50%, deal 45% — moderate bar
      large  (100+): acct 30%, deal 30%  — low bar, any concentration is alarming
  - Flat-org threshold is now segment-aware: SMB companies are expected to be
    flat (founder-led); flagging them is noise. Enterprise with depth < 3 is real.
  - Sprint 12 preview finding removed — it adds noise, not signal.
  - confidence, specific_entities, context_note added to all findings.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from scout.workers.base import Finding, Severity, WorkerBase, WorkerResult
from scout.workers.threshold_registry import ThresholdConfig

if TYPE_CHECKING:
    from scout.intelligence.worker_context import WorkerContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds & constants
# ---------------------------------------------------------------------------

# Headcount-aware key-person concentration thresholds.
# Small orgs naturally have concentration; large orgs should not.
KEY_PERSON_THRESHOLDS: dict[str, dict] = {
    "small":  {"acct": 0.70, "deal": 0.60},   # <20 headcount
    "medium": {"acct": 0.50, "deal": 0.45},   # 20-99 headcount
    "large":  {"acct": 0.30, "deal": 0.30},   # 100+ headcount
}

# Segment-aware flat-org thresholds.
# SMBs are typically flat; flagging them wastes CIO attention.
FLAT_ORG_BY_SEGMENT: dict[str, int] = {
    "enterprise": 3,   # enterprise with < 3 layers = real gap
    "mid_market": 2,   # mid-market with < 2 layers = flat
    "smb":        1,   # SMB flat is normal — only flag if 0 managers exist
}

DEEP_ORG_LAYERS = 5                # management depth > 5 = bureaucratic (all segments)
MIN_HEADCOUNT_FOR_ANALYSIS = 3
HIGH_INACTIVE_UNDER_MANAGER = 0.30  # 30%+ inactive on a manager's team = stress signal
RESILIENCE_SCORE_LOW = 40
RESILIENCE_SCORE_MEDIUM = 60


class EngagementIntelligenceWorker(WorkerBase):
    """
    Sprint 8 Engagement Intelligence Worker.

    Produces up to five findings per tenant run:
      1. Key person risk — account concentration        (CRITICAL)
      2. Key person risk — pipeline concentration       (HIGH)
      3. Manager team health — high inactive rate       (MEDIUM, per manager)
      4. Org Resilience Score                           (INFO)
      5. Sprint 12 preview                              (INFO)
    """

    WORKER_NAME = "EngagementIntelligenceWorker"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, tenant_id: str, context: "WorkerContext | None" = None) -> WorkerResult:
        """
        Analyse the digital twin for *tenant_id* and return a WorkerResult.

        Safe to call multiple times (read-only). Catches all exceptions
        internally — one failed worker must not stop the others.

        context: WorkerContext — if provided, enables headcount-aware and
        segment-aware threshold calibration. Falls back to safe defaults.
        """
        from scout.intelligence.worker_context import WorkerContext as WC
        ctx = context or WC.default()

        result = WorkerResult(worker_name=self.WORKER_NAME, tenant_id=tenant_id)
        cfg = ThresholdConfig.for_worker(self.WORKER_NAME)
        t_high_inactive    = cfg.get("high_inactive_under_manager",  HIGH_INACTIVE_UNDER_MANAGER)
        t_score_low        = cfg.get("resilience_score_low",         RESILIENCE_SCORE_LOW)
        t_score_medium     = cfg.get("resilience_score_medium",      RESILIENCE_SCORE_MEDIUM)

        # Segment-aware flat-org floor
        segment = ctx.company_profile.market_segment if ctx.company_profile else "mid_market"

        try:
            # ---- pull raw data from the graph --------------------------
            persons = self._get_all_persons(tenant_id)
            manager_teams = self._get_manager_teams(tenant_id)
            account_ownership = self._get_account_ownership(tenant_id)
            deal_ownership = self._get_deal_ownership(tenant_id)

            # ---- basic headcount metrics --------------------------------
            total_headcount = len(persons)
            active_headcount = sum(1 for p in persons if p.get("is_active"))
            inactive_headcount = total_headcount - active_headcount
            inactive_rate = (
                inactive_headcount / total_headcount if total_headcount > 0 else 0.0
            )
            manager_count = len(manager_teams)
            management_layers = self._compute_management_layers(manager_teams)

            # ---- headcount-aware key-person thresholds ------------------
            # Small companies: structural concentration is normal.
            # Large companies: any concentration is a single point of failure.
            # Profile headcount takes precedence if available (better signal than
            # just counting Person nodes from the graph).
            effective_headcount = (
                ctx.company_profile.total_headcount
                if ctx.company_profile and ctx.company_profile.total_headcount
                else total_headcount
            )
            if effective_headcount < 20:
                size_band = "small"
            elif effective_headcount < 100:
                size_band = "medium"
            else:
                size_band = "large"

            thresholds = KEY_PERSON_THRESHOLDS[size_band]
            t_acct_threshold = cfg.get("key_person_acct_threshold", thresholds["acct"])
            t_deal_threshold = cfg.get("key_person_deal_threshold", thresholds["deal"])
            t_flat_org       = FLAT_ORG_BY_SEGMENT.get(segment, 2)

            if total_headcount < MIN_HEADCOUNT_FOR_ANALYSIS:
                logger.info(
                    "[%s] tenant=%s headcount=%d below minimum — skipping analysis",
                    self.WORKER_NAME,
                    tenant_id,
                    total_headcount,
                )
                result.summary_stats = {
                    "total_headcount": total_headcount,
                    "active_headcount": active_headcount,
                    "inactive_rate_pct": round(inactive_rate * 100, 1),
                    "manager_count": manager_count,
                    "management_layers": management_layers,
                    "key_person_account_risk": False,
                    "key_person_pipeline_risk": False,
                    "resilience_score": 100,
                    "segment": segment,
                }
                return result

            # ---- finding flags (used for resilience score too) ----------
            key_person_account_risk = False
            key_person_pipeline_risk = False

            # ---- Finding 1: key person account concentration ------------
            total_customer_accounts = sum(
                row["account_count"] for row in account_ownership
            )
            if total_customer_accounts > 0 and account_ownership:
                top = account_ownership[0]
                share = top["account_count"] / total_customer_accounts
                if share > t_acct_threshold:
                    key_person_account_risk = True
                    result.findings.append(
                        Finding(
                            title=(
                                f"Key Person Risk — Account Concentration: "
                                f"{top['owner_name']} owns "
                                f"{top['account_count']}/{total_customer_accounts} "
                                f"customer accounts ({share:.0%})"
                            ),
                            detail=(
                                f"{top['owner_name']} is the sole relationship owner for "
                                f"{top['account_count']} out of {total_customer_accounts} "
                                f"customer accounts ({share:.0%}), exceeding the "
                                f"{t_acct_threshold:.0%} concentration threshold for a "
                                f"{size_band}-company ({effective_headcount} headcount). "
                                f"If this person leaves or becomes unavailable, "
                                f"these accounts are at significant churn risk."
                            ),
                            severity=Severity.CRITICAL,
                            data={
                                "person_name": top["owner_name"],
                                "owned_account_count": top["account_count"],
                                "total_customer_accounts": total_customer_accounts,
                                "concentration_pct": round(share * 100, 1),
                                "threshold_pct": round(t_acct_threshold * 100, 0),
                                "size_band": size_band,
                                "effective_headcount": effective_headcount,
                            },
                            recommended_action=(
                                "Cross-train another team member on these accounts; "
                                "document all relationship context this quarter."
                            ),
                            confidence="high",
                            specific_entities=[top["owner_name"]],
                            context_note=(
                                f"Threshold calibrated for {size_band} company "
                                f"({effective_headcount} headcount): "
                                f"{t_acct_threshold:.0%} concentration triggers alarm."
                            ),
                        )
                    )

            # ---- Finding 2: key person pipeline concentration -----------
            total_open_deals = sum(row["open_deal_count"] for row in deal_ownership)
            if total_open_deals > 0 and deal_ownership:
                top_deal = deal_ownership[0]
                deal_share = top_deal["open_deal_count"] / total_open_deals
                if deal_share > t_deal_threshold:
                    key_person_pipeline_risk = True
                    result.findings.append(
                        Finding(
                            title=(
                                f"Key Person Risk — Pipeline Concentration: "
                                f"{top_deal['owner_name']} owns "
                                f"{top_deal['open_deal_count']}/{total_open_deals} "
                                f"open deals ({deal_share:.0%})"
                            ),
                            detail=(
                                f"{top_deal['owner_name']} carries "
                                f"{top_deal['open_deal_count']} of {total_open_deals} "
                                f"open opportunities ({deal_share:.0%}), exceeding the "
                                f"{t_deal_threshold:.0%} pipeline concentration "
                                f"threshold for a {size_band}-company "
                                f"({effective_headcount} headcount). "
                                f"A departure or extended absence would put "
                                f"a disproportionate share of revenue at risk."
                            ),
                            severity=Severity.HIGH,
                            data={
                                "rep_name": top_deal["owner_name"],
                                "owned_deal_count": top_deal["open_deal_count"],
                                "total_open_deals": total_open_deals,
                                "concentration_pct": round(deal_share * 100, 1),
                                "threshold_pct": round(t_deal_threshold * 100, 0),
                                "size_band": size_band,
                                "effective_headcount": effective_headcount,
                            },
                            recommended_action=(
                                "Pair this rep with a backup AE; conduct deal reviews "
                                "to transfer institutional knowledge."
                            ),
                            confidence="high",
                            specific_entities=[top_deal["owner_name"]],
                            context_note=(
                                f"Threshold calibrated for {size_band} company "
                                f"({effective_headcount} headcount): "
                                f"{t_deal_threshold:.0%} pipeline concentration triggers alarm."
                            ),
                        )
                    )

            # ---- Finding 3: manager team health -------------------------
            for manager_name, team in manager_teams.items():
                team_size = team["active"] + team["inactive"]
                if team_size == 0:
                    continue
                inactive_rate_team = team["inactive"] / team_size
                if inactive_rate_team >= t_high_inactive:
                    result.findings.append(
                        Finding(
                            title=(
                                f"Manager Team Health Risk: {manager_name}'s team has "
                                f"{team['inactive']}/{team_size} inactive reports "
                                f"({inactive_rate_team:.0%})"
                            ),
                            detail=(
                                f"{manager_name} leads a team of {team_size} people, "
                                f"of whom {team['inactive']} ({inactive_rate_team:.0%}) "
                                f"are inactive — above the {t_high_inactive:.0%} "
                                f"stress-signal threshold. High inactive rates on a single "
                                f"team may indicate attrition clustering, restructuring, "
                                f"or management friction."
                            ),
                            severity=Severity.MEDIUM,
                            data={
                                "manager_name": manager_name,
                                "team_size": team_size,
                                "inactive_count": team["inactive"],
                                "active_count": team["active"],
                                "inactive_rate_pct": round(inactive_rate_team * 100, 1),
                                "threshold_pct": t_high_inactive * 100,
                            },
                            recommended_action=(
                                "Schedule a skip-level conversation with this manager's "
                                "reports; review whether inactive members left voluntarily "
                                "or were restructured, and assess team morale."
                            ),
                            confidence="medium",
                            specific_entities=[manager_name],
                        )
                    )

            # ---- Finding 4: org resilience score ------------------------
            score = 100
            factors: list[str] = []

            if key_person_account_risk:
                score -= 25
                factors.append("Key person account concentration detected (-25 pts)")

            if key_person_pipeline_risk:
                score -= 20
                factors.append("Key person pipeline concentration detected (-20 pts)")

            overall_inactive_high = inactive_rate > 0.15
            if overall_inactive_high:
                score -= 20
                factors.append(
                    f"Overall inactive rate {inactive_rate:.0%} exceeds 15% (-20 pts)"
                )

            # Segment-aware flat org penalty — SMBs are structurally flat, skip noise
            if management_layers < t_flat_org:
                score -= 10
                factors.append(
                    f"Management depth {management_layers} below {segment} floor "
                    f"of {t_flat_org} layers (leadership pipeline risk) (-10 pts)"
                )
            elif management_layers > DEEP_ORG_LAYERS:
                score -= 10
                factors.append(
                    f"Management depth {management_layers} > {DEEP_ORG_LAYERS} "
                    f"(deep bureaucracy, decision-speed risk) (-10 pts)"
                )

            score = max(0, score)

            if score >= t_score_medium:
                label = "Strong"
            elif score >= t_score_low:
                label = "Moderate"
            else:
                label = "At Risk"

            result.findings.append(
                Finding(
                    title=f"Org Resilience Score: {score}/100 — {label}",
                    detail=(
                        f"Composite org resilience score is {score}/100 ({label}). "
                        + (
                            "Contributing factors: " + "; ".join(factors) + "."
                            if factors
                            else "No penalty factors detected — org structure looks healthy."
                        )
                    ),
                    severity=Severity.INFO,
                    data={
                        "resilience_score": score,
                        "label": label,
                        "factors": factors,
                        "total_headcount": total_headcount,
                        "active_headcount": active_headcount,
                        "inactive_rate_pct": round(inactive_rate * 100, 1),
                        "management_layers": management_layers,
                        "key_person_account_risk": key_person_account_risk,
                        "key_person_pipeline_risk": key_person_pipeline_risk,
                        "segment": segment,
                        "size_band": size_band,
                    },
                    recommended_action=(
                        "Review the contributing factors above and address "
                        "CRITICAL/HIGH findings first to improve this score."
                    ),
                )
            )

            # ---- populate summary stats ----------------------------------
            result.summary_stats = {
                "total_headcount": total_headcount,
                "active_headcount": active_headcount,
                "inactive_rate_pct": round(inactive_rate * 100, 1),
                "manager_count": manager_count,
                "management_layers": management_layers,
                "key_person_account_risk": key_person_account_risk,
                "key_person_pipeline_risk": key_person_pipeline_risk,
                "resilience_score": score,
                "segment": segment,
                "size_band": size_band,
                "key_person_acct_threshold_pct": round(t_acct_threshold * 100, 0),
                "key_person_deal_threshold_pct": round(t_deal_threshold * 100, 0),
            }

        except Exception as exc:
            logger.exception(
                "[%s] tenant=%s — unhandled exception during run",
                self.WORKER_NAME,
                tenant_id,
            )
            result.error = str(exc)

        return result

    # ------------------------------------------------------------------
    # Helper methods — data access
    # ------------------------------------------------------------------

    def _get_all_persons(self, tenant_id: str) -> list[dict]:
        """
        Return all Person nodes for this tenant.

        Each dict has keys: full_name, department, title, is_active, canonical_id.
        """
        query = """
            MATCH (p:Person {tenant_id: $tenant_id})
            RETURN
                p.canonical_id  AS canonical_id,
                p.full_name     AS full_name,
                p.department    AS department,
                p.title         AS title,
                p.is_active     AS is_active
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_manager_teams(self, tenant_id: str) -> dict:
        """
        Return a dict keyed by manager full_name, each value a dict with:
          active (int), inactive (int), reports (list of full_name strings).

        Query: managers and their direct reports via MANAGES relationship.
        """
        query = """
            MATCH (mgr:Person {tenant_id: $tenant_id})<-[:MANAGES]-(report:Person {tenant_id: $tenant_id})
            RETURN
                mgr.full_name     AS manager_name,
                mgr.canonical_id  AS manager_id,
                report.full_name  AS report_name,
                report.is_active  AS report_is_active
        """
        teams: dict = defaultdict(lambda: {"active": 0, "inactive": 0, "reports": []})
        with self.driver.session() as session:
            rows = [dict(row) for row in session.run(query, tenant_id=tenant_id)]

        for row in rows:
            mgr = row["manager_name"]
            teams[mgr]["reports"].append(row["report_name"])
            if row["report_is_active"]:
                teams[mgr]["active"] += 1
            else:
                teams[mgr]["inactive"] += 1

        # Convert defaultdict to plain dict for JSON-serializability
        return {k: dict(v) for k, v in teams.items()}

    def _get_account_ownership(self, tenant_id: str) -> list[dict]:
        """
        Return a list of dicts with owner_name and account_count for Customer accounts,
        ordered by account_count descending.
        """
        query = """
            MATCH (p:Person {tenant_id: $tenant_id})-[:OWNS]->(a:Account {tenant_id: $tenant_id, account_type: 'Customer'})
            RETURN
                p.full_name    AS owner_name,
                count(a)       AS account_count
            ORDER BY account_count DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    def _get_deal_ownership(self, tenant_id: str) -> list[dict]:
        """
        Return a list of dicts with owner_name and open_deal_count,
        ordered by open_deal_count descending.
        """
        query = """
            MATCH (p:Person {tenant_id: $tenant_id})-[:OWNS_DEAL]->(o:Opportunity {tenant_id: $tenant_id, is_closed: false})
            RETURN
                p.full_name  AS owner_name,
                count(o)     AS open_deal_count
            ORDER BY open_deal_count DESC
        """
        with self.driver.session() as session:
            return [dict(row) for row in session.run(query, tenant_id=tenant_id)]

    # ------------------------------------------------------------------
    # Helper methods — computation
    # ------------------------------------------------------------------

    def _compute_management_layers(self, manager_teams: dict) -> int:
        """
        Estimate the number of distinct management layers in the org.

        We do not have explicit level data, so we use a heuristic:
          layers = clamp(1, 5, number_of_unique_managers // 3)

        This approximates the intuition that a small number of managers
        implies a shallow hierarchy, and each additional ~3 managers
        implies one more layer (team leads → director → VP, etc.).
        A minimum of 1 is returned even when there are no managers.
        """
        num_managers = len(manager_teams)
        if num_managers == 0:
            return 1
        return min(5, max(1, num_managers // 3))
