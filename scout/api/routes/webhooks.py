"""
scout/api/routes/webhooks.py — Webhook Ingestion Endpoints (Sprint 27)

Receives real-time events from connected source systems and routes them
through the WebhookProcessor pipeline.

Flow per incoming webhook:
  1. Verify HMAC-SHA256 signature (per-source secret from env vars)
  2. Persist WebhookEvent row (idempotency_key prevents duplicate processing)
  3. Call persist_and_process() — synchronous in this implementation;
     a production setup would hand off to Celery/SQS after persisting.
  4. Return HTTP 200 immediately (source systems require fast acks)

Source systems supported:
  - Salesforce (HMAC via X-Salesforce-Signature)
  - HubSpot    (HMAC via X-HubSpot-Signature)
  - Workday    (HMAC via X-Workday-Signature)
  - NetSuite   (HMAC via X-NetSuite-Signature)
  - Generic    (no auth — internal/testing only)

Security:
  - Signature verification is enforced when the matching env var is set
  - Missing signature header → 401 when secret is configured
  - Invalid signature → 401
  - No secret configured → warning logged, request accepted (dev mode)

Idempotency:
  - Source systems may retry on network failure; idempotency_key (the
    source's delivery ID) prevents duplicate action emission.
  - If a key is already in the DB, the endpoint returns 200 immediately.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from scout.db.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# ── Payload and response models ────────────────────────────────────────────────

class WebhookPayload(BaseModel):
    """
    Universal webhook payload shape accepted by all Scout webhook endpoints.

    Source systems normalize their event payloads to this structure before
    POSTing. The `records` list contains the raw changed objects in the
    same format as bulk extraction responses.
    """
    source: str            # sfdc | workday | netsuite | hubspot | generic
    event_type: str        # opportunity.updated | worker.terminated | po.approved | etc.
    tenant_id: str         # Scout tenant this event belongs to
    records: list[dict]    # raw changed records from the source system
    delivery_id: str | None = None  # source's unique delivery ID (for idempotency)


class WebhookResponse(BaseModel):
    """Confirmation envelope returned to the source system after ingestion."""
    received: bool
    event_type: str
    record_count: int
    event_id: str | None = None          # Scout's WebhookEvent ID
    actions_triggered: int = 0           # how many actions were created/updated


# ── Signature verification ─────────────────────────────────────────────────────

def _verify_hmac(secret: str, payload_bytes: bytes, signature: str) -> bool:
    """
    Verify an HMAC-SHA256 signature against the raw request body.

    Uses hmac.compare_digest for constant-time comparison (prevents timing
    attacks). Strips the common "sha256=" prefix if present.
    """
    if signature.startswith("sha256="):
        signature = signature[7:]

    computed = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


def _check_signature(
    source_name: str,
    env_var: str,
    header_value: str | None,
    raw_body: bytes,
) -> None:
    """
    Enforce HMAC verification when the secret env var is configured.
    Raises HTTPException(401) on failure. Logs a warning and continues
    when no secret is set (development mode).
    """
    secret = os.environ.get(env_var, "")
    if not secret:
        logger.warning(
            f"{env_var} not set — skipping {source_name} signature verification. "
            "Set this variable before exposing to the internet."
        )
        return

    if not header_value:
        raise HTTPException(
            status_code=401,
            detail=f"Missing {source_name} signature header",
        )

    if not _verify_hmac(secret, raw_body, header_value):
        raise HTTPException(
            status_code=401,
            detail=f"Invalid {source_name} webhook signature",
        )


# ── Shared ingestion logic ─────────────────────────────────────────────────────

def _ingest(
    source: str,
    payload: WebhookPayload,
    db: Session,
) -> WebhookResponse:
    """
    Persist and process a webhook event. Shared by all source-specific endpoints.

    Each record in payload.records is treated as a separate event so that
    partial failures don't block the entire batch. The delivery_id is used
    as the idempotency key when provided.
    """
    from scout.actions.webhook_processor import persist_and_process

    all_action_ids: list[str] = []
    first_event_id: str | None = None

    for i, record in enumerate(payload.records):
        # Build per-record payload: merge top-level context with the record
        event_payload = {
            "source": source,
            "event_type": payload.event_type,
            **record,
        }

        # Idempotency key: delivery_id + record index (or record's own ID)
        record_id = record.get("Id") or record.get("canonical_id") or str(i)
        idem_key = (
            f"{source}:{payload.tenant_id}:{payload.delivery_id}:{record_id}"
            if payload.delivery_id
            else None
        )

        event, action_ids = persist_and_process(
            db=db,
            source=source,
            event_type=payload.event_type,
            tenant_id=payload.tenant_id,
            payload=event_payload,
            idempotency_key=idem_key,
        )

        if first_event_id is None:
            first_event_id = event.id
        all_action_ids.extend(action_ids)

    db.commit()

    logger.info(
        f"Webhook ingested: source={source} event_type={payload.event_type} "
        f"records={len(payload.records)} actions={len(all_action_ids)} "
        f"tenant={payload.tenant_id}"
    )

    return WebhookResponse(
        received=True,
        event_type=payload.event_type,
        record_count=len(payload.records),
        event_id=first_event_id,
        actions_triggered=len(all_action_ids),
    )


# ── Salesforce ─────────────────────────────────────────────────────────────────

@router.post(
    "/salesforce",
    response_model=WebhookResponse,
    summary="Salesforce change event webhook",
)
async def salesforce_webhook(
    request: Request,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
    x_salesforce_signature: Optional[str] = Header(default=None),
) -> WebhookResponse:
    """
    Receive real-time Salesforce change events (Platform Events or Outbound Messaging).

    Persists each record as a WebhookEvent and dispatches to the appropriate
    handler (opportunity.updated, contact.terminated, account.updated, etc.).
    """
    raw_body = await request.body()
    _check_signature("Salesforce", "SALESFORCE_WEBHOOK_SECRET", x_salesforce_signature, raw_body)
    return _ingest("sfdc", payload, db)


# ── HubSpot ────────────────────────────────────────────────────────────────────

@router.post(
    "/hubspot",
    response_model=WebhookResponse,
    summary="HubSpot event webhook",
)
async def hubspot_webhook(
    request: Request,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
    x_hubspot_signature: Optional[str] = Header(default=None),
) -> WebhookResponse:
    """
    Receive HubSpot contact, company, and deal change events.

    Uses HubSpot's HMAC-SHA256 (v2) signature scheme.
    """
    raw_body = await request.body()
    _check_signature("HubSpot", "HUBSPOT_WEBHOOK_SECRET", x_hubspot_signature, raw_body)
    return _ingest("hubspot", payload, db)


# ── Workday ────────────────────────────────────────────────────────────────────

@router.post(
    "/workday",
    response_model=WebhookResponse,
    summary="Workday HR event webhook",
)
async def workday_webhook(
    request: Request,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
    x_workday_signature: Optional[str] = Header(default=None),
) -> WebhookResponse:
    """
    Receive real-time HR events from Workday (terminations, new hires, comp changes).

    Dispatches immediately so offboarding actions are created within minutes
    of a termination event, not at the next nightly scan.
    """
    raw_body = await request.body()
    _check_signature("Workday", "WORKDAY_WEBHOOK_SECRET", x_workday_signature, raw_body)
    return _ingest("workday", payload, db)


# ── NetSuite ───────────────────────────────────────────────────────────────────

@router.post(
    "/netsuite",
    response_model=WebhookResponse,
    summary="NetSuite financial event webhook",
)
async def netsuite_webhook(
    request: Request,
    payload: WebhookPayload,
    db: Session = Depends(get_db),
    x_netsuite_signature: Optional[str] = Header(default=None),
) -> WebhookResponse:
    """
    Receive real-time NetSuite events (PO approvals, invoice creation, contract renewals).

    PO approvals and contract renewals immediately trigger evidence completion
    checks so the corresponding RemediationActions are marked COMPLETE without
    waiting for the next evidence scanner cycle.
    """
    raw_body = await request.body()
    _check_signature("NetSuite", "NETSUITE_WEBHOOK_SECRET", x_netsuite_signature, raw_body)
    return _ingest("netsuite", payload, db)


# ── Generic (internal / testing) ──────────────────────────────────────────────

@router.post(
    "/generic",
    response_model=WebhookResponse,
    summary="Generic webhook (internal/testing only — no auth)",
)
async def generic_webhook(
    payload: WebhookPayload,
    db: Session = Depends(get_db),
) -> WebhookResponse:
    """
    No-auth webhook endpoint for local development and CI/CD testing.

    Routes to the same processor as the signed endpoints. Block via
    network policy (firewall, API gateway) before exposing externally.
    """
    logger.warning(
        "Generic webhook used — ensure network policy blocks external access in production. "
        f"source={payload.source} event_type={payload.event_type} tenant={payload.tenant_id}"
    )
    return _ingest(payload.source, payload, db)
