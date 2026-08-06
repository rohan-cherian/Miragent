"""
tests/workers/test_vendor_benchmark_worker.py — Tests for VendorBenchmarkWorker (Sprint 18)

All tests run against a real Neo4j instance seeded via the mock connector scan.
The seeded_driver fixture is module-scoped to avoid redundant scans.

Run with:
    poetry run python -m pytest tests/workers/test_vendor_benchmark_worker.py -v
"""

import time

import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.workers.base import Severity


REQUIRED_SUMMARY_KEYS = {
    "total_vendors_analyzed",
    "vendors_enriched",
    "vendors_overpaying",
    "total_potential_savings",
    "vendors_in_negotiation_window",
    "total_spend_benchmarked",
}


@pytest.fixture(scope="module")
def seeded_driver():
    """Seed the graph with the mock connector and return a live Neo4j driver."""
    from neo4j import GraphDatabase
    from scout.config import settings

    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "vendor-benchmark-test"})
    scan_id = post.json()["scan_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        data = client.get(f"/scans/{scan_id}").json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert data["status"] == "completed", f"Scan failed: {data}"

    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    yield driver
    driver.close()


# ─────────────────────────────────────────────────────────────────────────────
class TestVendorBenchmarkWorker:

    def _run(self, seeded_driver):
        from scout.workers.vendor_benchmark import VendorBenchmarkWorker
        return VendorBenchmarkWorker(seeded_driver).run("vendor-benchmark-test")

    def test_run_returns_result(self, seeded_driver):
        result = self._run(seeded_driver)
        assert result.worker_name == "VendorBenchmarkWorker"

    def test_no_error(self, seeded_driver):
        result = self._run(seeded_driver)
        assert result.error is None

    def test_summary_has_required_keys(self, seeded_driver):
        result = self._run(seeded_driver)
        for key in REQUIRED_SUMMARY_KEYS:
            assert key in result.summary_stats, f"Missing summary key: {key}"

    def test_total_vendors_analyzed_positive(self, seeded_driver):
        result = self._run(seeded_driver)
        assert result.summary_stats["total_vendors_analyzed"] > 0

    def test_potential_savings_non_negative(self, seeded_driver):
        result = self._run(seeded_driver)
        assert result.summary_stats["total_potential_savings"] >= 0

    def test_vendors_enriched_lte_total(self, seeded_driver):
        result = self._run(seeded_driver)
        assert result.summary_stats["vendors_enriched"] <= result.summary_stats["total_vendors_analyzed"]

    def test_has_findings(self, seeded_driver):
        result = self._run(seeded_driver)
        assert len(result.findings) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        result = self._run(seeded_driver)
        valid_severities = set(Severity)
        for finding in result.findings:
            assert finding.severity in valid_severities, (
                f"Invalid severity {finding.severity!r} in finding: {finding.title}"
            )

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        result = self._run(seeded_driver)
        # Should not raise
        json.dumps(result.to_dict())

    def test_enrichment_window_count_non_negative(self, seeded_driver):
        result = self._run(seeded_driver)
        assert result.summary_stats["vendors_in_negotiation_window"] >= 0
