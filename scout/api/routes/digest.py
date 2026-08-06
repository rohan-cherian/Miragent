"""
scout/api/routes/digest.py — Email digest management endpoints (Sprint 81).

Endpoints:
  GET    /digest/recipients          — list all recipients (admin only)
  POST   /digest/recipients          — add recipient (admin only)
  DELETE /digest/recipients/{id}     — deactivate recipient (admin only)
  POST   /digest/send-now            — trigger digest immediately (admin only)
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import DigestRecipient, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digest", tags=["digest"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AddRecipientRequest(BaseModel):
    email: str
    name: Optional[str] = None
    tenant_id: Optional[str] = None


class RecipientResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    tenant_id: Optional[str]
    active: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: User) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/recipients")
def list_recipients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all digest recipients (admin only)."""
    _require_admin(current_user)
    recipients = db.query(DigestRecipient).all()
    return {
        "recipients": [
            {
                "id": r.id,
                "email": r.email,
                "name": r.name,
                "tenant_id": r.tenant_id,
                "active": r.active,
            }
            for r in recipients
        ]
    }


@router.post("/recipients", status_code=201)
def add_recipient(
    body: AddRecipientRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a new digest recipient (admin only). Returns 409 if already exists."""
    _require_admin(current_user)

    # Check for existing active or inactive row with same email+tenant_id
    existing = (
        db.query(DigestRecipient)
        .filter(
            DigestRecipient.email == body.email,
            DigestRecipient.tenant_id == body.tenant_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Recipient {body.email!r} already exists for this scope.",
        )

    recipient = DigestRecipient(
        email=body.email,
        name=body.name,
        tenant_id=body.tenant_id,
        added_by=current_user.id,
        active=True,
    )
    db.add(recipient)
    db.commit()
    db.refresh(recipient)

    logger.info(
        "digest: recipient added — email=%s tenant_id=%s by=%s",
        recipient.email,
        recipient.tenant_id,
        current_user.id,
    )
    return {
        "id": recipient.id,
        "email": recipient.email,
        "name": recipient.name,
        "tenant_id": recipient.tenant_id,
        "active": recipient.active,
    }


@router.delete("/recipients/{recipient_id}", status_code=200)
def delete_recipient(
    recipient_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a digest recipient (sets active=False). Admin only."""
    _require_admin(current_user)

    recipient = db.query(DigestRecipient).filter(DigestRecipient.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail=f"Recipient {recipient_id!r} not found.")

    recipient.active = False
    db.commit()

    logger.info("digest: recipient deactivated — id=%s email=%s", recipient_id, recipient.email)
    return {"id": recipient_id, "active": False, "message": "Recipient deactivated."}


@router.post("/send-now")
def send_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger the portfolio digest immediately (admin only)."""
    _require_admin(current_user)

    from scout.email_digest import build_and_send_portfolio_digest

    logger.info("digest: manual send-now triggered by user=%s", current_user.id)
    result = build_and_send_portfolio_digest(db)

    return {
        "sent": result["sent"],
        "recipient_count": result["recipient_count"],
        "company_count": result["company_count"],
        "error": result.get("error"),
    }
