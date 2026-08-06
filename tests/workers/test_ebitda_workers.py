"""
Tests for Sprint 5 EBITDA Optimization Workers.

Pattern matches Sprint 4 tests: one seeded_driver fixture, one class
per worker, standard assertions: no error, stats populated, serialisable.
"""

import time
import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.workers.base import Severity


@pytest.fixture(scope="module")
def seeded_driver():
    """Run a scan to seed the graph before any worker runs."""
    from neo4j import GraphDatabase
    from scout.config import settings

    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "ebitda-test"})
    scan_id = post.json()["scan_id"]

    deadline = time.time() + 30
    while time.time() < deadline:
        data = client.get(f"/scans/{scan_id}").json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert data["status"] == "completed", f"Scan failed: {data}"

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    yield driver
    driver.close()


# ─────────────────────────────────────────────────────────────────────────────
class TestSaasLicenseWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.saas_license import SaasLicenseWorker
        result = SaasLicenseWorker(seeded_driver).run("ebitda-test")
        assert result.worker_name == "SaasLicenseWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.saas_license import SaasLicenseWorker
        assert SaasLicenseWorker(seeded_driver).run("ebitda-test").error is None

    def test_summary_stats_present(self, seeded_driver):
        from scout.workers.saas_license import SaasLicenseWorker
        stats = SaasLicenseWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "total_headcount" in stats
        assert "software_vendor_count" in stats
        assert "estimated_zombie_license_cost" in stats

    def test_zombie_cost_non_negative(self, seeded_driver):
        from scout.workers.saas_license import SaasLicenseWorker
        stats = SaasLicenseWorker(seeded_driver).run("ebitda-test").summary_stats
        assert stats.get("estimated_zombie_license_cost", 0) >= 0

    def test_severity_values_valid(self, seeded_driver):
        from scout.workers.saas_license import SaasLicenseWorker
        for f in SaasLicenseWorker(seeded_driver).run("ebitda-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.saas_license import SaasLicenseWorker
        json.dumps(SaasLicenseWorker(seeded_driver).run("ebitda-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestVendorNegotiationWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.vendor_negotiation import VendorNegotiationWorker
        result = VendorNegotiationWorker(seeded_driver).run("ebitda-test")
        assert result.worker_name == "VendorNegotiationWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.vendor_negotiation import VendorNegotiationWorker
        assert VendorNegotiationWorker(seeded_driver).run("ebitda-test").error is None

    def test_summary_has_renewal_count(self, seeded_driver):
        from scout.workers.vendor_negotiation import VendorNegotiationWorker
        stats = VendorNegotiationWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "renewals_in_90_days" in stats
        assert "estimated_negotiation_savings" in stats

    def test_estimated_savings_non_negative(self, seeded_driver):
        from scout.workers.vendor_negotiation import VendorNegotiationWorker
        stats = VendorNegotiationWorker(seeded_driver).run("ebitda-test").summary_stats
        assert stats.get("estimated_negotiation_savings", 0) >= 0

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.vendor_negotiation import VendorNegotiationWorker
        json.dumps(VendorNegotiationWorker(seeded_driver).run("ebitda-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestHeadcountEfficiencyWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
        result = HeadcountEfficiencyWorker(seeded_driver).run("ebitda-test")
        assert result.worker_name == "HeadcountEfficiencyWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
        assert HeadcountEfficiencyWorker(seeded_driver).run("ebitda-test").error is None

    def test_summary_has_headcount_metrics(self, seeded_driver):
        from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
        stats = HeadcountEfficiencyWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "total_headcount" in stats
        assert "ga_ratio_pct" in stats
        assert "contractor_pct" in stats
        assert "management_overhead_pct" in stats

    def test_ratios_are_percentages(self, seeded_driver):
        from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
        stats = HeadcountEfficiencyWorker(seeded_driver).run("ebitda-test").summary_stats
        assert 0 <= stats.get("ga_ratio_pct", 0) <= 100
        assert 0 <= stats.get("contractor_pct", 0) <= 100
        assert 0 <= stats.get("management_overhead_pct", 0) <= 100

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.headcount_efficiency import HeadcountEfficiencyWorker
        json.dumps(HeadcountEfficiencyWorker(seeded_driver).run("ebitda-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestProcessBottleneckWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        result = ProcessBottleneckWorker(seeded_driver).run("ebitda-test")
        assert result.worker_name == "ProcessBottleneckWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        assert ProcessBottleneckWorker(seeded_driver).run("ebitda-test").error is None

    def test_summary_stats_present(self, seeded_driver):
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        stats = ProcessBottleneckWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "total_vendor_count" in stats
        assert "fragmented_process_categories" in stats

    def test_always_has_findings(self, seeded_driver):
        """ProcessBottleneckWorker always produces at least the Sprint-7 info finding."""
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        result = ProcessBottleneckWorker(seeded_driver).run("ebitda-test")
        assert len(result.findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        json.dumps(ProcessBottleneckWorker(seeded_driver).run("ebitda-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestWorkingCapitalWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.working_capital import WorkingCapitalWorker
        result = WorkingCapitalWorker(seeded_driver).run("ebitda-test")
        assert result.worker_name == "WorkingCapitalWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.working_capital import WorkingCapitalWorker
        assert WorkingCapitalWorker(seeded_driver).run("ebitda-test").error is None

    def test_summary_has_spend_metrics(self, seeded_driver):
        from scout.workers.working_capital import WorkingCapitalWorker
        stats = WorkingCapitalWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "total_vendor_spend" in stats
        assert "estimated_wc_improvement" in stats

    def test_wc_improvement_non_negative(self, seeded_driver):
        from scout.workers.working_capital import WorkingCapitalWorker
        stats = WorkingCapitalWorker(seeded_driver).run("ebitda-test").summary_stats
        assert stats.get("estimated_wc_improvement", 0) >= 0

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.working_capital import WorkingCapitalWorker
        json.dumps(WorkingCapitalWorker(seeded_driver).run("ebitda-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestSentimentWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.sentiment import SentimentWorker
        result = SentimentWorker(seeded_driver).run("ebitda-test")
        assert result.worker_name == "SentimentWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.sentiment import SentimentWorker
        assert SentimentWorker(seeded_driver).run("ebitda-test").error is None

    def test_summary_has_risk_score(self, seeded_driver):
        from scout.workers.sentiment import SentimentWorker
        stats = SentimentWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "attrition_risk_score" in stats
        assert 0 <= stats["attrition_risk_score"] <= 100

    def test_summary_has_headcount_and_sentiment_source(self, seeded_driver):
        from scout.workers.sentiment import SentimentWorker
        stats = SentimentWorker(seeded_driver).run("ebitda-test").summary_stats
        assert "total_headcount" in stats
        assert "sentiment_data_source" in stats
        assert stats["sentiment_data_source"] == "org_structure_proxy"

    def test_always_has_sprint8_finding(self, seeded_driver):
        """SentimentWorker always includes the Sprint 8 preview finding."""
        from scout.workers.sentiment import SentimentWorker
        result = SentimentWorker(seeded_driver).run("ebitda-test")
        titles = [f.title for f in result.findings]
        assert any("Sprint 8" in t for t in titles)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.sentiment import SentimentWorker
        json.dumps(SentimentWorker(seeded_driver).run("ebitda-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestInsightsEndpointWithAllWorkers:
    """Integration test: GET /insights now runs all 13 workers."""

    def test_insights_includes_ebitda_workers(self):
        from fastapi.testclient import TestClient
        from scout.api.app import create_app

        app = create_app()
        client = TestClient(app)

        post = client.post("/scans", json={"tenant_id": "insights-ebitda-test"})
        scan_id = post.json()["scan_id"]
        deadline = time.time() + 45
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert data["status"] == "completed"

        resp = client.get("/insights", params={"tenant_id": "insights-ebitda-test"})
        assert resp.status_code == 200
        body = resp.json()

        workers_in_response = [w["worker"] for w in body["structured"].get("workers", [])]
        for expected in ["SaasLicenseWorker", "VendorNegotiationWorker",
                         "HeadcountEfficiencyWorker", "ProcessBottleneckWorker",
                         "WorkingCapitalWorker", "SentimentWorker"]:
            assert expected in workers_in_response, f"{expected} missing from /insights"
