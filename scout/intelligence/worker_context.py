"""
scout/intelligence/worker_context.py — WorkerContext

WorkerContext is the single object passed to every worker at runtime.
It bundles:
  - The CompanyProfile (calibrated thresholds, field trust, business model)
  - The StageVocabularyMapper (translates raw stage names to canonical ones)
  - Convenience accessors so workers don't need to import intelligence internals

Design principles:
  - Workers should never import CompanyProfileBuilder directly
  - WorkerContext is always available — if no profile was built, it provides
    safe, hardcoded defaults that match pre-intelligence behavior exactly
  - Workers opt in to intelligence; they don't break if context is None

Usage in a worker:
    def run(self, tenant_id: str, context: WorkerContext | None = None) -> WorkerResult:
        ctx = context or WorkerContext.default()

        # Calibrated threshold — falls back to hardcoded value if no profile
        stall_days = ctx.threshold("PipelineVelocityWorker", "stalled_days_standard", 30)

        # Stage translation
        canonical = ctx.stage(deal["stage"])          # "Stage 4 - Paper" → "negotiation"
        late_stages = ctx.late_stage_names()           # all raw names at proposal+

        # Field trust
        if ctx.field_trusted("opportunity.close_date"):
            ...  # safe to assert findings based on close_date

        # Business model context
        if ctx.is_subscription():
            ...  # apply retention-model logic
"""

from __future__ import annotations

import logging
from typing import Any

from scout.intelligence.company_profile import CompanyProfile, FieldTrustRecord
from scout.intelligence.stage_mapper import StageVocabularyMapper

logger = logging.getLogger(__name__)


