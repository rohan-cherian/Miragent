"""Pydantic schemas for request/response serialization (not SQLAlchemy models)."""
from datetime import datetime

from pydantic import BaseModel, EmailStr


# ── Tenant ────────────────────────────────────────────────


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantRead(BaseModel):
    id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── User ──────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str
    role: str = "viewer"


class UserRead(BaseModel):
    id: str
    email: str
    tenant_id: str
    role: str
    is_active: bool
    mfa_enabled: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ── Auth tokens ───────────────────────────────────────────


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    mfa_required: bool = False
    mfa_token: str | None = None
    tenant_id: str | None = None
    email: str | None = None


# ── API Keys ──────────────────────────────────────────────


class ApiKeyCreate(BaseModel):
    label: str


class ApiKeyRead(BaseModel):
    id: str
    key_prefix: str
    label: str
    tenant_id: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyRead):
    """Returned once on creation — raw_key is never stored and cannot be retrieved again."""

    raw_key: str
