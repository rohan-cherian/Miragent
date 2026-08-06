"""
Security headers middleware for SOC 2 compliance.

Adds HTTP security headers to every response. These headers instruct browsers
and proxies to enforce security policies, preventing XSS, clickjacking, and
content sniffing attacks.
"""

from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Appends security headers to every outgoing response."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        # Never cache API responses — they may contain sensitive tenant data
        response.headers["Cache-Control"] = "no-store"
        return response
