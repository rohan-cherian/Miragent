"""
Task 24, Part A — Pydantic DTOs for every reusable component in
openapi/console-api-v1.yaml (the frozen Task 2 contract).

Field names, types and required/optional status match the yaml EXACTLY —
nothing added, nothing renamed, no optionality flipped. The four enums are
NOT redefined here: scout.canonical.models' CaseStatus / DecisionState /
WriteState / TriageBand carry exactly the contract's value sets (verified
value-for-value against components/schemas before writing this file), so
they are imported and reused — one definition, no parallel drift.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors,
or googleapiclient.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from scout.canonical.models import (  # value sets == the OpenAPI enums, reused not redefined
    CaseStatus,
    DecisionState,
    TriageBand,
    WriteState,
)

__all__ = [
    "AuditEntry",
    "Case",
    "CaseStatus",
    "Citation",
    "Connection",
    "ContextPack",
    "DecisionRequest",
    "DecisionState",
    "Error409",
    "Error422",
    "IdentityQueueItem",
    "Recommendation",
    "Run",
    "TriageBand",
    "TriageResult",
    "WriteState",
]


# ── Enums that exist only in the contract (no canonical counterpart) ──────


class CitationSourceType(str, Enum):
    TICKET = "ticket"
    COMMENT = "comment"
    ARTICLE = "article"
    RESOLUTION = "resolution"
    GRAPH_PATH = "graph_path"


class CitationAccessStatus(str, Enum):
    OK = "ok"
    RESTRICTED = "restricted"
    MISSING = "missing"


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IdentityQueueStatus(str, Enum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class DecisionAction(str, Enum):
    """POST /cases/{id}/decision requestBody.action — the CONTRACT's enum.

    Note the deliberate difference from the backend: the contract says
    "edit"; scout.canonical.decisions accepts "approve_edited". The route
    layer owns that mapping (scout/api/routes/__init__.py) — this schema
    stays contract-exact.
    """

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


# ── Shared DTOs, contract-exact ───────────────────────────────────────────


class Citation(BaseModel):
    source_system: str
    source_type: CitationSourceType
    object_id: str
    excerpt: str
    source_ts: datetime
    deep_link: str
    access_status: CitationAccessStatus
    relevance: float | None = Field(default=None, ge=0, le=1)


class TriageResult(BaseModel):
    case_id: uuid.UUID
    band: TriageBand
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    citations: list[Citation]
    generated_at: datetime


class ContextPack(BaseModel):
    case_id: uuid.UUID
    summary: str
    citations: list[Citation]
    trust_filtered: bool
    generated_at: datetime


class Recommendation(BaseModel):
    case_id: uuid.UUID
    draft_text: str
    citations: list[Citation]
    decision_state: DecisionState
    generated_at: datetime


class Case(BaseModel):
    id: uuid.UUID
    status: CaseStatus
    subject: str
    requester: str
    created_at: datetime
    updated_at: datetime


class Connection(BaseModel):
    id: uuid.UUID
    source_system: str
    status: ConnectionStatus
    last_synced_at: datetime | None = None


class RunStage(BaseModel):
    """One row of raw_ingest.run_stage_event.

    Task 24 requires GET /runs/{id} to carry "the seven stages with progress,
    per-stage duration and log lines" — that is what drives the console's
    Pipeline Scan bars, timeline and mini-logs.
    """

    stage: str
    progress_pct: int
    log_line: str
    duration_ms: int | None = None
    created_at: datetime | None = None


class Run(BaseModel):
    id: uuid.UUID
    source_system: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    counts: dict[str, int] | None = None
    # Populated on the detail route only; the list stays light.
    stages: list[RunStage] | None = None


class IdentityQueueItem(BaseModel):
    id: uuid.UUID
    candidate_email: str
    status: IdentityQueueStatus
    created_at: datetime
    candidate_score: float | None = None


class AuditEntry(BaseModel):
    id: uuid.UUID
    actor: str
    action: str
    target_id: str
    at: datetime
    details: dict[str, Any] | None = None


# ── Request / error bodies ────────────────────────────────────────────────


class DecisionRequest(BaseModel):
    """POST /cases/{id}/decision requestBody — contract-exact."""

    action: DecisionAction
    edited_text: str | None = None
    note: str | None = None


class Error409(BaseModel):
    """Conflict409 body: {error, by, at}."""

    error: str
    by: str | None = None
    at: datetime | None = None


class Error422(BaseModel):
    """UnprocessableEntity422 body: {field, min}."""

    field: str
    min: int
