"""
Phase 5–6 — Sync Gmail inbox → src_gmail.tickets (one run).

Usage:
  poetry run python scripts/load_gmail_schema.py
  poetry run python scripts/gmail_sync_once.py
  poetry run python scripts/gmail_sync_once.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.auth import GmailTokenStore
from scout.gmail.client import GmailClient
from scout.gmail.store import GmailTicketStore
from scout.gmail.sync import run_sync


def _client() -> GmailClient:
    return GmailClient(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_store=GmailTokenStore(settings.gmail_token_path),
        user_id="me",
        refresh_token_fallback=settings.gmail_refresh_token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List tickets after sync")
    parser.add_argument("--max", type=int, default=100, help="Bootstrap max messages")
    args = parser.parse_args()

    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("Missing GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET", file=sys.stderr)
        return 1

    client = _client()
    profile = client.get_profile()
    mailbox = (profile.get("emailAddress") or settings.gmail_user or "me").strip()
    store = GmailTicketStore(settings.gmail_database_url)

    result = run_sync(
        client=client,
        store=store,
        mailbox=mailbox,
        bootstrap_max=args.max,
    )
    print(
        f"mailbox={result.mailbox} mode={result.mode} "
        f"fetched={result.fetched} inserted={result.inserted} "
        f"skipped_dupes={result.skipped_duplicates} "
        f"history_id={result.history_id} "
        f"total_tickets={store.count_tickets(mailbox)}"
    )

    if args.list:
        for row in store.list_tickets(mailbox, limit=20):
            print(
                f"  #{row['ticket_id']}  {row['gmail_message_id']}  "
                f"{row['subject']!r}  from={row['from_address']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
