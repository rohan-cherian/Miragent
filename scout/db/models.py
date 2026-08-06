"""SQLAlchemy ORM models for multi-tenant user and API key management."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from scout.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[list["User"]] = relationship("User", back_populates="tenant")
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="tenant")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, default="viewer")  # "admin" or "viewer"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    mfa_secret: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", back_populates="created_by_user", foreign_keys="ApiKey.created_by"
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    key_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)  # first 8 chars for display
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="api_keys")
    created_by_user: Mapped["User"] = relationship(
        "User", back_populates="api_keys", foreign_keys=[created_by]
    )


class WorkerConfig(Base):
    """
    Per-tenant threshold overrides for AI workers.

    Stores client-specific threshold values that override the platform defaults
    defined in scout/workers/threshold_registry.py.

    One row per (tenant_id, worker_name) pair. The `thresholds` JSON column
    contains only the values that differ from defaults — absent keys inherit
    the platform default at runtime via ThresholdConfig.for_worker().
    """

    __tablename__ = "worker_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "worker_name", name="uq_worker_config"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)  # email of admin


class FindingDisposition(Base):
    """
    Records how an executive responded to a surfaced finding.

    Drives the signal/noise feedback loop in Sprint 22: dismiss patterns
    trigger AI-generated threshold adjustment proposals, and completion
    patterns feed the organizational capacity model.

    disposition values:
      ACTED     — executive clicked "this is a priority" or created an action
      DISMISSED — executive dismissed as not relevant for this org
      DEFERRED  — acknowledged but not actioning now
      SNOOZED   — hide for N days, then resurface
    """

    __tablename__ = "finding_dispositions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    finding_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    disposition: Mapped[str] = mapped_column(String, nullable=False)  # ACTED|DISMISSED|DEFERRED|SNOOZED
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disposed_by: Mapped[str] = mapped_column(String, nullable=False)  # user email
    disposed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RemediationAction(Base):
    """
    A specific, assigned, trackable action tied to a worker finding.

    Completion is verified organically by reading source system logs
    (SFDC, Workday, NetSuite) rather than requiring manual status updates.
    See scout/actions/evidence_checkers.py for the verification logic.

    status values:
      OPEN        — assigned, not yet started
      IN_PROGRESS — partial evidence of completion detected in source systems
      COMPLETE    — strong evidence detected (auto) or manually confirmed
      DEFERRED    — acknowledged but intentionally deprioritized
      CANCELLED   — no longer relevant (finding resolved by other means)

    completion_method values:
      AUTO   — completed automatically based on source system evidence
      MANUAL — manually marked complete by the assignee or admin
    """

    __tablename__ = "remediation_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    finding_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)   # reassign_accounts | schedule_meeting | etc.
    assigned_to_email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String, nullable=True)
    effort: Mapped[str] = mapped_column(String, default="MEDIUM")       # LOW | MEDIUM | HIGH
    timeframe: Mapped[str] = mapped_column(String, default="SHORT")     # IMMEDIATE | SHORT | MEDIUM | LONG
    arr_impact: Mapped[float | None] = mapped_column(nullable=True)     # ARR at risk reduced by this action
    status: Mapped[str] = mapped_column(String, default="OPEN")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Evidence configuration — what source system to check for organic completion
    evidence_source: Mapped[str | None] = mapped_column(String, nullable=True)    # sfdc | workday | netsuite
    evidence_query_type: Mapped[str | None] = mapped_column(String, nullable=True) # account_owner_changed | meeting_logged | etc.
    evidence_target_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)  # IDs to check (account IDs, person IDs)
    # Completion tracking
    completion_method: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    # Sprint 26: worker-generated execution payload (exact params for the executor)
    execution_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)


# ── Sprint 22: Signal / Noise Engine ──────────────────────────────────────────

class NoiseProfile(Base):
    """
    Tracks dismiss/act rates per worker per tenant over a rolling window.

    Updated by the noise scanner background job whenever a FindingDisposition
    is recorded. When dismissed_rate exceeds the noise_threshold, a
    ThresholdProposal is automatically generated.

    The 30-day window means the profile reflects *current* behaviour, not
    historical accidents. A worker that had a noisy month last year won't
    permanently suppress future findings.
    """

    __tablename__ = "noise_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", "worker_name", name="uq_noise_profile"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)

    # Rolling 30-day counts
    window_days: Mapped[int] = mapped_column(default=30)
    total_surfaced: Mapped[int] = mapped_column(default=0)    # findings shown in window
    total_acted: Mapped[int] = mapped_column(default=0)       # ACTED dispositions
    total_dismissed: Mapped[int] = mapped_column(default=0)   # DISMISSED dispositions
    total_snoozed: Mapped[int] = mapped_column(default=0)     # SNOOZED dispositions

    # Derived rates (recomputed by scanner, stored for fast reads)
    acted_rate: Mapped[float] = mapped_column(default=0.0)      # acted / total_surfaced
    dismissed_rate: Mapped[float] = mapped_column(default=0.0)  # dismissed / total_surfaced
    signal_score: Mapped[float] = mapped_column(default=1.0)    # 0.0 = pure noise, 1.0 = pure signal

    # Capacity / WIP gate
    # Max open actions surfaced simultaneously for this worker. Starts at
    # platform default (5), adapts down if dismissed_rate is high.
    active_action_cap: Mapped[int] = mapped_column(default=5)

    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ThresholdProposal(Base):
    """
    AI-generated suggestion to change a worker threshold based on dismiss patterns.

    Lifecycle: PENDING → ACCEPTED (admin applies it) | REJECTED (admin dismisses it).

    When accepted, the orchestrator applies the proposed_value to the
    WorkerConfig overrides table — the same mechanism used by the admin portal.
    This means proposals and human overrides are unified; there's no separate
    'AI-set' vs 'human-set' distinction in the threshold store.

    rationale is shown to the admin so they can make an informed decision.
    It's generated by the noise scanner and references dismiss counts and rates.
    """

    __tablename__ = "threshold_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    worker_name: Mapped[str] = mapped_column(String, nullable=False)
    threshold_key: Mapped[str] = mapped_column(String, nullable=False)   # e.g. "inactive_rate_high"
    current_value: Mapped[float] = mapped_column(nullable=False)
    proposed_value: Mapped[float] = mapped_column(nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)        # "raise" | "lower"
    rationale: Mapped[str] = mapped_column(String, nullable=False)        # human-readable explanation
    confidence: Mapped[float] = mapped_column(default=0.5)               # 0–1, based on sample size
    status: Mapped[str] = mapped_column(String, default="PENDING")        # PENDING | ACCEPTED | REJECTED
    dismissed_count: Mapped[int] = mapped_column(default=0)              # dispositions that drove this
    dismissed_rate: Mapped[float] = mapped_column(default=0.0)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Sprint 23: Organic Action Tracking ────────────────────────────────────────

class EvidenceCheckLog(Base):
    """
    Audit log of every organic evidence check run against a source system.

    Stored so the admin portal can show "last checked 2 hours ago — no
    evidence yet" rather than leaving the status opaque. Also used to
    detect stalled checks (source system API unreachable, credentials
    rotated, etc.) and alert the admin.

    result values:
      FOUND        — strong evidence of completion found; action was auto-completed
      PARTIAL      — some evidence but not definitive (e.g., meeting scheduled, not held)
      NOT_YET      — no evidence yet, will check again
      ERROR        — connector raised an exception; check the error_detail
      SKIPPED      — action already complete or cancelled; check skipped
    """

    __tablename__ = "evidence_check_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    action_id: Mapped[str] = mapped_column(
        String, ForeignKey("remediation_actions.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    evidence_source: Mapped[str] = mapped_column(String, nullable=False)    # sfdc | workday | netsuite
    evidence_query_type: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str] = mapped_column(String, nullable=False)             # FOUND|PARTIAL|NOT_YET|ERROR|SKIPPED
    detail: Mapped[str | None] = mapped_column(String, nullable=True)       # human-readable result summary
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True) # exception message if ERROR
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    action: Mapped["RemediationAction"] = relationship("RemediationAction")


class ActionReminder(Base):
    """
    Scheduled reminders for open remediation actions.

    The reminder engine (Sprint 23 background job) creates these when an
    action is assigned and due_date is approaching. The delivery_method
    determines whether the reminder goes via email, Slack, or in-app
    notification. sent_at is populated once the reminder fires.

    status values:
      PENDING  — scheduled, not yet sent
      SENT     — delivered successfully
      FAILED   — delivery failed (check error_detail)
      SKIPPED  — action was completed before reminder fired
    """

    __tablename__ = "action_reminders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    action_id: Mapped[str] = mapped_column(
        String, ForeignKey("remediation_actions.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    assigned_to_email: Mapped[str] = mapped_column(String, nullable=False)
    delivery_method: Mapped[str] = mapped_column(String, default="email")   # email | slack | in_app
    send_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    action: Mapped["RemediationAction"] = relationship("RemediationAction")


# ── Sprint 24: Playbook Engine + Approval Gate ────────────────────────────────

class PlaybookRule(Base):
    """
    A single rule in a tenant's operational playbook.

    Defines what an autonomous agent is allowed to do — and under what
    conditions it must pause and ask a human before acting.

    The risk_tier drives the approval gate:
      LOW    — agent executes immediately, no human needed
      MEDIUM — agent executes unless override flag is set, logs for review
      HIGH   — agent always pauses and creates an ApprovalRequest
      BLOCKED— agent never executes this action type (admin must do it manually)

    Conditions are stored as a JSON dict and evaluated at runtime:
      {"max_arr_impact": 50000}       — only auto-execute if ARR at risk < $50k
      {"max_accounts_affected": 10}   — only auto-execute if < 10 accounts touched
      {"requires_business_hours": true} — only execute Mon–Fri 8am–6pm tenant TZ

    One row per (tenant_id, action_type). A missing row means the platform
    default applies: HIGH risk_tier (always requires approval) for unknown
    action types — conservative by default.
    """

    __tablename__ = "playbook_rules"
    __table_args__ = (UniqueConstraint("tenant_id", "action_type", name="uq_playbook_rule"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)    # reassign_accounts | approve_po | etc.
    risk_tier: Mapped[str] = mapped_column(String, default="HIGH")      # LOW | MEDIUM | HIGH | BLOCKED
    auto_execute: Mapped[bool] = mapped_column(Boolean, default=False)  # True = no human needed
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)         # runtime guard conditions
    description: Mapped[str] = mapped_column(String, default="")
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ApprovalRequest(Base):
    """
    A pending human approval for a high-risk autonomous action.

    Created by the execution engine when a PlaybookRule has risk_tier=HIGH
    or when execution conditions are not met for auto-execution.

    The proposed_payload is the exact action the agent wants to take —
    shown to the approver in the admin portal. On approval, the engine
    executes the payload directly. On rejection, the RemediationAction
    status is set to DEFERRED.

    status values:
      PENDING  — waiting for human review
      APPROVED — human approved; engine will execute on next cycle
      REJECTED — human rejected; action set to DEFERRED
      EXPIRED  — no response within expires_at; auto-escalated or cancelled
      EXECUTED — approved and successfully executed by agent
    """

    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(
        String, ForeignKey("remediation_actions.id"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String, nullable=False)
    proposed_payload: Mapped[dict] = mapped_column(JSON, default=dict)  # exact operation params
    rationale: Mapped[str] = mapped_column(String, nullable=False)       # why agent wants to do this
    status: Mapped[str] = mapped_column(String, default="PENDING")
    requested_by: Mapped[str] = mapped_column(String, default="system")  # "system" for agent
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    action: Mapped["RemediationAction"] = relationship("RemediationAction")


class ExecutionLog(Base):
    """
    Immutable audit record of every autonomous action taken by an agent.

    This is the compliance layer — a full record of what the system did,
    why it did it, who approved it (or that it was auto-approved under
    a LOW risk playbook rule), and what the source system returned.

    result values:
      SUCCESS  — source system accepted the change
      FAILURE  — source system rejected or returned an error
      PARTIAL  — some targets succeeded, some failed
      ROLLED_BACK — agent detected an error and reversed the change

    Never deleted. Append-only. Used for compliance audits, debugging,
    and feeding the signal/noise engine with execution outcomes.
    """

    __tablename__ = "execution_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(
        String, ForeignKey("remediation_actions.id"), nullable=False, index=True
    )
    approval_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    source_system: Mapped[str] = mapped_column(String, nullable=False)  # sfdc | workday | netsuite
    target_ids: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)           # what was sent to source system
    result: Mapped[str] = mapped_column(String, nullable=False)         # SUCCESS|FAILURE|PARTIAL|ROLLED_BACK
    result_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    source_system_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    executed_by: Mapped[str] = mapped_column(String, default="system")  # "system" or approver email
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    action: Mapped["RemediationAction"] = relationship("RemediationAction")


# ── Sprint 26: Worker-Generated Action Payloads ───────────────────────────────
# (payload column added to RemediationAction via migration — see below)
# RemediationAction already exists; we add the payload column via alembic in prod.
# For SQLite dev/test, drop_all + create_all picks it up automatically.


# ── Sprint 27: Webhook Event Queue ───────────────────────────────────────────


# ── Sprint 58: SSO / OIDC ────────────────────────────────────────────────────

class SSOProvider(Base):
    """
    OIDC/SAML SSO provider configuration per tenant.

    Each row describes one identity provider (Okta, Azure AD, Google Workspace,
    etc.) configured for a tenant. When a user signs in via SSO, the backend
    looks up the provider by email domain and redirects to the correct IdP.

    Supports OIDC Authorization Code Flow with PKCE (RFC 7636).
    SAML support is planned for a future sprint.

    provider_type values:
      oidc        — Generic OIDC (Okta, Ping, Auth0, etc.)
      azure_ad    — Microsoft Azure AD / Entra ID (OIDC variant)
      google      — Google Workspace (OIDC)

    Security note:
      client_secret is stored as-is in SQLite for development.
      In production, set SCOUT_SSO_ENCRYPTION_KEY and the app will
      AES-GCM encrypt it before write and decrypt on read.
    """

    __tablename__ = "sso_providers"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_slug", name="uq_sso_provider"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    provider_slug: Mapped[str] = mapped_column(String, nullable=False)   # e.g. "okta", "azure", "google"
    display_name: Mapped[str] = mapped_column(String, nullable=False)    # shown to users on login page
    provider_type: Mapped[str] = mapped_column(String, default="oidc")   # oidc | azure_ad | google

    # OIDC discovery — all other endpoints derived from this
    issuer_url: Mapped[str] = mapped_column(String, nullable=False)      # e.g. https://acme.okta.com/oauth2/default

    # OAuth2 client credentials
    client_id: Mapped[str] = mapped_column(String, nullable=False)
    client_secret: Mapped[str] = mapped_column(String, nullable=False)   # encrypted in prod

    # Domain hints — which email domains route to this provider
    # e.g. ["acmecorp.com", "acme.io"]
    domains: Mapped[list] = mapped_column(JSON, default=list)

    # JIT provisioning — auto-create user on first SSO login
    jit_provisioning: Mapped[bool] = mapped_column(Boolean, default=True)
    # Default role for JIT-provisioned users
    default_role: Mapped[str] = mapped_column(String, default="viewer")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant: Mapped["Tenant"] = relationship("Tenant")


# ── Sprint 60: DDQ Agent — Knowledge Base + Job Models ───────────────────────


class KBDocument(Base):
    """
    A document ingested into the tenant's DDQ knowledge base.

    Documents are chunked and stored as KBChunk rows.
    content_hash enables dedup — uploading the same file twice is a no-op.

    doc_type values: soc2 | security_policy | privacy_policy | bcp |
                     data_retention | msa | pen_test | previous_ddq | general
    """

    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[str] = mapped_column(String, nullable=False, default="general")
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    chunks: Mapped[list["KBChunk"]] = relationship(
        "KBChunk", back_populates="document", cascade="all, delete-orphan"
    )


class KBChunk(Base):
    """
    A single chunked segment of a KB document.

    Chunks overlap by CHUNK_OVERLAP words so that answers that span
    chunk boundaries are still retrievable.
    """

    __tablename__ = "kb_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("kb_documents.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped["KBDocument"] = relationship("KBDocument", back_populates="chunks")


class DDQJob(Base):
    """
    A single DDQ analysis job.

    Created when a user submits questions for analysis.
    Stores both the input (questions_text) and the output (result_json).

    status values: pending | running | done | failed
    """

    __tablename__ = "ddq_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    input_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unanswerable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


# ── Sprint 61: Payroll Document Agent ────────────────────────────────────────


class PayrollRequest(Base):
    """
    A single payroll document request made by an employee.

    Employees self-serve — they can only retrieve their own documents.
    The agent looks up the employee in the payroll connector (or mock roster),
    generates the requested document, and stores the full result here.

    document_type values: w2 | paystub | 1099 | ytd
    status values: pending | delivered | not_found | error
    """

    __tablename__ = "payroll_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String, nullable=False, index=True)  # employee email
    document_type: Mapped[str] = mapped_column(String, nullable=False)              # w2 | paystub | 1099 | ytd
    period: Mapped[str] = mapped_column(String, nullable=False)                     # "2025" or "2026-05-01"
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending | delivered | not_found | error
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)        # full document payload
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ── Sprint 63: Portal Access Agent ───────────────────────────────────────────


class PortalAccessRequest(Base):
    """
    A single portal access diagnosis request.

    Submitted by a support agent (or customer self-service) when a customer
    cannot log in to the portal. The agent diagnoses the root cause from IdP
    data and either resolves it autonomously or generates a precise fix instruction.

    diagnosis_code values:
      account_locked   — locked after failed attempts → auto-unlock
      not_provisioned  — user exists in IdP but not in portal group → add to group
      sso_mismatch     — SSO domain not matching customer email domain → config fix
      mfa_reset        — MFA device lost/changed → reset enrollment
      domain_mismatch  — email domain not in allowed list → escalate
      suspended        — account manually suspended → escalate, never auto-resolve
      not_found        — no IdP account found → escalate
      unknown          — could not determine → escalate with diagnostic data

    status values: analyzing | resolved | escalated | pending_action
    """

    __tablename__ = "portal_access_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    submitted_by: Mapped[str] = mapped_column(String, nullable=False)          # email of support agent / customer
    customer_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reported_issue: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="analyzing")
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ── Sprint 62: Mission Control ────────────────────────────────────────────────


class ProcessBlueprint(Base):
    """
    A discovered process that is a candidate for AI agent automation.

    Blueprints are seeded by the Scout scan and represent recurring
    operational workflows identified from ticket/activity data. The operator
    reviews each blueprint and decides whether to deploy an agent.

    status values: discovered → reviewed → configured → active
    """

    __tablename__ = "process_blueprints"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    process_name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # customer_support / vendor / hr / sales / finance
    volume_per_week: Mapped[float] = mapped_column(nullable=False, default=0.0)
    median_resolution_hours: Mapped[float] = mapped_column(nullable=False, default=0.0)
    automation_potential: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0-100 score
    recommended_agent: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    systems_involved: Mapped[list] = mapped_column(JSON, default=list)
    resolution_patterns: Mapped[dict] = mapped_column(JSON, default=dict)  # {pattern: pct}
    status: Mapped[str] = mapped_column(String, nullable=False, default="discovered")  # discovered/reviewed/configured/active
    sop_coverage: Mapped[bool] = mapped_column(Boolean, default=False)
    conformance_gap: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class AgentDeployment(Base):
    """
    An active or pending agent deployment for a tenant.

    Each row represents one deployed agent instance with its runtime
    metrics, configuration, and link back to the process blueprint it
    was configured from.

    status values: configuring → active | paused
    """

    __tablename__ = "agent_deployments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="configuring")  # active/paused/configuring
    blueprint_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    requests_handled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requests_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolution_rate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    deployed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)


# ── Sprint 64: Support Triage Agent ──────────────────────────────────────────


class SupportTicket(Base):
    """
    A single support ticket triaged by the SupportTriageAgent.

    The agent classifies the ticket, pulls CRM account context, assigns a
    priority score, routes to the correct team queue, and drafts a first
    response. Escalation-worthy tickets are flagged with an escalation_reason.

    category values:
      portal_access | billing_dispute | technical_bug | feature_request |
      account_mgmt  | security_concern | data_question | general_inquiry

    priority_label values: P1-Critical | P2-High | P3-Medium | P4-Low

    assigned_queue values:
      engineering | billing | customer-success | security | product | general

    status values: triaged | escalated | draft_ready | error
    """

    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    submitted_by: Mapped[str] = mapped_column(String, nullable=False)           # email of support agent
    customer_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    priority_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-100
    priority_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # P1-Critical / P2-High / …
    assigned_queue: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # engineering / billing / …
    drafted_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)   # CRM account snapshot
    escalation_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="triaged")  # triaged | escalated | draft_ready | error
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class WebhookEvent(Base):
    """
    Incoming webhook event from a source system, stored before processing.

    The event queue decouples ingestion from processing: webhooks return
    HTTP 200 immediately (so the source system doesn't timeout), then
    the processor handles the event asynchronously.

    source values:     sfdc | workday | netsuite | hubspot | generic
    event_type values: contact.terminated | opportunity.updated |
                       po.created | hire.completed | etc.

    status values:
      PENDING    — received, not yet processed
      PROCESSING — currently being handled (prevents double-processing)
      DONE       — processed successfully
      FAILED     — processing error; see error_detail
      IGNORED    — event type not mapped to any action (logged but skipped)
    """

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, index=True
    )  # prevents duplicate processing of retried webhooks
    status: Mapped[str] = mapped_column(String, default="PENDING", index=True)
    actions_triggered: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ── Sprint 65: Payment Status Agent ───────────────────────────────────────────


class VendorInquiry(Base):
    """
    Audit record of every vendor payment status inquiry processed by the
    PaymentStatusAgent.

    Stores the original lookup parameters, the full structured result, and
    the draft vendor response. Used for:
      - Audit trail (who looked up what, when)
      - Analytics (inquiry volume by vendor, most-queried invoices)
      - Response quality review (compare draft to final sent response)
    """

    __tablename__ = "vendor_inquiries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    invoice_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    vendor_email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    inquiry_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


# ── Sprint 66: Benefits Agent ──────────────────────────────────────────────────


class BenefitsInquiry(Base):
    """
    Audit record of every employee benefits inquiry processed by the
    BenefitsAgent.

    Stores the original question, the classified category, and the full
    structured result. Used for:
      - Audit trail (who asked what, when)
      - Analytics (most common benefits questions by category)
      - HR insight (identify employees with action items like uncaptured 401k match)
    """

    __tablename__ = "benefits_inquiries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    employee_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_category: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


# ── Sprint 67: Vendor Onboarding Agent ────────────────────────────────────────


class VendorOnboardingCase(Base):
    """
    Audit record of each vendor onboarding case managed by the
    VendorOnboardingAgent.

    Tracks vendor contact info, onboarding stage, entity type, and freeform
    notes. Used for:
      - Audit trail of stage transitions and procurement actions
      - Dashboard queries (in-progress, blocked/stalled)
      - ERP pre-population once banking info is collected

    stage values (in order):
      initiated | w9_requested | w9_received | banking_requested |
      banking_received | erp_setup | active | on_hold
    """

    __tablename__ = "vendor_onboarding_cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    vendor_name: Mapped[str] = mapped_column(String, nullable=False)
    vendor_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False, default="initiated")
    entity_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


# ── Sprint 68: IT Access Agent ────────────────────────────────────────────────


class ITAccessRequest(Base):
    """
    Audit record of each IT access provisioning request managed by the
    ITAccessAgent.

    Tracks requester, target user, requested system, approval tier, and
    current provisioning status.

    status values:
      pending_manager | pending_it | pending_ciso | provisioned | rejected | in_progress
    """

    __tablename__ = "it_access_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requester_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_user_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    system_key: Mapped[str] = mapped_column(String, nullable=False)
    approval_tier: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending_manager")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


# ── Sprint 69: Compliance Response Agent ──────────────────────────────────────


class ComplianceJob(Base):
    """
    Audit record of each customer security questionnaire processed by the
    ComplianceResponseAgent.

    Stores the customer name, detected questionnaire type, question count,
    and the full structured result (answers + confidence scores).
    """

    __tablename__ = "compliance_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    questionnaire_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Sprint 70: Board Report Job ────────────────────────────────────────────────


class BoardReportJob(Base):
    """
    Persists generated board report packages for a tenant.

    Each row represents one on-demand board report generation. The full
    structured report (all sections, metrics, narratives) is stored in
    report_data as JSON for retrieval without regenerating.
    """

    __tablename__ = "board_report_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    period: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    report_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Sprint 72: Design Session Mode ────────────────────────────────────────────


class DesignSession(Base):
    """
    Tracks a guided 5-step operator onboarding session.

    Created when an operator first sets up Miragent. The wizard walks them
    through reviewing Scout findings, approving discovered blueprints, and
    configuring agent thresholds before going live.

    current_step values: connect | discover | review | configure | golive
    """

    __tablename__ = "design_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    current_step: Mapped[str] = mapped_column(String, default="connect")
    session_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # full MOCK_SESSION + approval decisions
    approved_blueprints: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    skipped_blueprints: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    configurations: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Sprint 71: DDQ Template Job ────────────────────────────────────────────────


class DDQTemplateJob(Base):
    """
    Persists DDQ template fill jobs for a tenant.

    Each row represents one on-demand template-fill run. The parsed
    questions and drafted answers are stored in result as JSON for
    retrieval without reprocessing.
    """

    __tablename__ = "ddq_template_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Sprint 73: Communication Analysis ─────────────────────────────────────────


class CommIngestJob(Base):
    """
    Audit record of a customer communication ingestion + analysis run.

    Each row represents one analysis pass over the customer-facing communication
    sources (support email queue, shared Slack channels, Zendesk/Freshservice).

    Scope (GDPR-safe): customer-to-company communications only.
    Internal DMs and employee-only channels are explicitly excluded.

    source values: email | slack | zendesk | all
    """

    __tablename__ = "comm_ingest_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)   # email / slack / zendesk / all
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Portfolio Intelligence ────────────────────────────────────────────────────


class InsightSnapshot(Base):
    """
    Persisted summary of one GET /insights run for a tenant.

    Written at the end of every successful /insights call so the portfolio
    view can retrieve the most recent intelligence for each company without
    re-running all 34 workers. One row per tenant per run; the portfolio
    view always reads the most recent row per tenant_id.

    This is the bridge between per-company analysis (GET /insights) and
    the fund-level dashboard (GET /portfolio/summary).

    Fields:
      critical / high / medium / low: finding counts from the run
      worker_summaries: {worker_name: summary_stats} for all workers
      top_findings: top 10 CRITICAL+HIGH findings (title + severity + worker)
      company_profile: segment, model, confidence, key metrics
      narrative_snippet: first 500 chars of the AI memo
      llm_provider / llm_model: which LLM generated the narrative
    """

    __tablename__ = "insight_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Finding counts
    critical: Mapped[int] = mapped_column(Integer, default=0)
    high: Mapped[int] = mapped_column(Integer, default=0)
    medium: Mapped[int] = mapped_column(Integer, default=0)
    low: Mapped[int] = mapped_column(Integer, default=0)
    total_findings: Mapped[int] = mapped_column(Integer, default=0)
    workers_run: Mapped[int] = mapped_column(Integer, default=0)

    # Structured intelligence
    worker_summaries: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    top_findings: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    company_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Narrative
    narrative_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class InsightSchedule(Base):
    """
    Configures automatic periodic /insights runs per tenant.

    Sprint 78 — Insight Scheduling.
    Once a schedule is set, the background scheduler wakes up every minute,
    checks which tenants are due, and fires their /insights run.

    cadence options: "daily", "weekly", "manual"
    hour_utc: which UTC hour to run (0-23). Only used for daily/weekly.
    day_of_week: 0=Monday … 6=Sunday. Only used for weekly.
    """
    __tablename__ = "insight_schedules"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    cadence: Mapped[str] = mapped_column(String, nullable=False, default="daily")
    hour_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    day_of_week: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ── Sprint 80: Multi-tenant access ────────────────────────────────────────────


class UserTenantAccess(Base):
    """
    Sprint 80 — Multi-tenant access.
    Grants a user read access to additional tenants beyond their home tenant.
    One row per (user_id, tenant_id) pair. The user's home tenant_id (from
    the User model) always grants access implicitly — this table covers extras.
    """
    __tablename__ = "user_tenant_access"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    granted_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)


# ── Sprint 81: Email digest recipients ────────────────────────────────────────


class DigestRecipient(Base):
    """
    Sprint 81 — Email digest.
    Stores email addresses that should receive the Monday morning
    portfolio health summary. One row per email address.
    Recipients can be scoped to specific tenants (tenant_id not null)
    or receive the full portfolio digest (tenant_id null).
    """
    __tablename__ = "digest_recipients"
    __table_args__ = (UniqueConstraint("email", "tenant_id", name="uq_digest_recipient"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    added_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ── Sprint 83: Connector credential storage ────────────────────────────────────

class ConnectorCredentialStore(Base):
    """
    Sprint 83 — Stores OAuth2 credentials for production connectors, per tenant.
    One row per (tenant_id, connector_id) pair.
    The auth_data JSON holds whatever the connector needs: access_token,
    refresh_token, instance_url, expires_at, etc.
    In production, auth_data should be encrypted at rest (AES-256 or KMS).
    """
    __tablename__ = "connector_credential_store"
    __table_args__ = (UniqueConstraint("tenant_id", "connector_id", name="uq_connector_cred"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String, nullable=False, index=True)  # "salesforce"
    auth_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)    # tokens etc
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    connected_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
