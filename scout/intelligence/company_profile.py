"""
scout/intelligence/company_profile.py — Per-tenant company profile

CompanyProfile is the core object of the Schema Intelligence Layer.
It answers the question every worker should be asking before it fires:
"What do I know about THIS company before I start making claims?"

What it captures:
  - Business model (subscription vs. transactional vs. services)
  - Market segment (SMB / mid-market / enterprise) inferred from ACV
  - Sales cycle calibration (median/P75 from closed-won history)
  - Stage vocabulary (their Salesforce stage names → canonical stages)
  - Field trust (per-field confidence based on null rates and consistency)
  - PE context (investment thesis, portfolio stage, target margins)

Why persisted per-tenant:
  The profile improves with every scan. After scan 1, we have rough
  estimates. After scan 5, we have statistically meaningful history.
  Storing it in SQLite means workers always have the best available
  understanding, even if the scan is re-run an hour later.

Design rule:
  CompanyProfile is ALWAYS safe to pass as None. Every worker must
  degrade gracefully to its hardcoded defaults if no profile exists.
  This ensures backwards compatibility and safe cold-start behavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ── Type aliases ───────────────────────────────────────────────────────────

BusinessModel = Literal["subscription", "transactional", "usage_based", "services", "mixed", "unknown"]
MarketSegment  = Literal["smb", "mid_market", "enterprise", "mixed", "unknown"]
PortfolioStage = Literal["hold", "growth", "exit_prep", "unknown"]
DataConfidence = Literal["high", "medium", "low", "uncertain"]


# ── FieldTrustRecord ───────────────────────────────────────────────────────

@dataclass
class FieldTrustRecord:
    """
    Reliability assessment for a single data field.

    Workers check this before asserting findings based on a field.
    A field with 60% null rate should not be used for definitive claims —
    findings based on it should be marked as uncertain.

    Example:
        close_date: null_rate=0.03, confidence=0.95, use_for_analysis=True
        legacy_tier: null_rate=0.83, confidence=0.12, use_for_analysis=False
    """
    field_name: str
    null_rate: float = 0.0           # 0.0 = always populated, 1.0 = always null
    confidence: float = 1.0          # 0.0–1.0 overall reliability score
    semantic_note: str = ""          # human/AI-readable note on what this field means
    use_for_analysis: bool = True    # False = skip this field entirely
    use_with_caveat: bool = False    # True = use but mark findings as uncertain
    caveat_note: str = ""            # why it should be used with caution

    @classmethod
    def from_null_rate(cls, field_name: str, null_rate: float) -> "FieldTrustRecord":
        """Construct a trust record from a measured null rate."""
        if null_rate >= 0.80:
            return cls(
                field_name=field_name,
                null_rate=null_rate,
                confidence=0.10,
                use_for_analysis=False,
                semantic_note=f"Field is {null_rate*100:.0f}% null — likely deprecated or unused.",
            )
        elif null_rate >= 0.50:
            return cls(
                field_name=field_name,
                null_rate=null_rate,
                confidence=0.40,
                use_for_analysis=True,
                use_with_caveat=True,
                caveat_note=f"Field is {null_rate*100:.0f}% null — findings may be incomplete.",
            )
        elif null_rate >= 0.25:
            return cls(
                field_name=field_name,
                null_rate=null_rate,
                confidence=0.70,
                use_for_analysis=True,
                use_with_caveat=True,
                caveat_note=f"Field has {null_rate*100:.0f}% null rate — some records missing.",
            )
        else:
            return cls(
                field_name=field_name,
                null_rate=null_rate,
                confidence=0.95,
                use_for_analysis=True,
            )


# ── StageMappingRecord ─────────────────────────────────────────────────────

@dataclass
class StageMappingRecord:
    """
    Maps a company's custom stage name to a canonical pipeline stage.

    Companies bastardize Salesforce stage names in countless ways.
    This record captures what we've inferred (or a human has confirmed)
    about what each stage actually means in this company's process.
    """
    raw_name: str                    # e.g. "Stage 4 - Paper"
    canonical: str                   # e.g. "negotiation"
    confidence: float = 1.0          # how confident we are in the mapping
    deal_count: int = 0              # how many deals have used this stage
    avg_probability: float | None = None  # typical probability at this stage
    avg_days_in_stage: float | None = None  # median time spent here
    is_closed_won: bool = False
    is_closed_lost: bool = False
    inferred: bool = True            # False = human-confirmed


# ── CompanyProfile ─────────────────────────────────────────────────────────

@dataclass
class CompanyProfile:
    """
    Everything Miragent knows about a specific portfolio company's
    data patterns, business model, and configuration.

    This is the primary output of the Schema Intelligence Layer.
    Workers consume it via WorkerContext.

    Thread safety: CompanyProfile is read-only at worker runtime.
    The builder creates it before workers run; workers never mutate it.
    """

    tenant_id: str

    # ── Business model ────────────────────────────────────────────────────
    business_model: BusinessModel = "unknown"
    market_segment: MarketSegment = "unknown"

    # ── Sales cycle calibration ───────────────────────────────────────────
    # Derived from closed-won opportunity history in the graph.
    # None = insufficient data (< 5 closed-won deals).
    median_sales_cycle_days: int | None = None
    p75_sales_cycle_days: int | None = None     # 75th percentile — anything above = stalled
    p25_sales_cycle_days: int | None = None     # 25th percentile — lightning-fast deals
    median_deal_size: float | None = None
    avg_deal_size: float | None = None
    win_rate: float | None = None               # closed_won / (closed_won + closed_lost)
    closed_won_count: int = 0                   # how many won deals informed calibration

    # ── Stage vocabulary ──────────────────────────────────────────────────
    # Maps this company's custom stage names to canonical pipeline stages.
    # Canonical stages: prospecting, qualification, discovery, demo,
    #                   proposal, negotiation, closed_won, closed_lost
    stage_map: dict[str, StageMappingRecord] = field(default_factory=dict)

    # ── Field trust ───────────────────────────────────────────────────────
    # Per-field reliability scores derived from null rate analysis.
    field_trust: dict[str, FieldTrustRecord] = field(default_factory=dict)

    # ── Workforce calibration ─────────────────────────────────────────────
    total_headcount: int | None = None
    avg_span_of_control: float | None = None
    contractor_pct: float | None = None

    # ── PE context ────────────────────────────────────────────────────────
    # Set by operating partners — not inferred from data.
    portfolio_stage: PortfolioStage = "unknown"
    investment_thesis: str = ""           # e.g. "retention + margin expansion"
    target_ebitda_margin: float | None = None  # e.g. 0.20 = 20%

    # ── Calibrated thresholds ────────────────────────────────────────────
    # Worker-specific thresholds derived from this company's data patterns.
    # These override the hardcoded defaults in threshold_registry.py.
    # Format: {worker_name: {threshold_key: value}}
    calibrated_thresholds: dict[str, dict[str, Any]] = field(default_factory=dict)

    # ── Known exceptions and annotations ────────────────────────────────
    # Human-written notes about known anomalies in this company's data.
    # E.g. "Legacy_Stage_Override__c is from pre-2022 migration — ignore"
    known_exceptions: list[str] = field(default_factory=list)

    # ── Metadata ──────────────────────────────────────────────────────────
    built_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    scan_count: int = 0
    data_confidence: DataConfidence = "low"  # increases as we accumulate scans

    # ── Helpers ───────────────────────────────────────────────────────────

    def get_threshold(self, worker_name: str, key: str, default: Any = None) -> Any:
        """
        Return a calibrated threshold for a specific worker.
        Falls back to `default` if no calibration exists.

        Usage in a worker:
            stall_days = ctx.company_profile.get_threshold(
                "PipelineVelocityWorker", "stalled_days_standard", fallback=30
            )
        """
        worker_cfg = self.calibrated_thresholds.get(worker_name, {})
        return worker_cfg.get(key, default)

    def trust_field(self, field_name: str) -> FieldTrustRecord:
        """
        Return trust record for a field.
        Returns a high-confidence default if no record exists
        (safe fallback: don't penalize fields we haven't profiled).
        """
        return self.field_trust.get(
            field_name,
            FieldTrustRecord(field_name=field_name, confidence=0.80),
        )

    def canonical_stage(self, raw_stage: str) -> str:
        """
        Translate a raw stage name to its canonical form.
        Returns "unknown" if the stage name hasn't been mapped.
        """
        rec = self.stage_map.get(raw_stage)
        return rec.canonical if rec else "unknown"

    def is_late_stage(self, raw_stage: str) -> bool:
        """True if the stage is negotiation or later (but not closed)."""
        canonical = self.canonical_stage(raw_stage)
        return canonical in {"negotiation", "proposal"}

    def is_closed(self, raw_stage: str) -> bool:
        """True if the stage represents a closed deal."""
        rec = self.stage_map.get(raw_stage)
        if rec:
            return rec.is_closed_won or rec.is_closed_lost
        canonical = self.canonical_stage(raw_stage)
        return canonical in {"closed_won", "closed_lost"}

    @property
    def has_sales_history(self) -> bool:
        """True if we have enough won deals to calibrate sales cycle thresholds."""
        return self.closed_won_count >= 5 and self.median_sales_cycle_days is not None

    @property
    def segment_label(self) -> str:
        """Human-readable market segment."""
        return {
            "smb": "SMB",
            "mid_market": "Mid-Market",
            "enterprise": "Enterprise",
            "mixed": "Mixed Segments",
            "unknown": "Unknown",
        }.get(self.market_segment, "Unknown")

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage and logging."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompanyProfile":
        """Deserialize from storage."""
        # Reconstruct nested dataclasses
        stage_map = {
            k: StageMappingRecord(**v)
            for k, v in data.pop("stage_map", {}).items()
        }
        field_trust = {
            k: FieldTrustRecord(**v)
            for k, v in data.pop("field_trust", {}).items()
        }
        profile = cls(**data)
        profile.stage_map = stage_map
        profile.field_trust = field_trust
        return profile

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"CompanyProfile({self.tenant_id}): "
            f"model={self.business_model}, segment={self.market_segment}, "
            f"median_cycle={self.median_sales_cycle_days}d, "
            f"won_deals={self.closed_won_count}, "
            f"confidence={self.data_confidence}, "
            f"stages_mapped={len(self.stage_map)}"
        )
