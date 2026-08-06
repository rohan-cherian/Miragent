"""
scout/actions/playbook.py — Playbook Engine (Sprint 24)

The playbook is the safety contract between Miragent's autonomous agents
and the client organisation. It answers one question for every action type:

  "Is the agent allowed to do this automatically, or does a human need
   to approve it first?"

Design philosophy:
  Conservative by default. Unknown action types always require approval.
  Clients explicitly unlock auto-execution for action types they trust,
  with conditions that bound the scope. This builds trust incrementally —
  agents earn autonomy as they prove accurate and well-scoped.

Maturity progression (mirrors the threshold maturity tiers):
  Tier 1 — No auto-execution. All actions require approval. Agents are
            purely advisory. Human clicks "Execute" for each one.
  Tier 2 — LOW risk actions auto-execute. MEDIUM still need approval.
            Agents handle the trivial, humans handle the sensitive.
  Tier 3 — MEDIUM risk actions auto-execute with conditions (ARR cap,
            account count limit). Agents handle most operational work.
  Tier 4 — HIGH risk actions auto-execute with strong conditions and
            rollback capability. Agents handle almost everything;
            humans set policy and review exceptions.

Platform defaults (what new tenants start with):
  Every action type defaults to HIGH risk / approval required. Admins
  use the playbook portal to lower risk tiers for actions they're
  comfortable with.

Condition evaluation:
  Conditions are stored as a JSON dict and evaluated against the
  execution context at runtime. Supported condition keys:

    max_arr_impact        — maximum ARR at risk the agent can auto-act on
    max_accounts_affected — maximum number of accounts the agent can touch
    max_users_affected    — maximum number of people the agent can affect
    business_hours_only   — only execute between 8am–6pm on weekdays
    requires_prior_evidence — only execute if EvidenceCheckLog shows PARTIAL first
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from scout.db.models import PlaybookRule

logger = logging.getLogger(__name__)


# ── Risk tiers ─────────────────────────────────────────────────────────────────

class RiskTier:
    LOW = "LOW"           # auto-execute, log for review
    MEDIUM = "MEDIUM"     # auto-execute if conditions met, else request approval
    HIGH = "HIGH"         # always request approval
    BLOCKED = "BLOCKED"   # never execute autonomously


# ── Platform defaults ──────────────────────────────────────────────────────────
# Conservative: every novel action type starts at HIGH (requires approval).
# Clients can lower risk tiers in their playbook to enable auto-execution.

PLATFORM_DEFAULTS: dict[str, dict] = {
    # ── SFDC actions ──────────────────────────────────────────────────────
    "reassign_accounts": {
        "risk_tier": RiskTier.HIGH,
        "auto_execute": False,
        "description": "Reassign Salesforce accounts from one owner to another. "
                        "Set to LOW/MEDIUM to allow auto-execution when a rep departs.",
    },
    "update_opportunity_stage": {
        "risk_tier": RiskTier.HIGH,
        "auto_execute": False,
        "description": "Advance or revert an opportunity stage in Salesforce.",
    },
    "log_activity": {
        "risk_tier": RiskTier.LOW,     # Low stakes — just logging
        "auto_execute": True,
        "description": "Log a call, task, or note against a Salesforce record. "
                        "Low risk — creates a record, does not change ownership or data.",
    },
    "create_contact": {
        "risk_tier": RiskTier.MEDIUM,
        "auto_execute": False,
        "description": "Create a new Contact record in Salesforce.",
    },
    "update_account_health": {
        "risk_tier": RiskTier.LOW,
        "auto_execute": True,
        "description": "Update the Health Score field on a Salesforce Account.",
    },

    # ── Workday actions ───────────────────────────────────────────────────
    "initiate_comp_review": {
        "risk_tier": RiskTier.HIGH,
        "auto_execute": False,
        "description": "Initiate a compensation review cycle for a worker. "
                        "High risk — directly impacts payroll.",
    },
    "update_position_status": {
        "risk_tier": RiskTier.MEDIUM,
        "auto_execute": False,
        "description": "Update a job position status (e.g., OPEN → IN_REVIEW).",
    },
    "send_onboarding_tasks": {
        "risk_tier": RiskTier.LOW,
        "auto_execute": True,
        "description": "Trigger onboarding task sequences for a new hire.",
    },
    "deprovision_access": {
        "risk_tier": RiskTier.MEDIUM,
        "auto_execute": False,
        "description": "Revoke system access for a departed employee. "
                        "Set to LOW for immediate auto-execution on termination detection.",
    },

    # ── NetSuite actions ──────────────────────────────────────────────────
    "approve_po": {
        "risk_tier": RiskTier.HIGH,
        "auto_execute": False,
        "description": "Approve a Purchase Order in NetSuite. "
                        "Set conditions (max_arr_impact) to enable auto-approval under a $ threshold.",
    },
    "create_renewal_order": {
        "risk_tier": RiskTier.HIGH,
        "auto_execute": False,
        "description": "Create a contract renewal order in NetSuite.",
    },
    "flag_vendor_invoice": {
        "risk_tier": RiskTier.LOW,
        "auto_execute": True,
        "description": "Add a flag/note to a vendor invoice for finance team review.",
    },
    "route_for_approval": {
        "risk_tier": RiskTier.MEDIUM,
        "auto_execute": False,
        "description": "Route a document through the NetSuite approval workflow.",
    },
}


# ── Playbook decision ──────────────────────────────────────────────────────────


@dataclass
class PlaybookDecision:
    """The result of evaluating the playbook for one action."""
    action_type: str
    risk_tier: str
    can_auto_execute: bool           # True = execute now, False = request approval
    blocking_reason: str = ""        # why auto-execution was blocked (for transparency)
    conditions_checked: dict = field(default_factory=dict)


def evaluate(
    db: Session,
    tenant_id: str,
    action_type: str,
    execution_context: dict,
) -> PlaybookDecision:
    """
    Evaluate the playbook for a given action type and execution context.

    Returns a PlaybookDecision indicating whether the agent can proceed
    autonomously or must pause for human approval.

    execution_context keys (all optional):
      arr_impact         — estimated ARR impact of this action
      accounts_affected  — number of Salesforce accounts being touched
      users_affected     — number of people being affected
      is_business_hours  — whether current time is within business hours
    """
    # Load tenant override (if any)
    rule = db.execute(
        select(PlaybookRule).where(
            PlaybookRule.tenant_id == tenant_id,
            PlaybookRule.action_type == action_type,
        )
    ).scalar_one_or_none()

    # Fall back to platform defaults
    platform = PLATFORM_DEFAULTS.get(action_type, {
        "risk_tier": RiskTier.HIGH,
        "auto_execute": False,
        "description": "Unknown action type — defaulting to HIGH risk.",
    })

    risk_tier = rule.risk_tier if rule else platform["risk_tier"]
    auto_execute = rule.auto_execute if rule else platform["auto_execute"]
    conditions = dict(rule.conditions or {}) if rule else {}

    # BLOCKED is absolute
    if risk_tier == RiskTier.BLOCKED:
        return PlaybookDecision(
            action_type=action_type,
            risk_tier=risk_tier,
            can_auto_execute=False,
            blocking_reason="This action type is blocked by the organisational playbook.",
        )

    # HIGH always requires approval
    if risk_tier == RiskTier.HIGH:
        return PlaybookDecision(
            action_type=action_type,
            risk_tier=risk_tier,
            can_auto_execute=False,
            blocking_reason="High-risk action — human approval required.",
        )

    if not auto_execute:
        return PlaybookDecision(
            action_type=action_type,
            risk_tier=risk_tier,
            can_auto_execute=False,
            blocking_reason="Auto-execution is disabled in the playbook for this action type.",
        )

    # Evaluate conditions
    failing_conditions = _check_conditions(conditions, execution_context)
    if failing_conditions:
        reason = "; ".join(failing_conditions)
        return PlaybookDecision(
            action_type=action_type,
            risk_tier=risk_tier,
            can_auto_execute=False,
            blocking_reason=f"Condition(s) not met: {reason}",
            conditions_checked=conditions,
        )

    return PlaybookDecision(
        action_type=action_type,
        risk_tier=risk_tier,
        can_auto_execute=True,
        conditions_checked=conditions,
    )


def _check_conditions(conditions: dict, context: dict) -> list[str]:
    """
    Evaluate all conditions. Returns a list of failure messages.
    Empty list = all conditions met.
    """
    failures = []

    if "max_arr_impact" in conditions:
        arr = context.get("arr_impact", 0) or 0
        cap = conditions["max_arr_impact"]
        if arr > cap:
            failures.append(
                f"ARR impact ${arr:,.0f} exceeds playbook limit ${cap:,.0f}"
            )

    if "max_accounts_affected" in conditions:
        n = context.get("accounts_affected", 0) or 0
        cap = conditions["max_accounts_affected"]
        if n > cap:
            failures.append(
                f"{n} accounts affected exceeds playbook limit {cap}"
            )

    if "max_users_affected" in conditions:
        n = context.get("users_affected", 0) or 0
        cap = conditions["max_users_affected"]
        if n > cap:
            failures.append(
                f"{n} users affected exceeds playbook limit {cap}"
            )

    if conditions.get("business_hours_only"):
        if not context.get("is_business_hours", True):
            failures.append("Action restricted to business hours (8am–6pm weekdays)")

    return failures


# ── Playbook management helpers ────────────────────────────────────────────────


def get_playbook(db: Session, tenant_id: str) -> list[dict]:
    """
    Return the full playbook for a tenant — merged platform defaults with overrides.

    Used by the admin portal to show the current policy and allow editing.
    """
    rows = db.execute(
        select(PlaybookRule).where(PlaybookRule.tenant_id == tenant_id)
    ).scalars().all()
    overrides = {r.action_type: r for r in rows}

    result = []
    for action_type, platform in PLATFORM_DEFAULTS.items():
        override = overrides.get(action_type)
        result.append({
            "action_type": action_type,
            "risk_tier": override.risk_tier if override else platform["risk_tier"],
            "auto_execute": override.auto_execute if override else platform["auto_execute"],
            "conditions": dict(override.conditions or {}) if override else {},
            "description": platform["description"],
            "is_overridden": override is not None,
            "updated_by": override.updated_by if override else None,
            "updated_at": override.updated_at.isoformat() if override else None,
        })

    return result


def upsert_rule(
    db: Session,
    tenant_id: str,
    action_type: str,
    risk_tier: str,
    auto_execute: bool,
    conditions: dict,
    updated_by: str,
) -> PlaybookRule:
    """Create or update a playbook rule for one action type."""
    rule = db.execute(
        select(PlaybookRule).where(
            PlaybookRule.tenant_id == tenant_id,
            PlaybookRule.action_type == action_type,
        )
    ).scalar_one_or_none()

    if rule is None:
        rule = PlaybookRule(tenant_id=tenant_id, action_type=action_type)
        db.add(rule)

    rule.risk_tier = risk_tier
    rule.auto_execute = auto_execute
    rule.conditions = conditions
    rule.updated_by = updated_by
    db.commit()
    db.refresh(rule)
    return rule
