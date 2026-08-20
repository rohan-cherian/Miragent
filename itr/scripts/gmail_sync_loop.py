"""
Gmail -> MinIO raw bucket, every N seconds (default 60).

This is the workhorse. Even with Pub/Sub push enabled, keep this running:
Gmail watches expire after 7 days and push delivery is best-effort, so the
poller is what makes the pipeline eventually consistent regardless.

Ctrl+C to stop.

Usage:
  poetry run python scripts/gmail_sync_loop.py
  poetry run python scripts/gmail_sync_loop.py --interval 60 --max 200
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
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
    parser.add_argument("--interval", type=int, default=60, help="Seconds between syncs")
    parser.add_argument("--max", type=int, default=None, help="Max messages per run")
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
    ledger.ensure_schema()  # once at startup, not once per tick

    lake = RawLakeClient()
    lake.ensure_bucket()

    sync = build_raw_sync(ledger=ledger, lake=lake)
    if args.max is not None:
        sync.max_per_run = args.max

    interval = max(10, args.interval)
    print(f"Mailbox : {sync.account_id}")
    print(f"Target  : {lake.endpoint}/{lake.bucket}/{sync.prefix}/YYYY/MM/DD/")
    print(f"Gmail raw sync loop every {interval}s - Ctrl+C to stop")

    try:
        while True:
            started = datetime.now(timezone.utc).isoformat(timespec="seconds")
            try:
                result = sync.run()
                counts = ledger.counts(sync.account_id)
                print(f"[{started}] {result.summary()} ledger_total={counts['written']}")
                for err in result.errors[:3]:
                    print(f"    error: {err}", file=sys.stderr)
            except Exception as exc:
                # Never let one bad tick kill the loop; nothing is marked
                # stored unless its PUT succeeded, so the next tick retries it.
                print(f"[{started}] ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        sync.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
