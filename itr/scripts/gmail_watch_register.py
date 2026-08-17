"""
Register / renew / stop Gmail push notifications (Cloud Pub/Sub).

Gmail has no plain HTTP webhook. Push requires, in Google Cloud:
  1. A Pub/Sub topic, e.g. projects/<proj>/topics/gmail-scout
  2. gmail-api-push@system.gserviceaccount.com granted Pub/Sub Publisher on it
  3. A push subscription pointing at your PUBLIC HTTPS endpoint:
       https://<your-host>/gmail/push?token=<GMAIL_PUSH_SHARED_SECRET>
Then this script calls users.watch to start delivery.

A watch expires after 7 days — re-run this at least weekly. The 60s poller
covers any gap, which is why it stays on regardless.

Usage:
  poetry run python scripts/gmail_watch_register.py
  poetry run python scripts/gmail_watch_register.py --topic projects/p/topics/t
  poetry run python scripts/gmail_watch_register.py --stop
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.auth import GmailTokenStore
from scout.gmail.client import GmailClient
from scout.gmail.raw_ledger import GmailRawLedger, RawSyncState


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default=settings.gmail_pubsub_topic, help="Pub/Sub topic")
    parser.add_argument("--stop", action="store_true", help="Stop push notifications")
    args = parser.parse_args()

    client = GmailClient(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_store=GmailTokenStore(settings.gmail_token_path),
        user_id="me",
        refresh_token_fallback=settings.gmail_refresh_token,
    )

    try:
        profile = client.get_profile()
        account = (profile.get("emailAddress") or "me").strip()

        if args.stop:
            client.stop_watch()
            print(f"Push notifications stopped for {account}.")
            return 0

        if not args.topic:
            print(
                "No Pub/Sub topic. Set GMAIL_PUBSUB_TOPIC in .env.local or pass --topic\n"
                "  e.g. projects/my-project/topics/gmail-scout\n\n"
                "Push is optional - scripts/gmail_sync_loop.py already syncs every 60s.",
                file=sys.stderr,
            )
            return 1

        labels = [x.strip() for x in settings.gmail_push_label_ids.split(",") if x.strip()]
        res = client.watch(topic_name=args.topic, label_ids=labels or None)
        expiration = res.get("expiration")
        expires_at = (
            datetime.fromtimestamp(int(expiration) / 1000.0, tz=timezone.utc).isoformat()
            if expiration
            else "unknown"
        )

        ledger = GmailRawLedger(settings.gmail_database_url)
        ledger.ensure_schema()
        state = ledger.get_state(account) or RawSyncState(account_id=account)
        state.watch_expiration_ms = int(expiration) if expiration else None
        ledger.save_state(state)

        print(f"Watch registered for {account}")
        print(f"  topic      : {args.topic}")
        print(f"  historyId  : {res.get('historyId')}")
        print(f"  expires    : {expires_at}  (re-run within 7 days)")
        print(f"  labels     : {labels or 'all mail'}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
