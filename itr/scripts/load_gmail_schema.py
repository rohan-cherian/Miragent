"""
Apply the src_gmail schema files, in order:

  002_src_gmail_raw.sql      raw-lake dedup ledger + cursor
  003_src_gmail_regrain.sql  Task 5 grain: mailbox/thread/message/attachment

Both are re-runnable.

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
    print("src_gmail ready:")
    print("  ledger  raw_objects · raw_skipped · sync_state")
    print("  grain   mailbox · thread · message · attachment")
    print("  runs    raw_ingest.runs · raw_ingest.run_stage_event")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
