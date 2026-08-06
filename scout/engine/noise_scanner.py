"""
scout/engine/noise_scanner.py — Signal/Noise Engine (Sprint 22)

Analyses finding disposition patterns per tenant/worker and:

  1. Maintains a rolling NoiseProfile with acted/dismissed/snoozed rates
  2. Computes a signal_score (0 = pure noise, 1 = pure signal)
  3. Adapts the active_action_cap (WIP gate) based on signal quality
  4. Generates ThresholdProposals when dismiss rates are persistently high

Why rolling 30 days?
  A worker that was miscalibrated six months ago shouldn't permanently
  suppress future findings. Short windows are responsive; long windows
  smooth over burst events. 30 days is the industry convention for
  "current operational tempo".

Why separate this from workers?
  Workers produce findings. The noise scanner observes *reactions* to
  findings. Keeping them separate means workers stay pure (compute
  findings given data) and the noise layer is a pure feedback mechanism.
  Neither needs to know the other exists; the DB is the integration point.

Signal score formula:
  signal_score = acted / (acted + dismissed)  when both > 0
               = 1.0                           when dismissed = 0
               = 0.0                           when acted = 0 and dismissed > 0

  Confidence is sqrt(sample_size / 20) clamped to [0, 1]. Below 5
  dispositions we don't generate proposals — too noisy to be meaningful.

Threshold proposal logic (per worker):
  If dismissed_rate > NOISE_TRIGGER (default 0.6) and we have >= MIN_SAMPLE
  dispositions, the scanner proposes raising the relevant threshold to
  reduce the number of findings. The proposed value is:

    proposed = current * (1 + dismissed_rate * RAISE_FACTOR)

  where RAISE_FACTOR = 0.25 means a 75% dismiss rate suggests a 18.75%
  threshold increase. This is conservative — the admin reviews and approves.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.db.models import (
    FindingDisposition,
    NoiseProfile,
    ThresholdProposal,
    WorkerConfig,
)
from scout.workers.threshold_registry import DEFAULTS, get_defaults, get_worker_names

logger = logging.getLogger(__name__)

# ── Tuning constants ───────────────────────────────────────────────────────────

WINDOW_DAYS = 30          # rolling window for dismiss rate calculation
MIN_SAMPLE = 5            # minimum dispositions before generating proposals
NOISE_TRIGGER = 0.60      # dismissed_rate above this → generate proposal
RAISE_FACTOR = 0.25       # how aggressively to propose threshold increases
MAX_WIP_CAP = 10          # maximum concurrent active actions per worker
MIN_WIP_CAP = 1           # floor — never suppress all findings
DEFAULT_WIP_CAP = 5       # starting cap for new workers

# Keys that are candidates for threshold adjustment based on dismiss patterns.
# These are thresholds where "raising the bar" reduces finding volume.
# When a worker's dismiss rate is persistently high, the scanner proposes
# raising the relevant threshold so fewer (but more actionable) findings surface.
_RAISE_CANDIDATES: dict[str, list[str]] = {
    "HireToRetireWorker":             ["inactive_rate_high", "inactive_rate_medium", "high_span"],
    "IssueToResolutionWorker":        ["old_deal_days", "stall_days", "early_stage_pct"],
    "VendorBenchmarkWorker":          ["overpaying_critical_pct", "overpaying_high_pct"],
    "ProcessBottleneckWorker":        ["fragmentation_threshold", "high_span_threshold"],
    "ChurnPredictionWorker":          ["customer_inactivity_days"],
    "PipelineVelocityWorker":         ["stalled_days_high_value", "stalled_days_standard", "concentration_pct"],
    "SalesCapacityWorker":            ["ideal_pipeline_multiple", "max_pipeline_per_rep"],
    "ExpansionRevenueWorker":         ["min_expansion_value"],
    "WorkforceWorker":                ["span_critical_max", "span_optimal_max"],
    "ExpenseAuditWorker":             ["outlier_std_devs", "high_spend_audit_threshold"],
    "LicenseManagementWorker":        ["renewal_warning_days", "renewal_critical_days", "high_spend_license"],
    "SaasLicenseWorker":              ["shelfware_threshold", "category_overlap_min"],
    "ApProcessingWorker":             ["high_concentration_pct", "small_vendor_spend"],
    "WorkingCapitalWorker":           ["unmanaged_spend_threshold", "annual_billing_threshold"],
    "RenewalWorkflowWorker":          ["renewal_risk_high_days", "renewal_risk_medium_days"],
    "EngagementIntelligenceWorker":   ["key_person_acct_threshold", "key_person_deal_threshold", "high_inactive_under_manager"],
    "PricingIntegrityWorker":         ["outlier_std_devs", "small_deal_threshold"],
    "ProcureToPayWorker":             ["high_spend_threshold", "concentration_pct"],
    "HeadcountEfficiencyWorker":      ["ga_ratio_high", "mgmt_overhead_high", "contractor_high"],
    "VendorNegotiationWorker":        ["negotiation_window_days", "high_leverage_spend", "concentration_pct"],
    "TamPenetrationWorker":           ["icp_score_strong", "concentration_risk_pct", "pipeline_icp_low"],
    "MarketingFunnelWorker":          ["low_win_rate", "stale_early_stage_days"],
    "CrossSellCampaignWorker":        ["priority_score_threshold"],
    "CrossSellIntelligenceWorker":    ["score_priority", "score_watch"],
    "LeadEnrichmentWorker":           ["high_revenue_threshold"],
    "MeetingPrepWorker":              ["large_deal_threshold"],
    "OutreachSequenceWorker":         ["top_prospects_n"],
    "SentimentWorker":                ["high_span_attrition_risk", "inactive_rate_high"],
    "VendorWorker":                   ["renewal_critical_days", "spend_concentration_pct"],
    "OnboardingWorker":               ["unowned_account_risk_high"],
    "OffboardingWorker":              ["high_arr_risk", "high_deal_risk"],
    "LeadToCashWorker":               ["recognition_rate_low"],
    # Sprint 57: R&D / DORA
    "DORAMetricsWorker":              ["cfr_medium", "mttr_medium_hrs"],
    "GitHubVelocityWorker":           ["pr_cycle_critical_hrs", "stale_pr_days"],
    # Sprint 59: Security Hygiene
    "SecurityHygieneWorker":          ["inactive_admin_days", "api_key_max_age_days", "admin_sprawl_critical_pct"],
    # Sprint 62: Process Conformance
    "ProcessConformanceWorker":       ["sla_breach_high_pct", "escalation_high_pct", "sop_coverage_min"],
}


# ── Main scanner ───────────────────────────────────────────────────────────────


def run_noise_scan(db: Session, tenant_id: str) -> dict[str, Any]:
    """
    Run the full noise scan for one tenant.

    On first run (no dispositions yet): seeds baseline NoiseProfile rows for
    every registered worker so the Intelligence page shows all workers at their
    default signal_score=1.0 / wip_cap=5 state rather than appearing empty.

    Returns a summary dict (useful for logging and tests):
      {
        "profiles_updated": int,
        "proposals_created": int,
        "workers_scanned": [str, ...],
      }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    # Load all dispositions in the rolling window for this tenant
    rows = db.execute(
        select(FindingDisposition).where(
            FindingDisposition.tenant_id == tenant_id,
            FindingDisposition.disposed_at >= cutoff,
        )
    ).scalars().all()

    # Group by worker_name
    by_worker: dict[str, list[FindingDisposition]] = {}
    for row in rows:
        by_worker.setdefault(row.worker_name, []).append(row)

    proposals_created = 0

    # Update profiles for workers that have disposition data
    for worker_name, dispositions in by_worker.items():
        profile = _upsert_profile(db, tenant_id, worker_name, dispositions)
        if _should_propose(profile):
            n = _create_proposals(db, tenant_id, worker_name, profile)
            proposals_created += n

    # Seed baseline profiles for all registered workers that have no data yet.
    # This ensures the Intelligence page always shows all workers, not just
    # the ones that happen to have dispositions in the rolling window.
    all_worker_names = set(get_worker_names())
    existing_profile_workers = set(by_worker.keys())
    seeded: list[str] = []
    for worker_name in sorted(all_worker_names - existing_profile_workers):
        _seed_baseline_profile(db, tenant_id, worker_name)
        seeded.append(worker_name)

    db.commit()

    return {
        "profiles_updated": len(by_worker),
        "profiles_seeded": len(seeded),
        "proposals_created": proposals_created,
        "workers_scanned": list(by_worker.keys()),
        "workers_seeded": seeded,
    }


