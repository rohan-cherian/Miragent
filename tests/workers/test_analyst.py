"""Tests for the AIAnalyst and InsightMemo."""

import pytest
from scout.workers.analyst import AIAnalyst, InsightMemo
from scout.workers.base import Finding, Severity, WorkerResult


def make_result(worker_name: str, findings: list[Finding] | None = None) -> WorkerResult:
    r = WorkerResult(worker_name=worker_name, tenant_id="test-tenant")
    r.summary_stats = {"total_headcount": 14, "vendor_count": 12}
    r.findings = findings or [
        Finding(
            title="3 managers are overloaded",
            detail="Elena, James, Sarah each have >10 reports",
            severity=Severity.HIGH,
            data={"overloaded": 3},
            recommended_action="Review org design",
        ),
        Finding(
            title="$890k AWS spend — 46% of vendor budget",
            detail="High spend concentration in Cloud Infrastructure",
            severity=Severity.HIGH,
            data={"vendor": "AWS", "pct": 46},
        ),
    ]
    return r


class TestAIAnalyst:

    def test_analyst_instantiates(self):
        analyst = AIAnalyst()
        assert analyst is not None

    def test_generate_memo_returns_memo(self):
        analyst = AIAnalyst()
        results = [make_result("WorkforceWorker"), make_result("VendorWorker")]
        memo = analyst.generate_memo("test-tenant", results)
        assert isinstance(memo, InsightMemo)

    def test_memo_has_narrative(self):
        analyst = AIAnalyst()
        results = [make_result("WorkforceWorker")]
        memo = analyst.generate_memo("test-tenant", results)
        assert memo.narrative
        assert len(memo.narrative) > 50  # not an empty string

    def test_memo_has_structured_data(self):
        analyst = AIAnalyst()
        results = [make_result("WorkforceWorker")]
        memo = analyst.generate_memo("test-tenant", results)
        assert "workers" in memo.structured
        assert "total_critical" in memo.structured
        assert "total_high" in memo.structured

    def test_memo_to_dict(self):
        import json
        analyst = AIAnalyst()
        results = [make_result("WorkforceWorker"), make_result("VendorWorker")]
        memo = analyst.generate_memo("test-tenant", results)
        d = memo.to_dict()
        assert "narrative" in d
        assert "structured" in d
        assert "ai_generated" in d
        # Must be JSON-serialisable
        json.dumps(d)

    def test_fallback_narrative_mentions_findings(self):
        """The fallback narrative (no API key) must mention findings."""
        analyst = AIAnalyst()
        analyst._client = None  # Force fallback mode
        results = [make_result("WorkforceWorker")]
        memo = analyst.generate_memo("test-tenant", results)
        assert "overloaded" in memo.narrative.lower() or "manager" in memo.narrative.lower()

    def test_total_counts_correct(self):
        """total_critical and total_high must sum findings correctly."""
        analyst = AIAnalyst()
        findings = [
            Finding("Critical thing", "detail", Severity.CRITICAL, {}),
            Finding("High thing 1", "detail", Severity.HIGH, {}),
            Finding("High thing 2", "detail", Severity.HIGH, {}),
            Finding("Low thing", "detail", Severity.LOW, {}),
        ]
        results = [make_result("WorkforceWorker", findings)]
        memo = analyst.generate_memo("test-tenant", results)
        assert memo.structured["total_critical"] == 1
        assert memo.structured["total_high"] == 2

    def test_empty_findings_handled_gracefully(self):
        """Analyst must handle workers that returned no findings."""
        analyst = AIAnalyst()
        empty_result = WorkerResult(worker_name="WorkforceWorker", tenant_id="test-tenant")
        memo = analyst.generate_memo("test-tenant", [empty_result])
        assert memo.narrative  # still produces output


class TestInsightsEndpoint:
    """Integration test: GET /insights against a seeded graph."""

    def test_insights_requires_tenant_id(self):
        import time
        from fastapi.testclient import TestClient
        from scout.api.app import create_app
        client = TestClient(create_app())
        resp = client.get("/insights")
        assert resp.status_code == 422

    def test_insights_returns_dict_with_narrative(self):
        import time
        from fastapi.testclient import TestClient
        from scout.api.app import create_app

        app = create_app()
        client = TestClient(app)

        # Seed the graph
        post = client.post("/scans", json={"tenant_id": "insights-test"})
        scan_id = post.json()["scan_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)
        assert data["status"] == "completed"

        # Now call insights
        resp = client.get("/insights", params={"tenant_id": "insights-test"})
        assert resp.status_code == 200
        body = resp.json()
        assert "narrative" in body
        assert "structured" in body
        assert len(body["narrative"]) > 100
