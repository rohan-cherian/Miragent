"""
scout/api/routes/health_score.py — Company Health Score (Sprint 77)

Aggregates findings across all Scout workers into a single 0-100 operational
health score, broken down by 6 business dimensions. Designed as the executive
summary metric a PE firm tracks across their portfolio.

Endpoints:
  GET /health-score                        → HealthScoreResponse
  GET /health-score/history?months=6       → list[HistoryPoint]
  GET /health-score/dimension/{key}        → DimensionScore
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/health-score", tags=["health-score"])

# ── Scoring model ──────────────────────────────────────────────────────────────

DIMENSIONS: dict[str, dict[str, Any]] = {
    "revenue_growth": {"weight": 0.25, "label": "Revenue & Growth",     "icon": "trending_up"},
    "customer_health": {"weight": 0.20, "label": "Customer Health",      "icon": "heart"},
    "operational":     {"weight": 0.20, "label": "Operations",           "icon": "settings"},
    "security":        {"weight": 0.15, "label": "Security & Compliance","icon": "shield"},
    "team_org":        {"weight": 0.10, "label": "Team & Org",           "icon": "users"},
    "financial":       {"weight": 0.10, "label": "Financial Health",     "icon": "dollar"},
}

MOCK_SCORES: dict[str, dict[str, Any]] = {
    "revenue_growth": {
        "score": 78,
        "prior_score": 74,
        "signals": [
            {"label": "ARR Growth",           "value": "+3.3% MoM",         "positive": True},
            {"label": "Net Revenue Retention", "value": "107%",              "positive": True},
            {"label": "Pipeline Coverage",    "value": "5.7x",              "positive": True},
            {"label": "Win Rate",             "value": "28%",               "positive": True},
            {"label": "Pipeline Concentration","value": "Top 3 deals = 31%","positive": False},
        ],
        "top_risk": "Pipeline concentration — 3 deals represent 31% of weighted pipeline",
        "top_opportunity": "Win rate improving from 25% to 28% MoM — sales motion tightening",
    },
    "customer_health": {
        "score": 71,
        "prior_score": 68,
        "signals": [
            {"label": "NPS Score",           "value": "42 (↑4)",   "positive": True},
            {"label": "Monthly Churn",        "value": "0.9%",      "positive": True},
            {"label": "At-Risk ARR",          "value": "$320K",     "positive": False},
            {"label": "Support Tickets Open", "value": "23 (↓8)",  "positive": True},
            {"label": "CSAT",                 "value": "87%",       "positive": True},
        ],
        "top_risk": "ConsultancyCo cancellation ($36K ARR) + Enterprise Client Corp API complaints ($180K ARR, renewal next month)",
        "top_opportunity": "Series B Startup signaling enterprise expansion — $52K → $150K+ ACV potential",
    },
    "operational": {
        "score": 65,
        "prior_score": 67,
        "signals": [
            {"label": "Vendor Onboarding SLA", "value": "107% breach",               "positive": False},
            {"label": "Portal Access SLA",     "value": "110% breach",               "positive": False},
            {"label": "Payroll Automation",    "value": "96% requests automated",    "positive": True},
            {"label": "AP Processing",         "value": "9 stuck invoices",          "positive": False},
            {"label": "IT Access SLA",         "value": "3 CISO approvals pending",  "positive": False},
        ],
        "top_risk": "2 SLA conformance breaches (portal access +110%, vendor onboarding +107%) — both flagged critical",
        "top_opportunity": "Agent automation layer handling 4 request types autonomously — 47 hours/month saved",
    },
    "security": {
        "score": 54,
        "prior_score": 61,
        "signals": [
            {"label": "MFA Enrollment",    "value": "48% (↓ from 62%)",  "positive": False},
            {"label": "Admin Sprawl",      "value": "35% of users are admin", "positive": False},
            {"label": "Stale API Keys",    "value": "3 keys > 90 days",  "positive": False},
            {"label": "Orphaned Accounts", "value": "2 accounts",        "positive": False},
            {"label": "SOC 2 Type II",     "value": "Current (2024)",    "positive": True},
        ],
        "top_risk": "MFA enrollment at 48% — critical threshold breach. 3 stale admin credentials unrotated.",
        "top_opportunity": "SOC 2 Type II in good standing. Pen test clean. Strong compliance foundation.",
    },
    "team_org": {
        "score": 72,
        "prior_score": 70,
        "signals": [
            {"label": "Headcount Growth",       "value": "+2 MoM (48 total)", "positive": True},
            {"label": "ARR per Employee",        "value": "$175K",             "positive": True},
            {"label": "Open Engineering Reqs",  "value": "7 roles",           "positive": False},
            {"label": "Attrition MTD",           "value": "1 departure",       "positive": True},
            {"label": "Contractor Ratio",        "value": "8%",                "positive": True},
        ],
        "top_risk": "7 open engineering reqs with 18-week avg fill time — feature velocity risk in Q3",
        "top_opportunity": "ARR/employee at $175K and improving — healthy efficiency metric at current stage",
    },
    "financial": {
        "score": 76,
        "prior_score": 73,
        "signals": [
            {"label": "Gross Margin",        "value": "80.2%",          "positive": True},
            {"label": "Monthly Burn",        "value": "$318K (↓$24K)",  "positive": True},
            {"label": "Cash Runway",         "value": "21.5 months",    "positive": True},
            {"label": "EBITDA Margin",       "value": "-47.9%",         "positive": False},
            {"label": "Payroll % of OpEx",   "value": "74%",            "positive": True},
        ],
        "top_risk": "EBITDA margin at -47.9% — burn improvement needed before Series B. 21.5 months runway.",
        "top_opportunity": "Burn rate declining MoM ($342K → $318K). Gross margin at 80%+ is PE-grade.",
    },
}

MOCK_HISTORY = [
    {"month": "Dec 2025", "score": 64},
    {"month": "Jan 2026", "score": 66},
    {"month": "Feb 2026", "score": 68},
    {"month": "Mar 2026", "score": 71},
    {"month": "Apr 2026", "score": 69},
    {"month": "May 2026", "score": 70},
]

# ── Score helpers ──────────────────────────────────────────────────────────────

def _band(score: int) -> str:
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 55:
        return "Needs Attention"
    if score >= 40:
        return "At Risk"
    return "Critical"


def _compute_overall(scores: dict[str, dict[str, Any]], key: str = "score") -> int:
    total = sum(scores[k][key] * DIMENSIONS[k]["weight"] for k in DIMENSIONS)
    return math.ceil(total) if total % 1 >= 0.5 else math.floor(total)


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    key: str
    label: str
    icon: str
    score: int
    prior_score: int
    change: int
    weight: float
    band: str
    signals: list[dict]
    top_risk: str
    top_opportunity: str


@dataclass
class HealthScoreResponse:
    tenant_id: str
    overall_score: int
    prior_overall: int
    overall_change: int
    overall_band: str
    dimensions: list[DimensionScore]
    weakest_dimension: str
    strongest_dimension: str
    score_narrative: str
    computed_at: str
    period: str


# ── Builder ────────────────────────────────────────────────────────────────────

def _build_response(tenant_id: str) -> HealthScoreResponse:
    overall = _compute_overall(MOCK_SCORES, "score")
    prior_overall = _compute_overall(MOCK_SCORES, "prior_score")

    dimensions: list[DimensionScore] = []
    for key, dim in DIMENSIONS.items():
        ms = MOCK_SCORES[key]
        dimensions.append(
            DimensionScore(
                key=key,
                label=dim["label"],
                icon=dim["icon"],
                score=ms["score"],
                prior_score=ms["prior_score"],
                change=ms["score"] - ms["prior_score"],
                weight=dim["weight"],
                band=_band(ms["score"]),
                signals=ms["signals"],
                top_risk=ms["top_risk"],
                top_opportunity=ms["top_opportunity"],
            )
        )

    weakest = min(dimensions, key=lambda d: d.score).key
    strongest = max(dimensions, key=lambda d: d.score).key
    weakest_score = MOCK_SCORES[weakest]["score"]

    # Contribution of weakest dimension to overall
    weight_pct = int(DIMENSIONS[weakest]["weight"] * 100)
    # Rough estimate: moving weakest from current to 70 adds:
    score_gain = round((70 - weakest_score) * DIMENSIONS[weakest]["weight"])

    narrative = (
        f"Miragent's operational health score is {overall}/100 ({_band(overall)}), "
        f"{'up' if overall >= prior_overall else 'down'} {abs(overall - prior_overall)} point"
        f"{'s' if abs(overall - prior_overall) != 1 else ''} from last month. "
        f"{DIMENSIONS[weakest]['label']} remains the top priority at {weakest_score}/100, "
        f"weighted at {weight_pct}% of the overall score — "
        f"addressing the primary issue would add approximately {score_gain} points to the overall score."
    )

    return HealthScoreResponse(
        tenant_id=tenant_id,
        overall_score=overall,
        prior_overall=prior_overall,
        overall_change=overall - prior_overall,
        overall_band=_band(overall),
        dimensions=dimensions,
        weakest_dimension=weakest,
        strongest_dimension=strongest,
        score_narrative=narrative,
        computed_at=datetime.now(timezone.utc).isoformat(),
        period="May 2026",
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("")
def get_health_score(tenant_id: str = Query(default="acme-corp")) -> dict:
    """Return the full HealthScoreResponse for a tenant."""
    resp = _build_response(tenant_id)
    data = asdict(resp)
    return data


@router.get("/history")
def get_health_score_history(
    tenant_id: str = Query(default="acme-corp"),
    months: int = Query(default=6, ge=1, le=24),
) -> list[dict]:
    """Return monthly overall health scores for sparkline rendering."""
    return MOCK_HISTORY[-months:]


@router.get("/dimension/{key}")
def get_dimension_score(
    key: str,
    tenant_id: str = Query(default="acme-corp"),
) -> dict:
    """Return detailed DimensionScore for a single dimension key."""
    if key not in DIMENSIONS:
        raise HTTPException(status_code=404, detail=f"Unknown dimension key: {key}")
    resp = _build_response(tenant_id)
    for dim in resp.dimensions:
        if dim.key == key:
            return asdict(dim)
    raise HTTPException(status_code=404, detail=f"Dimension not found: {key}")
