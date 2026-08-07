"""
Zendesk webhook emission with HMAC-SHA256 signing.

Signature contract (Zendesk docs)::

    X-Zendesk-Webhook-Signature = base64(HMAC_SHA256(timestamp + body, secret))
    X-Zendesk-Webhook-Signature-Timestamp = <ISO-8601>

Used as the write-path side effect for ticket updates so next week's event
listener can verify authenticity the same way production does.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from scout.emulators.zendesk.store import ZendeskStore


def sign_payload(*, body: str, timestamp: str, secret: str) -> str:
    """Return base64 HMAC-SHA256 of ``timestamp + body``."""
    digest = hmac.new(
        secret.encode("utf-8"),
        (timestamp + body).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    import base64

    return base64.b64encode(digest).decode("ascii")


def verify_signature(
    *,
    body: str,
    timestamp: str,
    signature: str,
    secret: str,
) -> bool:
    """Constant-time check that ``signature`` matches the Zendesk HMAC."""
    expected = sign_payload(body=body, timestamp=timestamp, secret=secret)
    return hmac.compare_digest(expected, signature)


def build_ticket_event_payload(
    ticket: dict[str, Any],
    *,
    account_id: int,
    event_type: str = "zen:event-type:ticket.StatusChanged",
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Zendesk-shaped ticket event webhook body."""
    ticket_id = ticket["id"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "type": event_type,
        "account_id": account_id,
        "id": str(uuid.uuid4()),
        "time": now,
        "zendesk_event_version": "2022-06-20",
        "subject": f"zen:ticket:{ticket_id}",
        "detail": {
            "id": str(ticket_id),
            "subject": ticket.get("subject"),
            "status": ticket.get("status"),
            "priority": ticket.get("priority"),
            "requester_id": str(ticket.get("requester_id") or ""),
            "assignee_id": str(ticket.get("assignee_id") or ""),
            "organization_id": str(ticket.get("organization_id") or ""),
            "created_at": ticket.get("created_at"),
            "updated_at": ticket.get("updated_at"),
        },
        "event": {
            "current": {
                "status": ticket.get("status"),
                "priority": ticket.get("priority"),
            },
            "previous": previous or {},
        },
    }


def emit_ticket_webhook(
    store: ZendeskStore,
    ticket: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    event_type: str = "zen:event-type:ticket.StatusChanged",
) -> dict[str, Any]:
    """
    Sign and record a webhook delivery for a ticket change.

    Always appends to ``store.emitted_webhooks``. Does not HTTP-POST unless
    a future listener configures ``store.webhook_url`` (out of scope here —
    emission + HMAC is the contract for week four).
    """
    payload = build_ticket_event_payload(
        ticket,
        account_id=store.account_id,
        event_type=event_type,
        previous=previous,
    )
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    timestamp = payload["time"]
    signature = sign_payload(
        body=body,
        timestamp=timestamp,
        secret=store.webhook_secret,
    )
    headers = {
        "Content-Type": "application/json",
        "X-Zendesk-Webhook-Signature": signature,
        "X-Zendesk-Webhook-Signature-Timestamp": timestamp,
        "X-Zendesk-Account-Id": str(store.account_id),
    }
    delivery = {
        "url": store.webhook_url,
        "headers": headers,
        "body": body,
        "payload": payload,
    }
    store.record_webhook(delivery)
    return delivery
