"""Authentication helper functions for password hashing, JWT, and API key management."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from scout.config import settings
from scout.db.database import get_db

# ── Password hashing ──────────────────────────────────────
# Use bcrypt directly (passlib has a known incompatibility with bcrypt>=4.x).
# We pre-hash with SHA-256 so passwords longer than 72 bytes are safe.


def _prep(password: str) -> bytes:
    """SHA-256 → hex digest keeps the input within bcrypt's 72-byte limit."""
    return hashlib.sha256(password.encode()).hexdigest().encode()


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt (SHA-256 pre-hash for long passwords)."""
    return bcrypt.hashpw(_prep(password), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the bcrypt hash."""
    return bcrypt.checkpw(_prep(plain), hashed.encode())


# ── API key utilities ─────────────────────────────────────


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hex digest of a raw API key (stored in DB instead of the key itself)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key with a recognisable 'sk-' prefix."""
    return "sk-" + secrets.token_urlsafe(32)


# ── JWT ───────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")


def create_jwt(data: dict, expires_minutes: int = 60 * 8) -> str:
    """Create a signed HS256 JWT that expires after *expires_minutes* minutes."""
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload["exp"] = expire
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict:
    """Decode and verify a JWT.

    Raises HTTP 401 if the token is invalid or expired.
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Current-user dependency ───────────────────────────────


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    """FastAPI dependency — decode JWT and return the matching User row.

    Raises HTTP 401 if the token is invalid, expired, or the user no longer exists.
    """
    from scout.db.models import User  # local import to avoid circular deps

    payload = decode_jwt(token)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
