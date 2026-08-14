"""
Gmail Desktop OAuth helpers (authorization code + refresh).

Uses httpx only — no Google client libraries required.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from scout.connectors.oauth2 import OAuth2Token

logger = logging.getLogger(__name__)

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


@dataclass
class GmailStoredTokens:
    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "Bearer"
    scope: str = DEFAULT_SCOPE

    def to_oauth2(self) -> OAuth2Token:
        return OAuth2Token(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=self.expires_at,
            token_type=self.token_type,
        )


class GmailTokenStore:
    """Persist tokens under ``secrets/gmail_token.json`` (gitignored)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> GmailStoredTokens | None:
        if not self.path.is_file():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        refresh = data.get("refresh_token") or ""
        access = data.get("access_token") or ""
        if not refresh:
            return None
        return GmailStoredTokens(
            access_token=access,
            refresh_token=refresh,
            expires_at=float(data.get("expires_at") or 0),
            token_type=data.get("token_type") or "Bearer",
            scope=data.get("scope") or DEFAULT_SCOPE,
        )

    def save(self, tokens: GmailStoredTokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(tokens), indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Gmail tokens saved to %s", self.path)


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scope: str = DEFAULT_SCOPE,
    state: str = "miragent-gmail",
) -> str:
    """Browser URL for Desktop OAuth consent."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",  # request refresh_token
        "prompt": "consent",  # force refresh_token even if previously granted
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URI}?{urlencode(params)}"


def exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> GmailStoredTokens:
    """Exchange one-time auth code for access + refresh tokens."""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    with httpx.Client(timeout=30.0) as client:
        res = client.post(TOKEN_URI, data=form)
        res.raise_for_status()
        data = res.json()
    return _tokens_from_response(data)


def refresh_access_token(
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> GmailStoredTokens:
    """Refresh an expired access token (keeps the same refresh_token)."""
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    with httpx.Client(timeout=30.0) as client:
        res = client.post(TOKEN_URI, data=form)
        res.raise_for_status()
        data = res.json()
    # Google often omits refresh_token on refresh — keep the old one
    if "refresh_token" not in data:
        data["refresh_token"] = refresh_token
    return _tokens_from_response(data)


def _tokens_from_response(data: dict[str, Any]) -> GmailStoredTokens:
    expires_in = int(data.get("expires_in") or 3600)
    refresh = data.get("refresh_token")
    if not refresh:
        raise ValueError(
            "No refresh_token in Google response. Re-run login with prompt=consent "
            "and ensure access_type=offline."
        )
    return GmailStoredTokens(
        access_token=data["access_token"],
        refresh_token=refresh,
        expires_at=time.time() + expires_in,
        token_type=data.get("token_type") or "Bearer",
        scope=data.get("scope") or DEFAULT_SCOPE,
    )
