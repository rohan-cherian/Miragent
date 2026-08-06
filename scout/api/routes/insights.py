"""
scout/api/routes/insights.py — GET /insights

Runs all Intelligence Workers against the current state of the graph,
then passes their findings to the AI Analyst to generate an executive memo.

This endpoint is the payoff of Sprint 3 — it's what makes Miragent an
"Agentic CIO in a Box" rather than just a data visualisation tool.

Flow:
  1. Client calls GET /insights?tenant_id=acme-corp
  2. Route creates a Neo4j driver + GraphWriter
  3. Instantiates all workers (WorkforceWorker, VendorWorker)
  4. Runs each worker → collects WorkerResult objects
  5. Passes all results to AIAnalyst → gets back an InsightMemo
  6. Returns the memo as JSON (narrative + structured findings)

The endpoint is synchronous (blocks until all workers + AI complete).
At production scale, this would be an async job like /scans. For Sprint 3,
the workers are fast (pure graph reads) and Claude's response is <5 seconds.
"""

import logging

from fastapi import APIRouter, Depends, Query
from neo4j import GraphDatabase

from scout.analysis.llm_analyst import LLMAnalyst
from scout.api.routes.graph import get_writer
from scout.config import settings
from scout.db.database import SessionLocal
from scout.graph.writer import GraphWriter
from scout.intelligence import build_company_context
from scout.workers.analyst import AIAnalyst
from scout.workers.ap_processing import APProcessingWorker
from scout.workers.churn_prediction import ChurnPredictionWorker
from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
from scout.workers.expansion_revenue import ExpansionRevenueWorker
from scout.workers.expense_audit import ExpenseAuditWorker
from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
from scout.workers.hire_to_retire import HireToRetireWorker
from scout.workers.issue_to_resolution import IssueToResolutionWorker
from scout.workers.lead_enrichment import LeadEnrichmentWorker
from scout.workers.lead_to_cash import LeadToCashWorker
from scout.workers.license_management import LicenseManagementWorker
from scout.workers.marketing_funnel import MarketingFunnelWorker
from scout.workers.meeting_prep import MeetingPrepWorker
from scout.workers.offboarding import OffboardingWorker
from scout.workers.onboarding import OnboardingWorker
from scout.workers.outreach_sequence import OutreachSequenceWorker
from scout.workers.procure_to_pay import ProcureToPayWorker
from scout.workers.renewal_workflow import RenewalWorkflowWorker
from scout.workers.tam_penetration import TamPenetrationWorker
from scout.workers.pipeline_velocity import PipelineVelocityWorker
from scout.workers.pricing_integrity import PricingIntegrityWorker
from scout.workers.process_bottleneck import ProcessBottleneckWorker
from scout.workers.saas_license import SaasLicenseWorker
from scout.workers.sales_capacity import SalesCapacityWorker
from scout.workers.sentiment import SentimentWorker
from scout.workers.vendor import VendorWorker
from scout.workers.vendor_benchmark import VendorBenchmarkWorker
from scout.workers.vendor_negotiation import VendorNegotiationWorker
from scout.workers.working_capital import WorkingCapitalWorker
from scout.workers.workforce import WorkforceWorker
from scout.workers.dora_metrics import DORAMetricsWorker
from scout.workers.github_velocity import GitHubVelocityWorker
from scout.workers.security_hygiene import SecurityHygieneWorker
from scout.workers.process_conformance import ProcessConformanceWorker  # Sprint 62: Process Conformance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["Insights"])


