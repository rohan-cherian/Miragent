"""
scout/api/routes/copilot.py — Miragent Copilot.

Sprint 79: Natural language Q&A against the digital twin.

POST /copilot/ask
  Input:  { tenant_id, question }
  Output: { answer, intent, data, sources }

Architecture — intent classification + safe Cypher templates:
  1. Classify the question into one of N intents using keyword heuristics
     (no LLM call needed for routing — fast and deterministic).
  2. Run the corresponding pre-written Cypher query against Neo4j.
  3. If no graph data is available, fall back to the most recent
     InsightSnapshot narrative.
  4. Pass the raw data + question to the LLM for natural language synthesis.
  5. Return the synthesised answer with source attribution.

Why not LLM → Cypher (Text-to-SQL style)?
  Pre-written query templates are safer (no injection risk), faster,
  and more testable. The LLM's job here is synthesis, not query writing.

Intents:
  pipeline    — deal velocity, stalled deals, coverage ratio
  churn       — at-risk customers, renewal pressure
  workforce   — headcount, manager spans, key-person risk
  vendors     — SaaS spend, vendor savings, benchmark gaps
  revenue     — ARR, win rate, expansion opportunities
  snapshot    — catch-all: uses InsightSnapshot narrative + top findings
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from neo4j import GraphDatabase
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from scout.analysis.llm_analyst import LLMAnalyst
from scout.config import settings
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import ApprovalRequest, InsightSnapshot, RemediationAction, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/copilot", tags=["copilot"])

# Module-level analyst — reused across requests
_analyst = LLMAnalyst()

# ── Intent classification ─────────────────────────────────────────────────────

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "pipeline": [
        "pipeline", "deal", "deals", "stall", "stalled", "coverage",
        "opport", "forecast", "close", "stage", "funnel",
    ],
    "churn": [
        "churn", "at risk", "at-risk", "renew", "renewal", "cancel",
        "lose", "losing", "lost customer", "retention",
    ],
    "workforce": [
        "headcount", "employee", "staff", "people", "hire", "hiring",
        "manager", "org", "team", "span", "key person", "attrition",
        "turnover", "who report",
    ],
    "vendors": [
        "vendor", "saas", "software", "spend", "subscription", "license",
        "saving", "savings", "benchmark", "overpay", "contract",
    ],
    "revenue": [
        "arr", "revenue", "win rate", "won", "mrr", "expand", "expansion",
        "upsell", "cross-sell", "cross sell", "quota",
    ],
}


def _classify_intent(question: str) -> str:
    q = question.lower()
    scores: dict[str, int] = {intent: 0 for intent in _INTENT_KEYWORDS}
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                scores[intent] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "snapshot"


# ── Graph query runners ───────────────────────────────────────────────────────

def _query_pipeline(driver, tenant_id: str) -> dict[str, Any]:
    with driver.session() as s:
        result = s.run("""
            MATCH (o:Opportunity {tenant_id: $tid, is_closed: false})
            OPTIONAL MATCH (o)-[:OWNED_BY]->(p:Person)
            RETURN
              count(o) AS open_deals,
              sum(o.amount) AS open_pipeline_value,
              sum(CASE WHEN o.days_in_stage > 30 THEN 1 ELSE 0 END) AS stalled_deals,
              sum(CASE WHEN o.days_in_stage > 30 THEN o.amount ELSE 0 END) AS stalled_value,
              avg(o.days_in_stage) AS avg_days_in_stage
        """, tid=tenant_id).single()

        won = s.run("""
            MATCH (o:Opportunity {tenant_id: $tid, is_closed: true})
            WHERE o.stage CONTAINS 'Won'
            RETURN count(o) AS won_count, sum(o.amount) AS won_value
        """, tid=tenant_id).single()

        lost = s.run("""
            MATCH (o:Opportunity {tenant_id: $tid, is_closed: true})
            WHERE o.stage CONTAINS 'Lost'
            RETURN count(o) AS lost_count
        """, tid=tenant_id).single()

    won_c = int(won["won_count"] or 0) if won else 0
    lost_c = int(lost["lost_count"] or 0) if lost else 0
    win_rate = won_c / (won_c + lost_c) * 100 if (won_c + lost_c) > 0 else None

    return {
        "open_deals": int(result["open_deals"] or 0) if result else 0,
        "open_pipeline_value": float(result["open_pipeline_value"] or 0) if result else 0,
        "stalled_deals": int(result["stalled_deals"] or 0) if result else 0,
        "stalled_value": float(result["stalled_value"] or 0) if result else 0,
        "avg_days_in_stage": round(float(result["avg_days_in_stage"] or 0), 1) if result else 0,
        "won_count": won_c,
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
    }


def _query_workforce(driver, tenant_id: str) -> dict[str, Any]:
    with driver.session() as s:
        result = s.run("""
            MATCH (p:Person {tenant_id: $tid})
            RETURN
              count(p) AS total,
              sum(CASE WHEN p.is_active = true THEN 1 ELSE 0 END) AS active,
              sum(CASE WHEN p.is_manager = true AND p.is_active = true THEN 1 ELSE 0 END) AS managers
        """, tid=tenant_id).single()

        overloaded = s.run("""
            MATCH (m:Person {tenant_id: $tid, is_manager: true, is_active: true})
            WHERE size([(m)<-[:REPORTS_TO]-(:Person {is_active: true}) | 1]) > 8
            RETURN m.name AS name,
                   size([(m)<-[:REPORTS_TO]-(:Person {is_active: true}) | 1]) AS span
            ORDER BY span DESC LIMIT 5
        """, tid=tenant_id).data()

    return {
        "total_headcount": int(result["total"] or 0) if result else 0,
        "active_headcount": int(result["active"] or 0) if result else 0,
        "manager_count": int(result["managers"] or 0) if result else 0,
        "overloaded_managers": overloaded,
    }


def _query_vendors(driver, tenant_id: str) -> dict[str, Any]:
    with driver.session() as s:
        result = s.run("""
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            RETURN
              count(v) AS vendor_count,
              sum(v.annual_spend) AS total_spend,
              sum(CASE WHEN v.utilisation_rate < 0.5 THEN v.annual_spend ELSE 0 END) AS underutilised_spend
            """, tid=tenant_id).single()

        top_vendors = s.run("""
            MATCH (v:Vendor {tenant_id: $tid, is_active: true})
            WHERE v.annual_spend IS NOT NULL
            RETURN v.name AS name, v.annual_spend AS spend, v.category AS category
            ORDER BY v.annual_spend DESC LIMIT 5
        """, tid=tenant_id).data()

    return {
        "vendor_count": int(result["vendor_count"] or 0) if result else 0,
        "total_annual_spend": float(result["total_spend"] or 0) if result else 0,
        "underutilised_spend": float(result["underutilised_spend"] or 0) if result else 0,
        "top_vendors": top_vendors,
    }


def _query_churn(driver, tenant_id: str) -> dict[str, Any]:
    with driver.session() as s:
        at_risk = s.run("""
            MATCH (a:Account {tenant_id: $tid, account_type: 'Customer'})
            WHERE a.health_score IS NOT NULL AND a.health_score < 60
            RETURN a.name AS name, a.health_score AS score,
                   a.annual_revenue AS arr
            ORDER BY a.health_score ASC LIMIT 8
        """, tid=tenant_id).data()

        renewals = s.run("""
            MATCH (o:Opportunity {tenant_id: $tid, is_closed: false})
            WHERE toLower(o.stage) CONTAINS 'renew'
            RETURN count(o) AS renewal_count, sum(o.amount) AS renewal_value
        """, tid=tenant_id).single()

    return {
        "at_risk_accounts": at_risk,
        "at_risk_count": len(at_risk),
        "renewal_deals": int(renewals["renewal_count"] or 0) if renewals else 0,
        "renewal_value": float(renewals["renewal_value"] or 0) if renewals else 0,
    }


def _query_revenue(driver, tenant_id: str) -> dict[str, Any]:
    with driver.session() as s:
        result = s.run("""
            MATCH (o:Opportunity {tenant_id: $tid, is_closed: true})
            WHERE o.stage CONTAINS 'Won'
            RETURN
              sum(o.amount) AS arr,
              count(o) AS won_count,
              avg(o.amount) AS avg_deal_size
        """, tid=tenant_id).single()

        expansion = s.run("""
            MATCH (a:Account {tenant_id: $tid, account_type: 'Customer'})
            WHERE a.expansion_potential IS NOT NULL AND a.expansion_potential > 0
            RETURN count(a) AS expansion_accounts,
                   sum(a.expansion_potential) AS expansion_value
        """, tid=tenant_id).single()

    return {
        "total_arr": float(result["arr"] or 0) if result else 0,
        "closed_won_count": int(result["won_count"] or 0) if result else 0,
        "avg_deal_size": float(result["avg_deal_size"] or 0) if result else 0,
        "expansion_accounts": int(expansion["expansion_accounts"] or 0) if expansion else 0,
        "expansion_potential": float(expansion["expansion_value"] or 0) if expansion else 0,
    }


def _get_snapshot_context(db: Session, tenant_id: str) -> dict[str, Any] | None:
    snap = (
        db.query(InsightSnapshot)
        .filter(InsightSnapshot.tenant_id == tenant_id)
        .order_by(desc(InsightSnapshot.run_at))
        .first()
    )
    if not snap:
        return None
    run_at = snap.run_at
    if run_at and run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    return {
        "narrative": snap.narrative_snippet,
        "top_findings": snap.top_findings or [],
        "critical": snap.critical,
        "high": snap.high,
        "total_findings": snap.total_findings,
        "run_at": run_at.isoformat() if run_at else None,
    }


# ── LLM synthesis ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are Miragent Copilot — an AI advisor embedded inside a PE operating platform.
You have access to live data from the company's CRM, HR system, finance, and vendor contracts.
Answer the user's question directly and concisely using the data provided.
Be specific: quote numbers, name accounts, flag risks.
Use plain English. No jargon. Keep answers under 200 words unless more detail is essential.
If the data is insufficient to answer, say so clearly and suggest what data would help."""


