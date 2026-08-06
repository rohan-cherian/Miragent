"""
scout/api/routes/sso.py — SSO / OIDC Authentication (Sprint 58)

Implements OIDC Authorization Code Flow with PKCE for enterprise SSO.
Supports Okta, Azure AD, Google Workspace, and any generic OIDC provider.

Flow:
  1. Admin configures a provider via POST /auth/sso/providers
  2. User navigates to GET /auth/sso/login?provider_id=xxx
     (or the frontend detects their email domain and redirects automatically)
  3. Backend builds the authorization URL and redirects to the IdP
  4. IdP authenticates the user and calls GET /auth/sso/callback?code=xxx&state=xxx
  5. Backend exchanges the code for tokens, validates the ID token,
     JIT-provisions the user if needed, and issues a Miragent JWT
  6. Frontend receives the JWT in a URL fragment or secure cookie

Security:
  - PKCE (code_verifier/code_challenge) prevents authorization code interception
  - Signed state JWT (HS256, 10-minute TTL) prevents CSRF
  - ID token validated: signature (JWKS), iss, aud, exp, nonce
  - JIT provisioning creates users with minimal scope (tenant locked)

Provider config:
  POST /auth/sso/providers   — admin-only: configure a new OIDC provider
  GET  /auth/sso/providers   — admin-only: list providers for current tenant
  DELETE /auth/sso/providers/{id} — admin-only: disable a provider

Auth flow:
  GET  /auth/sso/login       — begin OIDC flow (redirects to IdP)
  GET  /auth/sso/callback    — handle IdP callback, issue Miragent JWT

Domain detection:
  GET  /auth/sso/detect?email=user@acme.com — returns provider_id if domain
       matches a configured provider; used by the login page to auto-route SSO users
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.config import settings
from scout.db.auth_utils import create_jwt, get_current_user
from scout.db.database import get_db
from scout.db.models import SSOProvider, Tenant, User
from scout.db.auth_utils import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["SSO"])

# Public domain-check router — no auth required, separate prefix so the
# login page can call it before the user has authenticated.
public_router = APIRouter(prefix="/sso", tags=["SSO"])

# OIDC discovery document path (RFC 8414 / OpenID Connect Discovery 1.0)
_OIDC_DISCOVERY_PATH = "/.well-known/openid-configuration"

# PKCE method
_PKCE_METHOD = "S256"

# State JWT TTL (10 minutes — IdP round-trip should always be faster)
_STATE_TTL_SECONDS = 600


# ── Request / Response models ─────────────────────────────────────────────────

class SSOProviderCreate(BaseModel):
    provider_slug: str          # e.g. "okta", "azure-ad"
    display_name: str           # e.g. "Acme Corp Okta"
    provider_type: str = "oidc" # oidc | azure_ad | google
    issuer_url: str             # https://acme.okta.com/oauth2/default
    client_id: str
    client_secret: str
    domains: list[str] = []     # email domains → ["acmecorp.com"]
    jit_provisioning: bool = True
    default_role: str = "viewer"


class SSOProviderRead(BaseModel):
    id: str
    provider_slug: str
    display_name: str
    provider_type: str
    issuer_url: str
    client_id: str
    domains: list[str]
    jit_provisioning: bool
    default_role: str
    is_active: bool

    class Config:
        from_attributes = True


# ── Admin: manage providers ───────────────────────────────────────────────────

def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to manage SSO providers",
        )
    return current_user


@router.get(
    "/providers",
    response_model=list[SSOProviderRead],
    summary="List SSO providers for current tenant",
)
def list_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin),
) -> list[SSOProvider]:
    return (
        db.query(SSOProvider)
        .filter(
            SSOProvider.tenant_id == current_user.tenant_id,
            SSOProvider.is_active.is_(True),
        )
        .all()
    )


@router.post(
    "/providers",
    response_model=SSOProviderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Configure a new SSO provider (admin only)",
)
def create_provider(
    body: SSOProviderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin),
) -> SSOProvider:
    # Validate the issuer URL by fetching the discovery document
    discovery = _fetch_discovery(body.issuer_url)
    if not discovery:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Could not fetch OIDC discovery document from "
                f"{body.issuer_url}{_OIDC_DISCOVERY_PATH}. "
                "Check the issuer URL and ensure it is reachable."
            ),
        )

    provider = SSOProvider(
        tenant_id=current_user.tenant_id,
        provider_slug=body.provider_slug,
        display_name=body.display_name,
        provider_type=body.provider_type,
        issuer_url=body.issuer_url.rstrip("/"),
        client_id=body.client_id,
        client_secret=body.client_secret,
        domains=body.domains,
        jit_provisioning=body.jit_provisioning,
        default_role=body.default_role,
        is_active=True,
        created_by=current_user.email,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    logger.info(
        "SSO provider configured: tenant=%s slug=%s issuer=%s by=%s",
        current_user.tenant_id, body.provider_slug, body.issuer_url, current_user.email,
    )
    return provider


@router.delete(
    "/providers/{provider_id}",
    summary="Disable an SSO provider (admin only)",
)
def delete_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin),
) -> dict:
    provider = db.query(SSOProvider).filter(
        SSOProvider.id == provider_id,
        SSOProvider.tenant_id == current_user.tenant_id,
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    provider.is_active = False
    db.commit()
    return {"ok": True, "provider_id": provider_id}


# ── Sprint 74: Mock SSO domain registry ──────────────────────────────────────

SSO_DOMAIN_REGISTRY: dict[str, dict[str, str]] = {
    "enterprise-client.com": {"provider": "okta",     "display": "Okta",            "logo": "okta"},
    "bigcorp.com":           {"provider": "azure_ad", "display": "Azure AD",         "logo": "azure"},
    "techcorp.io":           {"provider": "azure_ad", "display": "Azure AD",         "logo": "azure"},
    "enterprise.com":        {"provider": "okta",     "display": "Okta",             "logo": "okta"},
    "bigretail.com":         {"provider": "google",   "display": "Google Workspace", "logo": "google"},
    "healthcare.org":        {"provider": "saml",     "display": "SAML SSO",         "logo": "saml"},
    "govtech.gov":           {"provider": "azure_ad", "display": "Azure AD",         "logo": "azure"},
    "security-firm.com":     {"provider": "okta",     "display": "Okta",             "logo": "okta"},
    "acme-corp.com":         {"provider": "okta",     "display": "Okta",             "logo": "okta"},
}

_BUTTON_LABELS: dict[str, str] = {
    "okta":     "Sign in with Okta",
    "azure_ad": "Sign in with Azure AD",
    "google":   "Sign in with Google Workspace",
    "saml":     "Sign in with SAML SSO",
}


@public_router.get(
    "/domain-check",
    summary="Check if a domain has SSO configured (Sprint 74 — public, no auth required)",
)
def domain_check(
    domain: str = Query(..., description="Email domain to check, e.g. enterprise-client.com"),
) -> dict:
    """
    Given an email domain, return SSO provider metadata if the domain is configured
    for single sign-on. Used by the login page to show 'Sign in with [Provider]'
    when a user types a recognised enterprise email address.

    This endpoint does NOT require authentication — it is called before login.

    Returns:
        {
            "sso_enabled": bool,
            "provider": str | null,
            "provider_display": str | null,
            "button_label": str | null,
            "logo": str | null,
        }
    """
    key = domain.strip().lower()
    cfg = SSO_DOMAIN_REGISTRY.get(key)
    if not cfg:
        return {
            "sso_enabled": False,
            "provider": None,
            "provider_display": None,
            "button_label": None,
            "logo": None,
        }

    provider = cfg["provider"]
    return {
        "sso_enabled": True,
        "provider": provider,
        "provider_display": cfg["display"],
        "button_label": _BUTTON_LABELS.get(provider, f"Sign in with {cfg['display']}"),
        "logo": cfg["logo"],
    }


# ── Domain detection ──────────────────────────────────────────────────────────

@router.get(
    "/detect",
    summary="Detect SSO provider by email domain",
)
def detect_provider(
    email: str = Query(..., description="User email address"),
    db: Session = Depends(get_db),
) -> dict:
    """
    Given a user's email address, return the SSO provider configured for
    their email domain (if any). Used by the login page to auto-suggest
    'Sign in with [Company SSO]' when the user types their email.

    Returns: { "provider_found": bool, "provider_id": str|null, "display_name": str|null }
    """
    if "@" not in email:
        return {"provider_found": False, "provider_id": None, "display_name": None}

    domain = email.split("@", 1)[1].lower()

    providers = (
        db.query(SSOProvider)
        .filter(SSOProvider.is_active.is_(True))
        .all()
    )
    for p in providers:
        if domain in [d.lower() for d in (p.domains or [])]:
            return {
                "provider_found": True,
                "provider_id": p.id,
                "display_name": p.display_name,
                "provider_slug": p.provider_slug,
            }

    return {"provider_found": False, "provider_id": None, "display_name": None}


# ── OIDC Authorization Code Flow ──────────────────────────────────────────────

@router.get(
    "/login",
    summary="Begin SSO login — redirects to identity provider",
    response_class=RedirectResponse,
)
def sso_login(
    provider_id: str = Query(..., description="SSOProvider.id"),
    redirect_uri: str = Query(
        ...,
        description="Where to send the user after authentication (must be allow-listed)"
    ),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """
    Build the OIDC Authorization URL and redirect the user's browser to the IdP.

    PKCE:
      A code_verifier (32 bytes, URL-safe base64) is generated per request.
      code_challenge = BASE64URL(SHA-256(ASCII(code_verifier)))
      The challenge is sent to the IdP; the verifier is stored in the state JWT.
    """
    provider = db.query(SSOProvider).filter(
        SSOProvider.id == provider_id,
        SSOProvider.is_active.is_(True),
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO provider not found")

    discovery = _fetch_discovery(provider.issuer_url)
    if not discovery:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot reach identity provider. Please try again.",
        )

    authorization_endpoint = discovery.get("authorization_endpoint", "")
    if not authorization_endpoint:
        raise HTTPException(
            status_code=500,
            detail="OIDC discovery missing authorization_endpoint",
        )

    # PKCE
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = _s256_challenge(code_verifier)
    nonce = secrets.token_urlsafe(16)

    # State JWT — binds the callback to this specific flow invocation
    state_payload = {
        "provider_id": provider_id,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "nonce": nonce,
        "iat": int(time.time()),
        "exp": int(time.time()) + _STATE_TTL_SECONDS,
        "purpose": "sso_state",
    }
    state = jwt.encode(state_payload, settings.jwt_secret, algorithm="HS256")

    # Build the authorization URL
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": _callback_uri(),
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": _PKCE_METHOD,
    }

    # Azure AD / Entra ID requires login_hint for domain
    if provider.provider_type == "azure_ad":
        params["response_mode"] = "query"

    auth_url = f"{authorization_endpoint}?{urlencode(params)}"
    logger.info("SSO login initiated: provider=%s", provider.provider_slug)
    return RedirectResponse(url=auth_url, status_code=302)


@router.get(
    "/callback",
    summary="Handle identity provider callback and issue Miragent JWT",
)
def sso_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> dict:
    """
    Handle the authorization code callback from the IdP.

    1. Validate and unpack the state JWT (CSRF protection)
    2. Exchange authorization code for tokens
    3. Validate the ID token (signature, iss, aud, exp, nonce)
    4. Extract user identity (email, name) from ID token claims
    5. JIT-provision user if they don't exist (if provider allows it)
    6. Issue a Miragent JWT and return it

    Returns:
        { "access_token": str, "token_type": "bearer", "user": { ... } }
    """
    # ── Unpack and validate state JWT ────────────────────────────────────────
    try:
        state_data = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    except JWTError as exc:
        logger.warning("SSO callback: invalid state JWT: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired SSO state. Please start the login flow again.",
        ) from exc

    if state_data.get("purpose") != "sso_state":
        raise HTTPException(status_code=400, detail="Invalid state token purpose")

    provider_id = state_data["provider_id"]
    redirect_uri = state_data["redirect_uri"]
    code_verifier = state_data["code_verifier"]
    expected_nonce = state_data["nonce"]

    # ── Load provider ────────────────────────────────────────────────────────
    provider = db.query(SSOProvider).filter(
        SSOProvider.id == provider_id,
        SSOProvider.is_active.is_(True),
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="SSO provider not found")

    # ── Fetch discovery document ─────────────────────────────────────────────
    discovery = _fetch_discovery(provider.issuer_url)
    if not discovery:
        raise HTTPException(status_code=503, detail="Cannot reach identity provider")

    token_endpoint = discovery.get("token_endpoint", "")
    jwks_uri = discovery.get("jwks_uri", "")

    if not token_endpoint or not jwks_uri:
        raise HTTPException(status_code=500, detail="OIDC discovery incomplete")

    # ── Exchange code for tokens ─────────────────────────────────────────────
    try:
        token_resp = httpx.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _callback_uri(),
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
            timeout=15.0,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except Exception as exc:
        logger.error("SSO token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Token exchange with identity provider failed",
        ) from exc

    id_token_raw = token_data.get("id_token")
    if not id_token_raw:
        raise HTTPException(status_code=502, detail="No id_token in provider response")

    # ── Validate ID token ────────────────────────────────────────────────────
    id_claims = _validate_id_token(
        id_token=id_token_raw,
        jwks_uri=jwks_uri,
        issuer=provider.issuer_url,
        client_id=provider.client_id,
        expected_nonce=expected_nonce,
    )

    email: str = id_claims.get("email", "").lower()
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Identity provider did not return an email claim. "
                   "Ensure the 'email' scope is granted.",
        )

    full_name: str = id_claims.get("name", "") or id_claims.get("preferred_username", "")

    # ── Upsert user ──────────────────────────────────────────────────────────
    user = db.query(User).filter(User.email == email).first()

    if not user:
        if not provider.jit_provisioning:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"User {email} is not registered and JIT provisioning is disabled "
                    f"for this SSO provider. Contact your administrator."
                ),
            )
        # JIT provision: create the user under the provider's tenant
        user = User(
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),  # random, unusable password
            tenant_id=provider.tenant_id,
            role=provider.default_role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(
            "SSO JIT provisioned user: email=%s tenant=%s role=%s",
            email, provider.tenant_id, provider.default_role,
        )
    else:
        # Verify the user belongs to this tenant (prevent cross-tenant SSO abuse)
        if user.tenant_id != provider.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email address belongs to a different tenant",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account has been deactivated",
            )

    # ── Issue Miragent JWT ───────────────────────────────────────────────────
    token = create_jwt({
        "sub": user.id,
        "email": user.email,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "sso": True,
        "sso_provider": provider.provider_slug,
    })

    logger.info(
        "SSO login successful: email=%s tenant=%s provider=%s",
        email, user.tenant_id, provider.provider_slug,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "tenant_id": user.tenant_id,
            "role": user.role,
            "full_name": full_name,
            "sso_provider": provider.provider_slug,
        },
    }


# ── OIDC helpers ──────────────────────────────────────────────────────────────

def _callback_uri() -> str:
    """The SSO callback URL — must match what's registered with the IdP."""
    base = getattr(settings, "api_base_url", "http://localhost:8000")
    return f"{base}/auth/sso/callback"


