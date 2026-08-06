"""Tests for the WorkforceWorker."""

import time
import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.workers.base import Severity


@pytest.fixture(scope="module")
def seeded_driver():
    """Run a scan to seed the graph, then return a Neo4j driver for workers."""
    from neo4j import GraphDatabase
    from scout.config import settings

    # Seed via the API (same as production)
    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "workforce-test"})
    scan_id = post.json()["scan_id"]

    deadline = time.time() + 30
    while time.time() < deadline:
        data = client.get(f"/scans/{scan_id}").json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert data["status"] == "completed"

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    yield driver
    driver.close()


class TestWorkforceWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        worker = WorkforceWorker(seeded_driver)
        result = worker.run("workforce-test")
        assert result is not None
        assert result.worker_name == "WorkforceWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        assert result.error is None

    def test_has_findings(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        assert len(result.findings) > 0

    def test_summary_stats_populated(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        assert "total_headcount" in result.summary_stats
        assert result.summary_stats["total_headcount"] > 0

    def test_findings_have_required_fields(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        for finding in result.findings:
            assert finding.title
            assert finding.detail
            assert isinstance(finding.severity, Severity)

    def test_severity_values_are_valid(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        valid = set(Severity)
        for finding in result.findings:
            assert finding.severity in valid

    def test_to_dict_serialisable(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        import json
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        d = result.to_dict()
        # Must be JSON-serialisable (no datetime objects, no custom types)
        json.dumps(d)

    def test_manager_count_in_stats(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        assert "manager_count" in result.summary_stats
        assert result.summary_stats["manager_count"] > 0

    def test_critical_and_high_counts(self, seeded_driver):
        from scout.workers.workforce import WorkforceWorker
        result = WorkforceWorker(seeded_driver).run("workforce-test")
        # Counts must be non-negative integers
        assert result.critical_count >= 0
        assert result.high_count >= 0


class TestVendorWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.vendor import VendorWorker
        result = VendorWorker(seeded_driver).run("workforce-test")
        assert result.worker_name == "VendorWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.vendor import VendorWorker
        result = VendorWorker(seeded_driver).run("workforce-test")
        assert result.error is None

    def test_has_findings(self, seeded_driver):
        from scout.workers.vendor import VendorWorker
        result = VendorWorker(seeded_driver).run("workforce-test")
        assert len(result.findings) > 0

    def test_total_spend_in_stats(self, seeded_driver):
        from scout.workers.vendor import VendorWorker
        result = VendorWorker(seeded_driver).run("workforce-test")
        assert "total_annual_vendor_spend" in result.summary_stats
        assert result.summary_stats["total_annual_vendor_spend"] > 0

    def test_renewal_findings_have_data(self, seeded_driver):
        from scout.workers.vendor import VendorWorker
        result = VendorWorker(seeded_driver).run("workforce-test")
        # Any renewal finding must have data attached
        for f in result.findings:
            if "renew" in f.title.lower():
                assert f.data  # data dict is not empty
