"""
scout/intelligence/ — Schema Intelligence Layer

The intelligence layer sits between raw data ingestion and the workers.
It builds a CompanyProfile — a persistent understanding of this company's
specific data patterns, business model, stage vocabulary, and field
reliability — so every worker can reason with context rather than
applying generic rules to opaque data.

Package structure:
  company_profile.py       — CompanyProfile dataclass + persistence
  company_profile_builder.py — Infers profile from graph data
  stage_mapper.py          — Maps custom stage names to canonical stages
  field_trust.py           — Per-field confidence scoring
  worker_context.py        — WorkerContext: what each worker receives

Usage:
    from scout.intelligence import build_company_context

    ctx = build_company_context(driver, tenant_id)
    result = PipelineVelocityWorker(driver).run(tenant_id, context=ctx)
"""

from scout.intelligence.company_profile import CompanyProfile
from scout.intelligence.worker_context import WorkerContext, build_company_context

__all__ = ["CompanyProfile", "WorkerContext", "build_company_context"]
