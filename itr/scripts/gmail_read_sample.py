"""
Phase 3 — Read recent Gmail messages (readonly).

Requires a prior successful:
  poetry run python scripts/gmail_oauth_login.py

Usage:
  poetry run python scripts/gmail_read_sample.py
  poetry run python scripts/gmail_read_sample.py --max 5
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
from scout.gmail.client import GmailClient, format_internal_date


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=5, help="Max messages to fetch")
    parser.add_argument("--q", default=None, help="Optional Gmail search query")
    args = parser.parse_args()

    if not settings.gmail_client_id or not settings.gmail_client_secret:
        print("Missing GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET in .env.local", file=sys.stderr)
        return 1

    client = GmailClient(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        token_store=GmailTokenStore(settings.gmail_token_path),
        user_id="me",
        refresh_token_fallback=settings.gmail_refresh_token,
    )

    profile = client.get_profile()
    print(f"Mailbox: {profile.get('emailAddress')}  messages={profile.get('messagesTotal')}")
    expected = settings.gmail_user.strip().lower()
    actual = (profile.get("emailAddress") or "").lower()
    if expected and expected not in {"me", ""} and actual != expected:
        print(
            f"WARNING: logged-in mailbox is {actual!r}, expected {expected!r}. "
            "Re-run gmail_oauth_login.py while signed into the correct Google account.",
            file=sys.stderr,
        )

    messages = client.fetch_messages(max_results=args.max, q=args.q)
    if not messages:
        print("No messages returned.")
        return 0

    for i, msg in enumerate(messages, 1):
        print("-" * 60)
        print(f"{i}. id={msg.id}  thread={msg.thread_id}")
        print(f"   date={format_internal_date(msg.internal_date_ms)}")
        print(f"   from={msg.from_header}")
        print(f"   subject={msg.subject}")
        preview = (msg.body_text or msg.snippet or "")[:200].replace("\n", " ")
        print(f"   body={preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
