"""
Task 4 — canonical layer provenance mixin.

Provenance carries the "where did this row come from" columns every
canonical table needs: which tenant, which source system and connector
run produced it, and when it was observed / became valid. Future
canonical models mix this in instead of repeating these columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, false
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class Provenance:
    """Declarative mixin — where a canonical row came from and when."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    source_system: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    connector_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─────────────────────────────────────────────────────────
# Task 10 — canonical itr360 tables.
#
# Everything below builds on Provenance above. case_event and
# decision_audit are pure append-only event logs and do not carry
# Provenance. problem_taxonomy is a static reference table (the
# classifier's fixed label space, not connector-ingested data) and
# also does not carry Provenance — matching schema/006_canonical_
# itr360_tables.sql exactly.
# ─────────────────────────────────────────────────────────

import enum

from sqlalchemy import ARRAY, ForeignKey, Index, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all itr360 canonical models."""


# TODO: verify against ITR_UI/src/contracts/state.js once that repo is
# available — ITR_UI is not present in this workspace, so these values
# are used as given in the Task 10 spec.
class CaseStatus(str, enum.Enum):
    NEW = "new"
    OPEN = "open"
    PENDING = "pending"
    HOLD = "hold"
    SOLVED = "solved"
    CLOSED = "closed"


# TODO: verify against ITR_UI/src/contracts/state.js once that repo is
# available — ITR_UI is not present in this workspace, so these values
# are used as given in the Task 10 spec.
class DecisionState(str, enum.Enum):
    DRAFT_PENDING = "draft_pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    EDITED_APPROVED = "edited_approved"
    REJECTED = "rejected"
    REDRAFTED = "redrafted"
    SUPERSEDED = "superseded"


# TODO: verify against ITR_UI/src/contracts/state.js once that repo is
# available — ITR_UI is not present in this workspace, so these values
# are used as given in the Task 10 spec.
class WriteState(str, enum.Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    EXECUTING = "executing"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# TODO: verify against ITR_UI/src/contracts/state.js once that repo is
# available — ITR_UI is not present in this workspace, so these values
# are used as given in the Task 10 spec.
class TriageBand(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NEEDS_HUMAN_TRIAGE = "needs_human_triage"


class Org(Provenance, Base):
    __tablename__ = "org"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)


class Person(Provenance, Base):
    __tablename__ = "person"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.org.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    primary_email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    job_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)


class Case(Provenance, Base):
    """Table name is ``case_`` — trailing underscore avoids the SQL reserved word."""

    __tablename__ = "case_"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_number"),
        {"schema": "itr360"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_number: Mapped[str] = mapped_column(Text, nullable=False)  # ITR-{year}-{seq:05d}
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.org.id"), nullable=True
    )
    requester_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.person.id"), nullable=True
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CaseStatus] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    related_case_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )

    messages: Mapped[list["Message"]] = relationship(back_populates="case")
    triage_results: Mapped[list["TriageResult"]] = relationship(back_populates="case")


class Message(Provenance, Base):
    __tablename__ = "message"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.case_.id"), nullable=False
    )
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.person.id"), nullable=True
    )
    direction: Mapped[str] = mapped_column(Text, nullable=False)  # inbound | outbound
    channel: Mapped[str] = mapped_column(Text, nullable=False, default="email")
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    pii_map: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pii_status: Mapped[str] = mapped_column(Text, nullable=False)
    src_message_id: Mapped[str] = mapped_column(Text, nullable=False)  # Gmail message ids are hex strings, not UUIDs
    thread_id: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)  # Task 15: case correlation lookup key
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    case: Mapped["Case"] = relationship(back_populates="messages")


class CaseEvent(Base):
    """Append-only event log — no Provenance."""

    __tablename__ = "case_event"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProblemTaxonomy(Base):
    """The classifier's label space — static reference data, no Provenance."""

    __tablename__ = "problem_taxonomy"
    __table_args__ = (
        UniqueConstraint("category", "problem_class"),
        {"schema": "itr360"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)  # 10 of these
    problem_class: Mapped[str] = mapped_column(Text, nullable=False)  # 100 of these
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    example_phrases: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    default_priority: Mapped[str | None] = mapped_column(Text, nullable=True)


class TriageResult(Provenance, Base):
    """MVP Phase 1 headline output."""

    __tablename__ = "triage_result"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.case_.id"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str | None] = mapped_column(Text, nullable=True)  # deterministic, not the LLM
    urgency_signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    band: Mapped[TriageBand] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)  # must quote the email
    evidence_spans: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # [{start,end,text}]
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    tier_used: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    case: Mapped["Case"] = relationship(back_populates="triage_results")