# ── Profile management ─────────────────────────────────────────────────────────


def _seed_baseline_profile(
    db: Session,
    tenant_id: str,
    worker_name: str,
) -> None:
    """
    Insert a NoiseProfile row for a worker that has no disposition data yet.

    Only creates the row if it doesn't already exist — this is purely a
    one-time bootstrap so the Intelligence page renders all workers
    immediately after the first refresh, rather than waiting for the first
    ACTED/DISMISSED disposition to be recorded.

    Baseline state: signal_score=1.0 (assumed good until proven noisy),
    acted_rate=0, dismissed_rate=0, wip_cap=DEFAULT_WIP_CAP.
    """
    existing = db.execute(
        select(NoiseProfile).where(
            NoiseProfile.tenant_id == tenant_id,
            NoiseProfile.worker_name == worker_name,
        )
    ).scalar_one_or_none()

    if existing is not None:
        return  # already seeded — don't overwrite real data

    profile = NoiseProfile(
        tenant_id=tenant_id,
        worker_name=worker_name,
        total_surfaced=0,
        total_acted=0,
        total_dismissed=0,
        total_snoozed=0,
        acted_rate=0.0,
        dismissed_rate=0.0,
        signal_score=1.0,
        active_action_cap=DEFAULT_WIP_CAP,
        computed_at=datetime.now(timezone.utc),
    )
    db.add(profile)


