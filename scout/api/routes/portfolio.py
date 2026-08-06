"""
scout/api/routes/portfolio.py — Portfolio-level fund view.

Endpoints:
  GET /portfolio/summary   → ranked health cards for multiple tenants
  GET /portfolio/tenants   → list tenants the current user can access

This is the Monday-morning dashboard for PE operating partners — a single
screen showing every portfolio company ranked by risk, with the key metrics
and top findings from the most recent intelligence run.

Data sources (in priority order):
  1. InsightSnapshot — persisted after each GET /insights run. Contains
     real worker findings, finding counts, company profile, and the top
     CRITICAL+HIGH findings. Always used when available.
  2. Graph heuristics — lightweight Cypher queries when no snapshot exists
     (i.e., the company has been scanned but /insights hasn't been run yet).
     Returns rough signals, not full worker intelligence.

The summary endpoint is fast (< 2s for 15 companies): snapshot reads are
SQLite point-lookups; graph heuristics are simple aggregation queries.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from neo4j import GraphDatabase
from sqlalchemy import desc
from sqlalchemy.orm import Session

from scout.config import settings
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import InsightSnapshot, User, UserTenantAccess

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _severity_label(critical: int, high: int, medium: int) -> str:
    if critical > 0:
        return "CRITICAL"
    if high > 0:
        return "HIGH"
    if medium > 0:
        return "MEDIUM"
    return "HEALTHY"


def _health_score(critical: int, high: int, medium: int, low: int) -> int:
    """
    0–100 health score. 100 = no findings. Penalises severe findings heavily.
    Critical findings are weighted 25 pts each to reflect their urgency.
    """
    penalty = (critical * 25) + (high * 10) + (medium * 4) + low
    return max(0, 100 - penalty)


# ── Snapshot-based card (real intelligence) ───────────────────────────────────

def _card_from_snapshot(snap: InsightSnapshot) -> dict[str, Any]:
    """Build a portfolio card from a persisted InsightSnapshot."""
    profile = snap.company_profile or {}
    worker_summaries = snap.worker_summaries or {}

    # Extract key metrics from worker summaries
    workforce = worker_summaries.get("WorkforceWorker", {})
    pipeline_w = worker_summaries.get("PipelineVelocityWorker", {})
    churn_w = worker_summaries.get("ChurnPredictionWorker", {})
    saas_w = worker_summaries.get("SaasLicenseWorker", {})
    vendor_w = worker_summaries.get("VendorBenchmarkWorker", {})

    headcount = workforce.get("total_headcount") or 0
    stalled_deals = pipeline_w.get("stalled_deals") or 0
    at_risk_arr = churn_w.get("at_risk_arr") or 0
    saas_spend = saas_w.get("total_software_spend") or 0
    vendor_savings = vendor_w.get("total_potential_savings") or 0

    run_at = snap.run_at
    if run_at and run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)

    return {
        "tenant_id": snap.tenant_id,
        "available": True,
        "data_source": "insight_snapshot",
        "last_insights_run": run_at.isoformat() if run_at else None,
        "error": None,
        "health_score": _health_score(snap.critical, snap.high, snap.medium, snap.low),
        "severity": _severity_label(snap.critical, snap.high, snap.medium),
        "finding_counts": {
            "critical": snap.critical,
            "high": snap.high,
            "medium": snap.medium,
            "low": snap.low,
            "total": snap.total_findings,
        },
        "top_findings": snap.top_findings or [],
        "company_profile": {
            "segment": profile.get("market_segment") or profile.get("segment"),
            "business_model": profile.get("business_model"),
            "data_confidence": profile.get("data_confidence"),
        },
        "metrics": {
            "headcount": headcount,
            "stalled_deals": stalled_deals,
            "at_risk_arr": at_risk_arr,
            "saas_annual_spend": saas_spend,
            "vendor_savings_opportunity": vendor_savings,
            "workers_run": snap.workers_run,
        },
        "narrative_snippet": snap.narrative_snippet,
        "llm_provider": snap.llm_provider,
        "llm_model": snap.llm_model,
    }


# ── Graph heuristic card (fallback when no snapshot exists) ───────────────────

def _card_from_graph(driver, tenant_id: str) -> dict[str, Any]:
    """
    Lightweight graph queries when no InsightSnapshot exists.
    Returns rough signals — not full worker intelligence.
    """
    try:
        with driver.session() as session:
            org = session.run("""
                MATCH (p:Person {tenant_id: $tid})
                RETURN
                  count(p) AS total_persons,
                  sum(CASE WHEN p.is_active = true THEN 1 ELSE 0 END) AS active_persons,
                  sum(CASE WHEN p.is_manager = true AND p.is_active = true THEN 1 ELSE 0 END) AS managers
            """, tid=tenant_id).single()

            revenue = session.run("""
                MATCH (o:Opportunity {tenant_id: $tid})
                RETURN
                  sum(CASE WHEN o.is_closed = true AND o.stage CONTAINS 'Won'
                      THEN o.amount ELSE 0 END) AS total_arr,
                  sum(CASE WHEN o.is_closed = false THEN o.amount ELSE 0 END) AS open_pipeline,
                  sum(CASE WHEN o.is_closed = true AND o.stage CONTAINS 'Won' THEN 1 ELSE 0 END) AS won,
                  sum(CASE WHEN o.is_closed = true AND o.stage CONTAINS 'Lost' THEN 1 ELSE 0 END) AS lost
            """, tid=tenant_id).single()

            vendors = session.run("""
                MATCH (v:Vendor {tenant_id: $tid, is_active: true})
                RETURN count(v) AS vendor_count,
                       sum(v.annual_spend) AS total_vendor_spend
            """, tid=tenant_id).single()

    except Exception as exc:
        logger.warning("Graph heuristic query failed for %s: %s", tenant_id, exc)
        return {"tenant_id": tenant_id, "available": False,
                "data_source": "none", "error": str(exc)}

    active = int((org["active_persons"] if org else 0) or 0)
    total = int((org["total_persons"] if org else 0) or 0)
    managers = int((org["managers"] if org else 0) or 0)
    arr = float((revenue["total_arr"] if revenue else 0) or 0)
    pipeline = float((revenue["open_pipeline"] if revenue else 0) or 0)
    won = int((revenue["won"] if revenue else 0) or 0)
    lost = int((revenue["lost"] if revenue else 0) or 0)
    win_rate = won / (won + lost) * 100 if (won + lost) > 0 else None
    vendor_spend = float((vendors["total_vendor_spend"] if vendors else 0) or 0)

    flags: list[str] = []
    if active > 0 and managers / active > 0.28:
        flags.append("Management overhead")
    if total > 0 and (total - active) / total > 0.15:
        flags.append("Attrition signal")
    if win_rate is not None and win_rate < 20:
        flags.append("Low win rate")
    if pipeline > 0 and arr > 0 and pipeline / arr < 2.0:
        flags.append("Pipeline thin")
    if vendor_spend > 0 and arr > 0 and vendor_spend / arr > 0.30:
        flags.append("High vendor spend ratio")

    critical = 1 if len(flags) >= 4 else 0
    high = min(len(flags), 3) if len(flags) >= 2 else 0
    medium = max(0, len(flags) - high - critical)

    return {
        "tenant_id": tenant_id,
        "available": True,
        "data_source": "graph_heuristics",
        "last_insights_run": None,
        "error": None,
        "health_score": _health_score(critical, high, medium, 0),
        "severity": _severity_label(critical, high, medium),
        "finding_counts": {"critical": critical, "high": high, "medium": medium, "low": 0, "total": len(flags)},
        "top_findings": [{"worker": "heuristic", "severity": "high", "title": f} for f in flags],
        "company_profile": {"segment": None, "business_model": None, "data_confidence": "low"},
        "metrics": {
            "headcount": active,
            "stalled_deals": None,
            "at_risk_arr": None,
            "saas_annual_spend": None,
            "vendor_savings_opportunity": None,
            "workers_run": 0,
        },
        "narrative_snippet": None,
        "llm_provider": None,
        "llm_model": None,
        "note": "Run GET /insights to generate full intelligence for this company.",
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/summary",
    summary="Portfolio health summary across multiple tenants",
    description=(
        "Returns a ranked health card per tenant, worst first. "
        "Uses persisted InsightSnapshot data when available (full worker intelligence), "
        "falling back to lightweight graph heuristics. "
        "Designed for PE operating partners managing multiple portfolio companies."
    ),
)
def portfolio_summary(
    tenant_ids: str = Query(
        ...,
        description="Comma-separated list of tenant IDs",
        examples=["acme-corp,techco,growthsaas"],
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    GET /portfolio/summary?tenant_ids=acme-corp,techco,growthsaas

    Returns company health cards ranked by health score (worst first).
    Cards sourced from InsightSnapshot (real intelligence) are always ranked
    above graph-heuristic cards (which appear only for companies that have
    been scanned but never had /insights run).
    """
    requested = [t.strip() for t in tenant_ids.split(",") if t.strip()][:20]
    if not requested:
        return {"companies": [], "aggregate": {}}

    # ── Pull latest snapshot per tenant from SQLite ──────────────────────
    latest_snapshots: dict[str, InsightSnapshot] = {}
    for snap in (
        db.query(InsightSnapshot)
        .filter(InsightSnapshot.tenant_id.in_(requested))
        .order_by(desc(InsightSnapshot.run_at))
        .all()
    ):
        if snap.tenant_id not in latest_snapshots:
            latest_snapshots[snap.tenant_id] = snap

    # ── Build cards ──────────────────────────────────────────────────────
    tenants_needing_graph = [t for t in requested if t not in latest_snapshots]

    companies: list[dict] = []

    # Snapshot-based cards (full intelligence)
    for tid in requested:
        if tid in latest_snapshots:
            companies.append(_card_from_snapshot(latest_snapshots[tid]))

    # Graph heuristic cards (fallback)
    if tenants_needing_graph:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        try:
            for tid in tenants_needing_graph:
                companies.append(_card_from_graph(driver, tid))
        finally:
            driver.close()

    # ── Sort: unavailable last → snapshot before heuristic → worst first ─
    source_rank = {"insight_snapshot": 0, "graph_heuristics": 1, "none": 2}
    companies.sort(key=lambda c: (
        source_rank.get(c.get("data_source", "none"), 2),
        c.get("health_score", 100),
    ))

    # ── Aggregate ────────────────────────────────────────────────────────
    available = [c for c in companies if c.get("available")]
    snap_based = [c for c in available if c.get("data_source") == "insight_snapshot"]

    aggregate = {
        "total_companies": len(requested),
        "companies_with_data": len(available),
        "companies_with_full_intelligence": len(snap_based),
        "companies_needing_insights_run": len(available) - len(snap_based),
        "critical_count": sum(1 for c in available if c["severity"] == "CRITICAL"),
        "high_count": sum(1 for c in available if c["severity"] == "HIGH"),
        "healthy_count": sum(1 for c in available if c["severity"] == "HEALTHY"),
        "avg_health_score": round(
            sum(c["health_score"] for c in available) / len(available)
        ) if available else 0,
        "total_critical_findings": sum(
            c["finding_counts"]["critical"] for c in snap_based
        ),
        "total_high_findings": sum(
            c["finding_counts"]["high"] for c in snap_based
        ),
    }

    return {"companies": companies, "aggregate": aggregate}


