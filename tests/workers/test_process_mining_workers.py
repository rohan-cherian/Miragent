"""Tests for Sprint 7 Process Mining Workers."""

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

    post = client.post("/scans", json={"tenant_id": "pm-test"})
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
class TestLeadToCashWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        result = LeadToCashWorker(seeded_driver).run("pm-test")
        assert result.worker_name == "LeadToCashWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        assert LeadToCashWorker(seeded_driver).run("pm-test").error is None

    def test_summary_has_pipeline_metrics(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        stats = LeadToCashWorker(seeded_driver).run("pm-test").summary_stats
        assert "total_pipeline_deals" in stats
        assert "won_deals" in stats
        assert "lost_deals" in stats
        assert "open_deals" in stats
        assert "recognition_rate_pct" in stats

    def test_recognition_rate_is_percentage(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        stats = LeadToCashWorker(seeded_driver).run("pm-test").summary_stats
        assert 0 <= stats.get("recognition_rate_pct", 0) <= 100

    def test_has_findings(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        assert len(LeadToCashWorker(seeded_driver).run("pm-test").findings) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        for f in LeadToCashWorker(seeded_driver).run("pm-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.lead_to_cash import LeadToCashWorker
        json.dumps(LeadToCashWorker(seeded_driver).run("pm-test").to_dict())

    def test_won_plus_lost_plus_open_equals_total(self, seeded_driver):
        from scout.workers.lead_to_cash import LeadToCashWorker
        stats = LeadToCashWorker(seeded_driver).run("pm-test").summary_stats
        total = stats.get("total_pipeline_deals", 0)
        won = stats.get("won_deals", 0)
        lost = stats.get("lost_deals", 0)
        open_deals = stats.get("open_deals", 0)
        assert won + lost + open_deals == total


# ─────────────────────────────────────────────────────────────────────────────
class TestHireToRetireWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        result = HireToRetireWorker(seeded_driver).run("pm-test")
        assert result.worker_name == "HireToRetireWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        assert HireToRetireWorker(seeded_driver).run("pm-test").error is None

    def test_summary_has_headcount_metrics(self, seeded_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        stats = HireToRetireWorker(seeded_driver).run("pm-test").summary_stats
        assert "total_headcount" in stats
        assert "active_headcount" in stats
        assert "inactive_headcount" in stats
        assert "inactive_rate_pct" in stats

    def test_active_plus_inactive_equals_total(self, seeded_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        stats = HireToRetireWorker(seeded_driver).run("pm-test").summary_stats
        assert stats.get("active_headcount", 0) + stats.get("inactive_headcount", 0) == stats.get("total_headcount", 0)

    def test_inactive_rate_is_percentage(self, seeded_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        stats = HireToRetireWorker(seeded_driver).run("pm-test").summary_stats
        assert 0 <= stats.get("inactive_rate_pct", 0) <= 100

    def test_has_findings(self, seeded_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        assert len(HireToRetireWorker(seeded_driver).run("pm-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.hire_to_retire import HireToRetireWorker
        json.dumps(HireToRetireWorker(seeded_driver).run("pm-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestProcureToPayWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.procure_to_pay import ProcureToPayWorker
        result = ProcureToPayWorker(seeded_driver).run("pm-test")
        assert result.worker_name == "ProcureToPayWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.procure_to_pay import ProcureToPayWorker
        assert ProcureToPayWorker(seeded_driver).run("pm-test").error is None

    def test_summary_has_vendor_metrics(self, seeded_driver):
        from scout.workers.procure_to_pay import ProcureToPayWorker
        stats = ProcureToPayWorker(seeded_driver).run("pm-test").summary_stats
        assert "total_vendors" in stats
        assert "total_annual_spend" in stats
        assert "unmanaged_vendors" in stats

    def test_spend_non_negative(self, seeded_driver):
        from scout.workers.procure_to_pay import ProcureToPayWorker
        stats = ProcureToPayWorker(seeded_driver).run("pm-test").summary_stats
        assert stats.get("total_annual_spend", 0) >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.procure_to_pay import ProcureToPayWorker
        assert len(ProcureToPayWorker(seeded_driver).run("pm-test").findings) >= 1

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.procure_to_pay import ProcureToPayWorker
        json.dumps(ProcureToPayWorker(seeded_driver).run("pm-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestIssueToResolutionWorker:

    def test_run_returns_result(self, seeded_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        result = IssueToResolutionWorker(seeded_driver).run("pm-test")
        assert result.worker_name == "IssueToResolutionWorker"

    def test_no_error(self, seeded_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        assert IssueToResolutionWorker(seeded_driver).run("pm-test").error is None

    def test_summary_has_issue_metrics(self, seeded_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        stats = IssueToResolutionWorker(seeded_driver).run("pm-test").summary_stats
        assert "open_issues_proxy" in stats
        assert "stalled_deals" in stats
        assert "resolution_rate_proxy" in stats

    def test_stalled_deals_non_negative(self, seeded_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        stats = IssueToResolutionWorker(seeded_driver).run("pm-test").summary_stats
        assert stats.get("stalled_deals", 0) >= 0

    def test_has_findings(self, seeded_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        assert len(IssueToResolutionWorker(seeded_driver).run("pm-test").findings) >= 1

    def test_findings_have_valid_severity(self, seeded_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        for f in IssueToResolutionWorker(seeded_driver).run("pm-test").findings:
            assert f.severity in set(Severity)

    def test_to_dict_serialisable(self, seeded_driver):
        import json
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        json.dumps(IssueToResolutionWorker(seeded_driver).run("pm-test").to_dict())


# ─────────────────────────────────────────────────────────────────────────────
class TestInsightsEndpointWith26Workers:
    """GET /insights now runs all 26 workers."""

    def test_all_sprint7_workers_present(self):
        from fastapi.testclient import TestClient
        from scout.api.app import create_app

        app = create_app()
        client = TestClient(app)

        post = client.post("/scans", json={"tenant_id": "insights-s7-test"})
        scan_id = post.json()["scan_id"]
        deadline = time.time() + 45
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert data["status"] == "completed"

        resp = client.get("/insights", params={"tenant_id": "insights-s7-test"})
        assert resp.status_code == 200
        body = resp.json()

        workers_in_response = [w["worker"] for w in body["structured"].get("workers", [])]
        for expected in [
            "LeadToCashWorker", "HireToRetireWorker",
            "ProcureToPayWorker", "IssueToResolutionWorker",
        ]:
            assert expected in workers_in_response, f"{expected} missing from /insights"

        # Total should be 32 workers (Sprints 3-18)
        assert len(workers_in_response) == 36, (
            f"Expected 36 workers, got {len(workers_in_response)}: {workers_in_response}"
        )
