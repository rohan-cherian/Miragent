"""
Shared emulator rate limiting.

When a client exceeds the configured request budget, the emulator returns a
genuine HTTP 429 Too Many Requests with a real Retry-After header. Clients
must honour that header — this is not a simulated flag inside a 200 body.

All six vendor emulators reuse this module. Pass a vendor-shaped body from
``scout.shared.errors.build_error_body`` into ``enforce(body=...)`` so the
429 payload matches Salesforce, Zendesk, etc. The HTTP contract is always
the same: status 429 + Retry-After (seconds until the window clears).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse, Response


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single rate-limit check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int = 0

    @property
    def headers(self) -> dict[str, str]:
        """Standard rate-limit response headers."""
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
        }
        if not self.allowed and self.retry_after_seconds > 0:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers


class EmulatorRateLimiter:
    """
    Sliding-window rate limiter for vendor API emulators.

    Args:
        max_requests: Max requests allowed per key inside ``window_seconds``.
        window_seconds: Sliding window length in seconds.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def reset(self, key: str | None = None) -> None:
        """Clear state for one key, or all keys if ``key`` is None."""
        with self._lock:
            if key is None:
                self._windows.clear()
            else:
                self._windows.pop(key, None)

    def check(self, key: str, *, now: float | None = None) -> RateLimitResult:
        """
        Record a request for ``key`` and return whether it is allowed.

        On denial, ``retry_after_seconds`` is the number of whole seconds the
        client must wait before the oldest request falls out of the window.
        """
        now = time.time() if now is None else now
        window_start = now - self.window_seconds

        with self._lock:
            window = self._windows.setdefault(key, deque())

            while window and window[0] < window_start:
                window.popleft()

            if len(window) >= self.max_requests:
                oldest = window[0]
                # Ceiling so Retry-After is never 0 while still over limit.
                retry_after = max(1, int(oldest + self.window_seconds - now) + 1)
                return RateLimitResult(
                    allowed=False,
                    limit=self.max_requests,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )

            window.append(now)
            remaining = self.max_requests - len(window)
            return RateLimitResult(
                allowed=True,
                limit=self.max_requests,
                remaining=remaining,
            )

    def enforce(
        self,
        key: str,
        *,
        body: dict[str, Any] | None = None,
        now: float | None = None,
    ) -> Response | None:
        """
        Allow the request, or return a real HTTP 429 Response.

        Returns:
            ``None`` if the request is within budget (caller continues).
            A ``JSONResponse`` with status 429 and ``Retry-After`` if not.
        """
        result = self.check(key, now=now)
        if result.allowed:
            return None

        payload = body if body is not None else {
            "error": "rate_limit_exceeded",
            "message": (
                f"Rate limit exceeded. Retry after "
                f"{result.retry_after_seconds} seconds."
            ),
        }
        return JSONResponse(
            content=payload,
            status_code=429,
            headers=result.headers,
        )
