"""
API key authentication for Scout.

Validates X-API-Key header against:
  1. settings.scout_api_key  — backward-compatible dev/single-tenant key
  2. The ApiKey table in SQLite — per-tenant database keys (Sprint 15)

In production, rotate settings.scout_api_key and issue per-tenant keys via
POST /users/me/api-keys.
"""

from datetime import datetime, timezone

from fastapi import Header, HTTPException, status

from scout.config import settings


async def require_api_key(x_api_key: str = Header(default="")) -> str:
    """FastAPI dependency — validates the X-API-Key header.

    Usage in a route:
        @router.get("/protected")
        def protected(api_key: str = Depends(require_api_key)):
            ...

    Validation order:
      1. If auth_enabled=False → pass through (dev/test shortcut)
      2. If key matches settings.scout_api_key → pass (backward compat)
      3. Hash the key and look it up in the ApiKey table (is_active=True)
      4. If found → update last_used_at and pass
      5. If not found → 401

    Returns the api_key string on success.
    Raises HTTP 401 if missing or wrong.
    """
    if not settings.auth_enabled:
        return x_api_key

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # ── Backward compat: dev/single-tenant key ────────────────
    if x_api_key == settings.scout_api_key:
        return x_api_key

    # ── Database lookup ───────────────────────────────────────
    # We create a session directly (not via Depends) because this is middleware,
    # not a regular route handler.
    try:
        from scout.db.auth_utils import hash_api_key
        from scout.db.database import SessionLocal
        from scout.db.models import ApiKey

        key_hash = hash_api_key(x_api_key)
        db = SessionLocal()
        try:
            api_key_row = (
                db.query(ApiKey)
                .filter(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
                .first()
            )
            if api_key_row:
                api_key_row.last_used_at = datetime.now(timezone.utc)
                db.commit()
                return x_api_key
        finally:
            db.close()
    except Exception:
        # If the DB isn't available (e.g. before init_db runs in tests), fall through to 401.
        pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