class WorkerContext:
    """
    Runtime context injected into workers by the insight pipeline.

    Every method has a safe default so workers that receive context=None
    (or WorkerContext.default()) behave exactly as they did before
    the Schema Intelligence Layer was introduced.
    """

    def __init__(
        self,
        company_profile: CompanyProfile | None,
        stage_mapper: StageVocabularyMapper | None,
    ) -> None:
        self._profile = company_profile
        self._mapper  = stage_mapper or StageVocabularyMapper.default()

    # ── Factory methods ────────────────────────────────────────────────────

    @classmethod
    def default(cls) -> "WorkerContext":
        """
        A no-op context with safe defaults.
        Workers using this behave identically to pre-intelligence behavior.
        """
        return cls(company_profile=None, stage_mapper=StageVocabularyMapper.default())

    @classmethod
    def from_profile(cls, profile: CompanyProfile) -> "WorkerContext":
        """Build a context from a fully built CompanyProfile."""
        mapper = StageVocabularyMapper.from_stage_stats(
            [
                {
                    "stage_name":        rec.raw_name,
                    "deal_count":        rec.deal_count,
                    "avg_probability":   rec.avg_probability,
                    "avg_days_in_stage": rec.avg_days_in_stage,
                    "won_count":         1 if rec.is_closed_won else 0,
                    "lost_count":        1 if rec.is_closed_lost else 0,
                }
                for rec in profile.stage_map.values()
            ]
        ) if profile.stage_map else StageVocabularyMapper.default()

        return cls(company_profile=profile, stage_mapper=mapper)

    # ── Threshold access ───────────────────────────────────────────────────

    def threshold(self, worker_name: str, key: str, default: Any) -> Any:
        """
        Return a calibrated threshold for a worker.
        Falls back to `default` if no calibration exists.

        Example:
            stall = ctx.threshold("PipelineVelocityWorker", "stalled_days_standard", 30)
        """
        if self._profile is None:
            return default
        return self._profile.get_threshold(worker_name, key, default)

    # ── Stage translation ──────────────────────────────────────────────────

    def stage(self, raw_stage: str | None) -> str:
        """Translate a raw stage name to its canonical form."""
        if not raw_stage:
            return "unknown"
        return self._mapper.map(raw_stage)

    def late_stage_names(self) -> set[str]:
        """All raw stage names that are at proposal or later (but not closed)."""
        return self._mapper.get_stages_at_or_after("proposal")

    def negotiation_stage_names(self) -> set[str]:
        """All raw stage names that map to the negotiation canonical stage."""
        return self._mapper.get_stages_at_or_after("negotiation")

    def closed_won_stage_names(self) -> set[str]:
        """All raw stage names that map to closed_won."""
        return self._mapper.get_closed_won_stages()

    def active_stage_names(self) -> set[str]:
        """All raw stage names for deals still actively in play."""
        return self._mapper.get_active_stages()

    def is_late_stage(self, raw_stage: str | None) -> bool:
        """True if the raw stage maps to proposal or negotiation."""
        return self._mapper.is_late_stage(raw_stage or "")

    # ── Field trust ────────────────────────────────────────────────────────

    def field_trusted(self, field_name: str, min_confidence: float = 0.70) -> bool:
        """
        True if the field has sufficient data quality for definitive assertions.

        Usage:
            if ctx.field_trusted("opportunity.close_date"):
                # Safe to use close_date in findings
        """
        if self._profile is None:
            return True  # default: trust all fields (pre-intelligence behavior)
        record = self._profile.trust_field(field_name)
        return record.use_for_analysis and record.confidence >= min_confidence

    def field_trust_note(self, field_name: str) -> str:
        """Return any caveat note for a field, or empty string."""
        if self._profile is None:
            return ""
        record = self._profile.trust_field(field_name)
        return record.caveat_note if record.use_with_caveat else ""

    # ── Business model helpers ─────────────────────────────────────────────

    def is_subscription(self) -> bool:
        """True if the company appears to use a subscription / recurring revenue model."""
        if self._profile is None:
            return False
        return self._profile.business_model in {"subscription", "mixed"}

    def is_enterprise(self) -> bool:
        """True if the company sells into enterprise accounts."""
        if self._profile is None:
            return False
        return self._profile.market_segment in {"enterprise", "mixed"}

    def is_smb(self) -> bool:
        """True if the company sells primarily to SMB."""
        if self._profile is None:
            return False
        return self._profile.market_segment == "smb"

    # ── Sales cycle context ────────────────────────────────────────────────

    @property
    def median_sales_cycle(self) -> int | None:
        """Median days to close a deal, from won history. None if unknown."""
        return self._profile.median_sales_cycle_days if self._profile else None

    @property
    def p75_sales_cycle(self) -> int | None:
        """P75 days to close. Anything above this in a single stage = stalling."""
        return self._profile.p75_sales_cycle_days if self._profile else None

    @property
    def avg_deal_size(self) -> float | None:
        """Average closed-won deal size."""
        return self._profile.avg_deal_size if self._profile else None

    @property
    def win_rate(self) -> float | None:
        """Historical win rate. None if insufficient data."""
        return self._profile.win_rate if self._profile else None

    @property
    def has_calibrated_history(self) -> bool:
        """True if the profile has enough history to derive calibrated thresholds."""
        return self._profile is not None and self._profile.has_sales_history

    # ── General profile access ─────────────────────────────────────────────

    @property
    def company_profile(self) -> CompanyProfile | None:
        """Raw CompanyProfile for workers that need direct access."""
        return self._profile

    @property
    def segment_label(self) -> str:
        """Human-readable market segment label for findings."""
        if self._profile is None:
            return "unknown"
        return self._profile.segment_label

    @property
    def data_confidence(self) -> str:
        """Overall data confidence level: high / medium / low / uncertain."""
        if self._profile is None:
            return "low"
        return self._profile.data_confidence

    def confidence_note(self) -> str:
        """
        A brief note to append to findings when data confidence is not high.
        Returns empty string when confidence is high (no note needed).
        """
        c = self.data_confidence
        if c == "high":
            return ""
        if c == "medium":
            return " (Note: based on partial data — validate before acting)"
        if c == "low":
            return " (Note: limited scan history — findings may improve with more scans)"
        return " (Note: data quality issues detected — treat findings as directional)"


# ── Pipeline factory function ─────────────────────────────────────────────

def build_company_context(driver, tenant_id: str) -> WorkerContext:
    """
    Top-level factory: build a WorkerContext for a tenant.

    Called once per scan, before any workers run. The resulting context
    is passed to every worker in the pipeline.

    Usage in insights.py:
        from scout.intelligence import build_company_context
        ctx = build_company_context(driver, tenant_id)
        result = PipelineVelocityWorker(driver).run(tenant_id, context=ctx)
    """
    from scout.intelligence.company_profile_builder import CompanyProfileBuilder

    try:
        builder = CompanyProfileBuilder(driver)
        profile = builder.build(tenant_id)
        return WorkerContext.from_profile(profile)
    except Exception as exc:
        logger.warning(
            "build_company_context failed for %s: %s — using default context",
            tenant_id, exc
        )
        return WorkerContext.default()
