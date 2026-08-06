"""
tests/shared/test_rate_limit.py — W1-SRC-04 shared emulator rate limiting

Contract under test:
  - Over-limit calls get a genuine HTTP 429
  - Retry-After header is present and > 0
  - This is not a 200 with a "rate_limited" flag in JSON
"""

from __future__ import annotations

import time

import pytest
from starlette.responses import JSONResponse

from scout.shared.rate_limit import EmulatorRateLimiter, RateLimitResult


class TestEmulatorRateLimiterAllows:
    def test_under_limit_is_allowed(self):
        limiter = EmulatorRateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            result = limiter.check("token-a")
            assert result.allowed is True
            assert result.remaining >= 0

    def test_remaining_decrements(self):
        limiter = EmulatorRateLimiter(max_requests=3, window_seconds=60)
        assert limiter.check("t").remaining == 2
        assert limiter.check("t").remaining == 1
        assert limiter.check("t").remaining == 0

    def test_keys_are_isolated(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=60)
        assert limiter.check("a").allowed is True
        assert limiter.check("b").allowed is True
        assert limiter.check("a").allowed is False
        assert limiter.check("b").allowed is False


class TestEmulatorRateLimiterDeniesWithRealHttp429:
    def test_over_limit_check_not_allowed(self):
        limiter = EmulatorRateLimiter(max_requests=2, window_seconds=60)
        limiter.check("k")
        limiter.check("k")
        denied = limiter.check("k")
        assert denied.allowed is False
        assert denied.remaining == 0
        assert denied.retry_after_seconds >= 1

    def test_enforce_returns_none_when_allowed(self):
        limiter = EmulatorRateLimiter(max_requests=2, window_seconds=60)
        assert limiter.enforce("k") is None

    def test_enforce_returns_genuine_429_with_retry_after(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=30)
        assert limiter.enforce("k") is None

        response = limiter.enforce("k")
        assert response is not None
        assert isinstance(response, JSONResponse)
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert int(response.headers["Retry-After"]) >= 1
        # Must be a real 429 — not a 200 carrying a rate-limit flag
        assert response.status_code != 200

    def test_retry_after_reflects_window(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=10)
        t0 = 1_000_000.0
        assert limiter.check("k", now=t0).allowed is True
        denied = limiter.check("k", now=t0 + 1.0)
        assert denied.allowed is False
        # Oldest at t0, window 10s → clear around t0+10 → ~9s left at t0+1
        assert denied.retry_after_seconds == 10

    def test_custom_body_still_uses_http_429(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=60)
        limiter.enforce("k")
        body = {"error": "APIRateLimitExceeded", "message": "too many"}
        response = limiter.enforce("k", body=body)
        assert response is not None
        assert response.status_code == 429
        assert response.headers["Retry-After"]
        assert response.body  # vendor envelope can be swapped later

    def test_sliding_window_recovers(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=2)
        assert limiter.enforce("k") is None
        assert limiter.enforce("k") is not None
        time.sleep(2.1)
        assert limiter.enforce("k") is None


class TestEmulatorRateLimiterValidation:
    def test_invalid_max_requests(self):
        with pytest.raises(ValueError):
            EmulatorRateLimiter(max_requests=0)

    def test_invalid_window(self):
        with pytest.raises(ValueError):
            EmulatorRateLimiter(window_seconds=0)

    def test_reset_clears_key(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=60)
        limiter.check("k")
        assert limiter.check("k").allowed is False
        limiter.reset("k")
        assert limiter.check("k").allowed is True


class TestRateLimitResultHeaders:
    def test_denied_headers_include_retry_after(self):
        result = RateLimitResult(
            allowed=False, limit=10, remaining=0, retry_after_seconds=15
        )
        assert result.headers["Retry-After"] == "15"
        assert result.headers["X-RateLimit-Remaining"] == "0"

    def test_allowed_headers_omit_retry_after(self):
        result = RateLimitResult(allowed=True, limit=10, remaining=7)
        assert "Retry-After" not in result.headers
        assert result.headers["X-RateLimit-Remaining"] == "7"