def _fetch_discovery(issuer_url: str) -> dict | None:
    """
    Fetch the OIDC discovery document.

    RFC 8414 / OpenID Connect Discovery 1.0:
    GET {issuer}/.well-known/openid-configuration

    Returns None on any error (network, non-200, invalid JSON).
    """
    issuer = issuer_url.rstrip("/")

    # Azure AD has a non-standard discovery URL format
    if "login.microsoftonline.com" in issuer and "v2.0" not in issuer:
        discovery_url = f"{issuer}/v2.0/.well-known/openid-configuration"
    else:
        discovery_url = f"{issuer}{_OIDC_DISCOVERY_PATH}"

    try:
        resp = httpx.get(discovery_url, timeout=10.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("OIDC discovery failed for %s: %s", issuer_url, exc)
        return None


def _s256_challenge(code_verifier: str) -> str:
    """
    Compute the PKCE code challenge (S256 method).

    code_challenge = BASE64URL(SHA-256(ASCII(code_verifier)))
    """
    import base64
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _validate_id_token(
    id_token: str,
    jwks_uri: str,
    issuer: str,
    client_id: str,
    expected_nonce: str,
) -> dict:
    """
    Validate an OIDC ID token.

    Performs:
      1. Fetch provider's JWKS (JSON Web Key Set)
      2. Verify JWT signature using matching key
      3. Validate standard claims: iss, aud, exp, nonce

    Returns the decoded claims dict on success.
    Raises HTTPException on any validation failure.
    """
    # Fetch JWKS
    try:
        jwks_resp = httpx.get(jwks_uri, timeout=10.0)
        jwks_resp.raise_for_status()
        jwks = jwks_resp.json()
    except Exception as exc:
        logger.error("Failed to fetch JWKS from %s: %s", jwks_uri, exc)
        raise HTTPException(
            status_code=502,
            detail="Cannot fetch identity provider's public keys",
        ) from exc

    # Decode and validate using python-jose
    try:
        # python-jose can validate against a JWKS directly
        claims = jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256", "ES256"],
            audience=client_id,
            issuer=issuer,
            options={"verify_exp": True},
        )
    except JWTError as exc:
        logger.warning("ID token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"ID token validation failed: {exc}",
        ) from exc

    # Validate nonce (replay protection)
    token_nonce = claims.get("nonce", "")
    if token_nonce != expected_nonce:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID token nonce mismatch — possible replay attack",
        )

    return claims
