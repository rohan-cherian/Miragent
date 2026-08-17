"""
Gmail integration (Desktop OAuth + readonly API).

Two independent pipelines share the auth/client layer:

  raw lake  — scout.gmail.raw_sync: EVERY message -> JSON -> MinIO raw bucket
  tickets   — scout.gmail.sync:     customer senders only -> src_gmail.tickets
"""

from scout.gmail.auth import (
    GmailTokenStore,
    build_authorization_url,
    exchange_code,
    refresh_access_token,
)
from scout.gmail.client import GmailClient, GmailMessage
from scout.gmail.envelope import build_envelope, serialise
from scout.gmail.raw_ledger import GmailRawLedger, RawSyncState
from scout.gmail.raw_sync import GmailRawSync, RawSyncResult, build_raw_sync
from scout.gmail.store import GmailTicketStore
from scout.gmail.sync import SyncResult, run_sync

__all__ = [
    "GmailClient",
    "GmailMessage",
    "GmailRawLedger",
    "GmailRawSync",
    "GmailTicketStore",
    "GmailTokenStore",
    "RawSyncResult",
    "RawSyncState",
    "SyncResult",
    "build_authorization_url",
    "build_envelope",
    "build_raw_sync",
    "exchange_code",
    "refresh_access_token",
    "run_sync",
    "serialise",
]
