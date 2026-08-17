"""
itr/scout/gmail/mime.py — Gmail message dict -> ParsedMessage (Task 7).

Pure functions only: no network calls, no database, no config. Give it a
``format=full`` Gmail message dict, get back a ParsedMessage.

Two things make this more than a field-copier:

* **Quoted history is stripped.** "Plain text, else snippet" is too thin for
  real mail — a reply that carries the whole thread inline poisons every
  downstream embedding and prompt with text the sender never wrote.

* **The signature is extracted BEFORE stripping, and kept.** At Task 14 the
  signature block is the identity signal for senders not yet in the alias
  table. Discard it and the unknown-sender path has almost nothing to work
  with. Order matters: strip first and a signature sitting above the quoted
  history is lost, while one buried inside the quote is wrongly promoted.

MIME primitives (base64url decoding, recursive part walking, text/plain
preference, HTML fallback) are imported from ``envelope`` rather than written
again — two parsers over the same input drift apart, and the raw lake and the
canonical row must never disagree about what an email said.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from scout.gmail.envelope import _strip_tags, extract_bodies

__all__ = ["ParsedMessage", "MimeParseError", "parse_message", "split_signature", "strip_quoted"]


class MimeParseError(ValueError):
    """Raised when a message cannot be parsed. Never return partial data."""


@dataclass
class ParsedMessage:
    """One Gmail message, flattened. Field names match src_gmail.message."""

    external_id: str
    thread_external_id: str
    subject: str | None = None
    from_address: str | None = None
    from_display_name: str | None = None
    reply_to: str | None = None
    to_addresses: list[str] = field(default_factory=list)
    cc_addresses: list[str] = field(default_factory=list)
    in_reply_to: str | None = None
    references_header: str | None = None
    list_id: str | None = None
    body_text: str = ""
    body_html_present: bool = False
    quoted_stripped: bool = False
    signature_block: str | None = None
    internal_date_ms: int | None = None
    history_id: str | None = None
    label_ids: list[str] = field(default_factory=list)


# ── address parsing ──────────────────────────────────────────────────────────

_ADDR_RE = re.compile(r"<([^<>@\s]+@[^<>@\s]+)>")
_BARE_ADDR_RE = re.compile(r"([^<>@\s,]+@[^<>@\s,]+)")


def split_address(value: str) -> tuple[str | None, str | None]:
    """``"Priya Nair" <priya@x.com>`` -> ``("priya@x.com", "Priya Nair")``."""
    text = (value or "").strip()
    if not text:
        return None, None
    match = _ADDR_RE.search(text)
    if match:
        address = match.group(1).strip().lower()
        display = text[: match.start()].strip().strip('"').strip()
        return address, display or None
    bare = _BARE_ADDR_RE.search(text)
    return (bare.group(1).strip().lower(), None) if bare else (None, text or None)


def split_address_list(value: str) -> list[str]:
    """Comma-separated recipients -> bare addresses, order preserved."""
    out: list[str] = []
    for chunk in (value or "").split(","):
        address, _ = split_address(chunk)
        if address:
            out.append(address)
    return out


# ── signature extraction ─────────────────────────────────────────────────────

# RFC 3676 signature delimiter: a line containing exactly "-- ".
_SIG_DELIM_RE = re.compile(r"\n-{2} *\n")

_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
_EMAIL_RE = re.compile(r"[^\s<>@,]+@[^\s<>@,]+\.[a-z]{2,}", re.I)
_TITLE_WORDS = (
    "manager", "director", "engineer", "developer", "analyst", "consultant",
    "officer", "president", "ceo", "cto", "cfo", "coo", "head of", "lead",
    "specialist", "administrator", "architect", "designer", "founder",
    "supervisor", "coordinator", "executive", "assistant", "technician",
    "support", "sales", "marketing", "recruiter", "partner", "advisor",
)
# A name-like line: one to four capitalised words, no sentence punctuation.
_NAME_LIKE_RE = re.compile(r"^[A-Z][\w.'-]*(?: [A-Z][\w.'-]*){0,3}[,.]?$")


def _looks_like_signature(block: str) -> bool:
    """Trailing block heuristic: a name-like line plus a contact signal."""
    lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
    if not lines or len(lines) > 8:
        return False
    if not any(_NAME_LIKE_RE.match(ln) for ln in lines):
        return False
    lowered = block.lower()
    return bool(
        _EMAIL_RE.search(block)
        or _PHONE_RE.search(block)
        or any(word in lowered for word in _TITLE_WORDS)
    )


def split_signature(body: str) -> tuple[str, str | None]:
    """Split a body into ``(body_without_signature, signature_block)``.

    Tries the explicit ``\\n-- \\n`` delimiter first, as the doc specifies.
    Only if that is absent does it fall back to inspecting the trailing block
    after the final blank line — a heuristic, so it is deliberately narrow.
    """
    if not body:
        return body, None

    match = _SIG_DELIM_RE.search(body)
    if match:
        head = body[: match.start()]
        # The signature runs to the end of the author's own text; anything
        # quoted below it belongs to an earlier message, not this signature.
        tail = body[match.end() :]
        cut = _first_quote_position(tail)
        signature = (tail if cut is None else tail[:cut]).strip()
        return head.rstrip(), signature or None

    blocks = re.split(r"\n\s*\n", body.rstrip())
    if len(blocks) < 2:
        return body.rstrip(), None
    candidate = blocks[-1].strip()
    if _looks_like_signature(candidate):
        head = body.rstrip()[: body.rstrip().rfind(candidate)]
        return head.rstrip(), candidate
    return body.rstrip(), None


# ── quoted history ───────────────────────────────────────────────────────────

_QUOTE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "On Tue, 12 Aug 2026 at 09:14, Priya Nair <priya@x.com> wrote:"
    re.compile(r"^\s*On .{0,200}?\bwrote:\s*$", re.M),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.M | re.I),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.M | re.I),
    # Outlook draws a rule of underscores above the forwarded header block.
    re.compile(r"^_{5,}\s*$", re.M),
    # Outlook forward header block.
    re.compile(r"^\s*From:.*$\n(?:^\s*(?:Sent|To|Cc|Subject):.*$\n?){1,4}", re.M),
    # Classic quote markers.
    re.compile(r"^\s*>+ ?.*$", re.M),
)


def _first_quote_position(text: str) -> int | None:
    """Index of the earliest quoted-history marker, or None."""
    positions = [m.start() for p in _QUOTE_PATTERNS for m in [p.search(text)] if m]
    return min(positions) if positions else None


def strip_quoted(body: str) -> tuple[str, bool]:
    """Remove quoted history. Returns ``(clean_body, quoted_stripped)``."""
    if not body:
        return body, False
    cut = _first_quote_position(body)
    if cut is None:
        return body.rstrip(), False
    return body[:cut].rstrip(), True


# ── entry point ──────────────────────────────────────────────────────────────


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    """Lowercased header map for the top-level message."""
    out: dict[str, str] = {}
    for header in payload.get("headers") or []:
        name = str(header.get("name") or "").strip().lower()
        if name and name not in out:
            out[name] = str(header.get("value") or "")
    return out


def parse_message(raw: dict[str, Any]) -> ParsedMessage:
    """Convert a ``format=full`` Gmail message dict into a ParsedMessage.

    Raises ``MimeParseError`` rather than returning partial data: a half-parsed
    message that reaches src_gmail is worse than one that visibly failed.
    """
    if not isinstance(raw, dict):
        raise MimeParseError(f"expected a Gmail message dict, got {type(raw).__name__}")

    external_id = str(raw.get("id") or "").strip()
    if not external_id:
        raise MimeParseError("Gmail message has no id")

    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise MimeParseError(f"message {external_id} has no payload")

    try:
        text_body, html_body = extract_bodies(payload)
    except Exception as exc:
        raise MimeParseError(f"message {external_id}: could not decode bodies: {exc}") from exc

    headers = _headers(payload)

    # text/plain wins; fall back to HTML converted to text. Inline images and
    # other attachment parts are never treated as a body by extract_bodies.
    body = text_body or (_strip_tags(html_body) if html_body else "")
    if not body:
        body = str(raw.get("snippet") or "")

    # Whether this message carried quoted history is a property of what
    # arrived, so it is decided on the original body. Extracting the signature
    # can itself consume the quoted tail, which would otherwise leave
    # quoted_stripped false for a reply that plainly quoted a thread.
    had_quoted_history = _first_quote_position(body) is not None

    # Signature FIRST, so stripping cannot take it with the quoted history.
    body, signature = split_signature(body)
    body, _ = strip_quoted(body)
    if signature is None and had_quoted_history:
        # A signature can sit between the author's text and the quote; it only
        # becomes the trailing block once the quote is gone.
        body, signature = split_signature(body)
    quoted_stripped = had_quoted_history

    from_address, from_display_name = split_address(headers.get("from", ""))
    reply_to, _ = split_address(headers.get("reply-to", ""))

    internal_raw = raw.get("internalDate")
    try:
        internal_date_ms = int(internal_raw) if internal_raw is not None else None
    except (TypeError, ValueError) as exc:
        raise MimeParseError(f"message {external_id}: bad internalDate {internal_raw!r}") from exc

    history_id = raw.get("historyId")
    return ParsedMessage(
        external_id=external_id,
        thread_external_id=str(raw.get("threadId") or external_id),
        subject=headers.get("subject") or None,
        from_address=from_address,
        from_display_name=from_display_name,
        # Only record Reply-To when it actually differs from From.
        reply_to=reply_to if reply_to and reply_to != from_address else None,
        to_addresses=split_address_list(headers.get("to", "")),
        cc_addresses=split_address_list(headers.get("cc", "")),
        in_reply_to=headers.get("in-reply-to") or None,
        references_header=headers.get("references") or None,
        list_id=headers.get("list-id") or None,
        body_text=body.strip(),
        body_html_present=bool(html_body),
        quoted_stripped=quoted_stripped,
        signature_block=signature,
        internal_date_ms=internal_date_ms,
        history_id=str(history_id) if history_id is not None else None,
        label_ids=list(raw.get("labelIds") or []),
    )
