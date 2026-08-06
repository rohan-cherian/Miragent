"""
Tests for Sprint 4 Revenue Optimization Workers.

All tests use the seeded_driver fixture from test_workforce_worker.py
(runs a full scan to populate Neo4j before any worker runs).

Pattern:
  - One fixture seeds the graph (run once per module)
  - Each test class covers one worker
  - Tests verify: no error, findings produced, stats populated, serialisable
"""

import time
import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.workers.base import Severity


@pytest.fixture(scope="module")
def seeded_driver():
    """Run a scan to seed the graph with persons, accounts, and opportunities."""
    from neo4j import GraphDatabase
    from scout.config import settings

    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "revenue-test"})
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
class TestPipelineVelocityWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        result = PipelineVelocityWorker(seeded_driver).run("revenue-test")
        assert result is not None
        assert result.worker_name == "PipelineVelocityWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        result = PipelineVelocityWorker(seeded_driver).run("revenue-test")
        assert result.error is None

    def test_summary_stats_present(self, seeded_driver):
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        result = PipelineVelocityWorker(seeded_driver).run("revenue-test")
        assert "open_deals" in result.summary_stats
        assert "total_pipeline_value" in result.summary_stats
        assert result.summary_stats["open_deals"] >= 0

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        result = PipelineVelocityWorker(seeded_driver).run("revenue-test")
        valid = set(Severity)
        for f in result.findings:
            assert f.severity in valid

    def test_findings_have_title_and_detail(self, seeded_driver):
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        result = PipelineVelocityWorker(seeded_driver).run("revenue-test")
        for f in result.findings:
            assert f.title
            assert f.detail

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.pipeline_velocity import PipelineVelocityWorker
        result = PipelineVelocityWorker(seeded_driver).run("revenue-test")
        json.dumps(result.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestChurnPredictionWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.churn_prediction import ChurnPredictionWorker
        result = ChurnPredictionWorker(seeded_driver).run("revenue-test")
        assert result.worker_name == "ChurnPredictionWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.churn_prediction import ChurnPredictionWorker
        result = ChurnPredictionWorker(seeded_driver).run("revenue-test")
        assert result.error is None

    def test_summary_has_customer_count(self, seeded_driver):
        from scout.workers.churn_prediction import ChurnPredictionWorker
        result = ChurnPredictionWorker(seeded_driver).run("revenue-test")
        assert "total_customers" in result.summary_stats
        assert result.summary_stats["total_customers"] >= 0

    def test_at_risk_accounts_is_non_negative(self, seeded_driver):
        from scout.workers.churn_prediction import ChurnPredictionWorker
        result = ChurnPredictionWorker(seeded_driver).run("revenue-test")
        assert result.summary_stats.get("at_risk_accounts", 0) >= 0

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.churn_prediction import ChurnPredictionWorker
        result = ChurnPredictionWorker(seeded_driver).run("revenue-test")
        json.dumps(result.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestExpansionRevenueWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.expansion_revenue import ExpansionRevenueWorker
        result = ExpansionRevenueWorker(seeded_driver).run("revenue-test")
        assert result.worker_name == "ExpansionRevenueWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.expansion_revenue import ExpansionRevenueWorker
        result = ExpansionRevenueWorker(seeded_driver).run("revenue-test")
        assert result.error is None

    def test_summary_has_won_deal_count(self, seeded_driver):
        from scout.workers.expansion_revenue import ExpansionRevenueWorker
        result = ExpansionRevenueWorker(seeded_driver).run("revenue-test")
        assert "total_customers_with_won_deals" in result.summary_stats

    def test_expansion_candidates_count_in_stats(self, seeded_driver):
        from scout.workers.expansion_revenue import ExpansionRevenueWorker
        result = ExpansionRevenueWorker(seeded_driver).run("revenue-test")
        assert "expansion_candidates" in result.summary_stats
        assert result.summary_stats["expansion_candidates"] >= 0

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.expansion_revenue import ExpansionRevenueWorker
        result = ExpansionRevenueWorker(seeded_driver).run("revenue-test")
        json.dumps(result.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestPricingIntegrityWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.pricing_integrity import PricingIntegrityWorker
        result = PricingIntegrityWorker(seeded_driver).run("revenue-test")
        assert result.worker_name == "PricingIntegrityWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.pricing_integrity import PricingIntegrityWorker
        result = PricingIntegrityWorker(seeded_driver).run("revenue-test")
        assert result.error is None

    def test_summary_has_acv_stats(self, seeded_driver):
        from scout.workers.pricing_integrity import PricingIntegrityWorker
        result = PricingIntegrityWorker(seeded_driver).run("revenue-test")
        assert "mean_acv" in result.summary_stats
        assert "median_acv" in result.summary_stats

    def test_acv_stats_are_non_negative(self, seeded_driver):
        from scout.workers.pricing_integrity import PricingIntegrityWorker
        result = PricingIntegrityWorker(seeded_driver).run("revenue-test")
        assert result.summary_stats.get("mean_acv", 0) >= 0
        assert result.summary_stats.get("median_acv", 0) >= 0

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.pricing_integrity import PricingIntegrityWorker
        result = PricingIntegrityWorker(seeded_driver).run("revenue-test")
        json.dumps(result.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestSalesCapacityWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.sales_capacity import SalesCapacityWorker
        result = SalesCapacityWorker(seeded_driver).run("revenue-test")
        assert result.worker_name == "SalesCapacityWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.sales_capacity import SalesCapacityWorker
        result = SalesCapacityWorker(seeded_driver).run("revenue-test")
        assert result.error is None

    def test_summary_has_rep_counts(self, seeded_driver):
        from scout.workers.sales_capacity import SalesCapacityWorker
        result = SalesCapacityWorker(seeded_driver).run("revenue-test")
        assert "total_sales_reps" in result.summary_stats
        assert "active_reps" in result.summary_stats
        assert "idle_reps" in result.summary_stats

    def test_rep_counts_add_up(self, seeded_driver):
        from scout.workers.sales_capacity import SalesCapacityWorker
        result = SalesCapacityWorker(seeded_driver).run("revenue-test")
        total = result.summary_stats.get("total_sales_reps", 0)
        active = result.summary_stats.get("active_reps", 0)
        idle = result.summary_stats.get("idle_reps", 0)
        assert active + idle == total

    def test_total_pipeline_non_negative(self, seeded_driver):
        from scout.workers.sales_capacity import SalesCapacityWorker
        result = SalesCapacityWorker(seeded_driver).run("revenue-test")
        assert result.summary_stats.get("total_open_pipeline", 0) >= 0

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.sales_capacity import SalesCapacityWorker
        result = SalesCapacityWorker(seeded_driver).run("revenue-test")
        json.dumps(result.to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestInsightsEndpointWithRevenueWorkers:
    """Integration test: GET /insights includes all 7 workers now."""

    def test_insights_returns_all_workers(self):
        import time
        from fastapi.testclient import TestClient
        from scout.api.app import create_app

        app = create_app()
        client = TestClient(app)

        post = client.post("/scans", json={"tenant_id": "insights-revenue-test"})
        scan_id = post.json()["scan_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert data["status"] == "completed"

        resp = client.get("/insights", params={"tenant_id": "insights-revenue-test"})
        assert resp.status_code == 200
        body = resp.json()
        assert "narrative" in body
        assert "structured" in body

        workers_in_response = [w["worker"] for w in body["structured"].get("workers", [])]
        # Sprint 4 workers should all appear
        for expected in ["PipelineVelocityWorker", "ChurnPredictionWorker",
                         "ExpansionRevenueWorker", "PricingIntegrityWorker",
                         "SalesCapacityWorker"]:
            assert expected in workers_in_response, f"{expected} missing from /insights response"
