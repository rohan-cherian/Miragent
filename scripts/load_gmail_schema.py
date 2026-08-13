"""Apply schema/002_src_gmail_schema.sql to Postgres."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.store import GmailTicketStore


def main() -> int:
    dsn = settings.gmail_database_url.strip()
    print(f"DSN: {dsn}")
    store = GmailTicketStore(dsn)
    store.ensure_schema()
    print("src_gmail schema ready (sync_state + tickets).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
