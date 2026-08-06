"""
scout/api/routes/users.py — Multi-tenant user and API key management.

Endpoints:
  POST /users/tenants            — create a new tenant (public, onboarding)
  POST /users/register           — register a user under an existing tenant
  POST /users/login              — email+password → JWT (or MFA challenge if MFA enabled)
  POST /users/login/mfa          — exchange MFA token + TOTP code for full JWT
  GET  /users/me                 — JWT-protected: current user info
  GET  /users/me/api-keys        — list active API keys (no raw key)
  POST /users/me/api-keys        — generate a new API key (raw key shown once)
  DELETE /users/me/api-keys/{id} — deactivate an API key
"""

from datetime import datetime, timezone

import pyotp
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.db.auth_utils import (
    create_jwt,
    decode_jwt,
    generate_api_key,
    get_current_user,
    hash_api_key,
    hash_password,
    verify_password,
)
from scout.db.database import get_db
from scout.db.models import ApiKey, Tenant, User
from scout.db.schemas import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyRead,
    TenantCreate,
    TenantRead,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserRead,
)


class MfaLoginBody(BaseModel):
    mfa_token: str
    code: str

router = APIRouter(prefix="/users", tags=["users"])


# ── Tenant ────────────────────────────────────────────────


@router.post(
    "/tenants",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant",
    description="Public endpoint — call this during onboarding to register a new organisation.",
)
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)) -> TenantRead:
    existing = db.query(Tenant).filter(Tenant.slug == body.slug).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant slug '{body.slug}' is already taken.",
        )
    tenant = Tenant(name=body.name, slug=body.slug)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return TenantRead.model_validate(tenant)


# ── User registration & login ─────────────────────────────


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Requires a valid tenant_slug. Email must be unique across the system.",
)
def register_user(body: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    tenant = db.query(Tenant).filter(Tenant.slug == body.tenant_slug).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant '{body.tenant_slug}' not found.",
        )
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        tenant_id=tenant.id,
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description=(
        "Returns a JWT access token valid for 8 hours. "
        "If MFA is enabled, returns an mfa_token instead — exchange it via POST /users/login/mfa."
    ),
)
def login(body: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == body.email, User.is_active.is_(True)).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.mfa_enabled:
        # Issue a short-lived MFA-pending token (5 minutes)
        mfa_token = create_jwt(
            {"sub": user.id, "tenant_id": user.tenant_id, "email": user.email, "mfa_pending": True},
            expires_minutes=5,
        )
        return TokenResponse(mfa_required=True, mfa_token=mfa_token)

    token = create_jwt({"sub": user.id, "tenant_id": user.tenant_id, "email": user.email})
    return TokenResponse(
        access_token=token,
        tenant_id=user.tenant_id,
        email=user.email,
    )


@router.post(
    "/login/mfa",
    response_model=TokenResponse,
    summary="Complete MFA login",
    description="Exchange a short-lived mfa_token and a TOTP code for a full JWT access token.",
)
def login_mfa(body: MfaLoginBody, db: Session = Depends(get_db)) -> TokenResponse:
    payload = decode_jwt(body.mfa_token)
    if not payload.get("mfa_pending"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token is not an MFA-pending token.",
        )
    user_id: str | None = payload.get("sub")
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user or not user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or MFA not configured.",
        )
    if not pyotp.TOTP(user.mfa_secret).verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )
    token = create_jwt({"sub": user.id, "tenant_id": user.tenant_id, "email": user.email})
    return TokenResponse(
        access_token=token,
        tenant_id=user.tenant_id,
        email=user.email,
    )


# ── Current user ──────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get the current authenticated user",
)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


# ── API key management ────────────────────────────────────


@router.get(
    "/me/api-keys",
    response_model=list[ApiKeyRead],
    summary="List API keys for the current user",
    description="Returns active API keys. The raw key is never returned in this list.",
)
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ApiKeyRead]:
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.created_by == current_user.id, ApiKey.is_active.is_(True))
        .all()
    )
    return [ApiKeyRead.model_validate(k) for k in keys]


@router.post(
    "/me/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key",
    description=(
        "Generates a new API key for the current user's tenant. "
        "The raw key is returned ONCE and cannot be retrieved again."
    ),
)
def create_api_key(
    body: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiKeyCreateResponse:
    raw_key = generate_api_key()
    api_key = ApiKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:8],
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        label=body.label,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ApiKeyCreateResponse(
        id=api_key.id,
        key_prefix=api_key.key_prefix,
        label=api_key.label,
        tenant_id=api_key.tenant_id,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        raw_key=raw_key,
    )


@router.delete(
    "/me/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an API key",
)
def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    api_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.id == key_id,
            ApiKey.created_by == current_user.id,
            ApiKey.is_active.is_(True),
        )
        .first()
    )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already deactivated.",
        )
    api_key.is_active = False
    db.commit()
