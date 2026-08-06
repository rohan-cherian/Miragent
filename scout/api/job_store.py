"""
scout/api/job_store.py — In-memory scan job registry.

Why in-memory?
  Sprint 2 is deliberately stateless for simplicity. The job store
  lives in RAM, which means it resets when the API restarts.

Why thread-safe?
  FastAPI runs in a single async event loop, BUT the ingestion pipeline
  is CPU-heavy (Neo4j writes, resolver logic) so we run it in a
  ThreadPoolExecutor. That means the background thread writes to the
  job store while the main thread handles other HTTP requests.
  A threading.Lock prevents race conditions.

Production upgrade path:
  Replace this with Redis (already in your Docker stack!) using:
    redis_client.setex(scan_id, ttl=86400, value=job.model_dump_json())
  The API surface stays identical — only this file changes.
"""

import threading
from datetime import datetime, timezone

import shortuuid

from scout.api.models import ScanJob, ScanStatus


class JobStore:
    """
    Thread-safe, in-memory registry of scan jobs.

    Usage:
        store = JobStore()
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        store.mark_completed(job.scan_id, result=...)
        job = store.get(job.scan_id)
    """

    def __init__(self) -> None:
        self._jobs: dict[str, ScanJob] = {}
        self._lock = threading.Lock()  # Guards all reads and writes

    def create(self, tenant_id: str) -> ScanJob:
        """
        Create a new job in QUEUED status and store it.

        shortuuid generates a short, URL-safe unique ID like "scan-aB3xK9".
        Much friendlier in logs than a full UUID.
        """
        scan_id = f"scan-{shortuuid.uuid()[:8]}"
        job = ScanJob(
            scan_id=scan_id,
            tenant_id=tenant_id,
            status=ScanStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._jobs[scan_id] = job
        return job

    def get(self, scan_id: str) -> ScanJob | None:
        """Return the job, or None if not found."""
        with self._lock:
            return self._jobs.get(scan_id)

    def mark_running(self, scan_id: str) -> None:
        """Called by the background thread when the pipeline starts."""
        with self._lock:
            job = self._jobs.get(scan_id)
            if job:
                self._jobs[scan_id] = job.model_copy(update={
                    "status": ScanStatus.RUNNING,
                    "started_at": datetime.now(timezone.utc),
                })

    def mark_completed(self, scan_id: str, result) -> None:
        """Called by the background thread when the pipeline succeeds."""
        with self._lock:
            job = self._jobs.get(scan_id)
            if job:
                self._jobs[scan_id] = job.model_copy(update={
                    "status": ScanStatus.COMPLETED,
                    "completed_at": datetime.now(timezone.utc),
                    "result": result,
                })

    def mark_failed(self, scan_id: str, error: str) -> None:
        """Called by the background thread when the pipeline raises."""
        with self._lock:
            job = self._jobs.get(scan_id)
            if job:
                self._jobs[scan_id] = job.model_copy(update={
                    "status": ScanStatus.FAILED,
                    "completed_at": datetime.now(timezone.utc),
                    "error_message": error,
                })

    def list_all(self) -> list[ScanJob]:
        """Return all jobs, most recent first."""
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)


# Module-level singleton — shared across the entire FastAPI process
# (imported by routes, initialized once at startup)
job_store = JobStore()
