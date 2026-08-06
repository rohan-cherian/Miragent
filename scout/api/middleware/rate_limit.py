"""
Per-tenant sliding-window rate limiter.

Runs in-process using a dict of deque objects (one per tenant_id).
In production, replace with Redis INCR + EXPIRE for distributed rate
limiting across multiple API replicas.

Note: _windows and _lock are instance variables so that each create_app()
call gets its own fresh rate-limit state.  Module-level globals would cause
all TestClient instances in the same pytest process to share a single
bucket, hitting the limit long before real traffic would.
"""

import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from scout.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter keyed by tenant_id query parameter."""

    def __init__(self, app):
        super().__init__(app)
        # Per-instance state: isolated between different create_app() calls.
        self._windows: dict[str, deque] = {}
        self._lock = threading.Lock()

    async def dispatch(self, request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        tenant_id = request.query_params.get("tenant_id", "global")
        now = time.time()
        window_start = now - 60

        with self._lock:
            if tenant_id not in self._windows:
                self._windows[tenant_id] = deque()

            window = self._windows[tenant_id]

            # Remove timestamps older than 60 seconds
            while window and window[0] < window_start:
                window.popleft()

            if len(window) >= settings.rate_limit_per_minute:
                return JSONResponse(
                    {"detail": "Rate limit exceeded. Try again in 60 seconds."},
                    status_code=429,
                    headers={
                        "Retry-After": "60",
                        "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            window.append(now)
            remaining = settings.rate_limit_per_minute - len(window)

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
