"""
Gmail integration (Desktop OAuth + readonly API).

Phase 2–3: authenticate and read messages.
Later phases: connector, Postgres tickets, 1-minute sync.
"""

from scout.gmail.auth import GmailTokenStore, build_authorization_url, exchange_code, refresh_access_token
from scout.gmail.client import GmailClient, GmailMessage
from scout.gmail.store import GmailTicketStore
from scout.gmail.sync import SyncResult, run_sync

__all__ = [
    "GmailClient",
    "GmailMessage",
    "GmailTicketStore",
    "GmailTokenStore",
    "SyncResult",
    "build_authorization_url",
    "exchange_code",
    "refresh_access_token",
    "run_sync",
]