class ProposedAction(Provenance, Base):
    __tablename__ = "proposed_action"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.case_.id"), nullable=False
    )
    triage_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.triage_result.id"), nullable=True
    )
    resolution_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action_text: Mapped[str] = mapped_column(Text, nullable=False)
    draft_sentences: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)  # [Citation DTO]
    policy_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)


class RecommendationDecision(Provenance, Base):
    """
    Recording an approval is NOT the same event as a write succeeding —
    see write_execution below. Two separate tables, deliberately.
    """

    __tablename__ = "recommendation_decision"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key"),
        {"schema": "itr360"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    proposed_action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state: Mapped[DecisionState] = mapped_column(Text, nullable=False)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version_token: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    write_executions: Mapped[list["WriteExecution"]] = relationship(back_populates="decision")


class WriteExecution(Provenance, Base):
    __tablename__ = "write_execution"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.recommendation_decision.id"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)  # GMAIL_SEND_REPLY
    state: Mapped[WriteState] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # returned gmail message id
    suppressed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 'ACTION_MODE=draft_only'
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decision: Mapped["RecommendationDecision"] = relationship(back_populates="write_executions")


class IdentityUnresolvedQueue(Provenance, Base):
    __tablename__ = "identity_unresolved_queue"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    src_message_id: Mapped[str] = mapped_column(Text, nullable=False)  # Gmail message ids are hex strings, not UUIDs
    sender_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    sender_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_guess_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.person.id"), nullable=True
    )
    best_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")  # pending|resolved|dismissed
    resolved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismiss_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionAudit(Base):
    """
    Append only — see scout/governance/audit.py, the only code allowed
    to write here. No Provenance (has its own tenant_id). Column set
    matches audit.py's Core Table exactly: id, tenant_id, case_id,
    actor, action, category, inputs, outputs, confidence, trace_id,
    created_at.
    """

    __tablename__ = "decision_audit"
    __table_args__ = {"schema": "itr360"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)  # scan|identity|redaction|approval|system
    inputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index(
    "ix_itr360_decision_audit_category_created_at",
    DecisionAudit.category,
    DecisionAudit.created_at.desc(),
)


class PersonEmailAlias(Provenance, Base):
    """
    Task 11. Consumer Gmail addresses match nothing in a corporate
    directory, so the identity hop and org association come from
    THIS table, not from Person.primary_email.
    """

    __tablename__ = "person_email_alias"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        Index("ix_itr360_person_email_alias_tenant_id_email", "tenant_id", "email"),
        {"schema": "itr360"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itr360.person.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    email_kind: Mapped[str] = mapped_column(Text, nullable=False)  # personal | corporate | alias
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Quarantine(Provenance, Base):
    """
    Task 16. Failed records land here instead of being dropped. Never
    deleted — only advanced (pending -> retrying -> dead) or manually
    resolved. A dead row that vanishes is a bug that vanishes with it.
    """

    __tablename__ = "quarantine"
    __table_args__ = {"schema": "raw_ingest"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # raw ALWAYS retained (e.g. MinIO key)
    error_code: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. GM-ERR-1021
    error_reason: Mapped[str] = mapped_column(Text, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # pending|retrying|dead|resolved
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
