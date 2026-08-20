"""
Gmail integration (Desktop OAuth + readonly API).

Raw lake pipeline only:
  scout.gmail.sync — EVERY message -> JSON -> MinIO raw bucket
  (Task 8 still drops system / bulk mail)
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
from scout.gmail.sync import GmailRawSync, RawSyncResult, build_raw_sync

__all__ = [
    "GmailClient",
    "GmailMessage",
    "GmailRawLedger",
    "GmailRawSync",
    "GmailTokenStore",
    "RawSyncResult",
    "RawSyncState",
    "build_authorization_url",
    "build_envelope",
    "build_raw_sync",
    "exchange_code",
    "refresh_access_token",
    "serialise",
]
