"""
scout/api/routes/connectors.py — Connector management endpoints (Sprint 83).

Endpoints:
  GET    /connectors                          — list all connectors + status (admin)
  GET    /connectors/salesforce/auth-start    — begin Salesforce OAuth2 flow (admin)
  GET    /connectors/salesforce/callback      — OAuth2 callback — NO auth required
  POST   /connectors/salesforce/disconnect    — soft-delete credential row (admin)
  POST   /connectors/salesforce/test          — run health check with stored creds (admin)
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.config import settings
from scout.connectors.models import ConnectorCredentials
from scout.connectors.oauth2 import build_auth_url
from scout.connectors.registry import CONNECTOR_REGISTRY
from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import ConnectorCredentialStore, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])

# Scopes requested from Salesforce
_SF_SCOPE = "api refresh_token offline_access"


# ── Schemas ───────────────────────────────────────────────────────────────────

class ConnectorStatusResponse(BaseModel):
    connector_id: str
    display_name: str
    category: str
    is_mock: bool
    is_connected: bool
    connected_at: Optional[str]
    last_error: Optional[str]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")


def _get_credential_row(
    db: Session,
    tenant_id: str,
    connector_id: str,
) -> ConnectorCredentialStore | None:
    return (
        db.query(ConnectorCredentialStore)
        .filter_by(tenant_id=tenant_id, connector_id=connector_id, is_active=True)
        .first()
    )


# ── GET /connectors ───────────────────────────────────────────────────────────

@router.get("", response_model=list[ConnectorStatusResponse])
def list_connectors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all registered connectors with their connection status.
    Admin only.
    """
    _require_admin(current_user)

    result: list[ConnectorStatusResponse] = []
    for connector_id, cls in CONNECTOR_REGISTRY.items():
        cred_row = (
            db.query(ConnectorCredentialStore)
            .filter_by(tenant_id=current_user.tenant_id, connector_id=connector_id, is_active=True)
            .first()
        )
        result.append(
            ConnectorStatusResponse(
                connector_id=connector_id,
                display_name=cls.DISPLAY_NAME,
                category=str(cls.CATEGORY.value if hasattr(cls.CATEGORY, "value") else cls.CATEGORY),
                is_mock=settings.use_mock_connectors,
                is_connected=cred_row is not None,
                connected_at=cred_row.connected_at.isoformat() if cred_row and cred_row.connected_at else None,
                last_error=cred_row.last_error if cred_row else None,
            )
        )
    return result


# ── GET /connectors/salesforce/auth-start ────────────────────────────────────

@router.get("/salesforce/auth-start")
def salesforce_auth_start(
    return_url: bool = Query(False, alias="return_url"),
    current_user: User = Depends(get_current_user),
):
    """
    Build the Salesforce OAuth2 authorization URL and either redirect to it
    or return it as JSON (when ?return_url=true). Admin only.
    """
    _require_admin(current_user)

    redirect_uri = f"{settings.api_base_url}/connectors/salesforce/callback"

    # Encode state as base64: "{tenant_id}:{user_id}"
    raw_state = f"{current_user.tenant_id}:{current_user.id}"
    state = base64.urlsafe_b64encode(raw_state.encode()).decode()

    auth_url = build_auth_url(
        auth_url=f"{settings.sf_instance_url}/services/oauth2/authorize",
        client_id=settings.sf_client_id,
        redirect_uri=redirect_uri,
        scope=_SF_SCOPE,
        state=state,
    )

    if return_url:
        return {"auth_url": auth_url}

    return RedirectResponse(url=auth_url)


# ── GET /connectors/salesforce/callback ──────────────────────────────────────

@router.get("/salesforce/callback")
def salesforce_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    OAuth2 callback from Salesforce. NOT auth-protected — Salesforce redirects here.
    Exchanges the authorization code for tokens and stores them in
    ConnectorCredentialStore.
    """
    # Decode state to recover tenant_id and user_id
    try:
        decoded = base64.urlsafe_b64decode(state.encode()).decode()
        tenant_id, user_id = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter.")

    redirect_uri = f"{settings.api_base_url}/connectors/salesforce/callback"

    # Exchange code for tokens
    try:
        resp = httpx.post(
            f"{settings.sf_instance_url}/services/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.sf_client_id,
                "client_secret": settings.sf_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        token_data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Salesforce token exchange failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Salesforce token exchange failed: {exc.response.text}",
        )
    except Exception as exc:
        logger.error("Salesforce token exchange error: %s", exc)
        raise HTTPException(status_code=400, detail=f"Token exchange error: {exc}")

    # token_data has: access_token, refresh_token, instance_url, id, token_type, issued_at
    auth_data = {
        "access_token": token_data.get("access_token", ""),
        "refresh_token": token_data.get("refresh_token", ""),
        "instance_url": token_data.get("instance_url", ""),
        "client_id": settings.sf_client_id,
        "client_secret": settings.sf_client_secret,
        "token_type": token_data.get("token_type", "Bearer"),
    }

    # Upsert into ConnectorCredentialStore
    existing = (
        db.query(ConnectorCredentialStore)
        .filter_by(tenant_id=tenant_id, connector_id="salesforce")
        .first()
    )
    if existing:
        existing.auth_data = auth_data
        existing.is_active = True
        existing.last_error = None
        existing.connected_at = datetime.now(timezone.utc)
        existing.connected_by = user_id
    else:
        row = ConnectorCredentialStore(
            tenant_id=tenant_id,
            connector_id="salesforce",
            auth_data=auth_data,
            connected_by=user_id,
        )
        db.add(row)

    db.commit()

    logger.info(
        "Salesforce credentials stored for tenant=%s connected_by=%s",
        tenant_id,
        user_id,
    )

    # Redirect to success page
    return RedirectResponse(url=f"{settings.api_base_url}/connectors?connected=true")


# ── POST /connectors/salesforce/disconnect ────────────────────────────────────

@router.post("/salesforce/disconnect")
def salesforce_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Soft-delete the Salesforce credential for the current tenant.
    Admin only.
    """
    _require_admin(current_user)

    row = _get_credential_row(db, current_user.tenant_id, "salesforce")
    if not row:
        raise HTTPException(status_code=404, detail="No active Salesforce credentials found.")

    row.is_active = False
    db.commit()
    logger.info(
        "Salesforce credentials deactivated for tenant=%s by user=%s",
        current_user.tenant_id,
        current_user.id,
    )
    return {"disconnected": True}


# ── POST /connectors/salesforce/test ─────────────────────────────────────────

@router.post("/salesforce/test")
def salesforce_test(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run a health check against Salesforce using the stored credentials.
    Admin only.
    """
    _require_admin(current_user)

    row = _get_credential_row(db, current_user.tenant_id, "salesforce")
    if not row:
        return {"connected": False, "error": "No credentials stored"}

    from scout.connectors.salesforce import SalesforceConnector

    creds = ConnectorCredentials(
        connector_id="salesforce",
        tenant_id=current_user.tenant_id,
        auth_data=row.auth_data,
    )
    connector = SalesforceConnector(creds)

    health = connector.health_check()

    # Update last_used_at and record any error
    row.last_used_at = datetime.now(timezone.utc)
    if not health.is_healthy:
        row.last_error = health.error_message or "Health check failed"
    else:
        row.last_error = None
    db.commit()

    return {
        "connected": health.is_healthy,
        "error": health.error_message,
        "latency_ms": health.latency_ms,
        "connector_id": health.connector_id,
    }
