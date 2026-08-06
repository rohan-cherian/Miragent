"""
scout/api/routes/scans.py — POST /scans and GET /scans/{scan_id}

This is the heart of the async job pattern:

  POST /scans        → Accept the request, return 202 immediately
                       Launch the pipeline in a background thread
  GET  /scans/{id}  → Poll this to see the current status

Why 202 Accepted (not 200 OK)?
  The pipeline takes 2–30 seconds to run. If we made POST /scans wait
  for the pipeline to finish before responding, the HTTP client would
  time out. 202 means "I got it, I'll handle it, check back later."
  This is the standard pattern for any operation that takes > 1 second.

The async job pattern in 4 lines:
  1. Client POSTs → you create a job with status=queued, return scan_id
  2. Background thread runs the pipeline, updates job to running
  3. Pipeline completes → job updated to completed (or failed)
  4. Client polls GET /scans/{scan_id} until status != running/queued
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException

from scout.api.job_store import job_store
from scout.api.models import ScanJob, ScanRequest, ScanResponse, ScanResult, ScanStatus
from scout.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scans", tags=["Scans"])


def _run_pipeline(scan_id: str, tenant_id: str) -> None:
    """
    The function that runs in the background thread.

    This is NOT async — it's a regular blocking function.
    FastAPI's BackgroundTasks runs it in a thread pool so it
    doesn't block the event loop that handles other HTTP requests.

    Flow:
      1. Mark job as running (client sees status=running on next poll)
      2. Run the full ingestion pipeline
      3. Package the WriteStats into a ScanResult
      4. Mark job as completed (or failed if an exception occurred)
    """
    job_store.mark_running(scan_id)
    pipeline = None

    try:
        logger.info(f"[{scan_id}] Pipeline starting for tenant: {tenant_id}")
        pipeline = IngestionPipeline()
        pipeline_result = pipeline.run(tenant_id=tenant_id)

        w = pipeline_result.write_stats
        result = ScanResult(
            connectors_run=pipeline_result.connectors_run,
            records_extracted=pipeline_result.records_extracted,
            records_normalized=pipeline_result.records_normalized,
            records_skipped=pipeline_result.records_skipped,
            duration_seconds=round(pipeline_result.duration_seconds, 2),
            # Use write_stats when available; fall back to in-memory resolved counts
            # (Neo4j may be unavailable in dev/test — pipeline still produces valid data)
            persons_merged=w.persons_merged if w else pipeline_result.persons_resolved,
            vendors_merged=w.vendors_merged if w else pipeline_result.vendors_resolved,
            accounts_merged=w.accounts_merged if w else pipeline_result.accounts_resolved,
            manages_relationships=w.manages_relationships if w else 0,
            errors=pipeline_result.errors,
        )
        job_store.mark_completed(scan_id, result)
        logger.info(
            f"[{scan_id}] Pipeline completed: {result.persons_merged} persons, "
            f"{result.vendors_merged} vendors, {result.accounts_merged} accounts"
        )

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"[{scan_id}] Pipeline failed: {error_msg}", exc_info=True)
        job_store.mark_failed(scan_id, error_msg)

    finally:
        if pipeline:
            pipeline.close()


@router.post(
    "",
    response_model=ScanResponse,
    status_code=202,  # 202 Accepted — the work is in progress
    summary="Trigger a digital twin scan",
    description=(
        "Launches the Scout ingestion pipeline in the background. "
        "Returns immediately with a scan_id. "
        "Poll GET /scans/{scan_id} to check status."
    ),
)
def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks) -> ScanResponse:
    """
    POST /scans

    BackgroundTasks is FastAPI's built-in mechanism for fire-and-forget work.
    After this function returns, FastAPI runs the background task in a thread.

    Why not asyncio? The pipeline makes blocking calls (Neo4j driver, connector
    generators) that aren't async-safe. A thread is the right tool here.
    """
    # Create the job record immediately — client can poll right away
    job = job_store.create(request.tenant_id)

    # Schedule the pipeline to run after this response is sent
    background_tasks.add_task(_run_pipeline, job.scan_id, request.tenant_id)

    return ScanResponse(
        scan_id=job.scan_id,
        tenant_id=job.tenant_id,
        status=ScanStatus.QUEUED,
        created_at=job.created_at,
    )


@router.get(
    "/{scan_id}",
    response_model=ScanJob,
    summary="Get scan status and results",
    description=(
        "Poll this endpoint after triggering a scan. "
        "Status moves: queued → running → completed (or failed). "
        "When status=completed, the result field contains pipeline statistics."
    ),
)
def get_scan(scan_id: str) -> ScanJob:
    """
    GET /scans/{scan_id}

    The client should poll this every 1–2 seconds until status is
    'completed' or 'failed'. In Sprint 3 we'll add WebSockets for
    real-time push updates — but polling works great for now.
    """
    job = job_store.get(scan_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Scan '{scan_id}' not found. It may have expired or the ID is wrong.",
        )
    return job


@router.get(
    "",
    response_model=list[ScanJob],
    summary="List all scan jobs",
    description="Returns all scan jobs in this session, most recent first.",
)
def list_scans() -> list[ScanJob]:
    """GET /scans — returns all jobs. Useful for dashboards."""
    return job_store.list_all()
