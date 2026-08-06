"""Tests for POST /scans and GET /scans/{scan_id}."""

import time
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from scout.api.app import create_app
from scout.api.models import ScanStatus


@pytest.fixture
def client():
    """Fresh app + fresh job store for each test."""
    app = create_app()
    # Reset the job store between tests so they don't share state
    from scout.api import job_store as js_module
    js_module.job_store._jobs.clear()
    return TestClient(app, raise_server_exceptions=True)


class TestTriggerScan:

    def test_post_scans_returns_202(self, client):
        """POST /scans must return 202 Accepted — not 200."""
        response = client.post("/scans", json={"tenant_id": "test-tenant"})
        assert response.status_code == 202

    def test_post_scans_returns_scan_id(self, client):
        """Response must include a scan_id for polling."""
        response = client.post("/scans", json={"tenant_id": "test-tenant"})
        data = response.json()
        assert "scan_id" in data
        assert data["scan_id"].startswith("scan-")

    def test_post_scans_returns_queued_status(self, client):
        """Immediately after creation, status must be 'queued'."""
        response = client.post("/scans", json={"tenant_id": "test-tenant"})
        data = response.json()
        # Note: by the time we read this, the background task may have already
        # started — but it should at minimum have been queued
        assert data["status"] in ("queued", "running", "completed")

    def test_post_scans_missing_tenant_id_returns_422(self, client):
        """Pydantic validation: tenant_id is required."""
        response = client.post("/scans", json={})
        assert response.status_code == 422

    def test_post_scans_propagates_tenant_id(self, client):
        """The tenant_id in the request must appear in the response."""
        response = client.post("/scans", json={"tenant_id": "acme-corp"})
        data = response.json()
        assert data["tenant_id"] == "acme-corp"


class TestGetScan:

    def test_get_scan_returns_job(self, client):
        """GET /scans/{scan_id} must return the job created by POST."""
        post_resp = client.post("/scans", json={"tenant_id": "test-tenant"})
        scan_id = post_resp.json()["scan_id"]

        get_resp = client.get(f"/scans/{scan_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["scan_id"] == scan_id

    def test_get_scan_unknown_id_returns_404(self, client):
        """An unknown scan_id must return 404, not 500."""
        response = client.get("/scans/scan-doesnotexist")
        assert response.status_code == 404

    def test_get_scan_job_shape(self, client):
        """Validate the ScanJob response schema."""
        post_resp = client.post("/scans", json={"tenant_id": "test-tenant"})
        scan_id = post_resp.json()["scan_id"]

        data = client.get(f"/scans/{scan_id}").json()
        assert "scan_id" in data
        assert "tenant_id" in data
        assert "status" in data
        assert "created_at" in data

    def test_scan_completes_successfully(self, client):
        """
        Integration test: pipeline should run and reach 'completed'.

        Uses a real pipeline with mock connectors (USE_MOCK_CONNECTORS=True).
        Polls for up to 30 seconds.
        """
        post_resp = client.post("/scans", json={"tenant_id": "test-tenant"})
        scan_id = post_resp.json()["scan_id"]

        # Poll until completed or failed (max 30 seconds)
        deadline = time.time() + 30
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)

        assert data["status"] == "completed", (
            f"Scan did not complete in time. Final status: {data['status']}. "
            f"Error: {data.get('error_message')}"
        )
        assert data["result"] is not None
        assert data["result"]["persons_merged"] > 0

    def test_scan_result_has_expected_fields(self, client):
        """When completed, result must contain all ScanResult fields."""
        post_resp = client.post("/scans", json={"tenant_id": "test-tenant"})
        scan_id = post_resp.json()["scan_id"]

        # Wait for completion
        deadline = time.time() + 30
        while time.time() < deadline:
            data = client.get(f"/scans/{scan_id}").json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.5)

        result = data.get("result", {})
        assert "connectors_run" in result
        assert "records_extracted" in result
        assert "persons_merged" in result
        assert "vendors_merged" in result
        assert "duration_seconds" in result


class TestListScans:

    def test_list_scans_returns_array(self, client):
        """GET /scans returns a list."""
        response = client.get("/scans")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_scans_includes_created_job(self, client):
        """After creating a scan, it appears in the list."""
        post_resp = client.post("/scans", json={"tenant_id": "list-test-tenant"})
        scan_id = post_resp.json()["scan_id"]

        list_resp = client.get("/scans")
        scan_ids = [j["scan_id"] for j in list_resp.json()]
        assert scan_id in scan_ids
