"""
scout/api/routes/access.py — Multi-tenant access control (Sprint 80).

Endpoints:
  GET  /access/my-tenants               → list all tenants the current user can access
  GET  /access/users/{user_id}          → list all tenants a specific user can access (admin)
  POST /access/grant                    → grant a user access to a tenant (admin)
  DELETE /access/revoke/{user_id}/{tenant_id} → revoke access (admin)
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import InsightSnapshot, User, UserTenantAccess

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/access", tags=["access"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tenant_entry(
    tenant_id: str,
    is_home: bool,
    db: Session,
) -> dict:
    """Build a single tenant entry with last_insights_run and has_full_intelligence."""
    latest = (
        db.query(InsightSnapshot)
        .filter(InsightSnapshot.tenant_id == tenant_id)
        .order_by(desc(InsightSnapshot.run_at))
        .first()
    )
    run_at = None
    if latest and latest.run_at:
        ts = latest.run_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        run_at = ts.isoformat()

    return {
        "tenant_id": tenant_id,
        "is_home": is_home,
        "last_insights_run": run_at,
        "has_full_intelligence": latest is not None,
    }


def _tenants_for_user(user: User, db: Session) -> list[dict]:
    """Return all tenants a user can access (home + granted extras), deduped."""
    home_id = user.tenant_id
    granted_rows = (
        db.query(UserTenantAccess)
        .filter(UserTenantAccess.user_id == user.id)
        .all()
    )
    granted_ids = {row.tenant_id for row in granted_rows}

    tenants: list[dict] = [_tenant_entry(home_id, is_home=True, db=db)]
    for tid in granted_ids:
        if tid != home_id:
            tenants.append(_tenant_entry(tid, is_home=False, db=db))

    return tenants


# ── Request schemas ───────────────────────────────────────────────────────────

class GrantRequest(BaseModel):
    user_id: str
    tenant_id: str
    note: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "/my-tenants",
    summary="List all tenants the current user can access (home + granted)",
)
def my_tenants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Returns every tenant the authenticated user can access.
    The home tenant (from User.tenant_id) is always included.
    Additional tenants granted via UserTenantAccess are also returned.
    """
    return {"tenants": _tenants_for_user(current_user, db)}


@router.get(
    "/users/{user_id}",
    summary="List all tenants a specific user can access (admin only)",
)
def user_tenants(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Admin-only. Returns every tenant accessible by the specified user.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    return {"tenants": _tenants_for_user(target, db)}


@router.post(
    "/grant",
    summary="Grant a user access to a tenant (admin only)",
)
def grant_access(
    body: GrantRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Admin-only. Creates a UserTenantAccess row. Idempotent — a second call
    for the same (user_id, tenant_id) pair returns ok=True, created=False.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    existing = (
        db.query(UserTenantAccess)
        .filter(
            UserTenantAccess.user_id == body.user_id,
            UserTenantAccess.tenant_id == body.tenant_id,
        )
        .first()
    )
    if existing:
        return {"ok": True, "user_id": body.user_id, "tenant_id": body.tenant_id, "created": False}

    row = UserTenantAccess(
        user_id=body.user_id,
        tenant_id=body.tenant_id,
        granted_by=current_user.id,
        note=body.note,
    )
    db.add(row)
    db.commit()
    return {"ok": True, "user_id": body.user_id, "tenant_id": body.tenant_id, "created": True}


@router.delete(
    "/revoke/{user_id}/{tenant_id}",
    summary="Revoke a user's access to a tenant (admin only)",
)
def revoke_access(
    user_id: str,
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Admin-only. Deletes the UserTenantAccess row.
    Returns 400 if the tenant is the user's home tenant (cannot revoke home).
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    target = db.query(User).filter(User.id == user_id).first()
    if target and target.tenant_id == tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot revoke access to the user's home tenant",
        )

    row = (
        db.query(UserTenantAccess)
        .filter(
            UserTenantAccess.user_id == user_id,
            UserTenantAccess.tenant_id == tenant_id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()

    return {"ok": True}
