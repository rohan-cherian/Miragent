"""
Gmail ingestion API — push receiver + manual trigger + status.

Lives under ``scout/gmail/`` deliberately: ``scout/api/`` belongs to the
console API (Slice-1 Task 24, Sutej), and the Task 4 layering lint forbids
that package from importing ``scout.gmail``. Ingestion HTTP surface therefore
ships with the adapter that owns it.

Gmail has no plain HTTP webhook. Real push is: ``users.watch`` -> Pub/Sub
topic -> Pub/Sub POSTs a push message to a public HTTPS endpoint. This module
is that endpoint.

The notification body carries only ``{emailAddress, historyId}`` — never the
mail itself — so the handler just triggers the same sync the poller runs.
That makes push a latency optimisation over the 60s loop, not a second
ingestion path with its own bugs.

Endpoints:
  POST /gmail/push    Pub/Sub push target (guard with ?token=<shared secret>)
  POST /gmail/sync    manual trigger, same work, for testing
  GET  /gmail/status  ledger counts + cursor

Run:
  poetry run uvicorn scout.gmail.ingest_api:create_app --factory --port 8092
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, BackgroundTasks, FastAPI, Query, Request, Response, status

from scout.config import settings
from scout.gmail.raw_ledger import GmailRawLedger
from scout.gmail.raw_sync import build_raw_sync

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gmail"])

# Serialise syncs. Pub/Sub can deliver a burst of notifications for one batch
# of mail; without this they would race and waste Gmail quota re-fetching the
# same ids. Correctness does not depend on it — the ledger does — but quota does.
_sync_lock = threading.Lock()


def _decode_push_body(body: dict[str, Any]) -> dict[str, Any]:
    """
    Unwrap the Pub/Sub envelope.

    ``{"message": {"data": "<base64 of {emailAddress, historyId}>"}, ...}``
    """
    message = body.get("message") or {}
    data = message.get("data")
    if not data:
        return {}
    try:
        padded = data + "=" * (-len(data) % 4)
        return json.loads(base64.b64decode(padded).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        logger.warning("Undecodable Pub/Sub payload: %s", exc)
        return {}


def run_sync_now(account_id: str | None = None) -> dict[str, Any]:
    """Run one raw sync. Safe to call from a background task or a script."""
    if not _sync_lock.acquire(blocking=False):
        logger.info("Sync already running; skipping this trigger")
        return {"skipped": True, "reason": "sync already running"}
    try:
        sync = build_raw_sync(account_id=account_id)
        try:
            result = sync.run()
        finally:
            sync.client.close()
        logger.info("Gmail raw sync: %s", result.summary())
        return {
            "account_id": result.account_id,
            "mode": result.mode,
            "discovered": result.discovered,
            "written": result.written,
            "duplicates_skipped": result.skipped_known + result.skipped_duplicates,
            "skipped_non_customer": result.skipped_non_customer,
            "skipped_malformed": result.skipped_malformed,
            "failed": result.failed,
            "attachments_written": result.attachments_written,
            "bytes_written": result.bytes_written,
            "backfill_done": result.backfill_done,
            "history_id": result.history_id,
            "errors": result.errors[:10],
        }
    finally:
        _sync_lock.release()


@router.post("/gmail/push", status_code=status.HTTP_204_NO_CONTENT)
async def gmail_push(
    request: Request,
    background: BackgroundTasks,
    token: str = Query("", description="Shared secret matching GMAIL_PUSH_SHARED_SECRET"),
) -> Response:
    """
    Pub/Sub push target.

    Always ACKs with 204 unless the shared secret is wrong. A non-2xx makes
    Pub/Sub redeliver with backoff, and since the poller catches anything
    missed, redelivery storms cost more than they fix.
    """
    expected = settings.gmail_push_shared_secret
    if expected and token != expected:
        logger.warning("Rejected Gmail push with bad token")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        body = await request.json()
    except Exception:
        body = {}

    payload = _decode_push_body(body if isinstance(body, dict) else {})
    account = payload.get("emailAddress")
    logger.info(
        "Gmail push received (account=%s historyId=%s)",
        account,
        payload.get("historyId"),
    )
    background.add_task(run_sync_now, account)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/gmail/sync")
def gmail_sync_trigger(account_id: str | None = None) -> dict[str, Any]:
    """Manual trigger — runs the sync inline and returns the result."""
    return run_sync_now(account_id)


@router.get("/gmail/status")
def gmail_status(account_id: str | None = None) -> dict[str, Any]:
    ledger = GmailRawLedger(settings.gmail_database_url)
    resolved = account_id
    if not resolved:
        sync = build_raw_sync(ledger=ledger)
        try:
            resolved = sync.account_id
        finally:
            sync.client.close()
    state = ledger.get_state(resolved)
    return {
        "account_id": resolved,
        "bucket": settings.minio_bucket,
        "endpoint": settings.minio_endpoint,
        "prefix": settings.gmail_raw_prefix,
        "counts": ledger.counts(resolved),
        "backfill_done": state.backfill_done if state else False,
        "history_id": state.history_id if state else None,
        "last_synced_at": state.last_synced_at.isoformat()
        if state and state.last_synced_at
        else None,
        "watch_expiration_ms": state.watch_expiration_ms if state else None,
        "recent": [
            {**row, "written_at": row["written_at"].isoformat() if row["written_at"] else None}
            for row in ledger.recent(resolved, limit=10)
        ],
        "recent_skips": [
            {**row, "seen_at": row["seen_at"].isoformat() if row["seen_at"] else None}
            for row in ledger.recent_skips(resolved, limit=10)
        ],
    }


def create_app() -> FastAPI:
    """App factory for the standalone ingestion service (port 8092)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(
        title="ITR Gmail Ingestion API",
        version="0.1.0",
        description="Gmail push receiver and raw-lake ingestion triggers.",
    )
    app.include_router(router)

    @app.get("/health", tags=["ops"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "bucket": settings.minio_bucket,
            "endpoint": settings.minio_endpoint,
        }

    return app
