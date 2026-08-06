"""
tests/api/test_job_store.py — Unit tests for JobStore (Sprint 41)

JobStore is the in-memory, thread-safe registry of async scan jobs.
It exposes a state machine: QUEUED → RUNNING → COMPLETED | FAILED.

These tests run with NO external dependencies — pure Python in-memory.

Coverage:
  - create(): generates unique scan_id, stores job in QUEUED state
  - get(): returns job by scan_id, None for unknown IDs
  - mark_running(): transitions QUEUED → RUNNING, sets started_at
  - mark_completed(): transitions RUNNING → COMPLETED, stores result
  - mark_failed(): transitions RUNNING → FAILED, stores error_message
  - list_all(): returns all jobs sorted by created_at descending
  - Thread safety: concurrent writes don't corrupt state
  - State machine guards: noop on unknown scan_ids
"""

import threading
import time

import pytest

from scout.api.job_store import JobStore
from scout.api.models import ScanResult, ScanStatus


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def store():
    """Fresh JobStore for each test — isolated from the module singleton."""
    return JobStore()


def _make_result(**kwargs) -> ScanResult:
    defaults = dict(
        connectors_run=["salesforce", "workday"],
        records_extracted=450,
        records_normalized=440,
        records_skipped=10,
        duration_seconds=4.2,
        persons_merged=120,
        vendors_merged=35,
        accounts_merged=60,
        manages_relationships=80,
        errors=[],
    )
    defaults.update(kwargs)
    return ScanResult(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# CREATE
# ─────────────────────────────────────────────────────────────────────────────

class TestCreate:

    def test_create_returns_scan_job(self, store):
        job = store.create("acme-corp")
        assert job is not None

    def test_create_assigns_scan_id(self, store):
        job = store.create("acme-corp")
        assert job.scan_id.startswith("scan-")

    def test_create_assigns_tenant_id(self, store):
        job = store.create("acme-corp")
        assert job.tenant_id == "acme-corp"

    def test_create_starts_in_queued_status(self, store):
        job = store.create("acme-corp")
        assert job.status == ScanStatus.QUEUED

    def test_create_sets_created_at(self, store):
        job = store.create("acme-corp")
        assert job.created_at is not None

    def test_create_no_started_at_initially(self, store):
        job = store.create("acme-corp")
        assert job.started_at is None

    def test_create_no_result_initially(self, store):
        job = store.create("acme-corp")
        assert job.result is None

    def test_create_no_error_message_initially(self, store):
        job = store.create("acme-corp")
        assert job.error_message is None

    def test_create_unique_scan_ids(self, store):
        ids = {store.create("tenant").scan_id for _ in range(50)}
        assert len(ids) == 50  # all unique

    def test_create_stores_job_in_registry(self, store):
        job = store.create("acme-corp")
        assert store.get(job.scan_id) is not None

    def test_create_different_tenants(self, store):
        job_a = store.create("tenant-a")
        job_b = store.create("tenant-b")
        assert job_a.tenant_id == "tenant-a"
        assert job_b.tenant_id == "tenant-b"


# ─────────────────────────────────────────────────────────────────────────────
# GET
# ─────────────────────────────────────────────────────────────────────────────

class TestGet:

    def test_get_returns_job_for_valid_id(self, store):
        job = store.create("acme-corp")
        retrieved = store.get(job.scan_id)
        assert retrieved is not None
        assert retrieved.scan_id == job.scan_id

    def test_get_returns_none_for_unknown_id(self, store):
        assert store.get("scan-doesnotexist") is None

    def test_get_returns_none_for_empty_string(self, store):
        assert store.get("") is None

    def test_get_preserves_tenant_id(self, store):
        job = store.create("pinnacle-partners")
        retrieved = store.get(job.scan_id)
        assert retrieved.tenant_id == "pinnacle-partners"

    def test_get_multiple_jobs_independent(self, store):
        job_a = store.create("tenant-a")
        job_b = store.create("tenant-b")
        assert store.get(job_a.scan_id).tenant_id == "tenant-a"
        assert store.get(job_b.scan_id).tenant_id == "tenant-b"


# ─────────────────────────────────────────────────────────────────────────────
# MARK RUNNING
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkRunning:

    def test_mark_running_changes_status(self, store):
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        updated = store.get(job.scan_id)
        assert updated.status == ScanStatus.RUNNING

    def test_mark_running_sets_started_at(self, store):
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        updated = store.get(job.scan_id)
        assert updated.started_at is not None

    def test_mark_running_preserves_tenant_id(self, store):
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        updated = store.get(job.scan_id)
        assert updated.tenant_id == "acme-corp"

    def test_mark_running_noop_for_unknown_id(self, store):
        # Should not raise
        store.mark_running("scan-doesnotexist")

    def test_mark_running_does_not_set_completed_at(self, store):
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        updated = store.get(job.scan_id)
        assert updated.completed_at is None


# ─────────────────────────────────────────────────────────────────────────────
# MARK COMPLETED
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkCompleted:

    def test_mark_completed_changes_status(self, store):
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        store.mark_completed(job.scan_id, _make_result())
        updated = store.get(job.scan_id)
        assert updated.status == ScanStatus.COMPLETED

    def test_mark_completed_sets_completed_at(self, store):
        job = store.create("acme-corp")
        store.mark_completed(job.scan_id, _make_result())
        updated = store.get(job.scan_id)
        assert updated.completed_at is not None

    def test_mark_completed_stores_result(self, store):
        job = store.create("acme-corp")
        result = _make_result(persons_merged=99)
        store.mark_completed(job.scan_id, result)
        updated = store.get(job.scan_id)
        assert updated.result is not None
        assert updated.result.persons_merged == 99

    def test_mark_completed_result_has_correct_records(self, store):
        job = store.create("acme-corp")
        result = _make_result(records_extracted=500, records_normalized=490)
        store.mark_completed(job.scan_id, result)
        updated = store.get(job.scan_id)
        assert updated.result.records_extracted == 500
        assert updated.result.records_normalized == 490

    def test_mark_completed_clears_error_message(self, store):
        job = store.create("acme-corp")
        store.mark_completed(job.scan_id, _make_result())
        updated = store.get(job.scan_id)
        assert updated.error_message is None

    def test_mark_completed_noop_for_unknown_id(self, store):
        store.mark_completed("scan-doesnotexist", _make_result())  # no raise


# ─────────────────────────────────────────────────────────────────────────────
# MARK FAILED
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkFailed:

    def test_mark_failed_changes_status(self, store):
        job = store.create("acme-corp")
        store.mark_running(job.scan_id)
        store.mark_failed(job.scan_id, "Connection refused")
        updated = store.get(job.scan_id)
        assert updated.status == ScanStatus.FAILED

    def test_mark_failed_stores_error_message(self, store):
        job = store.create("acme-corp")
        store.mark_failed(job.scan_id, "Neo4j timeout")
        updated = store.get(job.scan_id)
        assert updated.error_message == "Neo4j timeout"

    def test_mark_failed_sets_completed_at(self, store):
        job = store.create("acme-corp")
        store.mark_failed(job.scan_id, "error")
        updated = store.get(job.scan_id)
        assert updated.completed_at is not None

    def test_mark_failed_result_is_none(self, store):
        job = store.create("acme-corp")
        store.mark_failed(job.scan_id, "error")
        updated = store.get(job.scan_id)
        assert updated.result is None

    def test_mark_failed_noop_for_unknown_id(self, store):
        store.mark_failed("scan-doesnotexist", "error")  # no raise


# ─────────────────────────────────────────────────────────────────────────────
# LIST ALL
# ─────────────────────────────────────────────────────────────────────────────

class TestListAll:

    def test_list_all_empty_store_returns_empty(self, store):
        assert store.list_all() == []

    def test_list_all_returns_all_jobs(self, store):
        store.create("tenant-a")
        store.create("tenant-b")
        store.create("tenant-c")
        assert len(store.list_all()) == 3

    def test_list_all_sorted_most_recent_first(self, store):
        job_a = store.create("tenant-a")
        time.sleep(0.01)  # ensure distinct timestamps
        job_b = store.create("tenant-b")
        jobs = store.list_all()
        # Most recent (job_b) should be first
        assert jobs[0].scan_id == job_b.scan_id
        assert jobs[1].scan_id == job_a.scan_id

    def test_list_all_includes_completed_jobs(self, store):
        job = store.create("tenant-a")
        store.mark_completed(job.scan_id, _make_result())
        jobs = store.list_all()
        statuses = {j.status for j in jobs}
        assert ScanStatus.COMPLETED in statuses

    def test_list_all_includes_failed_jobs(self, store):
        job = store.create("tenant-a")
        store.mark_failed(job.scan_id, "error")
        jobs = store.list_all()
        statuses = {j.status for j in jobs}
        assert ScanStatus.FAILED in statuses

    def test_list_all_returns_copy_not_reference(self, store):
        """Mutating the returned list should not corrupt the store."""
        store.create("tenant-a")
        jobs = store.list_all()
        jobs.clear()
        assert len(store.list_all()) == 1


# ─────────────────────────────────────────────────────────────────────────────
# STATE MACHINE TRANSITIONS
# ─────────────────────────────────────────────────────────────────────────────

class TestStateMachineTransitions:

    def test_full_success_lifecycle(self, store):
        job = store.create("acme-corp")
        assert store.get(job.scan_id).status == ScanStatus.QUEUED

        store.mark_running(job.scan_id)
        assert store.get(job.scan_id).status == ScanStatus.RUNNING

        store.mark_completed(job.scan_id, _make_result())
        assert store.get(job.scan_id).status == ScanStatus.COMPLETED

    def test_full_failure_lifecycle(self, store):
        job = store.create("acme-corp")
        assert store.get(job.scan_id).status == ScanStatus.QUEUED

        store.mark_running(job.scan_id)
        assert store.get(job.scan_id).status == ScanStatus.RUNNING

        store.mark_failed(job.scan_id, "Pipeline crashed")
        assert store.get(job.scan_id).status == ScanStatus.FAILED

    def test_two_jobs_independent_state(self, store):
        job_a = store.create("tenant-a")
        job_b = store.create("tenant-b")

        store.mark_running(job_a.scan_id)
        store.mark_completed(job_a.scan_id, _make_result())

        # job_b should still be QUEUED
        assert store.get(job_b.scan_id).status == ScanStatus.QUEUED
        # job_a should be COMPLETED
        assert store.get(job_a.scan_id).status == ScanStatus.COMPLETED


# ─────────────────────────────────────────────────────────────────────────────
# THREAD SAFETY
# ─────────────────────────────────────────────────────────────────────────────

class TestThreadSafety:

    def test_concurrent_creates_all_unique(self, store):
        """50 threads each create a job — all scan_ids must be unique."""
        scan_ids = []
        lock = threading.Lock()

        def create():
            job = store.create("tenant-concurrent")
            with lock:
                scan_ids.append(job.scan_id)

        threads = [threading.Thread(target=create) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(scan_ids) == 50
        assert len(set(scan_ids)) == 50  # all unique

    def test_concurrent_state_transitions_no_corruption(self, store):
        """Two threads driving separate jobs through lifecycle simultaneously."""
        job_a = store.create("tenant-a")
        job_b = store.create("tenant-b")
        errors = []

        def drive_job_a():
            try:
                store.mark_running(job_a.scan_id)
                store.mark_completed(job_a.scan_id, _make_result(persons_merged=10))
            except Exception as e:
                errors.append(str(e))

        def drive_job_b():
            try:
                store.mark_running(job_b.scan_id)
                store.mark_failed(job_b.scan_id, "b failed")
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=drive_job_a)
        t2 = threading.Thread(target=drive_job_b)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert errors == []
        assert store.get(job_a.scan_id).status == ScanStatus.COMPLETED
        assert store.get(job_b.scan_id).status == ScanStatus.FAILED