def _synthesise(question: str, intent: str, data: dict, tenant_id: str) -> str:
    data_str = _format_data_for_prompt(intent, data)
    user_msg = (
        f"Company: {tenant_id}\n"
        f"Question: {question}\n\n"
        f"Available data:\n{data_str}"
    )
    try:
        return _analyst._provider.complete(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        logger.warning("Copilot LLM synthesis failed: %s", exc)
        return _fallback_answer(intent, data, tenant_id)


def _format_data_for_prompt(intent: str, data: dict) -> str:
    lines = []
    for k, v in data.items():
        if isinstance(v, list):
            if v:
                lines.append(f"{k}:")
                for item in v[:5]:
                    if isinstance(item, dict):
                        lines.append("  - " + ", ".join(f"{ik}: {iv}" for ik, iv in item.items()))
                    else:
                        lines.append(f"  - {item}")
        elif v is not None:
            lines.append(f"{k}: {v}")
    return "\n".join(lines) if lines else "No data available."


def _fallback_answer(intent: str, data: dict, tenant_id: str) -> str:
    """Rule-based fallback when LLM is unavailable."""
    if intent == "pipeline":
        return (
            f"{tenant_id} has {data.get('open_deals', 0)} open deals "
            f"worth ${data.get('open_pipeline_value', 0):,.0f}. "
            f"{data.get('stalled_deals', 0)} deals are stalled (>30 days in stage)."
        )
    if intent == "workforce":
        return (
            f"{tenant_id} has {data.get('active_headcount', 0)} active employees "
            f"({data.get('manager_count', 0)} managers). "
            f"{len(data.get('overloaded_managers', []))} managers have >8 direct reports."
        )
    if intent == "vendors":
        return (
            f"{tenant_id} has {data.get('vendor_count', 0)} active vendors with "
            f"${data.get('total_annual_spend', 0):,.0f} in total annual spend."
        )
    if intent == "churn":
        return (
            f"{data.get('at_risk_count', 0)} customer accounts have low health scores. "
            f"{data.get('renewal_deals', 0)} renewal opportunities worth "
            f"${data.get('renewal_value', 0):,.0f} are in the pipeline."
        )
    if intent == "revenue":
        return (
            f"{tenant_id} has ${data.get('total_arr', 0):,.0f} in closed-won ARR "
            f"from {data.get('closed_won_count', 0)} deals."
        )
    # snapshot fallback
    narrative = data.get("narrative") or ""
    findings = data.get("top_findings") or []
    snippet = narrative[:300] if narrative else "No narrative available."
    if findings:
        top = findings[0].get("title", "") if findings else ""
        return f"Based on the last intelligence run: {snippet}\n\nTop finding: {top}"
    return snippet or "No data available. Run /insights first to populate intelligence."


# ── Suggested actions ─────────────────────────────────────────────────────────

def _make_hash(tenant_id: str, title: str) -> str:
    return hashlib.sha256(f"{tenant_id}:{title}".encode()).hexdigest()[:16]


def _suggest_actions(intent: str, data: dict, tenant_id: str) -> list[dict]:
    """Generate 0-3 suggested remediation actions from Copilot data."""
    actions: list[dict] = []

    if intent == "pipeline":
        stalled = int(data.get("stalled_deals") or 0)
        stalled_value = float(data.get("stalled_value") or 0)
        win_rate = data.get("win_rate_pct")

        if stalled > 0:
            title = f"Reassign {stalled} stalled deal(s) to active reps"
            actions.append({
                "title": title,
                "description": (
                    f"{stalled} deal(s) have been stalled for >30 days with "
                    f"${stalled_value:,.0f} at risk. Reassigning to active reps "
                    "can re-accelerate pipeline velocity."
                ),
                "action_type": "reassign_accounts",
                "risk_tier": "MEDIUM",
                "arr_impact": stalled_value if stalled_value > 0 else None,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

        if win_rate is not None and win_rate < 30:
            title = "Flag low win rate for pipeline review"
            actions.append({
                "title": title,
                "description": (
                    f"Win rate is {win_rate}%, below the 30% threshold. "
                    "A pipeline quality review can identify coaching opportunities."
                ),
                "action_type": "flag_for_review",
                "risk_tier": "LOW",
                "arr_impact": None,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

    elif intent == "churn":
        at_risk_accounts = data.get("at_risk_accounts") or []
        at_risk_count = int(data.get("at_risk_count") or 0)

        if at_risk_count > 0:
            total_arr = sum(
                float(a.get("arr") or 0)
                for a in at_risk_accounts
                if isinstance(a, dict)
            )
            risk_tier = "HIGH" if total_arr > 100_000 else "MEDIUM"
            title = f"Schedule health check meetings for {at_risk_count} at-risk account(s)"
            actions.append({
                "title": title,
                "description": (
                    f"{at_risk_count} customer account(s) have health scores below 60. "
                    f"Total ARR at risk: ${total_arr:,.0f}. Proactive outreach can "
                    "prevent churn."
                ),
                "action_type": "schedule_meeting",
                "risk_tier": risk_tier,
                "arr_impact": total_arr if total_arr > 0 else None,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

    elif intent == "workforce":
        overloaded = data.get("overloaded_managers") or []
        if overloaded:
            title = f"Flag {len(overloaded)} overloaded manager(s) for org review"
            actions.append({
                "title": title,
                "description": (
                    f"{len(overloaded)} manager(s) have >8 direct reports, indicating "
                    "span-of-control risk. An org review can identify rebalancing options."
                ),
                "action_type": "flag_for_review",
                "risk_tier": "MEDIUM",
                "arr_impact": None,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

    elif intent == "vendors":
        underutilised = float(data.get("underutilised_spend") or 0)
        if underutilised > 50_000:
            title = "Cancel or renegotiate underutilised vendor subscriptions"
            actions.append({
                "title": title,
                "description": (
                    f"${underutilised:,.0f} in vendor spend is underutilised (<50% usage). "
                    "Cancelling or renegotiating these contracts can generate immediate savings."
                ),
                "action_type": "cancel_subscription",
                "risk_tier": "MEDIUM",
                "arr_impact": underutilised,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

    elif intent == "revenue":
        expansion_potential = float(data.get("expansion_potential") or 0)
        if expansion_potential > 0:
            title = "Schedule expansion conversations with high-potential accounts"
            actions.append({
                "title": title,
                "description": (
                    f"${expansion_potential:,.0f} in expansion potential identified. "
                    "Scheduling targeted conversations can convert this to new ARR."
                ),
                "action_type": "schedule_meeting",
                "risk_tier": "LOW",
                "arr_impact": expansion_potential,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

    elif intent == "snapshot":
        top_findings = data.get("top_findings") or []
        if top_findings:
            finding = top_findings[0]
            finding_title = finding.get("title", "Top finding") if isinstance(finding, dict) else str(finding)
            title = f"Review and act on: {finding_title[:60]}"
            actions.append({
                "title": title,
                "description": (
                    f"The latest intelligence run flagged: {finding_title}. "
                    "Flag this for executive review to determine next steps."
                ),
                "action_type": "flag_for_review",
                "risk_tier": "MEDIUM",
                "arr_impact": None,
                "worker_name": "copilot",
                "finding_hash": _make_hash(tenant_id, title),
            })

    return actions[:3]


# ── Route ─────────────────────────────────────────────────────────────────────

class CopilotRequest(BaseModel):
    tenant_id: str
    question: str


class CreateActionRequest(BaseModel):
    tenant_id: str
    title: str
    description: str
    action_type: str
    risk_tier: str          # LOW | MEDIUM | HIGH
    arr_impact: float | None = None
    worker_name: str = "copilot"
    finding_hash: str | None = None
    assigned_to_email: str | None = None


@router.post(
    "/ask",
    summary="Ask a natural language question about a portfolio company",
    description=(
        "Classifies the question intent, queries the graph for relevant data, "
        "and synthesises a concise answer using the configured LLM. "
        "Falls back to InsightSnapshot data when the graph has insufficient data."
    ),
)
def ask(
    body: CopilotRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    tenant_id = body.tenant_id
    question = body.question.strip()

    if not question:
        return {"answer": "Please ask a question.", "intent": "none", "data": {}, "sources": []}

    intent = _classify_intent(question)
    logger.info("Copilot: tenant=%s intent=%s question=%r", tenant_id, intent, question[:80])

    data: dict[str, Any] = {}
    sources: list[str] = []

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        query_fn = {
            "pipeline":  _query_pipeline,
            "churn":     _query_churn,
            "workforce": _query_workforce,
            "vendors":   _query_vendors,
            "revenue":   _query_revenue,
        }.get(intent)

        if query_fn:
            try:
                data = query_fn(driver, tenant_id)
                sources.append("graph")
            except Exception as exc:
                logger.warning("Copilot graph query failed (%s): %s", intent, exc)

        # Always enrich with snapshot context if available
        snap_ctx = _get_snapshot_context(db, tenant_id)
        if snap_ctx:
            data["snapshot_narrative"] = snap_ctx.get("narrative")
            data["snapshot_run_at"] = snap_ctx.get("run_at")
            sources.append("insight_snapshot")

        # If no graph data came back, use snapshot as primary
        if intent == "snapshot" or not data:
            if snap_ctx:
                data = snap_ctx
            sources = ["insight_snapshot"]

    finally:
        driver.close()

    answer = _synthesise(question, intent, data, tenant_id)
    suggested_actions = _suggest_actions(intent, data, tenant_id)

    return {
        "answer": answer,
        "intent": intent,
        "data": data,
        "sources": sources,
        "llm_provider": _analyst._provider.name,
        "llm_available": _analyst._provider.is_available,
        "suggested_actions": suggested_actions,
    }


@router.post(
    "/create-action",
    summary="Create a remediation action from a Copilot suggestion",
    description=(
        "Creates a RemediationAction in the database. "
        "HIGH risk actions automatically create an ApprovalRequest."
    ),
)
def create_action(
    body: CreateActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    # Compute finding_hash if not provided
    finding_hash = body.finding_hash
    if not finding_hash:
        finding_hash = hashlib.sha256(
            f"{body.tenant_id}:{body.title}".encode()
        ).hexdigest()[:16]

    action = RemediationAction(
        tenant_id=body.tenant_id,
        finding_hash=finding_hash,
        worker_name=body.worker_name,
        title=body.title,
        description=body.description,
        action_type=body.action_type,
        assigned_to_email=body.assigned_to_email,
        arr_impact=body.arr_impact,
        status="OPEN",
        created_by=current_user.email,
    )
    db.add(action)
    db.flush()  # populate action.id before creating ApprovalRequest

    approval_id: str | None = None
    routed_to_approvals = False

    if body.risk_tier == "HIGH":
        approval = ApprovalRequest(
            tenant_id=body.tenant_id,
            action_id=action.id,
            action_type=body.action_type,
            risk_tier=body.risk_tier,
            proposed_payload={
                "title": body.title,
                "description": body.description,
                "arr_impact": body.arr_impact,
                "assigned_to_email": body.assigned_to_email,
            },
            rationale=(
                f"Copilot identified this as a HIGH-risk action. "
                f"ARR impact: ${body.arr_impact:,.0f}" if body.arr_impact
                else "Copilot identified this as a HIGH-risk action requiring approval."
            ),
            status="PENDING",
            requested_by=current_user.email,
        )
        db.add(approval)
        db.flush()
        approval_id = approval.id
        routed_to_approvals = True

    db.commit()

    logger.info(
        "Copilot action created: tenant=%s action_id=%s risk=%s routed=%s",
        body.tenant_id, action.id, body.risk_tier, routed_to_approvals,
    )

    return {
        "action_id": action.id,
        "approval_id": approval_id,
        "risk_tier": body.risk_tier,
        "routed_to_approvals": routed_to_approvals,
    }
