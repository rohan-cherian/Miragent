"""
scout/intelligence/stage_mapper.py — Stage Vocabulary Mapper

The single biggest source of false negatives across revenue workers:
hardcoded Salesforce stage names like "Negotiation/Review" that no
real company actually uses after 3+ years of customization.

This module maps whatever stage names a company uses to 8 canonical
pipeline stages, using three techniques in priority order:

  1. Exact match against a known-aliases library (fast, no AI)
  2. Normalized fuzzy match (handles case/punctuation variations)
  3. Behavioral inference from deal data (stages where probability
     is typically high = late stage, etc.)

The canonical stage vocabulary:
  prospecting  → Lead / first contact
  qualification → Validated fit / BANT criteria met
  discovery    → Needs assessment / demo scheduled
  demo         → Demo completed / solution presented
  proposal     → Formal proposal / SOW sent
  negotiation  → Pricing / legal / procurement review
  closed_won   → Deal signed
  closed_lost  → Deal lost or disqualified

Canonical ordering for "at or after" checks:
  prospecting(0) → qualification(1) → discovery(2) → demo(3)
  → proposal(4) → negotiation(5) → closed_won(6) / closed_lost(6)
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

from scout.intelligence.company_profile import StageMappingRecord

logger = logging.getLogger(__name__)

# ── Canonical stage ordering ───────────────────────────────────────────────

CANONICAL_STAGES = [
    "prospecting",
    "qualification",
    "discovery",
    "demo",
    "proposal",
    "negotiation",
    "closed_won",
    "closed_lost",
]

STAGE_ORDER: dict[str, int] = {s: i for i, s in enumerate(CANONICAL_STAGES)}

# Stages that represent active selling (not yet closed)
ACTIVE_STAGES = {"prospecting", "qualification", "discovery", "demo", "proposal", "negotiation"}

# Stages at or after proposal (high-value — deal is real, just needs to close)
LATE_STAGES = {"proposal", "negotiation"}


# ── Known aliases library ──────────────────────────────────────────────────
# Compiled from real Salesforce implementations across PE portfolio companies.
# Keys are lowercase stripped. Values are canonical stage names.

KNOWN_ALIASES: dict[str, str] = {
    # Prospecting variants
    "prospecting":                  "prospecting",
    "prospect":                     "prospecting",
    "lead":                         "prospecting",
    "new":                          "prospecting",
    "open":                         "prospecting",
    "stage 1":                      "prospecting",
    "stage 1 - connect":            "prospecting",
    "stage 1 - prospect":           "prospecting",
    "01 - prospecting":             "prospecting",
    "1 - prospecting":              "prospecting",
    "connect":                      "prospecting",
    "initial contact":              "prospecting",
    "outreach":                     "prospecting",

    # Qualification variants
    "qualification":                "qualification",
    "qualify":                      "qualification",
    "qualified":                    "qualification",
    "mql":                          "qualification",
    "sql":                          "qualification",
    "stage 2":                      "qualification",
    "stage 2 - qualify":            "qualification",
    "stage 2 - qualification":      "qualification",
    "02 - qualification":           "qualification",
    "bant":                         "qualification",
    "needs analysis":               "qualification",
    "needs assessment":             "qualification",
    "scoping":                      "qualification",
    "validating":                   "qualification",
    "validated":                    "qualification",

    # Discovery variants
    "discovery":                    "discovery",
    "discover":                     "discovery",
    "stage 2 - discover":           "discovery",
    "stage 3":                      "discovery",
    "stage 3 - discover":           "discovery",
    "stage 3 - discovery":          "discovery",
    "03 - discovery":               "discovery",
    "demo scheduled":               "discovery",
    "evaluation":                   "discovery",
    "evaluating":                   "discovery",
    "value proposition":            "discovery",

    # Demo variants
    "demo":                         "demo",
    "demo completed":               "demo",
    "presentation":                 "demo",
    "presented":                    "demo",
    "poc":                          "demo",
    "proof of concept":             "demo",
    "trial":                        "demo",
    "pilot":                        "demo",
    "stage 3 - solution":           "demo",
    "stage 4":                      "demo",
    "04 - demo":                    "demo",
    "solution":                     "demo",
    "solution design":              "demo",
    "id decision makers":           "demo",

    # Proposal variants
    "proposal":                     "proposal",
    "propose":                      "proposal",
    "proposed":                     "proposal",
    "proposal/price quote":         "proposal",
    "proposal price quote":         "proposal",
    "price quote":                  "proposal",
    "pricing":                      "proposal",
    "quoting":                      "proposal",
    "quote":                        "proposal",
    "sow":                          "proposal",
    "sow sent":                     "proposal",
    "stage 4 - propose":            "proposal",
    "stage 5":                      "proposal",
    "05 - proposal":                "proposal",
    "best case":                    "proposal",
    "stage 5 - proposal":           "proposal",

    # Negotiation variants
    "negotiation":                  "negotiation",
    "negotiate":                    "negotiation",
    "negotiating":                  "negotiation",
    "negotiation/review":           "negotiation",
    "negotiation review":           "negotiation",
    "legal review":                 "negotiation",
    "pending legal review":         "negotiation",
    "legal":                        "negotiation",
    "procurement":                  "negotiation",
    "procurement review":           "negotiation",
    "pending procurement":          "negotiation",
    "security review":              "negotiation",
    "infosec review":               "negotiation",
    "security assessment":          "negotiation",
    "contract":                     "negotiation",
    "contract review":              "negotiation",
    "contracting":                  "negotiation",
    "pending legal":                "negotiation",
    "paper":                        "negotiation",
    "in paper":                     "negotiation",
    "stage 4 - paper":              "negotiation",
    "stage 5 - negotiate":          "negotiation",
    "stage 5 - negotiation":        "negotiation",
    "stage 6":                      "negotiation",
    "06 - negotiation":             "negotiation",
    "verbal commit":                "negotiation",
    "verbal":                       "negotiation",
    "commit":                       "negotiation",
    "committed":                    "negotiation",
    "closing":                      "negotiation",
    "ready to close":               "negotiation",
    "decision":                     "negotiation",
    "decision makers":              "negotiation",
    "id. decision makers":          "negotiation",
    "technical review":             "negotiation",
    "final review":                 "negotiation",
    "executive review":             "negotiation",

    # Closed Won variants
    "closed won":                   "closed_won",
    "closedwon":                    "closed_won",
    "closed - won":                 "closed_won",
    "won":                          "closed_won",
    "closed/won":                   "closed_won",

    # Closed Lost variants
    "closed lost":                  "closed_lost",
    "closedlost":                   "closed_lost",
    "closed - lost":                "closed_lost",
    "lost":                         "closed_lost",
    "closed/lost":                  "closed_lost",
    "dead":                         "closed_lost",
    "disqualified":                 "closed_lost",
    "no decision":                  "closed_lost",
    "no deal":                      "closed_lost",
}


def _normalize(s: str) -> str:
    """Lowercase, strip punctuation and extra whitespace for fuzzy matching."""
    s = s.lower().strip()
    s = re.sub(r"[_\-/\\|]+", " ", s)   # normalize separators
    s = re.sub(r"\s+", " ", s)          # collapse whitespace
    return s.strip()


# Pre-built normalized alias lookup (built once at module load)
# This allows matching "Stage 4 - Paper" → normalize → "stage 4 paper" → "negotiation"
_NORMALIZED_ALIASES: dict[str, str] = {
    _normalize(k): v for k, v in KNOWN_ALIASES.items()
}


# ── StageVocabularyMapper ──────────────────────────────────────────────────

class StageVocabularyMapper:
    """
    Maps a company's custom stage names to canonical pipeline stages.

    Build one mapper per tenant from the stage statistics in the graph,
    then attach it to the WorkerContext for all workers in that scan.

    Usage:
        mapper = StageVocabularyMapper.from_stage_stats(stage_stats)
        canonical = mapper.map("Stage 4 - Paper")   # → "negotiation"
        late = mapper.get_stages_at_or_after("proposal")  # → {"Stage 4...", "Stage 5..."}
    """

    def __init__(self, stage_records: dict[str, StageMappingRecord]) -> None:
        self._records = stage_records

    @classmethod
    def from_stage_stats(cls, stage_stats: list[dict]) -> "StageVocabularyMapper":
        """
        Build a mapper from a list of stage statistics pulled from the graph.

        Each entry in stage_stats should have:
          {stage_name, deal_count, avg_probability, avg_days_in_stage,
           won_count, lost_count}

        This is the primary factory method — called by CompanyProfileBuilder.
        """
        records: dict[str, StageMappingRecord] = {}

        for stat in stage_stats:
            raw = stat.get("stage_name") or ""
            if not raw:
                continue

            deal_count = stat.get("deal_count", 0)
            avg_prob = stat.get("avg_probability")
            avg_days = stat.get("avg_days_in_stage")
            won_count = stat.get("won_count", 0)
            lost_count = stat.get("lost_count", 0)

            # Try to map via known-aliases library
            canonical, confidence = _resolve_canonical(raw, avg_prob, won_count, lost_count, deal_count)

            records[raw] = StageMappingRecord(
                raw_name=raw,
                canonical=canonical,
                confidence=confidence,
                deal_count=deal_count,
                avg_probability=avg_prob,
                avg_days_in_stage=avg_days,
                is_closed_won=(canonical == "closed_won"),
                is_closed_lost=(canonical == "closed_lost"),
                inferred=True,
            )

        logger.info(
            "StageVocabularyMapper: mapped %d stage names "
            "(%d high-confidence, %d uncertain)",
            len(records),
            sum(1 for r in records.values() if r.confidence >= 0.85),
            sum(1 for r in records.values() if r.confidence < 0.85),
        )

        return cls(records)

    @classmethod
    def default(cls) -> "StageVocabularyMapper":
        """
        A mapper pre-loaded with the standard Salesforce stage names.
        Used as a safe fallback when no stage stats are available.
        """
        default_stages = [
            {"stage_name": "Prospecting",       "deal_count": 0, "avg_probability": 10,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Qualification",      "deal_count": 0, "avg_probability": 20,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Needs Analysis",     "deal_count": 0, "avg_probability": 20,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Value Proposition",  "deal_count": 0, "avg_probability": 50,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Id. Decision Makers","deal_count": 0, "avg_probability": 60,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Perception Analysis","deal_count": 0, "avg_probability": 70,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Proposal/Price Quote","deal_count": 0,"avg_probability": 75,  "won_count": 0, "lost_count": 0},
            {"stage_name": "Negotiation/Review", "deal_count": 0, "avg_probability": 90, "won_count": 0, "lost_count": 0},
            {"stage_name": "Closed Won",         "deal_count": 0, "avg_probability": 100, "won_count": 1, "lost_count": 0},
            {"stage_name": "Closed Lost",        "deal_count": 0, "avg_probability": 0,  "won_count": 0, "lost_count": 1},
        ]
        return cls.from_stage_stats(default_stages)

    # ── Lookup methods ─────────────────────────────────────────────────────

    def map(self, raw_stage: str) -> str:
        """
        Map a raw stage name to its canonical form.
        Returns "unknown" if no mapping exists.
        """
        if not raw_stage:
            return "unknown"
        rec = self._records.get(raw_stage)
        if rec:
            return rec.canonical
        # Try fuzzy normalized lookup
        normalized = _normalize(raw_stage)
        for key, record in self._records.items():
            if _normalize(key) == normalized:
                return record.canonical
        # Last resort: normalized alias library
        return _NORMALIZED_ALIASES.get(normalized, "unknown")

    def record(self, raw_stage: str) -> StageMappingRecord | None:
        """Return the full mapping record for a stage name."""
        return self._records.get(raw_stage)

    def get_stages_at_or_after(self, canonical_threshold: str) -> set[str]:
        """
        Return all raw stage names that map to the given canonical stage
        or any later stage (excluding closed).

        Usage:
            late_stage_names = mapper.get_stages_at_or_after("proposal")
            # Returns: {"Proposal/Price Quote", "Negotiation/Review", ...}
        """
        threshold_order = STAGE_ORDER.get(canonical_threshold, 99)
        return {
            raw for raw, rec in self._records.items()
            if (STAGE_ORDER.get(rec.canonical, -1) >= threshold_order
                and not rec.is_closed_won and not rec.is_closed_lost)
        }

    def get_closed_won_stages(self) -> set[str]:
        """Return all raw stage names that map to closed_won."""
        return {raw for raw, rec in self._records.items() if rec.is_closed_won}

    def get_closed_lost_stages(self) -> set[str]:
        """Return all raw stage names that map to closed_lost."""
        return {raw for raw, rec in self._records.items() if rec.is_closed_lost}

    def get_active_stages(self) -> set[str]:
        """Return all raw stage names for deals still in play."""
        return {
            raw for raw, rec in self._records.items()
            if rec.canonical in ACTIVE_STAGES
        }

    def is_late_stage(self, raw_stage: str) -> bool:
        """True if the stage maps to proposal or negotiation."""
        return self.map(raw_stage) in LATE_STAGES

    def is_closed_won(self, raw_stage: str) -> bool:
        rec = self._records.get(raw_stage)
        return rec.is_closed_won if rec else (self.map(raw_stage) == "closed_won")

    def all_records(self) -> list[StageMappingRecord]:
        return list(self._records.values())

    def unmapped_stages(self) -> list[str]:
        """Return raw stage names that could not be mapped with high confidence."""
        return [raw for raw, rec in self._records.items() if rec.confidence < 0.70]

    def summary(self) -> dict:
        """Summary for logging and debugging."""
        return {
            "total_stages": len(self._records),
            "mapped_high_confidence": sum(1 for r in self._records.values() if r.confidence >= 0.85),
            "unmapped": self.unmapped_stages(),
            "canonical_distribution": {
                canonical: sum(1 for r in self._records.values() if r.canonical == canonical)
                for canonical in CANONICAL_STAGES
            },
        }


# ── Resolution logic ───────────────────────────────────────────────────────

def _resolve_canonical(
    raw: str,
    avg_prob: float | None,
    won_count: int,
    lost_count: int,
    deal_count: int,
) -> tuple[str, float]:
    """
    Resolve a raw stage name to its canonical form.
    Returns (canonical_stage, confidence_score).

    Priority:
      1. Known aliases (exact match after normalization) → confidence 0.95
      2. Behavioral inference from probability / won/lost ratios → confidence 0.70
      3. Unknown → confidence 0.10
    """
    normalized = _normalize(raw)

    # 1. Known alias lookup (normalized so "Stage 4 - Paper" matches "stage 4 paper")
    if normalized in _NORMALIZED_ALIASES:
        return _NORMALIZED_ALIASES[normalized], 0.95

    # 2. Behavioral inference
    #    These patterns work even when stage names are completely custom.

    # Pure won/lost determination — very reliable
    if won_count > 0 and lost_count == 0 and deal_count > 0:
        won_pct = won_count / deal_count
        if won_pct >= 0.90:
            return "closed_won", 0.90

    if lost_count > 0 and won_count == 0 and deal_count > 0:
        lost_pct = lost_count / deal_count
        if lost_pct >= 0.90:
            return "closed_lost", 0.90

    # Probability-based inference
    if avg_prob is not None:
        if avg_prob >= 95:
            return "negotiation", 0.75
        elif avg_prob >= 75:
            return "proposal", 0.70
        elif avg_prob >= 50:
            return "demo", 0.65
        elif avg_prob >= 30:
            return "discovery", 0.60
        elif avg_prob >= 15:
            return "qualification", 0.55
        else:
            return "prospecting", 0.55

    # 3. Unknown
    logger.debug("StageVocabularyMapper: could not map stage '%s'", raw)
    return "unknown", 0.10
