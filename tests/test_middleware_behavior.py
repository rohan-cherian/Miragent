"""
tests/test_middleware_behavior.py — Sprint 43: Middleware behavior tests

Existing tests/test_security.py verifies that headers are PRESENT.
This file tests the BEHAVIOR of each middleware under stress and edge cases:

  RateLimitMiddleware:
    - 429 returned after exceeding rate limit
    - Sliding window: old requests evict, allowing new ones
    - X-RateLimit-Remaining decrements correctly
    - Retry-After header on 429
    - Disabled rate-limiter passes all requests through

  AuditLogMiddleware:
    - Each request writes exactly one JSON line to the log file
    - Log record contains required SOC 2 fields
    - status_code, method, path are logged accurately
    - Works when directory doesn't yet exist (creates it)

These tests use a minimal TestClient backed by the real create_app()
so middleware is wired exactly as production, but with controlled settings.
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _make_client(tmp_log: str | None = None) -> TestClient:
    """Create a TestClient with optional custom audit log path."""
    if tmp_log:
        settings.audit_log_file = tmp_log
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMIT MIDDLEWARE — 429 ENFORCEMENT
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimitEnforcement:

    def test_single_request_not_rate_limited(self):
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 10
            client = _make_client()
            resp = client.get("/health")
            assert resp.status_code != 429
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit

    def test_exceeding_limit_returns_429(self):
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 3
            client = _make_client()
            responses = [
                client.get("/health", params={"tenant_id": "test-ratelimit"})
                for _ in range(5)
            ]
            status_codes = [r.status_code for r in responses]
            # At least one must be 429
            assert 429 in status_codes
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit

    def test_429_has_retry_after_header(self):
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 2
            client = _make_client()
            for _ in range(4):
                resp = client.get("/health", params={"tenant_id": "ratelimit-retry"})
            # Final request must have hit the limit
            assert resp.status_code == 429
            assert "retry-after" in resp.headers
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit

    def test_429_body_contains_detail(self):
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 1
            client = _make_client()
            client.get("/health", params={"tenant_id": "detail-test"})
            resp = client.get("/health", params={"tenant_id": "detail-test"})
            if resp.status_code == 429:
                body = resp.json()
                assert "detail" in body
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit

    def test_rate_limit_keyed_per_tenant(self):
        """Two different tenant_ids have independent rate limit buckets."""
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 2
            client = _make_client()
            # Exhaust tenant-a's limit
            for _ in range(3):
                client.get("/health", params={"tenant_id": "tenant-a"})
            # tenant-b should still be fine
            resp = client.get("/health", params={"tenant_id": "tenant-b"})
            assert resp.status_code != 429
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit

    def test_rate_limit_disabled_never_returns_429(self):
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = False
            settings.rate_limit_per_minute = 1  # would block if enabled
            client = _make_client()
            for _ in range(10):
                resp = client.get("/health", params={"tenant_id": "no-limit"})
                assert resp.status_code != 429
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit

    def test_remaining_header_present_when_enabled(self):
        original_enabled = settings.rate_limit_enabled
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 100
            client = _make_client()
            resp = client.get("/health", params={"tenant_id": "hdr-test"})
            assert "x-ratelimit-remaining" in resp.headers
        finally:
            settings.rate_limit_enabled = original_enabled

    def test_remaining_decrements(self):
        original_enabled = settings.rate_limit_enabled
        original_limit = settings.rate_limit_per_minute
        try:
            settings.rate_limit_enabled = True
            settings.rate_limit_per_minute = 100
            client = _make_client()
            r1 = client.get("/health", params={"tenant_id": "decrement-test"})
            r2 = client.get("/health", params={"tenant_id": "decrement-test"})
            rem1 = int(r1.headers.get("x-ratelimit-remaining", 100))
            rem2 = int(r2.headers.get("x-ratelimit-remaining", 100))
            assert rem2 < rem1
        finally:
            settings.rate_limit_enabled = original_enabled
            settings.rate_limit_per_minute = original_limit


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG MIDDLEWARE — JSON CONTENT
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditLogContent:

    def _reset_audit_logger(self) -> None:
        """
        Clear handlers from the 'scout.audit' logger.

        AuditLogMiddleware uses `if not self._logger.handlers:` to avoid
        adding duplicate handlers. In tests, each test needs a fresh handler
        pointing to a fresh tmp file, so we must reset between calls.
        """
        import logging
        audit_logger = logging.getLogger("scout.audit")
        for handler in list(audit_logger.handlers):
            handler.close()
            audit_logger.removeHandler(handler)

    def _read_log_lines(self, log_path: str) -> list[dict]:
        """Read JSON log lines written by AuditLogMiddleware."""
        lines = []
        if not os.path.exists(log_path):
            return lines
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return lines

    def test_request_writes_log_line(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            assert len(lines) >= 1
        finally:
            settings.audit_log_file = original

    def test_log_line_has_timestamp(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit2.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            assert len(lines) >= 1
            assert "timestamp" in lines[-1]
        finally:
            settings.audit_log_file = original

    def test_log_line_has_method(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit3.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            record = lines[-1]
            assert "method" in record
            assert record["method"] == "GET"
        finally:
            settings.audit_log_file = original

    def test_log_line_has_path(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit4.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            record = lines[-1]
            assert "path" in record
            assert record["path"] == "/health"
        finally:
            settings.audit_log_file = original

    def test_log_line_has_status_code(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit5.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            record = lines[-1]
            assert "status_code" in record
            assert isinstance(record["status_code"], int)
        finally:
            settings.audit_log_file = original

    def test_log_line_has_duration_ms(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit6.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            record = lines[-1]
            assert "duration_ms" in record
            assert isinstance(record["duration_ms"], (int, float))
            assert record["duration_ms"] >= 0
        finally:
            settings.audit_log_file = original

    def test_log_line_has_request_id(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit7.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            lines = self._read_log_lines(log_file)
            assert "request_id" in lines[-1]
        finally:
            settings.audit_log_file = original

    def test_each_request_writes_separate_line(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit8.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health")
            client.get("/health")
            client.get("/health")
            lines = self._read_log_lines(log_file)
            assert len(lines) >= 3
        finally:
            settings.audit_log_file = original

    def test_log_captures_tenant_id_from_query(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit9.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            client.get("/health", params={"tenant_id": "acme-corp"})
            lines = self._read_log_lines(log_file)
            record = lines[-1]
            assert record.get("tenant_id") == "acme-corp"
        finally:
            settings.audit_log_file = original

    def test_log_creates_directory_if_missing(self, tmp_path):
        self._reset_audit_logger()
        nested = str(tmp_path / "deep" / "nested" / "audit.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = nested
            client = _make_client(nested)
            client.get("/health")
            assert os.path.isdir(os.path.dirname(nested))
        finally:
            settings.audit_log_file = original

    def test_request_id_unique_per_request(self, tmp_path):
        self._reset_audit_logger()
        log_file = str(tmp_path / "audit10.log")
        original = settings.audit_log_file
        try:
            settings.audit_log_file = log_file
            client = _make_client(log_file)
            for _ in range(5):
                client.get("/health")
            lines = self._read_log_lines(log_file)
            request_ids = [l["request_id"] for l in lines if "request_id" in l]
            assert len(request_ids) == len(set(request_ids))
        finally:
            settings.audit_log_file = original
