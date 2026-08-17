"""
Task 1 — prove the Gmail token can SEND.

Builds a plain-text email, base64url-encodes it, and calls
users.messages.send. Prints the returned message id and thread id.
Exits non-zero with a readable message when the token lacks the send scope.

No database access; no config beyond scout.config. Uses httpx directly,
consistent with scout/gmail/client.py — no googleapiclient dependency.

Usage:
  poetry run python scripts/gmail_send_test.py --to persona1@gmail.com
  poetry run python scripts/gmail_send_test.py --to a@b.com --subject "Hi" --body "Test"
"""

from __future__ import annotations

import argparse
import base64
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from scout.config import settings
from scout.gmail.auth import GmailTokenStore, refresh_access_token

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Recipient address")
    parser.add_argument("--subject", default="Scout send-scope test (Task 1)")
    parser.add_argument(
        "--body",
        default="This is a one-off test proving the Gmail token can send. Safe to ignore.",
    )
    args = parser.parse_args()

    store = GmailTokenStore(settings.gmail_token_path)
    tokens = store.load()
    if tokens is None:
        print(
            "No saved Gmail token. Run: poetry run python scripts/gmail_oauth_login.py",
            file=sys.stderr,
        )
        return 1

    if SEND_SCOPE not in (tokens.scope or ""):
        print(
            "Token lacks the gmail.send scope.\n"
            f"  granted: {tokens.scope}\n"
            "  Fix: rm secrets/gmail_token.json && "
            "poetry run python scripts/gmail_oauth_login.py\n"
            "  (and confirm gmail.send is on the OAuth consent screen in Google Cloud Console)",
            file=sys.stderr,
        )
        return 1

    # Fresh access token — the saved one may be expired.
    fresh = refresh_access_token(
        refresh_token=tokens.refresh_token,
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
    )
    store.save(fresh)

    msg = EmailMessage()
    msg["To"] = args.to
    msg["Subject"] = args.subject
    msg.set_content(args.body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    with httpx.Client(timeout=30.0) as client:
        res = client.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {fresh.access_token}"},
            json={"raw": raw},
        )

    if res.status_code == 403:
        print(
            "Gmail refused the send (403). The consent screen scope change may not\n"
            "have propagated, or consent was granted before gmail.send was added.\n"
            f"  response: {res.text[:300]}",
            file=sys.stderr,
        )
        return 1
    if res.status_code >= 400:
        print(f"Send failed: HTTP {res.status_code}\n  {res.text[:300]}", file=sys.stderr)
        return 1

    data = res.json()
    print(f"sent: message_id={data.get('id')} thread_id={data.get('threadId')}")
    print(f"  to: {args.to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
