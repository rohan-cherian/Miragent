"""
scout/api/routes/graph.py — Read-only graph query endpoints.

These endpoints expose the intelligence in the digital twin.
They're thin wrappers around GraphWriter query methods — the
business logic lives in writer.py, not here.

The pattern:
  GraphWriter speaks Cypher → returns list[dict]
  These routes receive list[dict] → return Pydantic models (validated JSON)

Why separate from /scans?
  Scans WRITE to the graph (ingestion pipeline).
  Graph endpoints READ from the graph (query layer).
  Separating them makes access control easy: read-only roles
  can call /graph/* but not /scans.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import GraphDatabase

from scout.api.models import OrgNode, RenewalRow, SpanRow, VendorSpendRow
from scout.config import settings
from scout.graph.writer import GraphWriter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["Graph"])


# ── Dependency: shared Neo4j driver ───────────────────────────────────────────
#
# FastAPI's dependency injection system. Any route that declares
# `writer: GraphWriter = Depends(get_writer)` gets a fresh GraphWriter
# for that request, backed by the shared driver.
#
# In production: move the driver to the app lifespan (created once,
# shared across all requests). For Sprint 2, creating per-request is fine.

def get_writer() -> GraphWriter:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    return GraphWriter(driver)


@router.get(
    "/org-hierarchy",
    response_model=list[OrgNode],
    summary="Org hierarchy (MANAGES relationships)",
    description=(
        "Returns all manager → direct report pairs in the graph. "
        "Use tenant_id query param to scope to one tenant."
    ),
)
def org_hierarchy(
    tenant_id: str = Query(..., description="Tenant to query", examples=["acme-corp"]),
    writer: GraphWriter = Depends(get_writer),
) -> list[OrgNode]:
    try:
        rows = writer.get_org_hierarchy(tenant_id)
        return [OrgNode(**row) for row in rows]
    except Exception as exc:
        logger.error(f"org-hierarchy query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/span-of-control",
    response_model=list[SpanRow],
    summary="Span of control analysis",
    description=(
        "Returns each manager's direct report count and a span rating: "
        "OPTIMAL (5–10 reports), BELOW_OPTIMAL (<5), or OVERLOADED (>10)."
    ),
)
def span_of_control(
    tenant_id: str = Query(..., description="Tenant to query"),
    writer: GraphWriter = Depends(get_writer),
) -> list[SpanRow]:
    try:
        rows = writer.get_span_of_control(tenant_id)
        return [SpanRow(**row) for row in rows]
    except Exception as exc:
        logger.error(f"span-of-control query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/vendor-spend",
    response_model=list[VendorSpendRow],
    summary="Vendor spend by category",
    description="Returns total vendor spend and vendor count, grouped by category.",
)
def vendor_spend(
    tenant_id: str = Query(..., description="Tenant to query"),
    writer: GraphWriter = Depends(get_writer),
) -> list[VendorSpendRow]:
    try:
        rows = writer.get_vendor_spend_by_category(tenant_id)
        return [VendorSpendRow(**row) for row in rows]
    except Exception as exc:
        logger.error(f"vendor-spend query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/renewals",
    response_model=list[RenewalRow],
    summary="Upcoming contract renewals",
    description=(
        "Returns vendor contracts renewing within `within_days` days, "
        "sorted by renewal date ascending."
    ),
)
def renewals(
    tenant_id: str = Query(..., description="Tenant to query"),
    within_days: int = Query(180, ge=1, le=3650, description="Look-ahead window in days"),
    writer: GraphWriter = Depends(get_writer),
) -> list[RenewalRow]:
    try:
        rows = writer.get_upcoming_renewals(tenant_id, within_days=within_days)
        return [RenewalRow(**row) for row in rows]
    except Exception as exc:
        logger.error(f"renewals query failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
