"""
scout/api/routes/schedule.py — Insight scheduling endpoints.

Sprint 78: Allows PE operating partners to configure automatic /insights
runs per tenant so portfolio cards stay fresh without manual calls.

Endpoints:
  GET  /schedule              → list all schedules for the current user's tenant
  POST /schedule              → create or update a schedule
  DELETE /schedule/{tenant_id} → disable (soft-delete) a schedule

The actual execution is handled by the background scheduler started in
scout/scheduler.py, which runs in a daemon thread alongside the API server.

Cadence options:
  "daily"   — runs every day at hour_utc (e.g., 06:00 UTC = Monday-morning fresh)
  "weekly"  — runs every week on day_of_week at hour_utc
  "manual"  — schedule exists but auto-run is disabled

Design notes:
  - One schedule per tenant. POST is an upsert (create or update).
  - Schedules are stored in SQLite via the InsightSchedule model.
  - The scheduler reads this table every minute and fires due runs.
"""

from __future__ import annotations

import logging
from datetime import timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from scout.db.auth_utils import get_current_user
from scout.db.database import get_db
from scout.db.models import InsightSchedule, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/schedule", tags=["schedule"])


# ── Request / response schemas ────────────────────────────────────────────────

class ScheduleRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant to schedule insights for")
    cadence: Literal["daily", "weekly", "manual"] = Field(
        "daily",
        description="How often to run: daily, weekly, or manual (disabled auto-run)",
    )
    hour_utc: int = Field(
        6,
        ge=0, le=23,
        description="UTC hour to run (0–23). Default 6 = 06:00 UTC.",
    )
    day_of_week: int | None = Field(
        None,
        ge=0, le=6,
        description="Day of week for weekly cadence (0=Monday, 6=Sunday).",
    )
    enabled: bool = Field(True, description="Set false to pause without deleting.")


def _to_dict(s: InsightSchedule) -> dict:
    last_triggered = s.last_triggered_at
    if last_triggered and last_triggered.tzinfo is None:
        last_triggered = last_triggered.replace(tzinfo=timezone.utc)
    return {
        "id": s.id,
        "tenant_id": s.tenant_id,
        "cadence": s.cadence,
        "hour_utc": s.hour_utc,
        "day_of_week": s.day_of_week,
        "enabled": s.enabled,
        "last_triggered_at": last_triggered.isoformat() if last_triggered else None,
        "last_status": s.last_status,
        "last_error": s.last_error,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get(
    "",
    summary="List insight schedules for the current user's tenant",
)
def list_schedules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Returns all configured schedules visible to the current user."""
    schedules = (
        db.query(InsightSchedule)
        .filter(InsightSchedule.tenant_id == current_user.tenant_id)
        .all()
    )
    return {"schedules": [_to_dict(s) for s in schedules]}


@router.post(
    "",
    summary="Create or update an insight schedule",
)
def upsert_schedule(
    body: ScheduleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Create a new schedule or update the existing one for this tenant.
    Only admins can schedule for any tenant; non-admins may only schedule
    for their own tenant.
    """
    if current_user.role != "admin" and body.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="You can only configure schedules for your own tenant.",
        )

    if body.cadence == "weekly" and body.day_of_week is None:
        raise HTTPException(
            status_code=422,
            detail="day_of_week is required when cadence is 'weekly'.",
        )

    existing = (
        db.query(InsightSchedule)
        .filter(InsightSchedule.tenant_id == body.tenant_id)
        .first()
    )

    if existing:
        existing.cadence = body.cadence
        existing.hour_utc = body.hour_utc
        existing.day_of_week = body.day_of_week if body.cadence == "weekly" else None
        existing.enabled = body.enabled
        db.commit()
        db.refresh(existing)
        logger.info("Updated insight schedule for tenant %s", body.tenant_id)
        return {"schedule": _to_dict(existing), "created": False}
    else:
        schedule = InsightSchedule(
            tenant_id=body.tenant_id,
            cadence=body.cadence,
            hour_utc=body.hour_utc,
            day_of_week=body.day_of_week if body.cadence == "weekly" else None,
            enabled=body.enabled,
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)
        logger.info("Created insight schedule for tenant %s", body.tenant_id)
        return {"schedule": _to_dict(schedule), "created": True}


@router.delete(
    "/{tenant_id}",
    summary="Disable an insight schedule",
)
def delete_schedule(
    tenant_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Soft-deletes by setting enabled=False. Does not remove the row."""
    if current_user.role != "admin" and tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden.")

    schedule = (
        db.query(InsightSchedule)
        .filter(InsightSchedule.tenant_id == tenant_id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail=f"No schedule found for {tenant_id}.")

    schedule.enabled = False
    db.commit()
    logger.info("Disabled insight schedule for tenant %s", tenant_id)
    return {"ok": True, "tenant_id": tenant_id}