def _persist_snapshot(
    *,
    tenant_id: str,
    results: list,
    narrative: str,
    profile_summary: dict | None,
    llm_provider: str,
    llm_model: str,
) -> None:
    """
    Write a lightweight InsightSnapshot to SQLite after each /insights run.

    Never raises — snapshot persistence must not break the response.
    """
    from scout.workers.base import Severity
    from scout.db.models import InsightSnapshot

    try:
        critical = sum(r.critical_count for r in results)
        high     = sum(r.high_count for r in results)
        medium   = sum(
            sum(1 for f in r.findings if f.severity == Severity.MEDIUM)
            for r in results
        )
        low      = sum(
            sum(1 for f in r.findings if f.severity == Severity.LOW)
            for r in results
        )
        total    = sum(len(r.findings) for r in results)

        # Top CRITICAL + HIGH findings for portfolio card (capped at 10)
        top_findings: list[dict] = []
        for r in results:
            for f in r.findings:
                if f.severity.value in ("critical", "high") and len(top_findings) < 10:
                    top_findings.append({
                        "worker": r.worker_name,
                        "severity": f.severity.value,
                        "title": f.title[:120],
                    })

        # Worker summary stats map
        worker_summaries = {
            r.worker_name: r.summary_stats
            for r in results
            if r.summary_stats
        }

        snapshot = InsightSnapshot(
            tenant_id=tenant_id,
            critical=critical,
            high=high,
            medium=medium,
            low=low,
            total_findings=total,
            workers_run=len(results),
            worker_summaries=worker_summaries,
            top_findings=top_findings,
            company_profile=profile_summary,
            narrative_snippet=narrative[:500] if narrative else None,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

        db = SessionLocal()
        try:
            db.add(snapshot)
            db.commit()
            logger.info("InsightSnapshot persisted for tenant %s", tenant_id)
        finally:
            db.close()

    except Exception as exc:
        logger.warning("Failed to persist InsightSnapshot for %s: %s", tenant_id, exc)

# Module-level analysts — shared across requests to avoid re-initialising
# the HTTP client on every call.
_analyst = AIAnalyst()        # existing analyst (keeps backwards-compat)
_llm_analyst = LLMAnalyst()  # Sprint 16: LLM-powered narrative


@router.get(
    "",
    summary="Generate AI-powered executive insights",
    description=(
        "Runs all Intelligence Workers against the digital twin, "
        "then uses Claude to synthesise findings into an executive memo. "
        "Requires a prior scan to have populated the graph. "
        "Returns both the AI narrative and the structured findings."
    ),
    response_model=None,  # dict — narrative is freeform markdown
)
def get_insights(
    tenant_id: str = Query(..., description="Tenant to analyse", examples=["acme-corp"]),
    writer: GraphWriter = Depends(get_writer),
) -> dict:
    """
    GET /insights?tenant_id=acme-corp

    The one endpoint that answers: "What should I do about this company?"
    """
    logger.info(f"Generating insights for tenant: {tenant_id}")

    # Create a fresh driver for this request (workers need it directly)
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )

    try:
        # ── Build company context (Schema Intelligence Layer) ──────────────
        # Runs before any workers — builds CompanyProfile from graph data,
        # calibrates thresholds, maps stage vocabulary, scores field trust.
        # Falls back to safe defaults if the graph has insufficient data.
        logger.info("Building company context for tenant: %s", tenant_id)
        company_context = build_company_context(driver, tenant_id)
        logger.info(
            "Company context ready: segment=%s, model=%s, confidence=%s, "
            "median_cycle=%s days, stages_mapped=%d",
            company_context.segment_label,
            company_context.company_profile.business_model if company_context.company_profile else "unknown",
            company_context.data_confidence,
            company_context.median_sales_cycle,
            len(company_context.company_profile.stage_map) if company_context.company_profile else 0,
        )

        # ── Run all workers ────────────────────────────────────────────────
        # Context-aware workers (Layer 3): receive company_context
        # Legacy workers: receive no context (pre-intelligence behavior, safe)
        workers = [
            # Sprint 3: Intelligence Workers (org + vendor)
            WorkforceWorker(driver),
            VendorWorker(driver),
            # Sprint 4: Revenue Optimization Agents
            PipelineVelocityWorker(driver),
            ChurnPredictionWorker(driver),
            ExpansionRevenueWorker(driver),
            PricingIntegrityWorker(driver),
            SalesCapacityWorker(driver),
            # Sprint 5: EBITDA Optimization Agents
            SaasLicenseWorker(driver),
            VendorNegotiationWorker(driver),
            HeadcountEfficiencyWorker(driver),
            ProcessBottleneckWorker(driver),
            WorkingCapitalWorker(driver),
            SentimentWorker(driver),
            # Sprint 6: Full Funnel Revenue Intelligence
            TamPenetrationWorker(driver),
            MarketingFunnelWorker(driver),
            CrossSellIntelligenceWorker(driver),
            # Sprint 7: Process Mining
            LeadToCashWorker(driver),
            HireToRetireWorker(driver),
            ProcureToPayWorker(driver),
            IssueToResolutionWorker(driver),
            # Sprint 8: Engagement Intelligence
            EngagementIntelligenceWorker(driver),
            # Sprint 9: Revenue Agents
            OutreachSequenceWorker(driver),
            LeadEnrichmentWorker(driver),
            MeetingPrepWorker(driver),
            RenewalWorkflowWorker(driver),
            CrossSellCampaignWorker(driver),
            # Sprint 10: Ops Agents
            OnboardingWorker(driver),
            OffboardingWorker(driver),
            APProcessingWorker(driver),
            LicenseManagementWorker(driver),
            ExpenseAuditWorker(driver),
            # Sprint 18: Vendor Benchmark Intelligence
            VendorBenchmarkWorker(driver),
            # Sprint 57: R&D / DORA
            DORAMetricsWorker(driver),
            GitHubVelocityWorker(driver),
            # Sprint 59: Security Hygiene
            SecurityHygieneWorker(driver),
            # Sprint 62: Process Conformance
            ProcessConformanceWorker(driver),
        ]

        # Workers that have been upgraded to accept WorkerContext (Layer 3)
        CONTEXT_AWARE_WORKERS = {
            # Sprint 16 (initial Layer 3 batch)
            "PipelineVelocityWorker",
            "ChurnPredictionWorker",
            "SalesCapacityWorker",
            "ExpansionRevenueWorker",
            # Layer 3 batch 2
            "WorkforceWorker",
            "MarketingFunnelWorker",
            "PricingIntegrityWorker",
            # Layer 3 batch 3
            "RenewalWorkflowWorker",
            "CrossSellIntelligenceWorker",
            # Layer 3 batch 4
            "HeadcountEfficiencyWorker",
            "SaasLicenseWorker",
            # Layer 3 batch 5
            "EngagementIntelligenceWorker",
            "WorkingCapitalWorker",
            "SentimentWorker",
            "TamPenetrationWorker",
        }

        results = []
        for worker in workers:
            logger.info(f"Running {worker.WORKER_NAME} for {tenant_id}...")
            # Pass context to workers that support it; legacy workers get none
            if worker.WORKER_NAME in CONTEXT_AWARE_WORKERS:
                result = worker.run(tenant_id, context=company_context)
            else:
                result = worker.run(tenant_id)
            results.append(result)
            logger.info(
                f"{worker.WORKER_NAME}: {len(result.findings)} findings "
                f"({result.critical_count} critical, {result.high_count} high)"
            )

        # ── Generate AI memo ───────────────────────────────────────────────
        # Build the structured payload (same as AIAnalyst does internally)
        worker_results_dicts = [r.to_dict() for r in results]
        structured = {
            "tenant_id": tenant_id,
            "workers": worker_results_dicts,
            "total_critical": sum(r.critical_count for r in results),
            "total_high": sum(r.high_count for r in results),
        }

        logger.info(
            "Generating LLM narrative (provider=%s, available=%s)...",
            _llm_analyst._provider.name,
            _llm_analyst._provider.is_available,
        )
        narrative = _llm_analyst.generate_memo(worker_results_dicts, tenant_id)

        # Company profile summary for the frontend
        profile_summary = None
        if company_context.company_profile:
            p = company_context.company_profile
            profile_summary = {
                "business_model":           p.business_model,
                "market_segment":           p.market_segment,
                "data_confidence":          p.data_confidence,
                "median_sales_cycle_days":  p.median_sales_cycle_days,
                "p75_sales_cycle_days":     p.p75_sales_cycle_days,
                "win_rate":                 p.win_rate,
                "closed_won_count":         p.closed_won_count,
                "total_headcount":          p.total_headcount,
                "stages_mapped":            len(p.stage_map),
                "thresholds_calibrated":    p.has_sales_history,
                "unmapped_stages": [
                    rec.raw_name
                    for rec in p.stage_map.values()
                    if rec.confidence < 0.70
                ],
            }

        # ── Persist snapshot for portfolio view ───────────────────────────
        # Writes a lightweight summary to SQLite so GET /portfolio/summary
        # can show real intelligence without re-running workers.
        _persist_snapshot(
            tenant_id=tenant_id,
            results=results,
            narrative=narrative,
            profile_summary=profile_summary,
            llm_provider=_llm_analyst._provider.name,
            llm_model=_llm_analyst._provider.model,
        )

        return {
            "tenant_id":     tenant_id,
            "ai_generated":  _llm_analyst._provider.is_available,
            "llm_provider":  _llm_analyst._provider.name,
            "llm_model":     _llm_analyst._provider.model,
            "narrative":     narrative,
            "structured":    structured,
            "company_profile": profile_summary,
        }

    finally:
        driver.close()
