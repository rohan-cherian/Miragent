"""
scout/intelligence/company_profile_builder.py — CompanyProfileBuilder

Reads the Neo4j graph for a tenant and builds a CompanyProfile from
what it finds. This runs before any workers execute, so every worker
gets a calibrated, company-specific context instead of generic defaults.

What it infers (no external API calls, no Claude required):
  - Business model: from deal/revenue patterns (recurring vs. one-time)
  - Market segment: from median ACV (SMB < $25k, MM $25k-$150k, Ent > $150k)
  - Sales cycle: P25/median/P75 from closed-won opportunity history
  - Win rate: closed_won / (closed_won + closed_lost)
  - Stage vocabulary: maps custom stage names to canonical stages
  - Field trust: null-rate analysis on key fields used by workers
  - Calibrated thresholds: replaces hardcoded constants with data-derived values

Calibration rules:
  - PipelineVelocityWorker.stalled_days = P75 of sales cycle × 0.5
    (a deal that's spent half the historical P75 in one stage is stalling)
  - ChurnPredictionWorker.high_arr_concentration = P75 of rep ARR concentration
  - SalesCapacityWorker.max_pipeline_per_rep = P90 of rep pipeline distribution
  - MarketingFunnelWorker.benchmark_win_rate = max(observed_win_rate × 1.1, 0.25)
    (10% stretch above actual, floored at 25% industry baseline)

Design:
  Always returns a valid CompanyProfile — never raises.
  If there's insufficient data, the profile has low confidence and
  workers fall back to their hardcoded defaults via get_threshold().
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from scout.intelligence.company_profile import (
    CompanyProfile,
    FieldTrustRecord,
    DataConfidence,
)
from scout.intelligence.stage_mapper import StageVocabularyMapper

logger = logging.getLogger(__name__)

# ── Segment thresholds (ACV-based) ────────────────────────────────────────
SMB_MAX_ACV        = 25_000
ENTERPRISE_MIN_ACV = 150_000


class CompanyProfileBuilder:
    """
    Builds a CompanyProfile from a tenant's Neo4j graph data.

    Usage:
        builder = CompanyProfileBuilder(driver)
        profile = builder.build(tenant_id)
    """

    def __init__(self, driver) -> None:
        self.driver = driver

    def build(self, tenant_id: str) -> CompanyProfile:
        """
        Build a CompanyProfile for the given tenant.
        Always returns a valid profile; logs warnings on failures.
        """
        profile = CompanyProfile(tenant_id=tenant_id)

        try:
            with self.driver.session() as session:
                self._infer_sales_cycle(session, tenant_id, profile)
                self._infer_market_segment(session, tenant_id, profile)
                self._infer_business_model(session, tenant_id, profile)
                self._build_stage_map(session, tenant_id, profile)
                self._score_field_trust(session, tenant_id, profile)
                self._infer_workforce_stats(session, tenant_id, profile)
                self._calibrate_thresholds(profile)
                self._assess_data_confidence(profile)

            logger.info("CompanyProfileBuilder: %s", profile.summary())

        except Exception as exc:
            logger.warning(
                "CompanyProfileBuilder failed for %s: %s — using defaults",
                tenant_id, exc
            )
            profile.data_confidence = "low"

        return profile

    # ── Sales cycle calibration ────────────────────────────────────────────

    def _infer_sales_cycle(self, session, tenant_id: str, profile: CompanyProfile) -> None:
        """
        Derive P25/median/P75 sales cycle length and win rate
        from closed-won opportunity history.

        Only uses opportunities with a valid days_in_pipeline value.
        Requires ≥ 5 won deals for meaningful calibration.
        """
        rows = session.run("""
            MATCH (o:Opportunity {tenant_id: $tid, is_won: true})
            WHERE o.days_in_pipeline IS NOT NULL AND o.days_in_pipeline > 0
            RETURN
                o.days_in_pipeline AS days,
                o.amount AS amount
            ORDER BY o.days_in_pipeline
        """, tid=tenant_id).data()

        if len(rows) < 5:
            logger.debug(
                "CompanyProfileBuilder: only %d won deals for %s — skipping cycle calibration",
                len(rows), tenant_id
            )
            profile.closed_won_count = len(rows)
            return

        days_list = [r["days"] for r in rows if r["days"] and r["days"] > 0]
        amounts   = [r["amount"] for r in rows if r["amount"] and r["amount"] > 0]

        if len(days_list) >= 5:
            profile.median_sales_cycle_days = int(statistics.median(days_list))
            profile.p75_sales_cycle_days    = int(_percentile(days_list, 75))
            profile.p25_sales_cycle_days    = int(_percentile(days_list, 25))

        if amounts:
            profile.median_deal_size = statistics.median(amounts)
            profile.avg_deal_size    = statistics.mean(amounts)

        profile.closed_won_count = len(rows)

        # Also compute win rate using all closed deals
        win_loss = session.run("""
            MATCH (o:Opportunity {tenant_id: $tid})
            WHERE o.is_won IS NOT NULL OR o.is_closed = true
            RETURN
                sum(CASE WHEN o.is_won = true THEN 1 ELSE 0 END) AS won,
                sum(CASE WHEN o.is_won = false AND o.is_closed = true THEN 1 ELSE 0 END) AS lost
        """, tid=tenant_id).single()

        if win_loss:
            won  = win_loss["won"] or 0
            lost = win_loss["lost"] or 0
            total = won + lost
            if total > 0:
                profile.win_rate = round(won / total, 3)

        logger.debug(
            "Sales cycle: median=%dd, P75=%dd, win_rate=%.1f%%, n=%d",
            profile.median_sales_cycle_days or 0,
            profile.p75_sales_cycle_days or 0,
            (profile.win_rate or 0) * 100,
            profile.closed_won_count,
        )

    # ── Market segment inference ───────────────────────────────────────────

    def _infer_market_segment(self, session, tenant_id: str, profile: CompanyProfile) -> None:
        """
        Infer SMB / mid-market / enterprise from ACV distribution.
        Uses closed-won deal amounts as a proxy for ACV.
        """
        if not profile.median_deal_size:
            profile.market_segment = "unknown"
            return

        acv = profile.median_deal_size

        if acv < SMB_MAX_ACV:
            profile.market_segment = "smb"
        elif acv < ENTERPRISE_MIN_ACV:
            profile.market_segment = "mid_market"
        else:
            profile.market_segment = "enterprise"

        # Check if the distribution spans multiple segments (mixed)
        if profile.p75_sales_cycle_days and profile.p25_sales_cycle_days:
            p25_acv = profile.p25_sales_cycle_days  # approximate
            if (profile.median_deal_size < SMB_MAX_ACV and profile.avg_deal_size and
                    profile.avg_deal_size > ENTERPRISE_MIN_ACV):
                profile.market_segment = "mixed"

    # ── Business model inference ───────────────────────────────────────────

    def _infer_business_model(self, session, tenant_id: str, profile: CompanyProfile) -> None:
        """
        Infer subscription vs. transactional from account and deal patterns.

        Heuristics:
          - Accounts with account_type='Customer' + recurring won deals = subscription
          - Multiple small deals per account = transactional
          - Single large deals per account = subscription / enterprise
          - No renewal patterns visible = unknown
        """
        rows = session.run("""
            MATCH (a:Account {tenant_id: $tid, account_type: 'Customer'})
            OPTIONAL MATCH (o:Opportunity {tenant_id: $tid, is_won: true})-[:IN_ACCOUNT]->(a)
            WITH a, count(o) AS deal_count, avg(o.amount) AS avg_amount
            RETURN
                count(a) AS customer_count,
                avg(deal_count) AS avg_deals_per_customer,
                avg(avg_amount) AS overall_avg_amount
        """, tid=tenant_id).single()

        if not rows or not rows["customer_count"]:
            profile.business_model = "unknown"
            return

        avg_deals = rows["avg_deals_per_customer"] or 0

        # Multiple won deals per customer = likely expansion/renewal (subscription)
        if avg_deals >= 1.5:
            profile.business_model = "subscription"
        elif avg_deals >= 1.0:
            # One deal per customer — could go either way
            # Check if there are active customer accounts with no expansion (pure transactional)
            profile.business_model = "mixed"
        else:
            profile.business_model = "unknown"

    # ── Stage vocabulary mapping ───────────────────────────────────────────

    def _build_stage_map(self, session, tenant_id: str, profile: CompanyProfile) -> None:
        """
        Pull all stage names from the graph and build the stage vocabulary map.

        Queries both open and closed opportunities so we get the full
        picture of stages used — not just the current pipeline state.
        """
        rows = session.run("""
            MATCH (o:Opportunity {tenant_id: $tid})
            WHERE o.stage IS NOT NULL
            WITH o.stage AS stage_name,
                 count(o) AS deal_count,
                 avg(o.probability) AS avg_probability,
                 avg(o.days_in_pipeline) AS avg_days_in_stage,
                 sum(CASE WHEN o.is_won = true THEN 1 ELSE 0 END) AS won_count,
                 sum(CASE WHEN o.is_won = false AND o.is_closed = true THEN 1 ELSE 0 END) AS lost_count
            RETURN stage_name, deal_count, avg_probability, avg_days_in_stage, won_count, lost_count
            ORDER BY deal_count DESC
        """, tid=tenant_id).data()

        if not rows:
            # No stage data — use default standard Salesforce mapper
            profile.stage_map = {}
            return

        mapper = StageVocabularyMapper.from_stage_stats(rows)
        profile.stage_map = {r.raw_name: r for r in mapper.all_records()}

        summary = mapper.summary()
        logger.info(
            "Stage map for %s: %d stages, %d high-confidence, unmapped=%s",
            tenant_id,
            summary["total_stages"],
            summary["mapped_high_confidence"],
            summary["unmapped"],
        )

    # ── Field trust scoring ────────────────────────────────────────────────

    def _score_field_trust(self, session, tenant_id: str, profile: CompanyProfile) -> None:
        """
        Measure null rates for fields that workers rely on most heavily.
        These determine which findings can be asserted with high confidence
        vs. which should be flagged as uncertain.
        """
        # Opportunity fields used by revenue workers
        opp_fields = session.run("""
            MATCH (o:Opportunity {tenant_id: $tid})
            WITH count(o) AS total,
                 sum(CASE WHEN o.amount IS NULL THEN 1 ELSE 0 END) AS null_amount,
                 sum(CASE WHEN o.close_date IS NULL THEN 1 ELSE 0 END) AS null_close_date,
                 sum(CASE WHEN o.probability IS NULL THEN 1 ELSE 0 END) AS null_probability,
                 sum(CASE WHEN o.stage IS NULL THEN 1 ELSE 0 END) AS null_stage,
                 sum(CASE WHEN o.days_in_pipeline IS NULL THEN 1 ELSE 0 END) AS null_days
            RETURN total, null_amount, null_close_date, null_probability, null_stage, null_days
        """, tid=tenant_id).single()

        if opp_fields and opp_fields["total"] > 0:
            total = opp_fields["total"]
            for field_name, null_key in [
                ("opportunity.amount",         "null_amount"),
                ("opportunity.close_date",      "null_close_date"),
                ("opportunity.probability",     "null_probability"),
                ("opportunity.stage",           "null_stage"),
                ("opportunity.days_in_pipeline","null_days"),
            ]:
                null_rate = (opp_fields[null_key] or 0) / total
                profile.field_trust[field_name] = FieldTrustRecord.from_null_rate(
                    field_name, null_rate
                )

        # Account fields used by churn/expansion workers
        acct_fields = session.run("""
            MATCH (a:Account {tenant_id: $tid})
            WITH count(a) AS total,
                 sum(CASE WHEN a.annual_revenue IS NULL THEN 1 ELSE 0 END) AS null_revenue,
                 sum(CASE WHEN a.account_type IS NULL THEN 1 ELSE 0 END) AS null_type,
                 sum(CASE WHEN a.industry IS NULL THEN 1 ELSE 0 END) AS null_industry
            RETURN total, null_revenue, null_type, null_industry
        """, tid=tenant_id).single()

        if acct_fields and acct_fields["total"] > 0:
            total = acct_fields["total"]
            for field_name, null_key in [
                ("account.annual_revenue", "null_revenue"),
                ("account.account_type",   "null_type"),
                ("account.industry",       "null_industry"),
            ]:
                null_rate = (acct_fields[null_key] or 0) / total
                profile.field_trust[field_name] = FieldTrustRecord.from_null_rate(
                    field_name, null_rate
                )

        # Person fields used by workforce workers
        person_fields = session.run("""
            MATCH (p:Person {tenant_id: $tid, is_active: true})
            WITH count(p) AS total,
                 sum(CASE WHEN p.job_title IS NULL THEN 1 ELSE 0 END) AS null_title,
                 sum(CASE WHEN p.department IS NULL THEN 1 ELSE 0 END) AS null_dept,
                 sum(CASE WHEN p.email IS NULL THEN 1 ELSE 0 END) AS null_email
            RETURN total, null_title, null_dept, null_email
        """, tid=tenant_id).single()

        if person_fields and person_fields["total"] > 0:
            total = person_fields["total"]
            for field_name, null_key in [
                ("person.job_title",  "null_title"),
                ("person.department", "null_dept"),
                ("person.email",      "null_email"),
            ]:
                null_rate = (person_fields[null_key] or 0) / total
                profile.field_trust[field_name] = FieldTrustRecord.from_null_rate(
                    field_name, null_rate
                )

    # ── Workforce stats ────────────────────────────────────────────────────

    def _infer_workforce_stats(self, session, tenant_id: str, profile: CompanyProfile) -> None:
        """Pull basic headcount stats for context."""
        row = session.run("""
            MATCH (p:Person {tenant_id: $tid, is_active: true})
            RETURN
                count(p) AS headcount,
                sum(CASE WHEN p.employment_type = 'Contractor' THEN 1 ELSE 0 END) AS contractors
        """, tid=tenant_id).single()

        if row and row["headcount"]:
            total = row["headcount"]
            contractors = row["contractors"] or 0
            profile.total_headcount = total
            profile.contractor_pct = round(contractors / total, 3) if total else 0

    # ── Threshold calibration ──────────────────────────────────────────────

    def _calibrate_thresholds(self, profile: CompanyProfile) -> None:
        """
        Derive worker-specific thresholds from this company's profile.

        These replace the hardcoded constants in threshold_registry.py
        with values calibrated to what we know about this company.
        """
        cal = profile.calibrated_thresholds

        # ── PipelineVelocityWorker ─────────────────────────────────────────
        if profile.has_sales_history:
            p75 = profile.p75_sales_cycle_days
            median = profile.median_sales_cycle_days

            # A high-value deal that's spent >50% of P75 in one stage is stalling
            stalled_high = max(int(p75 * 0.50), 14)  # floor at 14 days
            # Standard deal stalled if it's spent >60% of P75
            stalled_std  = max(int(p75 * 0.60), 21)  # floor at 21 days

            cal["PipelineVelocityWorker"] = {
                "stalled_days_high_value": stalled_high,
                "stalled_days_standard":   stalled_std,
                # High-value threshold: P75 of deal sizes if we have it
                "high_value_threshold": (
                    int(profile.median_deal_size * 2)
                    if profile.median_deal_size else 100_000
                ),
            }

        # ── MarketingFunnelWorker ──────────────────────────────────────────
        if profile.win_rate is not None:
            # Set benchmark slightly above actual — creates a realistic stretch goal
            benchmark = min(max(profile.win_rate * 1.10, 0.15), 0.50)
            strong    = min(profile.win_rate * 1.30, 0.60)
            low       = max(profile.win_rate * 0.70, 0.10)

            cal["MarketingFunnelWorker"] = {
                "benchmark_win_rate": round(benchmark, 3),
                "strong_win_rate":    round(strong, 3),
                "low_win_rate":       round(low, 3),
            }

        # ── SalesCapacityWorker ────────────────────────────────────────────
        # Segment-aware pipeline expectations
        if profile.market_segment == "enterprise":
            cal["SalesCapacityWorker"] = {
                "ideal_pipeline_multiple": 4.0,   # enterprise needs deeper coverage
                "max_pipeline_per_rep":    1_000_000,
                "sales_manager_span_min":  4,
                "sales_manager_span_max":  8,
            }
        elif profile.market_segment == "smb":
            cal["SalesCapacityWorker"] = {
                "ideal_pipeline_multiple": 2.5,   # SMB cycles faster, less buffer needed
                "max_pipeline_per_rep":    400_000,
                "sales_manager_span_min":  6,
                "sales_manager_span_max":  12,
            }

        # ── ChurnPredictionWorker ──────────────────────────────────────────
        if profile.median_sales_cycle_days:
            # Inactivity threshold: 2x median cycle = customer has gone quiet
            inactivity_days = min(profile.median_sales_cycle_days * 2, 180)
            cal["ChurnPredictionWorker"] = {
                "customer_inactivity_days": max(inactivity_days, 45),
            }

    # ── Data confidence assessment ────────────────────────────────────────

    def _assess_data_confidence(self, profile: CompanyProfile) -> None:
        """
        Assign an overall data confidence level to the profile.

        high:    rich history, trusted fields, stage map complete
        medium:  partial history or some field trust issues
        low:     insufficient data for reliable calibration
        uncertain: data quality problems detected
        """
        score = 0

        if profile.closed_won_count >= 20:
            score += 3
        elif profile.closed_won_count >= 10:
            score += 2
        elif profile.closed_won_count >= 5:
            score += 1

        if profile.stage_map:
            mapped_pct = sum(
                1 for r in profile.stage_map.values() if r.confidence >= 0.85
            ) / max(len(profile.stage_map), 1)
            if mapped_pct >= 0.90:
                score += 2
            elif mapped_pct >= 0.70:
                score += 1

        if profile.total_headcount and profile.total_headcount >= 10:
            score += 1

        # Penalize for poor field trust
        untrustworthy = sum(
            1 for r in profile.field_trust.values() if not r.use_for_analysis
        )
        if untrustworthy >= 3:
            score -= 2

        if score >= 5:
            profile.data_confidence = "high"
        elif score >= 3:
            profile.data_confidence = "medium"
        elif score >= 1:
            profile.data_confidence = "low"
        else:
            profile.data_confidence = "uncertain"


# ── Percentile utility ─────────────────────────────────────────────────────

def _percentile(data: list[float], pct: float) -> float:
    """Return the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (pct / 100) * (len(sorted_data) - 1)
    lo  = int(idx)
    hi  = lo + 1
    if hi >= len(sorted_data):
        return sorted_data[-1]
    frac = idx - lo
    return sorted_data[lo] + frac * (sorted_data[hi] - sorted_data[lo])