@router.get(
    "/tenants",
    summary="List tenants visible to the current user",
)
def list_visible_tenants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Returns all tenants the current user can access (home + granted via
    UserTenantAccess), plus the timestamp of the most recent InsightSnapshot
    for each.
    """
    home_id = current_user.tenant_id

    # Collect granted tenant IDs (extras beyond home)
    granted_rows = (
        db.query(UserTenantAccess)
        .filter(UserTenantAccess.user_id == current_user.id)
        .all()
    )
    granted_ids = {row.tenant_id for row in granted_rows}

    def _entry(tenant_id: str, is_home: bool) -> dict:
        latest = (
            db.query(InsightSnapshot)
            .filter(InsightSnapshot.tenant_id == tenant_id)
            .order_by(desc(InsightSnapshot.run_at))
            .first()
        )
        run_at = None
        if latest and latest.run_at:
            ts = latest.run_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            run_at = ts.isoformat()
        return {
            "tenant_id": tenant_id,
            "is_home": is_home,
            "last_insights_run": run_at,
            "has_full_intelligence": latest is not None,
        }

    tenants = [_entry(home_id, is_home=True)]
    for tid in granted_ids:
        if tid != home_id:
            tenants.append(_entry(tid, is_home=False))

    return {"tenants": tenants}
