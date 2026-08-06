"""
scout/api/routes/auth.py — Authentication and key management endpoints.

Provides:
  GET  /auth/validate              — verify a supplied API key is valid
  GET  /auth/status                — public view of auth configuration
  POST /auth/rotate-key-instructions — SOC 2-friendly rotation guidance
"""

from fastapi import APIRouter, Depends

from scout.api.middleware.auth import require_api_key
from scout.config import settings

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get(
    "/validate",
    summary="Validate the supplied API key",
    description=(
        "Requires a valid X-API-Key header. Returns the current environment "
        "name so callers can confirm they are hitting the right stack."
    ),
)
async def validate_api_key(api_key: str = Depends(require_api_key)) -> dict:
    return {"valid": True, "environment": settings.environment}


@router.get(
    "/status",
    summary="Public auth configuration status",
    description=(
        "Returns the current authentication and rate-limiting configuration. "
        "No API key required — safe to call from monitoring dashboards."
    ),
)
def auth_status() -> dict:
    return {
        "auth_enabled": settings.auth_enabled,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "version": "Sprint 13",
    }


@router.post(
    "/rotate-key-instructions",
    summary="API key rotation instructions (SOC 2)",
    description=(
        "Returns step-by-step instructions for rotating the Scout API key. "
        "Actual rotation is performed out-of-band (Kubernetes secret / .env.local). "
        "The rotation event is captured in the audit trail automatically."
    ),
)
def rotate_key_instructions() -> dict:
    return {
        "message": (
            "To rotate the API key: update SCOUT_API_KEY in your Kubernetes secret "
            "or .env.local, then restart the pod. "
            "All existing connections will be invalidated immediately."
        ),
        "soc2_note": (
            "Key rotation events are automatically logged to the audit trail."
        ),
    }
