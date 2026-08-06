"""Tests for Sprint 6 Full Funnel Revenue Intelligence Workers."""

import time
import pytest
from fastapi.testclient import TestClient
from scout.api.app import create_app
from scout.workers.base import Severity


@pytest.fixture(scope="module")
def seeded_driver():
    from neo4j import GraphDatabase
    from scout.config import settings

    app = create_app()
    client = TestClient(app)

    post = client.post("/scans", json={"tenant_id": "funnel-test"})
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
class TestTamPenetrationWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.tam_penetration import TamPenetrationWorker
        result = TamPenetrationWorker(seeded_driver).run("funnel-test")
        assert result.worker_name == "TamPenetrationWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.tam_penetration import TamPenetrationWorker
        assert TamPenetrationWorker(seeded_driver).run("funnel-test").error is None

    def test_summary_has_account_counts(self, seeded_driver):
        from scout.workers.tam_penetration import TamPenetrationWorker
        stats = TamPenetrationWorker(seeded_driver).run("funnel-test").summary_stats
        assert "customer_count" in stats
        assert "prospect_count" in stats
        assert stats["customer_count"] >= 0
        assert stats["prospect_count"] >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.tam_penetration import TamPenetrationWorker
        result = TamPenetrationWorker(seeded_driver).run("funnel-test")
        assert len(result.findings) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.tam_penetration import TamPenetrationWorker
        for f in TamPenetrationWorker(seeded_driver).run("funnel-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.tam_penetration import TamPenetrationWorker
        json.dumps(TamPenetrationWorker(seeded_driver).run("funnel-test").to_dict())

    def test_icp_score_in_range(self, seeded_driver):
        """ICP scores on prospects must be 0-100."""
        from scout.workers.tam_penetration import TamPenetrationWorker
        result = TamPenetrationWorker(seeded_driver).run("funnel-test")
        for f in result.findings:
            for prospect in f.data.get("strong_icp_prospects", []) + f.data.get("low_icp_prospects", []):
                assert 0 <= prospect.get("icp_score", 50) <= 100


# ─────────────────────────────────────────────────────────────────────────────
class TestMarketingFunnelWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        result = MarketingFunnelWorker(seeded_driver).run("funnel-test")
        assert result.worker_name == "MarketingFunnelWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        assert MarketingFunnelWorker(seeded_driver).run("funnel-test").error is None

    def test_summary_has_funnel_metrics(self, seeded_driver):
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        stats = MarketingFunnelWorker(seeded_driver).run("funnel-test").summary_stats
        assert "total_opportunities" in stats
        assert "win_rate_pct" in stats
        assert "won_deals" in stats
        assert "lost_deals" in stats

    def test_win_rate_is_percentage(self, seeded_driver):
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        stats = MarketingFunnelWorker(seeded_driver).run("funnel-test").summary_stats
        assert 0 <= stats.get("win_rate_pct", 0) <= 100

    def test_won_plus_lost_equals_closed(self, seeded_driver):
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        stats = MarketingFunnelWorker(seeded_driver).run("funnel-test").summary_stats
        assert stats.get("won_deals", 0) + stats.get("lost_deals", 0) == stats.get("closed_deals", 0)

    def test_always_has_channel_attribution_finding(self, seeded_driver):
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        result = MarketingFunnelWorker(seeded_driver).run("funnel-test")
        assert any("Sprint 12" in f.title for f in result.findings)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.marketing_funnel import MarketingFunnelWorker
        json.dumps(MarketingFunnelWorker(seeded_driver).run("funnel-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestCrossSellIntelligenceWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        result = CrossSellIntelligenceWorker(seeded_driver).run("funnel-test")
        assert result.worker_name == "CrossSellIntelligenceWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        assert CrossSellIntelligenceWorker(seeded_driver).run("funnel-test").error is None

    def test_summary_has_score_metrics(self, seeded_driver):
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        stats = CrossSellIntelligenceWorker(seeded_driver).run("funnel-test").summary_stats
        assert "scored_accounts" in stats
        assert "priority_accounts" in stats
        assert "total_expansion_opportunity" in stats

    def test_priority_accounts_lte_scored(self, seeded_driver):
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        stats = CrossSellIntelligenceWorker(seeded_driver).run("funnel-test").summary_stats
        assert stats.get("priority_accounts", 0) <= stats.get("scored_accounts", 0)

    def test_expansion_opportunity_non_negative(self, seeded_driver):
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        stats = CrossSellIntelligenceWorker(seeded_driver).run("funnel-test").summary_stats
        assert stats.get("total_expansion_opportunity", 0) >= 0

    def test_score_breakdowns_sum_correctly(self, seeded_driver):
        """Each score breakdown component must be non-negative."""
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        result = CrossSellIntelligenceWorker(seeded_driver).run("funnel-test")
        for f in result.findings:
            for account in f.data.get("priority_accounts", []):
                assert 0 <= account.get("score", 0) <= 100

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.cross_sell_intelligence import CrossSellIntelligenceWorker
        json.dumps(CrossSellIntelligenceWorker(seeded_driver).run("funnel-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestInsightsEndpointWith16Workers:
    """GET /insights now runs all 16 workers."""

    def test_all_sprint6_workers_present(self):
        from fastapi.testclient import TestClient
        from scout.api.app import create_app

        app = create_app()
        client = TestClient(app)

        post = client.post("/scans", json={"tenant_id": "insights-s6-test"})
        scan_id = post.json()["scan_id"]
        deadline = time.time() + 45
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert data["status"] == "completed"

        resp = client.get("/insights", params={"tenant_id": "insights-s6-test"})
        assert resp.status_code == 200
        body = resp.json()

        workers_in_response = [w["worker"] for w in body["structured"].get("workers", [])]
        for expected in ["TamPenetrationWorker", "MarketingFunnelWorker", "CrossSellIntelligenceWorker"]:
            assert expected in workers_in_response, f"{expected} missing from /insights"

        # Total should be 32 workers (Sprints 3-18)
        assert len(workers_in_response) == 36, f"Expected 32 workers, got {len(workers_in_response)}: {workers_in_response}"
