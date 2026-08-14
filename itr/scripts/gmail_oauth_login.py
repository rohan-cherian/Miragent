"""
Phase 2 — Desktop OAuth login for Gmail (one-time).

Opens a browser, captures the redirect on GMAIL_REDIRECT_URI, saves tokens to
secrets/gmail_token.json, and writes GMAIL_REFRESH_TOKEN into .env.local.

Prereq in Google Cloud Console (Desktop client):
  Authorized redirect URI must include exactly:
    http://127.0.0.1:8089/
  (or whatever GMAIL_REDIRECT_URI is in .env.local)

Usage:
  poetry run python scripts/gmail_oauth_login.py
"""

from __future__ import annotations

import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.config import settings
from scout.gmail.auth import (
    GmailTokenStore,
    build_authorization_url,
    exchange_code,
)


def _parse_host_port(redirect_uri: str) -> tuple[str, int]:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port:
        return host, parsed.port
    return host, 80 if parsed.scheme == "http" else 443


def _upsert_env_local(refresh_token: str) -> None:
    path = ROOT / ".env.local"
    line = f"GMAIL_REFRESH_TOKEN={refresh_token}"
    if not path.is_file():
        try:
            path.write_text(line + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"Could not create .env.local ({exc}). Token file is enough.", file=sys.stderr)
        return
    text = path.read_text(encoding="utf-8")
    if re.search(r"^GMAIL_REFRESH_TOKEN=", text, flags=re.M):
        text = re.sub(
            r"^GMAIL_REFRESH_TOKEN=.*$",
            line,
            text,
            flags=re.M,
        )
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    try:
        path.write_text(text, encoding="utf-8")
    except PermissionError:
        print(
            "Could not update .env.local (file may be open/locked in the editor).\n"
            "That is OK — tokens are already in secrets/gmail_token.json.\n"
            "Optional: close .env.local, then add this line manually:\n"
            f"  {line}",
            file=sys.stderr,
        )


def main() -> int:
    client_id = settings.gmail_client_id.strip()
    client_secret = settings.gmail_client_secret.strip()
    redirect_uri = settings.gmail_redirect_uri.strip()
    scope = settings.gmail_scopes.strip()

    if not client_id or not client_secret:
        print("Missing GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET in .env.local", file=sys.stderr)
        return 1

    host, port = _parse_host_port(redirect_uri)
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            if "code" in qs:
                result["code"] = qs["code"][0]
                body = b"<html><body><h2>Gmail connected.</h2>You can close this tab.</body></html>"
                self.send_response(200)
            else:
                err = qs.get("error", ["unknown"])[0]
                result["error"] = err
                body = f"<html><body><h2>Auth failed: {err}</h2></body></html>".encode()
                self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    server = HTTPServer((host, port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    auth_url = build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
    )
    print("Opening browser for Google consent…")
    print(f"Redirect URI (must match Console): {redirect_uri}")
    print(f"Listening on {host}:{port}")
    print(auth_url)
    webbrowser.open(auth_url)

    thread.join(timeout=300)
    server.server_close()

    if "error" in result:
        print(f"OAuth error: {result['error']}", file=sys.stderr)
        return 1
    if "code" not in result:
        print("Timed out waiting for OAuth redirect (no code).", file=sys.stderr)
        print(
            "Add this exact redirect URI in Google Cloud Console → Credentials → your Desktop client:\n"
            f"  {redirect_uri}",
            file=sys.stderr,
        )
        return 1

    tokens = exchange_code(
        code=result["code"],
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    store = GmailTokenStore(settings.gmail_token_path)
    store.save(tokens)
    _upsert_env_local(tokens.refresh_token)

    print("Success.")
    print(f"  Tokens: {store.path}")
    print("  GMAIL_REFRESH_TOKEN written to .env.local")
    print("Next: poetry run python scripts/gmail_read_sample.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
