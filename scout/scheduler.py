"""
scout/scheduler.py — Background insight scheduler.

Sprint 78: Runs in a daemon thread alongside the API server. Every minute it
checks InsightSchedule for tenants whose next run is due and fires their
/insights analysis synchronously.

Design:
  - Single daemon thread started in create_app() via lifespan.
  - Reads InsightSchedule from SQLite every tick.
  - Computes next_due time based on cadence + hour_utc + day_of_week.
  - Only runs one tenant per tick to avoid overwhelming Neo4j.
  - Writes last_triggered_at + last_status back to SQLite.
  - Never crashes the API — all exceptions are caught and logged.

The scheduler is intentionally simple (thread + sleep loop) to avoid
adding APScheduler or Celery as dependencies. At production scale with
50+ tenants, a proper task queue would be appropriate.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()

# ── Sprint 81: Monday digest guard ───────────────────────────────────────────
# Stores the last date the digest was sent so we never double-send on the
# same Monday even if the process restarts within the same hour.
_last_digest_date: date | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_due(schedule, now: datetime) -> bool:
    """
    Return True if this schedule should fire now.

    Logic:
      - manual cadence: never auto-fires
      - If last_triggered_at is None: fire immediately (first run)
      - daily: fire if last_triggered_at is more than 23h ago AND current
        UTC hour matches schedule.hour_utc (±0, within the current minute)
      - weekly: same as daily but also check day_of_week
    """
    if not schedule.enabled or schedule.cadence == "manual":
        return False

    last = schedule.last_triggered_at
    if last and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)

    # First-ever run: fire at the configured hour
    if last is None:
        return now.hour == schedule.hour_utc

    hours_since = (now - last).total_seconds() / 3600

    if schedule.cadence == "daily":
        return hours_since >= 23 and now.hour == schedule.hour_utc

    if schedule.cadence == "weekly":
        dow_match = now.weekday() == (schedule.day_of_week or 0)
        return hours_since >= 167 and now.hour == schedule.hour_utc and dow_match

    return False


def _run_insights_for_tenant(tenant_id: str) -> tuple[str, str | None]:
    """
    Execute the full insights pipeline for one tenant.
    Returns (status, error_message).

    Imports are deferred to avoid circular imports at module load time.
    """
    try:
        from neo4j import GraphDatabase
        from scout.config import settings
        from scout.analysis.llm_analyst import LLMAnalyst
        from scout.api.routes.insights import _persist_snapshot
        from scout.api.routes.graph import get_writer
        from scout.intelligence import build_company_context
        from scout.workers.workforce import WorkforceWorker
        from scout.workers.vendor import VendorWorker
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        from scout.workers.churn_prediction import ChurnPredictionWorker
        from scout.workers.expansion_revenue import ExpansionRevenueWorker
        from scout.workers.pricing_integrity import PricingIntegrityWorker
        from scout.workers.sales_capacity import SalesCapacityWorker
        from scout.workers.saas_license import SaasLicenseWorker
        from scout.workers.vendor_negotiation import VendorNegotiationWorker
        from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        from scout.workers.working_capital import WorkingCapitalWorker
        from scout.workers.sentiment import SentimentWorker
        from scout.workers.tam_penetration import TamPenetrationWorker
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        from scout.workers.lead_to_cash import LeadToCashWorker
        from scout.workers.hire_to_retire import HireToRetireWorker
        from scout.workers.procure_to_pay import ProcureToPayWorker
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        from scout.workers.engagement_intelligence import EngagementIntelligenceWorker
        from scout.workers.outreach_sequence import OutreachSequenceWorker
        from scout.workers.lead_enrichment import LeadEnrichmentWorker
        from scout.workers.meeting_prep import MeetingPrepWorker
        from scout.workers.renewal_workflow import RenewalWorkflowWorker
        from scout.workers.cross_sell_campaign import CrossSellCampaignWorker
        from scout.workers.onboarding import OnboardingWorker
        from scout.workers.offboarding import OffboardingWorker
        from scout.workers.ap_processing import APProcessingWorker
        from scout.workers.license_management import LicenseManagementWorker
        from scout.workers.expense_audit import ExpenseAuditWorker
        from scout.workers.vendor_benchmark import VendorBenchmarkWorker
        from scout.workers.dora_metrics import DORAMetricsWorker
        from scout.workers.github_velocity import GitHubVelocityWorker
        from scout.workers.security_hygiene import SecurityHygieneWorker
        from scout.workers.process_conformance import ProcessConformanceWorker

        CONTEXT_AWARE = {
            "PipelineVelocityWorker", "ChurnPredictionWorker", "SalesCapacityWorker",
            "ExpansionRevenueWorker", "WorkforceWorker", "MarketingFunnelWorker",
            "PricingIntegrityWorker", "RenewalWorkflowWorker", "CrossSellIntelligenceWorker",
            "HeadcountEfficiencyWorker", "SaasLicenseWorker", "EngagementIntelligenceWorker",
            "WorkingCapitalWorker", "SentimentWorker", "TamPenetrationWorker",
        }

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        try:
            company_context = build_company_context(driver, tenant_id)

            workers = [
                WorkforceWorker(driver), VendorWorker(driver),
                PipelineVelocityWorker(driver), ChurnPredictionWorker(driver),
                ExpansionRevenueWorker(driver), PricingIntegrityWorker(driver),
                SalesCapacityWorker(driver), SaasLicenseWorker(driver),
                VendorNegotiationWorker(driver), HeadcountEfficiencyWorker(driver),
                ProcessBottleneckWorker(driver), WorkingCapitalWorker(driver),
                SentimentWorker(driver), TamPenetrationWorker(driver),
                MarketingFunnelWorker(driver), CrossSellIntelligenceWorker(driver),
                LeadToCashWorker(driver), HireToRetireWorker(driver),
                ProcureToPayWorker(driver), IssueToResolutionWorker(driver),
                EngagementIntelligenceWorker(driver), OutreachSequenceWorker(driver),
                LeadEnrichmentWorker(driver), MeetingPrepWorker(driver),
                RenewalWorkflowWorker(driver), CrossSellCampaignWorker(driver),
                OnboardingWorker(driver), OffboardingWorker(driver),
                APProcessingWorker(driver), LicenseManagementWorker(driver),
                ExpenseAuditWorker(driver), VendorBenchmarkWorker(driver),
                DORAMetricsWorker(driver), GitHubVelocityWorker(driver),
                SecurityHygieneWorker(driver), ProcessConformanceWorker(driver),
            ]

            results = []
            for worker in workers:
                try:
                    if worker.WORKER_NAME in CONTEXT_AWARE:
                        result = worker.run(tenant_id, context=company_context)
                    else:
                        result = worker.run(tenant_id)
                    results.append(result)
                except Exception as exc:
                    logger.warning(
                        "Scheduled run: worker %s failed for %s: %s",
                        worker.WORKER_NAME, tenant_id, exc,
                    )

            llm_analyst = LLMAnalyst()
            worker_dicts = [r.to_dict() for r in results]
            narrative = llm_analyst.generate_memo(worker_dicts, tenant_id)

            profile_summary = None
            if company_context.company_profile:
                p = company_context.company_profile
                profile_summary = {
                    "business_model": p.business_model,
                    "market_segment": p.market_segment,
                    "data_confidence": p.data_confidence,
                    "median_sales_cycle_days": p.median_sales_cycle_days,
                    "win_rate": p.win_rate,
                    "total_headcount": p.total_headcount,
                }

            _persist_snapshot(
                tenant_id=tenant_id,
                results=results,
                narrative=narrative,
                profile_summary=profile_summary,
                llm_provider=llm_analyst._provider.name,
                llm_model=llm_analyst._provider.model,
            )

        finally:
            driver.close()

        return "ok", None

    except Exception as exc:
        logger.exception("Scheduled insights run failed for tenant %s: %s", tenant_id, exc)
        return "error", str(exc)[:500]


def _scheduler_loop(tick_seconds: int = 60) -> None:
    """Main scheduler loop. Runs in a daemon thread."""
    logger.info("Insight scheduler started (tick=%ds)", tick_seconds)
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception as exc:
            logger.warning("Scheduler tick error: %s", exc)
        _stop_event.wait(timeout=tick_seconds)
    logger.info("Insight scheduler stopped.")


def _maybe_send_digest() -> None:
    """
    Sprint 81 — Send Monday morning portfolio digest if not already sent today.
    Uses a module-level guard (_last_digest_date) to prevent double-sending.
    """
    global _last_digest_date
    from scout.db.database import SessionLocal

    today = _now_utc().date()
    if _last_digest_date == today:
        logger.debug("Digest already sent today (%s) — skipping.", today)
        return

    logger.info("Scheduler: firing Monday portfolio digest for %s", today)
    db = SessionLocal()
    try:
        from scout.email_digest import build_and_send_portfolio_digest
        result = build_and_send_portfolio_digest(db)
        _last_digest_date = today
        logger.info(
            "Scheduler: digest result — sent=%s recipients=%d companies=%d error=%s",
            result["sent"],
            result["recipient_count"],
            result["company_count"],
            result.get("error"),
        )
    except Exception as exc:
        logger.exception("Scheduler: digest send failed: %s", exc)
    finally:
        db.close()


def _tick() -> None:
    """Check for due schedules and fire one if found."""
    from scout.db.database import SessionLocal
    from scout.db.models import InsightSchedule

    now = _now_utc()
    db = SessionLocal()
    try:
        schedules = db.query(InsightSchedule).filter(InsightSchedule.enabled.is_(True)).all()
        for schedule in schedules:
            if _is_due(schedule, now):
                tenant_id = schedule.tenant_id
                logger.info(
                    "Scheduler: firing insights run for %s (cadence=%s)",
                    tenant_id, schedule.cadence,
                )
                # Update last_triggered_at before running so overlapping ticks don't double-fire
                schedule.last_triggered_at = now
                schedule.last_status = "running"
                schedule.last_error = None
                db.commit()

                # Run in the same thread — workers are fast (<30s for mock data)
                status, error = _run_insights_for_tenant(tenant_id)

                # Re-fetch to avoid stale object after the long run
                schedule = db.query(InsightSchedule).filter_by(tenant_id=tenant_id).first()
                if schedule:
                    schedule.last_status = status
                    schedule.last_error = error
                    db.commit()

                logger.info(
                    "Scheduler: insights run for %s finished (status=%s)",
                    tenant_id, status,
                )
                # Only one tenant per tick
                break
    finally:
        db.close()

    # Monday morning digest: fire at 06:00 UTC on Mondays
    if now.weekday() == 0 and now.hour == 6 and now.minute < 2:
        # Only fire once per Monday (check last fired)
        _maybe_send_digest()


def start_scheduler(tick_seconds: int = 60) -> None:
    """Start the background scheduler daemon thread. Idempotent."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.debug("Scheduler already running — skipping start.")
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        args=(tick_seconds,),
        daemon=True,
        name="insight-scheduler",
    )
    _scheduler_thread.start()
    logger.info("Insight scheduler thread started.")


def stop_scheduler() -> None:
    """Signal the scheduler to stop. Used in tests and graceful shutdown."""
    _stop_event.set()
