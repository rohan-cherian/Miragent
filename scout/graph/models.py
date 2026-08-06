"""
scout/graph/models.py — Canonical entity models.

These are the DESTINATION shapes — what data looks like after it has
been extracted from source systems, normalized, and entity-resolved.

The canonical models are the Rosetta Stone of Scout:
  - Salesforce calls it: Title, Department, Email
  - Workday calls it:    jobTitle, department, email
  - Okta calls it:       profile.title, profile.department, profile.email
  - Canonical calls it:  job_title, department, email   ← one vocabulary

Once a record is canonical, it can be written to Neo4j the same way
regardless of which system(s) it came from.

Each canonical entity has:
  - canonical_id: a stable, deterministic ID (hash of tenant+email)
  - source_systems: which connectors contributed data
  - confidence_score: how certain we are this is one real entity
"""

import hashlib
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


def make_canonical_id(prefix: str, tenant_id: str, natural_key: str) -> str:
    """
    Generate a stable, deterministic canonical ID.

    WHY DETERMINISTIC?
    If we run a scan today and again tomorrow, the same real-world entity
    must get the same canonical_id both times. Otherwise we'd create
    duplicate nodes in Neo4j instead of updating the existing ones.

    How it works:
    1. Combine tenant_id + natural_key (email, vendor name, etc.)
    2. SHA-256 hash it → always the same output for the same input
    3. Take the first 16 characters → short enough to be readable

    Example:
        make_canonical_id("person", "acme-corp", "s.chen@acmecorp.com")
        → "person-a3f8c21d9e4b1234"
    """
    raw = f"{tenant_id}:{natural_key.lower().strip()}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


class CanonicalPerson(BaseModel):
    """
    A person — employee, contractor, or system user — resolved from
    one or more source systems.

    Source of truth hierarchy (highest → lowest priority):
    1. Workday  — employment data (name, department, manager, cost center)
    2. Okta     — auth data (last_login, is_active)
    3. Salesforce — CRM data (sfdc_id, last_login in SFDC)

    If Workday says department = "Engineering" and Salesforce says "Product",
    Workday wins — it's the HR system of record.
    """
    canonical_id: str
    tenant_id: str
    email: str                           # primary natural key

    # Identity
    full_name: str
    employee_id: str | None = None       # HR system employee number
    job_title: str | None = None
    department: str | None = None
    location: str | None = None
    cost_center: str | None = None

    # Org structure
    manager_canonical_id: str | None = None  # points to another CanonicalPerson

    # Employment
    employment_type: str = "Regular"     # Regular, Contractor, Intern
    is_active: bool = True
    start_date: str | None = None

    # Source system cross-references
    workday_id: str | None = None        # WD-0001
    salesforce_id: str | None = None     # 005Dn000003abc1
    okta_id: str | None = None

    # Provenance
    source_systems: list[str] = Field(default_factory=list)  # ["workday", "salesforce"]
    confidence_score: float = 1.0        # 1.0 = definite, 0.75 = probable

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_props(self) -> dict[str, Any]:
        """Flatten to a dict suitable for Neo4j SET properties."""
        return {
            "canonical_id": self.canonical_id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "full_name": self.full_name,
            "employee_id": self.employee_id,
            "job_title": self.job_title,
            "department": self.department,
            "location": self.location,
            "cost_center": self.cost_center,
            "employment_type": self.employment_type,
            "is_active": self.is_active,
            "start_date": self.start_date,
            "workday_id": self.workday_id,
            "salesforce_id": self.salesforce_id,
            "source_systems": self.source_systems,
            "confidence_score": self.confidence_score,
            "updated_at": self.updated_at.isoformat(),
        }


class CanonicalVendor(BaseModel):
    """
    A vendor — any company that the portfolio company pays money to.
    Source: primarily NetSuite (ERP), enriched by contract data.

    Powers: Vendor Intelligence Worker, Technology Rationalization Worker.
    """
    canonical_id: str
    tenant_id: str
    name: str                              # "Salesforce Inc"
    normalized_name: str                   # "salesforce" (for dedup)

    category: str | None = None            # "Software", "Cloud Infrastructure", etc.
    email: str | None = None
    phone: str | None = None
    is_active: bool = True

    # Financial
    annual_spend: float = 0.0
    payment_terms: str | None = None       # "Net 30", "Annual", etc.

    # Contract intelligence
    contract_renewal: str | None = None    # ISO date "2024-09-30"
    primary_contact: str | None = None

    # Source references
    netsuite_id: str | None = None

    source_systems: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_props(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "normalized_name": self.normalized_name,
            "category": self.category,
            "email": self.email,
            "is_active": self.is_active,
            "annual_spend": self.annual_spend,
            "payment_terms": self.payment_terms,
            "contract_renewal": self.contract_renewal,
            "primary_contact": self.primary_contact,
            "netsuite_id": self.netsuite_id,
            "source_systems": self.source_systems,
            "updated_at": self.updated_at.isoformat(),
        }


class CanonicalOpportunity(BaseModel):
    """
    A sales deal — open, won, or lost.
    Source: primarily Salesforce CRM, HubSpot, Dynamics 365 CRM.

    Powers: Pipeline Velocity, Churn Prediction, Expansion Revenue,
            Pricing Integrity, and Sales Capacity workers.
    """
    canonical_id: str
    tenant_id: str
    name: str                              # "Pinnacle — Platform Expansion"
    stage: str | None = None              # "Proposal/Price Quote", "Closed Won", etc.
    amount: float = 0.0                   # deal value in USD
    close_date: str | None = None         # ISO date "2024-02-29"
    probability: int = 0                  # 0–100
    is_closed: bool = False
    is_won: bool = False

    # Linkage to Account and owning AE
    account_canonical_id: str | None = None
    owner_canonical_id: str | None = None  # the AE who owns this deal

    # Days in pipeline (computed at ingest time)
    days_in_pipeline: int = 0

    # Source references
    salesforce_id: str | None = None

    source_systems: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_props(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "stage": self.stage,
            "amount": self.amount,
            "close_date": self.close_date,
            "probability": self.probability,
            "is_closed": self.is_closed,
            "is_won": self.is_won,
            "days_in_pipeline": self.days_in_pipeline,
            "salesforce_id": self.salesforce_id,
            "source_systems": self.source_systems,
            "updated_at": self.updated_at.isoformat(),
        }


class CanonicalAccount(BaseModel):
    """
    A customer or prospect account.
    Source: Salesforce CRM.

    Powers: NRR Sentinel, Expansion Intelligence, Pipeline Velocity workers.
    """
    canonical_id: str
    tenant_id: str
    name: str
    industry: str | None = None
    account_type: str | None = None        # "Customer", "Prospect", "Partner"
    annual_revenue: float | None = None
    employee_count: int | None = None
    owner_canonical_id: str | None = None  # the AE who owns this account

    salesforce_id: str | None = None

    source_systems: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_neo4j_props(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "industry": self.industry,
            "account_type": self.account_type,
            "annual_revenue": self.annual_revenue,
            "employee_count": self.employee_count,
            "salesforce_id": self.salesforce_id,
            "source_systems": self.source_systems,
            "updated_at": self.updated_at.isoformat(),
        }
