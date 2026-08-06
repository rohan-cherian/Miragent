"""Tests for GET /graph/* endpoints."""

import time
import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app


@pytest.fixture(scope="module")
def seeded_client():
    """
    Module-scoped fixture: runs a full scan once, then reuses the client
    for all graph tests. Seeding the graph takes ~5s; we only want to do it once.
    """
    app = create_app()
    client = TestClient(app, raise_server_exceptions=True)

    # Seed the graph with a full scan
    post_resp = client.post("/scans", json={"tenant_id": "graph-test-tenant"})
    scan_id = post_resp.json()["scan_id"]

    # Wait for completion
    deadline = time.time() + 30
    while time.time() < deadline:
        data = client.get(f"/scans/{scan_id}").json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)

    assert data["status"] == "completed", f"Seed scan failed: {data.get('error_message')}"
    return client


TENANT = "graph-test-tenant"


class TestOrgHierarchy:

    def test_org_hierarchy_returns_list(self, seeded_client):
        """GET /graph/org-hierarchy returns a list."""
        resp = seeded_client.get("/graph/org-hierarchy", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_org_hierarchy_has_records(self, seeded_client):
        """After seeding, the org hierarchy must have at least one MANAGES edge."""
        resp = seeded_client.get("/graph/org-hierarchy", params={"tenant_id": TENANT})
        data = resp.json()
        assert len(data) > 0

    def test_org_hierarchy_record_shape(self, seeded_client):
        """Each row must have manager and report fields."""
        resp = seeded_client.get("/graph/org-hierarchy", params={"tenant_id": TENANT})
        row = resp.json()[0]
        assert "manager" in row
        assert "report" in row

    def test_org_hierarchy_missing_tenant_returns_422(self, seeded_client):
        """tenant_id is required."""
        resp = seeded_client.get("/graph/org-hierarchy")
        assert resp.status_code == 422


class TestSpanOfControl:

    def test_span_returns_list(self, seeded_client):
        resp = seeded_client.get("/graph/span-of-control", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_span_has_records(self, seeded_client):
        resp = seeded_client.get("/graph/span-of-control", params={"tenant_id": TENANT})
        assert len(resp.json()) > 0

    def test_span_rating_values(self, seeded_client):
        """span_rating must be one of the three valid values."""
        resp = seeded_client.get("/graph/span-of-control", params={"tenant_id": TENANT})
        valid = {"OPTIMAL", "BELOW_OPTIMAL", "OVERLOADED"}
        for row in resp.json():
            assert row["span_rating"] in valid


class TestVendorSpend:

    def test_vendor_spend_returns_list(self, seeded_client):
        resp = seeded_client.get("/graph/vendor-spend", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_vendor_spend_has_records(self, seeded_client):
        resp = seeded_client.get("/graph/vendor-spend", params={"tenant_id": TENANT})
        assert len(resp.json()) > 0

    def test_vendor_spend_row_shape(self, seeded_client):
        resp = seeded_client.get("/graph/vendor-spend", params={"tenant_id": TENANT})
        row = resp.json()[0]
        assert "vendor_count" in row
        assert "total_spend" in row

    def test_vendor_spend_positive_amounts(self, seeded_client):
        """All spend amounts must be non-negative."""
        resp = seeded_client.get("/graph/vendor-spend", params={"tenant_id": TENANT})
        for row in resp.json():
            assert row["total_spend"] >= 0


class TestRenewals:

    def test_renewals_returns_list(self, seeded_client):
        resp = seeded_client.get("/graph/renewals", params={"tenant_id": TENANT})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_renewals_within_days_param(self, seeded_client):
        """within_days=1 should return fewer renewals than within_days=9999."""
        resp_short = seeded_client.get(
            "/graph/renewals", params={"tenant_id": TENANT, "within_days": 1}
        )
        resp_long = seeded_client.get(
            "/graph/renewals", params={"tenant_id": TENANT, "within_days": 9999}
        )
        assert len(resp_short.json()) <= len(resp_long.json())

    def test_renewals_invalid_within_days(self, seeded_client):
        """within_days must be >= 1."""
        resp = seeded_client.get(
            "/graph/renewals", params={"tenant_id": TENANT, "within_days": 0}
        )
        assert resp.status_code == 422
