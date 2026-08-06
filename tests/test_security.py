"""
tests/test_security.py — Sprint 13 security feature tests.

Covers:
  - API key authentication (enabled / disabled)
  - Rate-limit headers
  - HTTP security headers
  - Audit log directory creation
  - /auth/status public endpoint
"""

import os

import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> TestClient:
    """Create a fresh TestClient backed by a new app instance."""
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    """Verify that API key enforcement works as configured."""

    def test_health_no_auth_required(self):
        """GET /health is a public endpoint — no X-API-Key needed."""
        client = _client()
        response = client.get("/health")
        # Health may be degraded if Neo4j/Redis aren't running, but it must
        # reach the route handler (not be rejected by auth middleware).
        assert response.status_code in (200, 503)

    def test_insights_requires_api_key_when_enabled(self):
        """When auth is on and the wrong key is sent, expect 401."""
        original_auth = settings.auth_enabled
        original_key = settings.scout_api_key
        try:
            settings.auth_enabled = True
            settings.scout_api_key = "test-key-123"
            client = _client()
            response = client.get(
                "/auth/validate",
                headers={"X-API-Key": "wrong-key"},
            )
            assert response.status_code == 401
        finally:
            settings.auth_enabled = original_auth
            settings.scout_api_key = original_key

    def test_valid_api_key_accepted(self):
        """Correct X-API-Key must not result in a 401."""
        original_auth = settings.auth_enabled
        original_key = settings.scout_api_key
        try:
            settings.auth_enabled = True
            settings.scout_api_key = "test-key-123"
            client = _client()
            response = client.get(
                "/auth/validate",
                headers={"X-API-Key": "test-key-123"},
            )
            assert response.status_code != 401
        finally:
            settings.auth_enabled = original_auth
            settings.scout_api_key = original_key

    def test_auth_disabled_allows_any_key(self):
        """When auth_enabled=False, any (or no) key must pass through."""
        original_auth = settings.auth_enabled
        try:
            settings.auth_enabled = False
            client = _client()
            response = client.get(
                "/auth/validate",
                headers={"X-API-Key": "totally-wrong-key"},
            )
            # Should not be blocked by auth — may be 200 or other non-401
            assert response.status_code != 401
        finally:
            settings.auth_enabled = original_auth


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Verify that rate-limit headers are present on responses."""

    def test_rate_limit_headers_present(self):
        """Every response should carry X-RateLimit-Limit when limiting is on."""
        original_enabled = settings.rate_limit_enabled
        try:
            settings.rate_limit_enabled = True
            client = _client()
            response = client.get("/health")
            assert "x-ratelimit-limit" in response.headers
        finally:
            settings.rate_limit_enabled = original_enabled

    def test_rate_limit_per_minute_in_header(self):
        """X-RateLimit-Limit must match the configured value."""
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 42
            client = _client()
            response = client.get("/health")
            assert response.headers.get("x-ratelimit-limit") == "42"
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Verify that HTTP security headers are injected on every response."""

    def test_x_frame_options(self):
        client = _client()
        response = client.get("/health")
        assert response.headers.get("x-frame-options") == "DENY"

    def test_x_content_type_options(self):
        client = _client()
        response = client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    def test_security_headers_on_health(self):
        """All mandatory security headers must appear on GET /health."""
        client = _client()
        response = client.get("/health")
        headers = response.headers
        assert headers.get("x-frame-options") == "DENY"
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-xss-protection") == "1; mode=block"
        assert "max-age=31536000" in headers.get("strict-transport-security", "")
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog:
    """Verify SOC 2 audit logging infrastructure."""

    def test_audit_log_directory_created(self, tmp_path):
        """Making a request should ensure the logs directory exists."""
        log_file = str(tmp_path / "audit_sub" / "audit.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _client()
            client.get("/health")
            assert os.path.isdir(os.path.dirname(log_file))
        finally:
            settings.audit_log_file = original

    def test_auth_status_endpoint(self):
        """GET /auth/status returns the expected auth configuration keys."""
        client = _client()
        response = client.get("/auth/status")
        assert response.status_code == 200
        body = response.json()
        assert "auth_enabled" in body
        assert "rate_limit_enabled" in body
        assert "rate_limit_per_minute" in body
        assert body.get("version") == "Sprint 13"
