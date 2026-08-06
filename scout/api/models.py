"""
scout/api/models.py — Pydantic schemas for the Scout REST API.

These are the data contracts for every request and response body.
Pydantic validates them automatically — if a client sends the wrong
type, FastAPI returns a 422 Unprocessable Entity before your code runs.

Think of these as the "menu" of what the API accepts and returns.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Scan Job Models ────────────────────────────────────────────────────────────

class ScanStatus(str, Enum):
    """Lifecycle states of an async scan job."""
    QUEUED = "queued"       # Accepted, waiting for a worker
    RUNNING = "running"     # Pipeline is actively running
    COMPLETED = "completed" # Pipeline finished successfully
    FAILED = "failed"       # Pipeline finished with an error


class ScanRequest(BaseModel):
    """
    Body of POST /scans.

    Right now we only need tenant_id — but as connectors multiply,
    you'll add fields like connector_ids: list[str] | None to run
    a partial scan (e.g., only refresh Workday).
    """
    tenant_id: str = Field(
        ...,  # ... means required
        description="The tenant to scan",
        examples=["acme-corp"],
    )
    connector_ids: list[str] | None = Field(
        default=None,
        description="Specific connectors to run. None means all connectors.",
        examples=[["workday", "salesforce"]],
    )


class ScanResponse(BaseModel):
    """
    Response body of POST /scans (202 Accepted).

    Returns immediately — the scan runs in the background.
    The client uses scan_id to poll GET /scans/{scan_id}.
    """
    scan_id: str = Field(..., description="Unique identifier for this scan job")
    tenant_id: str
    status: ScanStatus
    created_at: datetime
    message: str = "Scan queued. Poll GET /scans/{scan_id} for status."


class ScanResult(BaseModel):
    """
    Stats written into the job store when the pipeline completes.
    Mirrors PipelineResult but flattened for JSON serialization.
    """
    connectors_run: list[str]
    records_extracted: int
    records_normalized: int
    records_skipped: int
    duration_seconds: float
    persons_merged: int
    vendors_merged: int
    accounts_merged: int
    manages_relationships: int
    errors: list[str]


class ScanJob(BaseModel):
    """
    The full job record stored in memory and returned by GET /scans/{scan_id}.

    Fields are populated progressively:
      - created_at + status=queued: set immediately on POST
      - started_at + status=running: set when pipeline begins
      - completed_at + result: set when pipeline finishes or fails
    """
    scan_id: str
    tenant_id: str
    status: ScanStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ScanResult | None = None
    error_message: str | None = None


# ── Health Models ──────────────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    """Health status of one backing service."""
    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """
    Response body of GET /health.

    Returns the overall system health and the status of each
    backing service. Used by Kubernetes liveness/readiness probes.

    status is "healthy" only if ALL services are healthy.
    """
    status: str  # "healthy" or "degraded"
    environment: str = "development"
    services: list[ServiceHealth]
    timestamp: datetime


# ── Graph Query Models ─────────────────────────────────────────────────────────

class OrgNode(BaseModel):
    """One manager→report relationship in the org hierarchy."""
    manager: str
    manager_title: str | None
    report: str
    report_title: str | None


class SpanRow(BaseModel):
    """One row in the span of control table."""
    manager: str
    title: str | None
    direct_reports: int
    span_rating: str  # OPTIMAL | BELOW_OPTIMAL | OVERLOADED


class VendorSpendRow(BaseModel):
    """Vendor spend aggregated by category."""
    category: str | None
    vendor_count: int
    total_spend: float


class RenewalRow(BaseModel):
    """One upcoming contract renewal."""
    vendor: str
    renewal_date: str
    days_until_renewal: int | str
    annual_spend: float
