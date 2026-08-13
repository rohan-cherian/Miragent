"""
Phase 7 — Sync Gmail → Postgres every N seconds (default 60).

Ctrl+C to stop.

Usage:
  poetry run python scripts/gmail_sync_loop.py
  poetry run python scripts/gmail_sync_loop.py --interval 60
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.auth import GmailTokenStore
from scout.gmail.client import GmailClient
from scout.gmail.store import GmailTicketStore
from scout.gmail.sync import run_sync


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=60, help="Seconds between syncs")
    parser.add_argument("--max", type=int, default=100, help="Bootstrap max messages")
    args = parser.parse_args()

    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("Missing GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET", file=sys.stderr)
        return 1

    client = GmailClient(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_store=GmailTokenStore(settings.gmail_token_path),
        user_id="me",
        refresh_token_fallback=settings.gmail_refresh_token,
    )
    store = GmailTicketStore(settings.gmail_database_url)
    store.ensure_schema()

    print(f"Gmail sync loop every {args.interval}s — Ctrl+C to stop")
    while True:
        started = datetime.now(timezone.utc).isoformat()
        try:
            profile = client.get_profile()
            mailbox = (profile.get("emailAddress") or settings.gmail_user or "me").strip()
            result = run_sync(
                client=client,
                store=store,
                mailbox=mailbox,
                bootstrap_max=args.max,
            )
            print(
                f"[{started}] mode={result.mode} fetched={result.fetched} "
                f"inserted={result.inserted} dupes={result.skipped_duplicates} "
                f"total={store.count_tickets(mailbox)}"
            )
        except KeyboardInterrupt:
            print("Stopped.")
            return 0
        except Exception as exc:
            print(f"[{started}] ERROR: {exc}", file=sys.stderr)

        try:
            time.sleep(max(5, args.interval))
        except KeyboardInterrupt:
            print("Stopped.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
