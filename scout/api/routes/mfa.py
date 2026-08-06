"""
scout/api/routes/mfa.py — TOTP-based MFA management endpoints.

Endpoints:
  POST /mfa/setup   — generate a TOTP secret and QR code (does not enable MFA yet)
  POST /mfa/verify  — verify a TOTP code and enable MFA
  POST /mfa/disable — disable MFA (requires current TOTP code + password)
  GET  /mfa/status  — return whether MFA is currently enabled
"""

import base64
import io

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.db.auth_utils import get_current_user, verify_password
from scout.db.database import get_db
from scout.db.models import User

router = APIRouter(prefix="/mfa", tags=["mfa"])


# ── Request / response bodies ──────────────────────────────


class MfaVerifyBody(BaseModel):
    code: str


class MfaDisableBody(BaseModel):
    code: str
    password: str


# ── Helpers ────────────────────────────────────────────────


def _make_qr_base64(uri: str) -> str:
    """Render *uri* as a QR code and return it as a base64-encoded PNG data URL."""
    qr = qrcode.QRCode()
    qr.add_data(uri)
    qr.make()
    img = qr.make_image()
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


# ── Endpoints ──────────────────────────────────────────────


@router.post(
    "/setup",
    summary="Generate a TOTP secret and QR code",
    description=(
        "Creates a new TOTP secret for the current user and stores it, but does NOT "
        "enable MFA. Call POST /mfa/verify with a valid code to activate MFA."
    ),
)
def setup_mfa(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    secret = pyotp.random_base32()
    uri = f"otpauth://totp/Miragent:{current_user.email}?secret={secret}&issuer=Miragent"
    qr_image_base64 = _make_qr_base64(uri)

    current_user.mfa_secret = secret
    db.commit()

    return {
        "secret": secret,
        "qr_uri": uri,
        "qr_image_base64": qr_image_base64,
    }


@router.post(
    "/verify",
    summary="Verify a TOTP code and enable MFA",
    description="Validates the 6-digit code against the stored secret. Sets mfa_enabled=True on success.",
)
def verify_mfa(
    body: MfaVerifyBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not current_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup not initiated. Call POST /mfa/setup first.",
        )
    if not pyotp.TOTP(current_user.mfa_secret).verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )
    current_user.mfa_enabled = True
    db.commit()
    return {"ok": True, "message": "MFA enabled successfully"}


@router.post(
    "/disable",
    summary="Disable MFA",
    description="Requires both a valid TOTP code and the current password to disable MFA.",
)
def disable_mfa(
    body: MfaDisableBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not current_user.mfa_enabled or not current_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled for this account.",
        )
    if not verify_password(body.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password.",
        )
    if not pyotp.TOTP(current_user.mfa_secret).verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code.",
        )
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    db.commit()
    return {"ok": True}


@router.get(
    "/status",
    summary="Get MFA status",
    description="Returns whether MFA is currently enabled for the authenticated user.",
)
def mfa_status(current_user: User = Depends(get_current_user)) -> dict:
    return {"mfa_enabled": current_user.mfa_enabled}
