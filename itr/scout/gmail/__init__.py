"""
Gmail integration (Desktop OAuth + readonly API).

Raw lake pipeline only:
  scout.gmail.raw_sync — EVERY message -> JSON -> MinIO raw bucket
"""

from scout.gmail.auth import (
    GmailTokenStore,
    build_authorization_url,
    exchange_code,
    refresh_access_token,
)
from scout.gmail.client import GmailClient, GmailMessage
from scout.gmail.customers import (
    DEFAULT_CUSTOMER_SENDERS,
    extract_email_address,
    gmail_from_query,
    is_customer_sender,
    parse_sender_list,
)
from scout.gmail.envelope import build_envelope, serialise
from scout.gmail.raw_ledger import GmailRawLedger, RawSyncState
from scout.gmail.raw_sync import GmailRawSync, RawSyncResult, build_raw_sync

__all__ = [
    "DEFAULT_CUSTOMER_SENDERS",
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
    "extract_email_address",
    "gmail_from_query",
    "is_customer_sender",
    "parse_sender_list",
    "refresh_access_token",
    "serialise",
]