def _upsert_profile(
    db: Session,
    tenant_id: str,
    worker_name: str,
    dispositions: list[FindingDisposition],
) -> NoiseProfile:
    """Create or update the NoiseProfile for one worker."""

    profile = db.execute(
        select(NoiseProfile).where(
            NoiseProfile.tenant_id == tenant_id,
            NoiseProfile.worker_name == worker_name,
        )
    ).scalar_one_or_none()

    total = len(dispositions)
    acted = sum(1 for d in dispositions if d.disposition == "ACTED")
    dismissed = sum(1 for d in dispositions if d.disposition == "DISMISSED")
    snoozed = sum(1 for d in dispositions if d.disposition == "SNOOZED")

    acted_rate = acted / total if total > 0 else 0.0
    dismissed_rate = dismissed / total if total > 0 else 0.0

    # Signal score: fraction of decisive dispositions that were positive
    decisive = acted + dismissed
    signal_score = (acted / decisive) if decisive > 0 else 1.0

    # WIP cap: start at default, shrink proportionally with noise
    # Intuition: 80% dismiss rate → cap drops to 1; 0% dismiss rate → cap stays at max
    wip_cap = max(
        MIN_WIP_CAP,
        min(MAX_WIP_CAP, round(DEFAULT_WIP_CAP * signal_score * 2)),
    )

    if profile is None:
        profile = NoiseProfile(
            tenant_id=tenant_id,
            worker_name=worker_name,
        )
        db.add(profile)

    profile.total_surfaced = total
    profile.total_acted = acted
    profile.total_dismissed = dismissed
    profile.total_snoozed = snoozed
    profile.acted_rate = acted_rate
    profile.dismissed_rate = dismissed_rate
    profile.signal_score = signal_score
    profile.active_action_cap = wip_cap
    profile.computed_at = datetime.now(timezone.utc)

    return profile


def _should_propose(profile: NoiseProfile) -> bool:
    """Return True if this profile warrants a threshold proposal."""
    return (
        profile.total_surfaced >= MIN_SAMPLE
        and profile.dismissed_rate >= NOISE_TRIGGER
    )


# ── Proposal generation ────────────────────────────────────────────────────────


def _create_proposals(
    db: Session,
    tenant_id: str,
    worker_name: str,
    profile: NoiseProfile,
) -> int:
    """
    Generate ThresholdProposal rows for a noisy worker.

    Returns the number of proposals created (skips if a PENDING proposal
    already exists for the same worker/key, to avoid duplicate proposals).
    """
    candidates = _RAISE_CANDIDATES.get(worker_name, [])
    if not candidates:
        return 0

    # Load current effective values (DB override or platform default)
    defaults = get_defaults(worker_name)
    db_row = db.execute(
        select(WorkerConfig).where(
            WorkerConfig.tenant_id == tenant_id,
            WorkerConfig.worker_name == worker_name,
        )
    ).scalar_one_or_none()
    overrides = dict(db_row.thresholds or {}) if db_row else {}
    effective = {**defaults, **overrides}

    # Load existing pending proposals to avoid duplicates
    existing_keys = set(
        row.threshold_key
        for row in db.execute(
            select(ThresholdProposal).where(
                ThresholdProposal.tenant_id == tenant_id,
                ThresholdProposal.worker_name == worker_name,
                ThresholdProposal.status == "PENDING",
            )
        ).scalars().all()
    )

    confidence = min(1.0, math.sqrt(profile.total_surfaced / 20))
    created = 0

    for key in candidates:
        if key in existing_keys:
            continue  # already have a pending proposal for this key
        if key not in effective:
            continue  # key not in this worker's threshold set

        current = float(effective[key])
        proposed = round(current * (1 + profile.dismissed_rate * RAISE_FACTOR), 4)

        if proposed <= current:
            continue  # no meaningful change

        rationale = (
            f"{worker_name} had a {profile.dismissed_rate:.0%} dismiss rate "
            f"over the last {WINDOW_DAYS} days "
            f"({profile.total_dismissed} dismissed out of {profile.total_surfaced} surfaced). "
            f"Raising '{key}' from {current} to {proposed} would reduce finding volume "
            f"by approximately {profile.dismissed_rate:.0%}, aligning alerts with "
            f"what your team considers actionable. "
            f"Confidence: {confidence:.0%} (based on {profile.total_surfaced} data points)."
        )

        proposal = ThresholdProposal(
            tenant_id=tenant_id,
            worker_name=worker_name,
            threshold_key=key,
            current_value=current,
            proposed_value=proposed,
            direction="raise",
            rationale=rationale,
            confidence=confidence,
            dismissed_count=profile.total_dismissed,
            dismissed_rate=profile.dismissed_rate,
        )
        db.add(proposal)
        created += 1

    return created


# ── Capacity gate helper ───────────────────────────────────────────────────────


def get_wip_cap(db: Session, tenant_id: str, worker_name: str) -> int:
    """
    Return the current WIP cap for a worker.

    Used by the findings orchestrator to decide how many open actions to
    maintain per worker. If no profile exists yet, returns the default.
    """
    profile = db.execute(
        select(NoiseProfile).where(
            NoiseProfile.tenant_id == tenant_id,
            NoiseProfile.worker_name == worker_name,
        )
    ).scalar_one_or_none()

    return profile.active_action_cap if profile else DEFAULT_WIP_CAP
