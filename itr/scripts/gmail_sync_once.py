"""
Gmail -> MinIO raw bucket, one run.

Writes every new message as raw/gmail/YYYY/MM/DD/email_NNN.json.
Safe to run repeatedly — the ledger guarantees no message is written twice.

Setup (first time):
  poetry run python scripts/load_gmail_schema.py
  poetry run python scripts/minio_smoke_test.py

Usage:
  poetry run python scripts/gmail_sync_once.py
  poetry run python scripts/gmail_sync_once.py --max 50
  poetry run python scripts/gmail_sync_once.py --list
  poetry run python scripts/gmail_sync_once.py --backfill   # walk whole mailbox
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.raw_ledger import GmailRawLedger
from scout.gmail.sync import build_raw_sync
from scout.raw.minio_client import RawLakeClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=None, help="Max messages this run")
    parser.add_argument("--list", action="store_true", help="List recent ledger rows after sync")
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Keep running until the whole mailbox is ingested",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("Missing GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET", file=sys.stderr)
        return 1

    ledger = GmailRawLedger(settings.gmail_database_url)
    ledger.ensure_schema()

    lake = RawLakeClient()
    lake.ensure_bucket()

    sync = build_raw_sync(ledger=ledger, lake=lake)
    if args.max is not None:
        sync.max_per_run = args.max

    print(f"Mailbox : {sync.account_id}")
    print(f"Target  : {lake.endpoint}/{lake.bucket}/{sync.prefix}/YYYY/MM/DD/")

    try:
        rounds = 0
        while True:
            rounds += 1
            result = sync.run()
            print(f"[round {rounds}] {result.summary()}")
            for err in result.errors[:5]:
                print(f"    error: {err}", file=sys.stderr)
            if not args.backfill:
                break
            if result.backfill_done or (result.written == 0 and result.failed == 0):
                print(f"Backfill complete after {rounds} round(s).")
                break
    finally:
        sync.client.close()

    counts = ledger.counts(sync.account_id)
    print(f"Ledger  : written={counts['written']} skipped={counts['skipped']}")

    if args.list:
        for row in ledger.recent(sync.account_id, limit=20):
            print(
                f"  {row['object_key']}  {row['size_bytes'] or 0} bytes  "
                f"att={row['attachment_count']}"
            )
        for row in ledger.recent_skips(sync.account_id, limit=10):
            print(f"  SKIPPED {row['gmail_message_id']}  {row['reason']}: {row['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
