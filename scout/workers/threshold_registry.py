"""
scout/workers/threshold_registry.py — Centralized threshold registry for all workers.

This is the single source of truth for:
  1. DEFAULT values — the hardcoded baselines, identical to what was previously
     scattered as module-level constants in each worker file.
  2. METADATA — labels, descriptions, data types, min/max ranges, and industry
     benchmark ranges shown in the admin portal UI.

How it works at runtime:
  - Workers call `ThresholdConfig.for_worker(worker_name, config_overrides)` to
    get a merged config object.
  - `config_overrides` is a plain dict loaded by the API/orchestrator from the
    WorkerConfig DB table for the tenant.
  - If no override is set, the default is returned transparently.
  - Workers never read module-level constants directly — they call cfg.get().

Adding a new threshold:
  1. Add the default to DEFAULTS[worker_name]
  2. Add metadata to METADATA[worker_name]
  3. Update the worker to call cfg.get("your_new_threshold") instead of the constant
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Threshold type constants ───────────────────────────────────────────────

T_PERCENTAGE  = "percentage"   # float 0.0–1.0, displayed as %
T_INTEGER     = "integer"      # whole number
T_CURRENCY    = "currency"     # dollar amount
T_DAYS        = "days"         # number of days
T_MULTIPLIER  = "multiplier"   # e.g. 3.0x pipeline coverage
T_BOOLEAN     = "boolean"      # true/false toggle
T_STD_DEVS    = "std_devs"     # standard deviations
T_HOURS       = "hours"        # number of hours
T_RATIO       = "ratio"        # rate/frequency (e.g. deployments per day)


# ── Registry ──────────────────────────────────────────────────────────────

DEFAULTS: dict[str, dict[str, Any]] = {

    "HireToRetireWorker": {
        "inactive_rate_high":      0.20,
        "inactive_rate_medium":    0.10,
        "high_span":               10,
        "min_headcount":           5,
        "ic_mgmt_heavy_ratio":     4,
        "ic_mgmt_thin_ratio":      12,
        "enabled":                 True,
    },

    "IssueToResolutionWorker": {
        "stall_days":              45,
        "old_deal_days":           90,
        "early_stage_pct":         50,
        "resolution_rate_low":     0.50,
        "enabled":                 True,
    },

    "LeadToCashWorker": {
        "recognition_rate_low":    0.20,
        "min_rep_deals":           1,
        "enabled":                 True,
    },

    "ProcessBottleneckWorker": {
        "fragmentation_threshold": 2,
        "high_span_threshold":     12,
        "enabled":                 True,
    },

    "VendorBenchmarkWorker": {
        "overpaying_critical_pct": 50,
        "overpaying_high_pct":     20,
        "negotiation_window_min":  30,
        "negotiation_window_max":  120,
        "savings_high_threshold":  10_000,
        "alternatives_spend_min":  30_000,
        "enabled":                 True,
    },

    "ChurnPredictionWorker": {
        "high_arr_concentration":    500_000,
        "customer_inactivity_days":  90,
        "enabled":                   True,
    },

    "PipelineVelocityWorker": {
        "stalled_days_high_value": 21,
        "stalled_days_standard":   30,
        "high_value_threshold":    100_000,
        "concentration_pct":       40,
        "enabled":                 True,
    },

    "SalesCapacityWorker": {
        "ideal_pipeline_multiple":  3.0,
        "max_pipeline_per_rep":     600_000,
        "sales_manager_span_min":   4,
        "sales_manager_span_max":   10,
        "enabled":                  True,
    },

    "ExpansionRevenueWorker": {
        "min_expansion_value":     50_000,
        "high_revenue_customer":   100_000,
        "enabled":                 True,
    },

    "WorkforceWorker": {
        "span_optimal_min":        5,
        "span_optimal_max":        10,
        "span_critical_max":       15,
        "key_person_threshold":    3,
        "enabled":                 True,
    },

    "ExpenseAuditWorker": {
        "outlier_std_devs":          1.5,
        "min_vendors_for_stats":     3,
        "high_spend_audit_threshold": 75_000,
        "enabled":                   True,
    },

    "LicenseManagementWorker": {
        "renewal_warning_days":    90,
        "renewal_critical_days":   30,
        "high_spend_license":      50_000,
        "zombie_monthly_cost":     150,
        "overlap_vendor_min":      3,
        "enabled":                 True,
    },

    "SaasLicenseWorker": {
        "zombie_license_cost_est": 150,
        "category_overlap_min":    2,
        "shelfware_threshold":     0.70,
        "enabled":                 True,
    },

    "ApProcessingWorker": {
        "early_pay_discount_rate": 0.02,
        "high_concentration_pct":  0.40,
        "batching_threshold":      5,
        "small_vendor_spend":      10_000,
        "ap_benchmark_days":       30,
        "enabled":                 True,
    },

    "WorkingCapitalWorker": {
        "unmanaged_spend_threshold": 25_000,
        "annual_billing_threshold":  50_000,
        "enabled":                   True,
    },

    "VendorWorker": {
        "renewal_critical_days":      30,   # renewal in <30 days = act NOW
        "renewal_high_days":          90,   # renewal in <90 days = start negotiation
        "renewal_medium_days":       180,   # renewal in <180 days = schedule review
        "spend_concentration_pct":    40,   # one vendor > this % of total spend = risk
        "consolidation_min_vendors":   3,   # ≥ this many vendors in same category = consolidation opportunity
        "enabled":                   True,
    },

    "RenewalWorkflowWorker": {
        "renewal_risk_high_days":    365,    # last won deal older than this = high risk
        "renewal_risk_medium_days":  270,    # last won deal older than this = medium risk
        "high_arr_threshold":        100_000, # above this, account gets executive-level attention
        "enabled":                   True,
    },

    "EngagementIntelligenceWorker": {
        "key_person_acct_threshold":    0.40,  # one person owns >40% of customer accounts
        "key_person_deal_threshold":    0.40,  # one person owns >40% of open pipeline
        "deep_org_layers":              5,     # management depth > 5 = bureaucratic
        "flat_org_threshold":           2,     # management depth < 2 = founder-led / flat
        "min_headcount_for_analysis":   3,     # below this, skip analysis
        "high_inactive_under_manager":  0.30,  # 30%+ inactive on a manager's team = stress
        "resilience_score_low":         40,    # below this = At Risk label
        "resilience_score_medium":      60,    # below this = Moderate label
        "enabled":                      True,
    },

    "PricingIntegrityWorker": {
        "outlier_std_devs":      1.5,   # deals > this many SDs below mean = discount outlier
        "min_deals_for_stats":   3,     # minimum closed-won deals to run analysis
        "small_deal_threshold":  0.40,  # deals < 40% of mean ACV = possible heavy discount
        "enabled":               True,
    },

    "ProcureToPayWorker": {
        "high_spend_threshold":   50_000,  # annual vendor spend above which payment terms are material
        "concentration_pct":      50,      # top-3 vendors > this % of total spend = risk
        "unmanaged_threshold":    25_000,  # vendor with no terms + spend above this = unmanaged
        "enabled":                True,
    },

    "HeadcountEfficiencyWorker": {
        "ga_ratio_high":       0.25,  # above this = overstaffed G&A
        "ga_ratio_benchmark":  0.18,  # benchmark for healthy mid-market
        "mgmt_overhead_high":  0.28,  # managers > 28% of headcount = too many layers
        "contractor_high":     0.20,  # contractors > 20% of workforce = structural risk
        "span_optimal_min":    5,     # managers with fewer DRs than this are underloaded
        "dept_imbalance":      0.40,  # dept is >40% of total headcount = concentration
        "enabled":             True,
    },

    "OnboardingWorker": {
        "unowned_account_risk_high":  5,   # 5+ unowned accounts = HIGH severity
        "enabled":                    True,
    },

    "OffboardingWorker": {
        "high_arr_risk":   100_000,  # inactive owner of account with >$100k won deals = critical
        "high_deal_risk":   50_000,  # inactive owner of open deal >$50k = high
        "enabled":          True,
    },

    "VendorNegotiationWorker": {
        "negotiation_window_days":  90,    # start negotiation this far before renewal
        "critical_window_days":     30,    # less than this = limited leverage
        "high_leverage_spend":     100_000, # above this, meaningful negotiating power
        "concentration_pct":        30,    # vendor > this % of total spend = dependency risk
        "typical_savings_pct":       0.18, # conservative savings estimate for negotiations
        "enabled":                   True,
    },

    "TamPenetrationWorker": {
        "icp_score_strong":       70,   # above this = strong ICP match
        "icp_score_moderate":     40,   # above this = partial ICP match
        "concentration_risk_pct": 60,   # >60% of customers in one industry = concentration risk
        "pipeline_icp_low":       0.50, # less than 50% of pipeline on ICP accounts = concern
        "enabled":                True,
    },

    "MarketingFunnelWorker": {
        "benchmark_win_rate":        0.25,  # 25% of all opportunities should close won
        "benchmark_proposal_to_win": 0.50,  # 50% of proposals should close
        "strong_win_rate":           0.40,  # above this is a strong win rate
        "low_win_rate":              0.15,  # below this is a concerning win rate
        "stale_early_stage_days":    45,    # qualification deals this old should have progressed
        "enabled":                   True,
    },

    "CrossSellCampaignWorker": {
        "priority_score_threshold":   30,   # accounts scoring 30+ get campaign briefs
        "max_campaigns":               5,   # max campaign briefs to generate per scan
        "expansion_arr_target_pct":   0.05, # target: add 5% of account revenue as expansion ARR
        "enabled":                    True,
    },

    "CrossSellIntelligenceWorker": {
        "score_priority":      70,    # accounts above this trigger cross-sell agent
        "score_watch":         40,    # accounts above this are worth monitoring
        "penetration_target":  0.05,  # target: win 5% of account's annual revenue
        "high_deal_count":      2,    # 2+ won deals = established multi-buyer
        "enabled":              True,
    },

    "LeadEnrichmentWorker": {
        "high_revenue_threshold":  10_000_000,  # accounts above this = priority for enrichment
        "missing_field_penalty":   33,           # ICP completeness points lost per missing field
        "enabled":                 True,
    },

    "MeetingPrepWorker": {
        "large_deal_threshold":  50_000,  # deals above this get enhanced briefings
        "max_briefs":             5,      # max meeting briefs to generate per scan
        "enabled":               True,
    },

    "OutreachSequenceWorker": {
        "sequence_touches":   5,  # number of touch-points in an outreach sequence
        "top_prospects_n":    5,  # generate sequences for top N prospects per scan
        "enabled":            True,
    },

    "SentimentWorker": {
        "high_span_attrition_risk":  10,   # managers with >this many reports = elevated attrition
        "inactive_rate_high":        0.20, # >20% inactive accounts = high turnover signal
        "inactive_rate_medium":      0.10, # >10% = moderate signal
        "contractor_morale_risk":    0.20, # above this, contractors may be displacing FTEs
        "leadership_depth_risk":      3,   # fewer than 3 managers in large dept = leadership gap
        "enabled":                   True,
    },

    # ── Sprint 57: R&D / DORA Workers ──────────────────────────────────────

    "DORAMetricsWorker": {
        # Deployment Frequency (deploys per day, rolling 30d)
        "deploy_freq_elite":         1.0,   # ≥1/day = elite performer
        "deploy_freq_high":          0.14,  # ≥1/week = high performer (~0.14/day)
        "deploy_freq_medium":        0.033, # ≥1/month = medium (~0.033/day)
        # Lead Time for Changes (hours from commit-merged to production)
        "lead_time_elite_hrs":       1.0,   # <1h = elite
        "lead_time_high_hrs":        24.0,  # <1d = high
        "lead_time_medium_hrs":      168.0, # <1wk = medium (>1wk = low)
        # Change Failure Rate (% of deploys causing an incident)
        "cfr_elite":                 0.05,  # <5% = elite
        "cfr_high":                  0.10,  # <10% = high
        "cfr_medium":                0.15,  # <15% = medium (>15% = low/critical)
        # Mean Time to Restore (hours to resolve production incident)
        "mttr_elite_hrs":            1.0,   # <1h = elite
        "mttr_high_hrs":             24.0,  # <24h = high
        "mttr_medium_hrs":           168.0, # <1wk = medium
        "enabled":                   True,
    },

    "GitHubVelocityWorker": {
        # PR cycle time (hours from open to merge)
        "pr_cycle_critical_hrs":     120.0, # >5 days = CRITICAL bottleneck
        "pr_cycle_high_hrs":          48.0, # >2 days = HIGH
        "pr_cycle_medium_hrs":        24.0, # >1 day = MEDIUM
        # Review lag (hours from PR open to first review)
        "review_lag_critical_hrs":    48.0, # >2 days = CRITICAL
        "review_lag_high_hrs":        24.0, # >1 day = HIGH
        # Stale PRs (open PRs with no activity)
        "stale_pr_days":              14,   # PRs untouched >14 days = stale
        "stale_pr_critical_count":    10,   # >10 stale PRs = CRITICAL
        "stale_pr_high_count":         5,   # >5 stale PRs = HIGH
        # Repo inactivity
        "repo_inactive_days":         30,   # no push in >30 days = stale
        # Bus factor risk (% of commits from single contributor)
        "bus_factor_pct":             0.70, # >70% from one person = HIGH risk
        "enabled":                   True,
    },

    # ── Sprint 59: Security Hygiene Worker ─────────────────────────────────

    "SecurityHygieneWorker": {
        # MFA enrollment rate (fraction of active users with MFA enabled)
        "mfa_enrollment_low":          0.80,  # <80% = HIGH severity
        "mfa_enrollment_critical":     0.50,  # <50% = CRITICAL severity
        # Inactive privileged accounts (days since last login)
        "inactive_admin_days":         60,    # admin not seen in >60 days = flag
        # API key rotation
        "api_key_max_age_days":        90,    # keys older than this need rotation
        # Admin sprawl (ratio of admins to total active users)
        "admin_sprawl_critical_pct":   0.20,  # >20% admins = CRITICAL
        "admin_sprawl_high_pct":       0.10,  # >10% admins = HIGH
        "enabled":                     True,
    },

    # ── Sprint 62: Process Conformance Worker ───────────────────────────────

    "ProcessConformanceWorker": {
        "sla_breach_critical_pct": 1.00,    # >100% over target = CRITICAL
        "sla_breach_high_pct":     0.50,    # >50% over target = HIGH
        "sla_breach_medium_pct":   0.20,    # >20% over target = MEDIUM
        "escalation_critical_pct": 0.40,    # >40% tier-2 escalation = CRITICAL
        "escalation_high_pct":     0.25,    # >25% = HIGH
        "sop_coverage_min":        0.80,    # <80% coverage = flag
        "enabled":                 True,
    },
}


METADATA: dict[str, dict[str, dict[str, Any]]] = {

    "HireToRetireWorker": {
        "inactive_rate_high": {
            "label":          "High attrition alert threshold",
            "description":    "Flag as HIGH when inactive headcount exceeds this percentage of total headcount.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.50,
            "industry_low":   0.15,
            "industry_high":  0.25,
        },
        "inactive_rate_medium": {
            "label":          "Medium attrition alert threshold",
            "description":    "Flag as MEDIUM when inactive headcount exceeds this percentage.",
            "type":           T_PERCENTAGE,
            "min":            0.03,
            "max":            0.30,
            "industry_low":   0.08,
            "industry_high":  0.15,
        },
        "high_span": {
            "label":          "Overloaded manager span",
            "description":    "Flag a manager as overloaded when they have this many or more direct reports.",
            "type":           T_INTEGER,
            "min":            5,
            "max":            20,
            "industry_low":   8,
            "industry_high":  12,
        },
        "min_headcount": {
            "label":          "Minimum headcount for org-shape analysis",
            "description":    "Only analyze IC-to-manager ratio when headcount is at or above this number.",
            "type":           T_INTEGER,
            "min":            2,
            "max":            25,
            "industry_low":   4,
            "industry_high":  10,
        },
        "ic_mgmt_heavy_ratio": {
            "label":          "Management-heavy IC:manager ratio",
            "description":    "Flag as management-heavy when IC-to-manager ratio falls below this value.",
            "type":           T_MULTIPLIER,
            "min":            2.0,
            "max":            7.0,
            "industry_low":   4.0,
            "industry_high":  6.0,
        },
        "ic_mgmt_thin_ratio": {
            "label":          "Management-thin IC:manager ratio",
            "description":    "Flag as management-thin when IC-to-manager ratio exceeds this value.",
            "type":           T_MULTIPLIER,
            "min":            8.0,
            "max":            20.0,
            "industry_low":   8.0,
            "industry_high":  14.0,
        },
    },

    "IssueToResolutionWorker": {
        "old_deal_days": {
            "label":          "Stalled deal threshold (days)",
            "description":    "Flag an open deal as stalled when it has been in the pipeline longer than this many days.",
            "type":           T_DAYS,
            "min":            30,
            "max":            180,
            "industry_low":   60,
            "industry_high":  90,
        },
        "stall_days": {
            "label":          "Stage stall threshold (days)",
            "description":    "Number of days a deal can remain in the same stage before being flagged.",
            "type":           T_DAYS,
            "min":            14,
            "max":            90,
            "industry_low":   30,
            "industry_high":  45,
        },
        "early_stage_pct": {
            "label":          "Early-stage pipeline concentration alert (%)",
            "description":    "Flag a pipeline bottleneck when this percentage or more of open deals are in early stages.",
            "type":           T_PERCENTAGE,
            "min":            0.25,
            "max":            0.80,
            "industry_low":   0.40,
            "industry_high":  0.60,
        },
        "resolution_rate_low": {
            "label":          "Low resolution rate threshold",
            "description":    "Flag low resolution velocity when closed-to-open deal ratio falls below this value.",
            "type":           T_MULTIPLIER,
            "min":            0.20,
            "max":            1.0,
            "industry_low":   0.40,
            "industry_high":  0.70,
        },
    },

    "VendorBenchmarkWorker": {
        "overpaying_critical_pct": {
            "label":          "CRITICAL overpaying threshold (%)",
            "description":    "Flag a vendor as CRITICAL when actual spend exceeds benchmark by this percentage.",
            "type":           T_PERCENTAGE,
            "min":            0.20,
            "max":            1.00,
            "industry_low":   0.40,
            "industry_high":  0.60,
        },
        "overpaying_high_pct": {
            "label":          "HIGH overpaying threshold (%)",
            "description":    "Flag a vendor as HIGH when actual spend exceeds benchmark by this percentage.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.50,
            "industry_low":   0.15,
            "industry_high":  0.25,
        },
        "negotiation_window_min": {
            "label":          "Negotiation window opens (days to renewal)",
            "description":    "Flag contracts as entering the negotiation window when renewal is this many days away.",
            "type":           T_DAYS,
            "min":            14,
            "max":            90,
            "industry_low":   30,
            "industry_high":  60,
        },
        "negotiation_window_max": {
            "label":          "Negotiation window closes (days to renewal)",
            "description":    "Upper bound of the negotiation window — contracts beyond this are too far out to act.",
            "type":           T_DAYS,
            "min":            60,
            "max":            365,
            "industry_low":   90,
            "industry_high":  180,
        },
        "savings_high_threshold": {
            "label":          "Potential savings HIGH threshold ($)",
            "description":    "Flag a vendor as HIGH priority when potential annual savings exceed this dollar amount.",
            "type":           T_CURRENCY,
            "min":            1_000,
            "max":            100_000,
            "industry_low":   5_000,
            "industry_high":  25_000,
        },
    },

    "PipelineVelocityWorker": {
        "stalled_days_high_value": {
            "label":          "High-value deal stall threshold (days)",
            "description":    "Days before a high-value deal (above threshold) is flagged as stalled.",
            "type":           T_DAYS,
            "min":            7,
            "max":            60,
            "industry_low":   14,
            "industry_high":  30,
        },
        "stalled_days_standard": {
            "label":          "Standard deal stall threshold (days)",
            "description":    "Days before a standard deal is flagged as stalled.",
            "type":           T_DAYS,
            "min":            14,
            "max":            90,
            "industry_low":   21,
            "industry_high":  45,
        },
        "high_value_threshold": {
            "label":          "High-value deal threshold ($)",
            "description":    "Deals above this amount are monitored more aggressively for stalling.",
            "type":           T_CURRENCY,
            "min":            10_000,
            "max":            500_000,
            "industry_low":   50_000,
            "industry_high":  150_000,
        },
        "concentration_pct": {
            "label":          "Pipeline concentration risk (%)",
            "description":    "Flag concentration risk when one deal represents this percentage or more of total pipeline.",
            "type":           T_PERCENTAGE,
            "min":            0.20,
            "max":            0.80,
            "industry_low":   0.30,
            "industry_high":  0.50,
        },
    },

    "SalesCapacityWorker": {
        "ideal_pipeline_multiple": {
            "label":          "Ideal pipeline coverage (x quota)",
            "description":    "Healthy pipeline should be at least this multiple of quota. Below this flags under-coverage.",
            "type":           T_MULTIPLIER,
            "min":            1.5,
            "max":            6.0,
            "industry_low":   2.5,
            "industry_high":  4.0,
        },
        "max_pipeline_per_rep": {
            "label":          "Max pipeline per rep ($)",
            "description":    "Flag a rep as over-concentrated when their open pipeline exceeds this amount.",
            "type":           T_CURRENCY,
            "min":            100_000,
            "max":            2_000_000,
            "industry_low":   400_000,
            "industry_high":  800_000,
        },
        "sales_manager_span_max": {
            "label":          "Sales manager max span",
            "description":    "Flag a sales manager as overloaded when they have this many or more direct reports.",
            "type":           T_INTEGER,
            "min":            5,
            "max":            15,
            "industry_low":   7,
            "industry_high":  10,
        },
    },

    "LicenseManagementWorker": {
        "renewal_warning_days": {
            "label":          "Renewal warning (days out)",
            "description":    "Flag a contract as needing attention when renewal is this many days away.",
            "type":           T_DAYS,
            "min":            30,
            "max":            180,
            "industry_low":   60,
            "industry_high":  90,
        },
        "renewal_critical_days": {
            "label":          "Renewal critical (days out)",
            "description":    "Flag a contract as CRITICAL when renewal is this many days away.",
            "type":           T_DAYS,
            "min":            7,
            "max":            60,
            "industry_low":   21,
            "industry_high":  45,
        },
        "high_spend_license": {
            "label":          "High-spend license negotiation threshold ($)",
            "description":    "Flag a license for negotiation review when annual spend exceeds this amount.",
            "type":           T_CURRENCY,
            "min":            5_000,
            "max":            500_000,
            "industry_low":   25_000,
            "industry_high":  100_000,
        },
        "overlap_vendor_min": {
            "label":          "Vendor overlap minimum (count)",
            "description":    "Flag category overlap when this many or more vendors exist in the same category.",
            "type":           T_INTEGER,
            "min":            2,
            "max":            6,
            "industry_low":   2,
            "industry_high":  3,
        },
    },

    "ExpenseAuditWorker": {
        "outlier_std_devs": {
            "label":          "Spend outlier sensitivity (σ)",
            "description":    "Flag spend as an outlier when it exceeds the category mean by this many standard deviations.",
            "type":           T_STD_DEVS,
            "min":            1.0,
            "max":            3.0,
            "industry_low":   1.5,
            "industry_high":  2.5,
        },
        "high_spend_audit_threshold": {
            "label":          "High-spend audit trigger ($)",
            "description":    "Flag any single vendor above this annual spend for an audit review.",
            "type":           T_CURRENCY,
            "min":            10_000,
            "max":            500_000,
            "industry_low":   50_000,
            "industry_high":  150_000,
        },
    },

    "WorkforceWorker": {
        "span_critical_max": {
            "label":          "Critical span of control threshold",
            "description":    "Flag a manager as CRITICAL when they have this many or more direct reports.",
            "type":           T_INTEGER,
            "min":            10,
            "max":            25,
            "industry_low":   12,
            "industry_high":  18,
        },
        "span_optimal_max": {
            "label":          "Optimal span of control maximum",
            "description":    "Upper end of the healthy manager span range.",
            "type":           T_INTEGER,
            "min":            6,
            "max":            15,
            "industry_low":   8,
            "industry_high":  10,
        },
    },

    "RenewalWorkflowWorker": {
        "renewal_risk_high_days": {
            "label":          "High renewal risk threshold (days)",
            "description":    "Flag a customer as HIGH renewal risk when their last won deal is older than this many days.",
            "type":           T_DAYS,
            "min":            180,
            "max":            730,
            "industry_low":   270,
            "industry_high":  450,
        },
        "renewal_risk_medium_days": {
            "label":          "Medium renewal risk threshold (days)",
            "description":    "Flag a customer as MEDIUM renewal risk when their last won deal is older than this many days.",
            "type":           T_DAYS,
            "min":            90,
            "max":            365,
            "industry_low":   180,
            "industry_high":  300,
        },
        "high_arr_threshold": {
            "label":          "High-ARR renewal attention threshold ($)",
            "description":    "Customers above this ARR with no expansion pipeline receive executive-level escalation.",
            "type":           T_CURRENCY,
            "min":            25_000,
            "max":            500_000,
            "industry_low":   50_000,
            "industry_high":  200_000,
        },
    },

    "PricingIntegrityWorker": {
        "outlier_std_devs": {
            "label":          "Discount outlier sensitivity (σ)",
            "description":    "Flag a deal as a discount outlier when its ACV falls more than this many standard deviations below the mean.",
            "type":           T_STD_DEVS,
            "min":            0.5,
            "max":            3.0,
            "industry_low":   1.0,
            "industry_high":  2.0,
        },
        "min_deals_for_stats": {
            "label":          "Minimum closed-won deals for analysis",
            "description":    "Skip pricing integrity analysis when fewer than this many closed-won deals exist.",
            "type":           T_INTEGER,
            "min":            2,
            "max":            10,
            "industry_low":   3,
            "industry_high":  5,
        },
        "small_deal_threshold": {
            "label":          "Small deal threshold (% of mean ACV)",
            "description":    "Flag a won deal as a possible heavy discount when its amount falls below this fraction of the mean ACV.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.70,
            "industry_low":   0.30,
            "industry_high":  0.50,
        },
    },

    "ProcureToPayWorker": {
        "high_spend_threshold": {
            "label":          "Material vendor spend threshold ($)",
            "description":    "Annual vendor spend above which payment terms are considered material and negotiable.",
            "type":           T_CURRENCY,
            "min":            5_000,
            "max":            500_000,
            "industry_low":   25_000,
            "industry_high":  100_000,
        },
        "concentration_pct": {
            "label":          "Vendor concentration risk (%)",
            "description":    "Flag spend concentration risk when top-3 vendors account for more than this percentage of total payables.",
            "type":           T_PERCENTAGE,
            "min":            0.30,
            "max":            0.80,
            "industry_low":   0.40,
            "industry_high":  0.60,
        },
        "unmanaged_threshold": {
            "label":          "Unmanaged vendor spend threshold ($)",
            "description":    "Flag a vendor as unmanaged when they have no payment terms and annual spend exceeds this amount.",
            "type":           T_CURRENCY,
            "min":            5_000,
            "max":            200_000,
            "industry_low":   15_000,
            "industry_high":  50_000,
        },
    },

    "HeadcountEfficiencyWorker": {
        "ga_ratio_high": {
            "label":          "G&A overstaffing threshold (%)",
            "description":    "Flag G&A as overstaffed when it exceeds this fraction of total headcount.",
            "type":           T_PERCENTAGE,
            "min":            0.15,
            "max":            0.45,
            "industry_low":   0.20,
            "industry_high":  0.30,
        },
        "ga_ratio_benchmark": {
            "label":          "G&A benchmark (%)",
            "description":    "Target G&A ratio for a healthy mid-market company — used in finding descriptions.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.30,
            "industry_low":   0.15,
            "industry_high":  0.22,
        },
        "mgmt_overhead_high": {
            "label":          "Management overhead threshold (%)",
            "description":    "Flag as bureaucratic when managers exceed this percentage of total headcount.",
            "type":           T_PERCENTAGE,
            "min":            0.15,
            "max":            0.45,
            "industry_low":   0.20,
            "industry_high":  0.35,
        },
        "contractor_high": {
            "label":          "Contractor concentration threshold (%)",
            "description":    "Flag structural risk when contractors/consultants exceed this share of total workforce.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.40,
            "industry_low":   0.15,
            "industry_high":  0.25,
        },
        "dept_imbalance": {
            "label":          "Department size concentration threshold (%)",
            "description":    "Flag a department as disproportionately large when it exceeds this share of total headcount.",
            "type":           T_PERCENTAGE,
            "min":            0.25,
            "max":            0.60,
            "industry_low":   0.35,
            "industry_high":  0.50,
        },
    },

    "OnboardingWorker": {
        "unowned_account_risk_high": {
            "label":          "Unowned account HIGH severity threshold (count)",
            "description":    "Flag as HIGH severity when a new hire inherits this many or more unowned accounts.",
            "type":           T_INTEGER,
            "min":            1,
            "max":            15,
            "industry_low":   3,
            "industry_high":  7,
        },
    },

    "OffboardingWorker": {
        "high_arr_risk": {
            "label":          "CRITICAL ARR-at-risk threshold ($)",
            "description":    "Flag as CRITICAL when an inactive employee owned accounts with cumulative won deals above this amount.",
            "type":           T_CURRENCY,
            "min":            10_000,
            "max":            1_000_000,
            "industry_low":   50_000,
            "industry_high":  250_000,
        },
        "high_deal_risk": {
            "label":          "HIGH open deal risk threshold ($)",
            "description":    "Flag as HIGH when an inactive employee owns an open deal above this value.",
            "type":           T_CURRENCY,
            "min":            5_000,
            "max":            500_000,
            "industry_low":   25_000,
            "industry_high":  100_000,
        },
    },

    "VendorNegotiationWorker": {
        "negotiation_window_days": {
            "label":          "Negotiation window opens (days to renewal)",
            "description":    "Start tracking contracts for negotiation when renewal is this many days away.",
            "type":           T_DAYS,
            "min":            30,
            "max":            180,
            "industry_low":   60,
            "industry_high":  120,
        },
        "critical_window_days": {
            "label":          "Negotiation leverage deadline (days to renewal)",
            "description":    "Flag limited leverage when renewal is fewer than this many days away.",
            "type":           T_DAYS,
            "min":            7,
            "max":            60,
            "industry_low":   21,
            "industry_high":  45,
        },
        "high_leverage_spend": {
            "label":          "High-leverage spend threshold ($)",
            "description":    "Annual spend above which the company has meaningful negotiating power with the vendor.",
            "type":           T_CURRENCY,
            "min":            10_000,
            "max":            500_000,
            "industry_low":   50_000,
            "industry_high":  200_000,
        },
        "concentration_pct": {
            "label":          "Vendor spend dependency threshold (%)",
            "description":    "Flag vendor dependency when they account for more than this percentage of total spend.",
            "type":           T_PERCENTAGE,
            "min":            0.15,
            "max":            0.60,
            "industry_low":   0.20,
            "industry_high":  0.40,
        },
        "typical_savings_pct": {
            "label":          "Typical negotiation savings rate (%)",
            "description":    "Conservative estimated savings percentage used when projecting negotiation potential.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.35,
            "industry_low":   0.12,
            "industry_high":  0.25,
        },
    },

    "TamPenetrationWorker": {
        "icp_score_strong": {
            "label":          "Strong ICP match score threshold",
            "description":    "Accounts scoring at or above this value are classified as strong ICP matches.",
            "type":           T_INTEGER,
            "min":            50,
            "max":            90,
            "industry_low":   60,
            "industry_high":  80,
        },
        "icp_score_moderate": {
            "label":          "Moderate ICP match score threshold",
            "description":    "Accounts scoring at or above this value (but below strong) are partial ICP matches.",
            "type":           T_INTEGER,
            "min":            20,
            "max":            65,
            "industry_low":   30,
            "industry_high":  55,
        },
        "concentration_risk_pct": {
            "label":          "Industry concentration risk threshold (%)",
            "description":    "Flag TAM concentration risk when more than this percentage of customers are in a single industry.",
            "type":           T_PERCENTAGE,
            "min":            0.40,
            "max":            0.85,
            "industry_low":   0.50,
            "industry_high":  0.70,
        },
        "pipeline_icp_low": {
            "label":          "Pipeline ICP alignment low threshold (%)",
            "description":    "Flag ICP misalignment when less than this fraction of pipeline is on ICP accounts.",
            "type":           T_PERCENTAGE,
            "min":            0.30,
            "max":            0.75,
            "industry_low":   0.40,
            "industry_high":  0.65,
        },
    },

    "MarketingFunnelWorker": {
        "benchmark_win_rate": {
            "label":          "Win rate benchmark (%)",
            "description":    "Expected percentage of all opportunities that close won. Below this flags conversion issues.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.50,
            "industry_low":   0.18,
            "industry_high":  0.30,
        },
        "strong_win_rate": {
            "label":          "Strong win rate threshold (%)",
            "description":    "Win rates above this are considered strong for the company's stage and market.",
            "type":           T_PERCENTAGE,
            "min":            0.25,
            "max":            0.65,
            "industry_low":   0.30,
            "industry_high":  0.50,
        },
        "low_win_rate": {
            "label":          "Concerning win rate threshold (%)",
            "description":    "Win rates below this trigger a HIGH-severity finding on conversion health.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.25,
            "industry_low":   0.10,
            "industry_high":  0.20,
        },
        "stale_early_stage_days": {
            "label":          "Stale early-stage deal threshold (days)",
            "description":    "Flag qualification-stage deals as stale when they have been open longer than this many days.",
            "type":           T_DAYS,
            "min":            14,
            "max":            90,
            "industry_low":   30,
            "industry_high":  60,
        },
    },

    "CrossSellCampaignWorker": {
        "priority_score_threshold": {
            "label":          "Campaign trigger score threshold",
            "description":    "Generate a cross-sell campaign brief for accounts scoring at or above this value.",
            "type":           T_INTEGER,
            "min":            10,
            "max":            50,
            "industry_low":   20,
            "industry_high":  40,
        },
        "max_campaigns": {
            "label":          "Maximum campaigns per scan",
            "description":    "Cap the number of cross-sell campaign briefs generated in a single scan.",
            "type":           T_INTEGER,
            "min":            1,
            "max":            20,
            "industry_low":   3,
            "industry_high":  10,
        },
        "expansion_arr_target_pct": {
            "label":          "Expansion ARR target (% of account revenue)",
            "description":    "Target expansion ARR expressed as a percentage of the account's current annual revenue.",
            "type":           T_PERCENTAGE,
            "min":            0.01,
            "max":            0.20,
            "industry_low":   0.03,
            "industry_high":  0.10,
        },
    },

    "CrossSellIntelligenceWorker": {
        "score_priority": {
            "label":          "Cross-sell priority score threshold",
            "description":    "Accounts scoring at or above this value are flagged as high-priority cross-sell targets.",
            "type":           T_INTEGER,
            "min":            40,
            "max":            90,
            "industry_low":   55,
            "industry_high":  80,
        },
        "score_watch": {
            "label":          "Cross-sell watch score threshold",
            "description":    "Accounts scoring at or above this value (but below priority) are flagged for monitoring.",
            "type":           T_INTEGER,
            "min":            20,
            "max":            65,
            "industry_low":   30,
            "industry_high":  55,
        },
        "penetration_target": {
            "label":          "Expansion revenue penetration target (%)",
            "description":    "Target expansion expressed as a percentage of the account's annual revenue.",
            "type":           T_PERCENTAGE,
            "min":            0.01,
            "max":            0.20,
            "industry_low":   0.03,
            "industry_high":  0.10,
        },
    },

    "LeadEnrichmentWorker": {
        "high_revenue_threshold": {
            "label":          "Priority enrichment revenue threshold ($)",
            "description":    "Accounts with estimated revenue above this are prioritized for enrichment.",
            "type":           T_CURRENCY,
            "min":            1_000_000,
            "max":            100_000_000,
            "industry_low":   5_000_000,
            "industry_high":  25_000_000,
        },
    },

    "MeetingPrepWorker": {
        "large_deal_threshold": {
            "label":          "Large deal enhanced briefing threshold ($)",
            "description":    "Deals above this value receive enhanced meeting prep briefs.",
            "type":           T_CURRENCY,
            "min":            5_000,
            "max":            500_000,
            "industry_low":   25_000,
            "industry_high":  100_000,
        },
        "max_briefs": {
            "label":          "Maximum meeting briefs per scan",
            "description":    "Cap the number of meeting prep briefs generated in a single scan.",
            "type":           T_INTEGER,
            "min":            1,
            "max":            20,
            "industry_low":   3,
            "industry_high":  10,
        },
    },

    "OutreachSequenceWorker": {
        "sequence_touches": {
            "label":          "Outreach sequence touch-points",
            "description":    "Number of touch-points in a generated outreach sequence.",
            "type":           T_INTEGER,
            "min":            3,
            "max":            10,
            "industry_low":   4,
            "industry_high":  7,
        },
        "top_prospects_n": {
            "label":          "Top prospects per scan",
            "description":    "Generate outreach sequences for this many top-scored prospects per scan.",
            "type":           T_INTEGER,
            "min":            1,
            "max":            20,
            "industry_low":   3,
            "industry_high":  10,
        },
    },

    "SentimentWorker": {
        "high_span_attrition_risk": {
            "label":          "Manager overload attrition risk threshold (direct reports)",
            "description":    "Flag elevated team attrition risk when a manager has more than this many direct reports.",
            "type":           T_INTEGER,
            "min":            5,
            "max":            20,
            "industry_low":   8,
            "industry_high":  14,
        },
        "inactive_rate_high": {
            "label":          "High attrition signal threshold (%)",
            "description":    "Flag a high attrition signal when more than this fraction of accounts are inactive.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.40,
            "industry_low":   0.15,
            "industry_high":  0.25,
        },
        "inactive_rate_medium": {
            "label":          "Moderate attrition signal threshold (%)",
            "description":    "Flag a moderate attrition signal when more than this fraction of accounts are inactive.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.25,
            "industry_low":   0.08,
            "industry_high":  0.15,
        },
        "contractor_morale_risk": {
            "label":          "Contractor displacement morale risk (%)",
            "description":    "Flag morale risk when contractors exceed this share of total workforce.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.40,
            "industry_low":   0.15,
            "industry_high":  0.28,
        },
        "leadership_depth_risk": {
            "label":          "Leadership depth risk threshold (manager count)",
            "description":    "Flag a leadership gap in a department when it has fewer than this many managers.",
            "type":           T_INTEGER,
            "min":            1,
            "max":            6,
            "industry_low":   2,
            "industry_high":  4,
        },
    },

    "EngagementIntelligenceWorker": {
        "key_person_acct_threshold": {
            "label":          "Key-person account concentration threshold (%)",
            "description":    "Flag CRITICAL when one person owns more than this share of all customer accounts.",
            "type":           T_PERCENTAGE,
            "min":            0.20,
            "max":            0.75,
            "industry_low":   0.30,
            "industry_high":  0.50,
        },
        "key_person_deal_threshold": {
            "label":          "Key-person pipeline concentration threshold (%)",
            "description":    "Flag HIGH when one person owns more than this share of all open pipeline deals.",
            "type":           T_PERCENTAGE,
            "min":            0.20,
            "max":            0.75,
            "industry_low":   0.30,
            "industry_high":  0.50,
        },
        "high_inactive_under_manager": {
            "label":          "Manager team inactive rate stress signal (%)",
            "description":    "Flag a manager's team as stressed when their inactive rate exceeds this threshold.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.60,
            "industry_low":   0.20,
            "industry_high":  0.40,
        },
        "resilience_score_low": {
            "label":          "Org Resilience Score — At Risk cutoff",
            "description":    "Scores below this value are labelled 'At Risk' in the resilience summary.",
            "type":           T_INTEGER,
            "min":            20,
            "max":            60,
            "industry_low":   30,
            "industry_high":  50,
        },
        "resilience_score_medium": {
            "label":          "Org Resilience Score — Moderate cutoff",
            "description":    "Scores below this value (but above At Risk) are labelled 'Moderate'.",
            "type":           T_INTEGER,
            "min":            40,
            "max":            80,
            "industry_low":   55,
            "industry_high":  70,
        },
    },

    "ChurnPredictionWorker": {
        "high_arr_concentration": {
            "label":          "Key-person ARR concentration threshold ($)",
            "description":    "Flag key-person risk when one rep owns more than this amount of ARR.",
            "type":           T_CURRENCY,
            "min":            100_000,
            "max":            2_000_000,
            "industry_low":   300_000,
            "industry_high":  750_000,
        },
        "customer_inactivity_days": {
            "label":          "Customer inactivity threshold (days)",
            "description":    "Flag a customer account as at-risk when there has been no pipeline activity for this many days.",
            "type":           T_DAYS,
            "min":            30,
            "max":            180,
            "industry_low":   60,
            "industry_high":  120,
        },
    },

    # ── Sprint 57: R&D / DORA Workers ──────────────────────────────────────

    "DORAMetricsWorker": {
        "deploy_freq_elite": {
            "label":          "Elite deployment frequency (deploys/day)",
            "description":    "Repositories deploying at or above this rate are DORA elite performers.",
            "type":           T_RATIO,
            "min":            0.1,
            "max":            10.0,
            "industry_low":   0.5,
            "industry_high":  2.0,
        },
        "cfr_medium": {
            "label":          "Change Failure Rate alert threshold",
            "description":    "Flag repos where the percentage of deployments causing incidents exceeds this value.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.40,
            "industry_low":   0.10,
            "industry_high":  0.20,
        },
        "mttr_medium_hrs": {
            "label":          "MTTR alert threshold (hours)",
            "description":    "Flag repos where mean time to restore a production incident exceeds this many hours.",
            "type":           T_HOURS,
            "min":            4,
            "max":            336,
            "industry_low":   24,
            "industry_high":  72,
        },
    },

    "GitHubVelocityWorker": {
        "pr_cycle_critical_hrs": {
            "label":          "PR cycle time — CRITICAL threshold (hours)",
            "description":    "Flag CRITICAL when the median PR cycle time in a repo exceeds this many hours.",
            "type":           T_HOURS,
            "min":            24,
            "max":            336,
            "industry_low":   48,
            "industry_high":  120,
        },
        "review_lag_critical_hrs": {
            "label":          "Review lag — CRITICAL threshold (hours)",
            "description":    "Flag CRITICAL when the median time from PR open to first review exceeds this many hours.",
            "type":           T_HOURS,
            "min":            8,
            "max":            96,
            "industry_low":   12,
            "industry_high":  48,
        },
        "stale_pr_days": {
            "label":          "Stale PR threshold (days)",
            "description":    "A PR with no activity for this many days is considered stale.",
            "type":           T_DAYS,
            "min":            7,
            "max":            60,
            "industry_low":   14,
            "industry_high":  30,
        },
        "bus_factor_pct": {
            "label":          "Bus-factor concentration threshold",
            "description":    "Flag a repo as HIGH risk when a single contributor is responsible for more than this share of commits.",
            "type":           T_PERCENTAGE,
            "min":            0.50,
            "max":            0.95,
            "industry_low":   0.65,
            "industry_high":  0.80,
        },
    },

    # ── Sprint 62: Process Conformance Worker ──────────────────────────────

    "ProcessConformanceWorker": {
        "sla_breach_high_pct": {
            "label":          "SLA breach HIGH threshold (%)",
            "description":    "Flag as HIGH when actual metric exceeds the stated SLA target by more than this percentage.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            1.00,
            "industry_low":   0.25,
            "industry_high":  0.50,
        },
        "escalation_high_pct": {
            "label":          "Tier-2 escalation rate HIGH threshold (%)",
            "description":    "Flag as HIGH when more than this fraction of tickets are escalated to tier-2.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.60,
            "industry_low":   0.15,
            "industry_high":  0.30,
        },
        "sop_coverage_min": {
            "label":          "Minimum SOP coverage rate (%)",
            "description":    "Flag a process coverage gap when documented SOPs cover less than this fraction of ticket categories.",
            "type":           T_PERCENTAGE,
            "min":            0.50,
            "max":            1.00,
            "industry_low":   0.70,
            "industry_high":  0.90,
        },
    },

    # ── Sprint 59: Security Hygiene Worker ─────────────────────────────────

    "SecurityHygieneWorker": {
        "mfa_enrollment_low": {
            "label":          "MFA enrollment HIGH alert threshold (%)",
            "description":    "Flag as HIGH when the fraction of active users with MFA enabled falls below this value.",
            "type":           T_PERCENTAGE,
            "min":            0.50,
            "max":            0.99,
            "industry_low":   0.80,
            "industry_high":  0.95,
        },
        "mfa_enrollment_critical": {
            "label":          "MFA enrollment CRITICAL threshold (%)",
            "description":    "Flag as CRITICAL when fewer than this fraction of active users have MFA enabled.",
            "type":           T_PERCENTAGE,
            "min":            0.20,
            "max":            0.70,
            "industry_low":   0.40,
            "industry_high":  0.60,
        },
        "inactive_admin_days": {
            "label":          "Inactive admin account threshold (days)",
            "description":    "Flag a privileged account as stale when it has not logged in for this many days.",
            "type":           T_DAYS,
            "min":            30,
            "max":            180,
            "industry_low":   45,
            "industry_high":  90,
        },
        "api_key_max_age_days": {
            "label":          "API key rotation threshold (days)",
            "description":    "Flag API keys that have not been rotated within this many days.",
            "type":           T_DAYS,
            "min":            30,
            "max":            365,
            "industry_low":   60,
            "industry_high":  90,
        },
        "admin_sprawl_critical_pct": {
            "label":          "Admin sprawl CRITICAL threshold (%)",
            "description":    "Flag as CRITICAL when admin-role users exceed this percentage of total active users.",
            "type":           T_PERCENTAGE,
            "min":            0.10,
            "max":            0.50,
            "industry_low":   0.15,
            "industry_high":  0.25,
        },
        "admin_sprawl_high_pct": {
            "label":          "Admin sprawl HIGH threshold (%)",
            "description":    "Flag as HIGH when admin-role users exceed this percentage of total active users.",
            "type":           T_PERCENTAGE,
            "min":            0.05,
            "max":            0.25,
            "industry_low":   0.08,
            "industry_high":  0.15,
        },
    },
}


# ── ThresholdConfig ────────────────────────────────────────────────────────


@dataclass
class ThresholdConfig:
    """
    Merged threshold configuration for one worker run.

    Produced by merging the platform defaults with any client-specific overrides
    stored in the WorkerConfig database table.

    Usage in a worker:
        cfg = ThresholdConfig.for_worker("HireToRetireWorker", config_overrides)
        threshold = cfg.get("inactive_rate_high")
        is_enabled = cfg.enabled
    """

    worker_name: str
    _values: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def for_worker(
        cls,
        worker_name: str,
        overrides: dict[str, Any] | None = None,
    ) -> "ThresholdConfig":
        """
        Merge defaults with tenant overrides.

        Args:
            worker_name:  Exact class name of the worker (e.g. "HireToRetireWorker")
            overrides:    Dict of threshold overrides from the WorkerConfig DB row.
                          May be None or empty if no overrides exist for this tenant.

        Returns:
            ThresholdConfig with .get() method that resolves values in priority order:
            override → default → None
        """
        defaults = DEFAULTS.get(worker_name, {})
        merged = {**defaults, **(overrides or {})}
        return cls(worker_name=worker_name, _values=merged)

    def get(self, key: str, fallback: Any = None) -> Any:
        """Return the resolved threshold value, falling back to `fallback` if not found."""
        return self._values.get(key, fallback)

    @property
    def enabled(self) -> bool:
        """Return False if this worker has been disabled for this tenant."""
        return bool(self._values.get("enabled", True))

    def as_dict(self) -> dict[str, Any]:
        """Return the full merged config as a plain dict."""
        return dict(self._values)


def get_worker_names() -> list[str]:
    """Return all worker names that have registered defaults."""
    return sorted(DEFAULTS.keys())


def get_defaults(worker_name: str) -> dict[str, Any]:
    """Return the default threshold dict for a worker."""
    return dict(DEFAULTS.get(worker_name, {}))


def get_metadata(worker_name: str | None = None) -> dict:
    """
    Return threshold metadata for one or all workers.

    Used by the admin portal API to populate slider labels, ranges,
    and industry benchmark indicators in the UI.
    """
    if worker_name:
        return {
            "worker_name": worker_name,
            "defaults":    DEFAULTS.get(worker_name, {}),
            "metadata":    METADATA.get(worker_name, {}),
        }
    return {
        name: {
            "defaults":  DEFAULTS.get(name, {}),
            "metadata":  METADATA.get(name, {}),
        }
        for name in sorted(DEFAULTS.keys())
    }
