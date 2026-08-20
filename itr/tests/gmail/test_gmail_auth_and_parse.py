"""Unit tests for Gmail auth URL + message parsing (no live Google calls)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from scout.gmail.auth import GmailStoredTokens, GmailTokenStore, build_authorization_url
from scout.gmail.client import parse_message


def test_build_authorization_url_contains_offline_consent():
    url = build_authorization_url(
        client_id="cid.apps.googleusercontent.com",
        redirect_uri="http://127.0.0.1:8089/",
    )
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "cid.apps.googleusercontent.com" in url
    assert "127.0.0.1" in url


def test_token_store_roundtrip(tmp_path: Path):
    path = tmp_path / "gmail_token.json"
    store = GmailTokenStore(path)
    tokens = GmailStoredTokens(
        access_token="a",
        refresh_token="r",
        expires_at=123.0,
    )
    store.save(tokens)
    loaded = store.load()
    assert loaded is not None
    assert loaded.refresh_token == "r"
    assert loaded.access_token == "a"
    assert json.loads(path.read_text())["refresh_token"] == "r"


def test_parse_message_plain_body():
    plain = base64.urlsafe_b64encode(b"Hello ticket world").decode().rstrip("=")
    raw = {
        "id": "m1",
        "threadId": "t1",
        "historyId": "99",
        "internalDate": "1700000000000",
        "snippet": "Hello…",
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Need help"},
                {"name": "From", "value": "user@example.com"},
                {"name": "To", "value": "motiveminds.itsupport@gmail.com"},
            ],
            "body": {"data": plain},
        },
    }
    msg = parse_message(raw)
    assert msg.id == "m1"
    assert msg.subject == "Need help"
    assert msg.body_text == "Hello ticket world"
    assert msg.from_header == "user@example.com"
