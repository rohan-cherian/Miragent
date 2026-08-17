"""
Apply schema/002_src_gmail_raw.sql — the raw-lake dedup ledger.

Usage:
  poetry run python scripts/load_gmail_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.raw_ledger import GmailRawLedger


def main() -> int:
    ledger = GmailRawLedger(settings.gmail_database_url)
    ledger.ensure_schema()
    print("src_gmail raw ledger ready (raw_objects + raw_partition_seq + raw_sync_state).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
