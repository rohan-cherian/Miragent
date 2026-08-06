"""
scout/connectors/models.py — Pydantic models for all connector data.

These models serve two purposes:
1. VALIDATION — Pydantic rejects any data that doesn't match the schema.
   A missing required field, a string where a number is expected, an
   invalid date format — all caught here, before they touch the graph.

2. DOCUMENTATION — the models ARE the API contract. Any developer reading
   these classes knows exactly what data flows through Scout.

Design principle: models at this layer are RAW (what connectors return).
Canonical models (Person, System, etc.) live in scout/graph/models.py
and are produced by the entity resolution pipeline.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────
# ENUMERATIONS
# Using enums instead of raw strings catches typos at
# development time rather than producing silent wrong data.
# ─────────────────────────────────────────────────────────

class ConnectorCategory(str, Enum):
    """Which business domain does this connector cover?"""
    HCM = "hcm"                    # Human Capital Management (Workday, ADP)
    CRM = "crm"                    # Customer Relationship Mgmt (Salesforce)
    ERP = "erp"                    # Enterprise Resource Planning (NetSuite, SAP)
    IDENTITY = "identity"          # SSO / IAM (Okta, Azure AD)
    PRODUCTIVITY = "productivity"  # Collaboration (Slack, Microsoft 365)
    ITSM = "itsm"                  # IT Service Mgmt (ServiceNow, Jira)
    FINANCE = "finance"            # Finance systems (Coupa, Concur)
    CLOUD = "cloud"                # Cloud infra (AWS, GCP, Azure)


class ExtractionStatus(str, Enum):
    """Result of an extraction run."""
    SUCCESS = "success"
    PARTIAL = "partial"    # some records failed, most succeeded
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILED = "auth_failed"


# ─────────────────────────────────────────────────────────
# CONNECTOR INFRASTRUCTURE MODELS
# These describe the connector itself, not the data it returns.
# ─────────────────────────────────────────────────────────

class ConnectorCredentials(BaseModel):
    """
    Authentication credentials for a connector.
    The connector_id identifies which connector these belong to.
    The rest is connector-specific (OAuth token, API key, etc.)

    Stored in Secrets Manager / Vault in production.
    Read from .env.local on your laptop.
    """
    connector_id: str
    tenant_id: str
    auth_data: dict[str, str]  # flexible: {"token": "..."} or {"key": "...", "secret": "..."}
    expires_at: datetime | None = None


class ExtractionCursor(BaseModel):
    """
    Tracks where an incremental extraction left off.
    Stored after each successful run so the next run
    picks up exactly where this one stopped.

    Without cursors: every run re-extracts everything (slow, expensive).
    With cursors: only new/changed records are extracted.
    """
    connector_id: str
    entity_type: str
    last_extracted_at: datetime
    checkpoint: dict[str, Any] = Field(default_factory=dict)
    # checkpoint holds connector-specific state:
    # Salesforce: {"next_records_url": "/services/data/v58.0/query/..."}
    # Workday:    {"offset": 450, "total": 1200}
    # NetSuite:   {"last_modified_date": "2024-01-15T10:30:00Z"}


class ConnectorHealth(BaseModel):
    """
    Result of a health check — is this connector working right now?
    Used by the orchestrator to decide whether to include a connector
    in a scan, and by monitoring to alert if a connector breaks.
    """
    connector_id: str
    is_healthy: bool
    latency_ms: float | None = None
    error_message: str | None = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class EntitySchema(BaseModel):
    """
    Describes one entity type that a connector can extract.
    Used for discovery: "what can this connector give us?"
    """
    entity_type: str       # e.g. "user", "opportunity", "vendor"
    display_name: str      # e.g. "Salesforce Users"
    supports_incremental: bool = True
    estimated_record_count: int | None = None
    fields: list[str] = Field(default_factory=list)  # available field names


# ─────────────────────────────────────────────────────────
# RAW RECORD — the universal output of every connector
# ─────────────────────────────────────────────────────────

class RawRecord(BaseModel):
    """
    The universal envelope that wraps every record any connector returns.

    Why a universal wrapper?
    - The orchestrator can handle records from any connector the same way
    - Provenance is always preserved (which system did this come from?)
    - The raw payload is kept intact — transformation happens downstream

    Think of it like a shipping box: same box shape regardless of what's inside.
    The 'payload' is the actual contents; everything else is the label.
    """
    connector_id: str          # which connector produced this ("salesforce", "workday")
    entity_type: str           # what kind of record ("user", "opportunity", "vendor")
    source_id: str             # the ID in the source system (Salesforce's "003...")
    tenant_id: str             # which company's data this belongs to
    payload: dict[str, Any]    # the actual record, exactly as the source system returned it
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    schema_version: str = "1.0"

    # Optional enrichment — connectors can add hints for entity resolution
    email_hint: str | None = None   # if there's an email in this record
    name_hint: str | None = None    # if there's a name in this record


class ExtractionResult(BaseModel):
    """
    Summary of a completed extraction run.
    Written to the database so you can track history and debug failures.
    """
    connector_id: str
    entity_type: str
    tenant_id: str
    status: ExtractionStatus
    records_extracted: int = 0
    records_failed: int = 0
    duration_seconds: float = 0.0
    error_details: str | None = None
    cursor: ExtractionCursor | None = None  # save this for the next incremental run
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
