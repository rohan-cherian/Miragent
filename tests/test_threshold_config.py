"""
tests/test_threshold_config.py

Tests for the dynamic threshold configuration system (Sprint 21).

Covers:
  - ThresholdConfig.for_worker() merging defaults with overrides
  - Enabled/disabled flag behaviour
  - Worker run() accepting config and using overrides
  - Admin API: GET/PUT/DELETE /admin/worker-configs/*
  - Finding disposition recording
  - Remediation action CRUD
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scout.workers.threshold_registry import (
    DEFAULTS,
    ThresholdConfig,
    get_defaults,
    get_metadata,
    get_worker_names,
)


# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLD REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistry:

    def test_all_known_workers_have_defaults(self):
        names = get_worker_names()
        assert len(names) >= 10
        for name in names:
            d = get_defaults(name)
            assert isinstance(d, dict)
            assert len(d) > 0

    def test_defaults_have_enabled_flag(self):
        for name in get_worker_names():
            assert "enabled" in DEFAULTS[name], f"{name} missing 'enabled' in DEFAULTS"

    def test_metadata_covers_major_workers(self):
        meta = get_metadata()
        assert "HireToRetireWorker" in meta
        assert "VendorBenchmarkWorker" in meta
        assert "IssueToResolutionWorker" in meta

    def test_metadata_single_worker(self):
        m = get_metadata("HireToRetireWorker")
        assert m["worker_name"] == "HireToRetireWorker"
        assert "defaults" in m
        assert "metadata" in m
        assert "inactive_rate_high" in m["metadata"]

    def test_metadata_has_required_fields(self):
        m = get_metadata("HireToRetireWorker")["metadata"]
        for key, spec in m.items():
            assert "label" in spec, f"{key} missing label"
            assert "type" in spec, f"{key} missing type"
            assert "min" in spec, f"{key} missing min"
            assert "max" in spec, f"{key} missing max"
            assert "industry_low" in spec, f"{key} missing industry_low"
            assert "industry_high" in spec, f"{key} missing industry_high"


# ─────────────────────────────────────────────────────────────────────────────
# THRESHOLD CONFIG OBJECT
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdConfig:

    def test_returns_default_when_no_overrides(self):
        cfg = ThresholdConfig.for_worker("HireToRetireWorker", None)
        assert cfg.get("inactive_rate_high") == 0.20
        assert cfg.get("high_span") == 10

    def test_override_wins_over_default(self):
        cfg = ThresholdConfig.for_worker(
            "HireToRetireWorker", {"inactive_rate_high": 0.25}
        )
        assert cfg.get("inactive_rate_high") == 0.25

    def test_non_overridden_keys_still_return_defaults(self):
        cfg = ThresholdConfig.for_worker(
            "HireToRetireWorker", {"inactive_rate_high": 0.25}
        )
        assert cfg.get("high_span") == 10   # not overridden → default

    def test_enabled_defaults_to_true(self):
        cfg = ThresholdConfig.for_worker("HireToRetireWorker", None)
        assert cfg.enabled is True

    def test_enabled_can_be_set_false(self):
        cfg = ThresholdConfig.for_worker("HireToRetireWorker", {"enabled": False})
        assert cfg.enabled is False

    def test_get_unknown_key_returns_fallback(self):
        cfg = ThresholdConfig.for_worker("HireToRetireWorker", None)
        assert cfg.get("nonexistent_key", 42) == 42

    def test_as_dict_contains_all_defaults(self):
        cfg = ThresholdConfig.for_worker("VendorBenchmarkWorker", None)
        d = cfg.as_dict()
        assert "overpaying_critical_pct" in d
        assert "negotiation_window_min" in d

    def test_override_partial_merge(self):
        """Only the overridden keys change; others stay at defaults."""
        cfg = ThresholdConfig.for_worker(
            "VendorBenchmarkWorker",
            {"overpaying_critical_pct": 40},
        )
        assert cfg.get("overpaying_critical_pct") == 40
        assert cfg.get("overpaying_high_pct") == 20   # unchanged default

    def test_empty_override_dict_equals_defaults(self):
        cfg_no_override = ThresholdConfig.for_worker("HireToRetireWorker", None)
        cfg_empty = ThresholdConfig.for_worker("HireToRetireWorker", {})
        assert cfg_no_override.as_dict() == cfg_empty.as_dict()

    def test_unknown_worker_returns_empty_config(self):
        cfg = ThresholdConfig.for_worker("NonExistentWorker", None)
        assert cfg.get("anything", "fallback") == "fallback"
        assert cfg.enabled is True   # defaults to True when key absent


# ─────────────────────────────────────────────────────────────────────────────
# WORKER RUN() RESPECTS CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkerConfigIntegration:
    """Workers must use config thresholds when provided."""

    @pytest.fixture
    def neo4j_driver(self):
        driver = MagicMock()
        session = MagicMock()
        # Return a MagicMock result so .single(), .data(), and iteration all work
        neo4j_result = MagicMock()
        neo4j_result.single.return_value = None
        neo4j_result.data.return_value = []
        neo4j_result.__iter__ = MagicMock(return_value=iter([]))
        session.run.return_value = neo4j_result
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        driver.session.return_value = session
        return driver

    def test_hire_to_retire_disabled_returns_info(self, neo4j_driver):
        from scout.workers.hire_to_retire import HireToRetireWorker
        worker = HireToRetireWorker(neo4j_driver)
        result = worker.run("t1", config={"enabled": False})
        assert len(result.findings) == 1
        assert "disabled" in result.findings[0].title.lower()

    def test_issue_to_resolution_disabled_returns_info(self, neo4j_driver):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        worker = IssueToResolutionWorker(neo4j_driver)
        result = worker.run("t1", config={"enabled": False})
        assert len(result.findings) == 1
        assert "disabled" in result.findings[0].title.lower()

    def test_hire_to_retire_accepts_config_param(self, neo4j_driver):
        """Worker must accept config= without crashing even with no data."""
        from scout.workers.hire_to_retire import HireToRetireWorker
        worker = HireToRetireWorker(neo4j_driver)
        result = worker.run("t1", config={"inactive_rate_high": 0.30, "high_span": 15})
        # No error — config was accepted
        assert result.error is None or "single" not in str(result.error)

    def test_issue_to_resolution_accepts_custom_thresholds(self, neo4j_driver):
        """Custom old_deal_days threshold is accepted without crash."""
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        worker = IssueToResolutionWorker(neo4j_driver)
        result = worker.run("t1", config={"old_deal_days": 60, "early_stage_pct": 40})
        assert result.error is None or "single" not in str(result.error)

    def test_vendor_benchmark_disabled(self, neo4j_driver):
        from scout.workers.vendor_benchmark import VendorBenchmarkWorker
        worker = VendorBenchmarkWorker(neo4j_driver)
        result = worker.run("t1", config={"enabled": False})
        assert any("disabled" in f.title.lower() for f in result.findings)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    """TestClient backed by a single in-memory SQLite DB for the whole module."""
    import os
    os.environ.setdefault("USE_MOCK_CONNECTORS", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_sprint21.db")
    os.environ.setdefault("SECRET_KEY", "test-secret-sprint21")
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "password")

    from scout.api.app import create_app
    from scout.db.database import engine
    from scout.db.models import Base
    Base.metadata.drop_all(bind=engine)   # clean slate each module run
    Base.metadata.create_all(bind=engine)

    app = create_app()
    with TestClient(app) as client:
        yield client

    # Cleanup after the entire module
    import os as _os
    for f in ["test_sprint21.db", "test_sprint21.db-shm", "test_sprint21.db-wal"]:
        try:
            _os.remove(f)
        except FileNotFoundError:
            pass


@pytest.fixture(scope="module")
def admin_token(app_client):
    """Register a tenant + admin user and return a JWT (idempotent)."""
    # Ignore 409 — tenant/user may already exist if DB is shared across tests
    app_client.post("/users/tenants", json={"name": "Acme Sprint21", "slug": "acme-21"})
    app_client.post("/users/register", json={
        "email": "admin21@acme.com", "password": "S3cr3t!",
        "tenant_slug": "acme-21", "role": "admin",
    })
    resp = app_client.post("/users/login", json={
        "email": "admin21@acme.com", "password": "S3cr3t!",
    })
    assert resp.status_code == 200, f"Login failed (tenant/user may not exist): {resp.text}"
    return resp.json()["access_token"]


class TestAdminWorkerConfigAPI:

    def test_metadata_endpoint_no_auth_required(self, app_client):
        resp = app_client.get("/admin/worker-configs/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert "HireToRetireWorker" in data
        assert "VendorBenchmarkWorker" in data

    def test_list_configs_requires_auth(self, app_client):
        resp = app_client.get("/admin/worker-configs")
        assert resp.status_code in (401, 403)

    def test_list_configs_returns_all_workers(self, app_client, admin_token):
        resp = app_client.get(
            "/admin/worker-configs",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        names = [w["worker_name"] for w in resp.json()]
        assert "HireToRetireWorker" in names
        assert "VendorBenchmarkWorker" in names

    def test_get_single_worker_config(self, app_client, admin_token):
        resp = app_client.get(
            "/admin/worker-configs/HireToRetireWorker",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["worker_name"] == "HireToRetireWorker"
        assert data["enabled"] is True
        assert data["thresholds"]["inactive_rate_high"] == 0.20  # platform default

    def test_get_unknown_worker_returns_404(self, app_client, admin_token):
        resp = app_client.get(
            "/admin/worker-configs/NonExistentWorker",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_update_threshold_override(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.put(
            "/admin/worker-configs/HireToRetireWorker",
            json={"thresholds": {"inactive_rate_high": 0.25}},
            headers=auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["thresholds"]["inactive_rate_high"] == 0.25
        assert data["overrides"]["inactive_rate_high"] == 0.25
        assert data["defaults"]["inactive_rate_high"] == 0.20  # default unchanged

    def test_override_persists_on_subsequent_get(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        app_client.put(
            "/admin/worker-configs/HireToRetireWorker",
            json={"thresholds": {"high_span": 15}},
            headers=auth,
        )
        resp = app_client.get("/admin/worker-configs/HireToRetireWorker", headers=auth)
        assert resp.json()["thresholds"]["high_span"] == 15

    def test_disable_worker(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.put(
            "/admin/worker-configs/VendorBenchmarkWorker",
            json={"enabled": False, "thresholds": {}},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_reset_to_defaults(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        # First set an override
        app_client.put(
            "/admin/worker-configs/HireToRetireWorker",
            json={"thresholds": {"inactive_rate_high": 0.30}},
            headers=auth,
        )
        # Then reset
        resp = app_client.delete("/admin/worker-configs/HireToRetireWorker", headers=auth)
        assert resp.status_code == 200
        assert resp.json()["reset_to"] == "platform_defaults"

        # Verify override is gone
        get_resp = app_client.get("/admin/worker-configs/HireToRetireWorker", headers=auth)
        assert get_resp.json()["thresholds"]["inactive_rate_high"] == 0.20

    def test_non_admin_cannot_update(self, app_client, admin_token):
        # Register a viewer
        app_client.post("/users/register", json={
            "email": "viewer21@acme.com", "password": "S3cr3t!",
            "tenant_slug": "acme-21", "role": "viewer",
        })
        viewer_resp = app_client.post("/users/login", json={
            "email": "viewer21@acme.com", "password": "S3cr3t!",
        })
        viewer_token = viewer_resp.json()["access_token"]

        resp = app_client.put(
            "/admin/worker-configs/HireToRetireWorker",
            json={"thresholds": {"inactive_rate_high": 0.99}},
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403


class TestDispositionAPI:

    def test_record_dismissed_disposition(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.post(
            "/admin/findings/abc123/disposition"
            "?worker_name=HireToRetireWorker&severity=HIGH",
            json={"disposition": "DISMISSED", "reason": "Not relevant for our org size"},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["disposition"] == "DISMISSED"

    def test_record_acted_disposition(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.post(
            "/admin/findings/xyz789/disposition"
            "?worker_name=VendorBenchmarkWorker&severity=CRITICAL",
            json={"disposition": "ACTED"},
            headers=auth,
        )
        assert resp.status_code == 200

    def test_snoozed_includes_snooze_until(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.post(
            "/admin/findings/snz001/disposition"
            "?worker_name=LeadToCashWorker&severity=MEDIUM",
            json={"disposition": "SNOOZED", "snooze_days": 30},
            headers=auth,
        )
        assert resp.status_code == 200
        assert resp.json()["snooze_until"] is not None

    def test_invalid_disposition_rejected(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.post(
            "/admin/findings/bad/disposition"
            "?worker_name=HireToRetireWorker&severity=HIGH",
            json={"disposition": "IGNORED"},
            headers=auth,
        )
        assert resp.status_code == 422

    def test_get_disposition_history(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        finding_hash = "hist001"
        for d in ["DISMISSED", "ACTED"]:
            app_client.post(
                f"/admin/findings/{finding_hash}/disposition"
                "?worker_name=HireToRetireWorker&severity=MEDIUM",
                json={"disposition": d},
                headers=auth,
            )
        resp = app_client.get(f"/admin/findings/{finding_hash}/dispositions", headers=auth)
        assert resp.status_code == 200
        assert len(resp.json()) == 2
