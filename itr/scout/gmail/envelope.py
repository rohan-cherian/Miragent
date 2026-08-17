"""
Gmail message -> raw JSON document.

Everything Gmail gives us for one message, in one self-contained object:
headers (both a convenience map and the ordered raw list), the text/plain and
text/html bodies, every attachment inlined as base64, and the MIME part tree.

Fidelity notes:
  * ``headers_raw`` preserves order and duplicates (Received, DKIM, ...).
    ``headers`` is the lowercased convenience map and keeps the FIRST value
    when a header repeats.
  * ``mime_tree`` is Gmail's own payload structure with the ``body.data``
    blobs stripped — the bytes already live in ``body`` and ``attachments``,
    so keeping them twice would double the object size for no gain.
  * ``content_sha256`` covers the message content only, deliberately
    excluding ``ingested_at``, so re-ingesting the same message produces the
    same fingerprint.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"

# Headers promoted for convenience. Everything else still appears in
# headers_raw and in the per-part header lists inside mime_tree.
_INTERESTING_HEADERS = (
    "from",
    "to",
    "cc",
    "bcc",
    "reply-to",
    "subject",
    "date",
    "message-id",
    "in-reply-to",
    "references",
    "delivered-to",
    "return-path",
    "list-id",
    "content-type",
)


def b64url_to_bytes(data: str) -> bytes:
    """Gmail uses base64url without padding."""
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return b""


def _decode_text(data: str, charset: str | None = None) -> str:
    raw = b64url_to_bytes(data)
    if not raw:
        return ""
    for enc in filter(None, (charset, "utf-8", "latin-1")):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _charset_of(part: dict[str, Any]) -> str | None:
    for header in part.get("headers") or []:
        if str(header.get("name", "")).lower() == "content-type":
            value = str(header.get("value", ""))
            if "charset=" in value.lower():
                token = value.lower().split("charset=", 1)[1]
                return token.split(";")[0].strip().strip('"').strip("'") or None
    return None


def _header_value(part: dict[str, Any], name: str) -> str | None:
    target = name.lower()
    for header in part.get("headers") or []:
        if str(header.get("name", "")).lower() == target:
            return str(header.get("value", ""))
    return None


def _is_attachment(part: dict[str, Any]) -> bool:
    """
    A part is an attachment if Gmail gave it an attachmentId, or it carries a
    filename. Inline images (Content-Disposition: inline + Content-ID) count —
    they are real content a downstream reader may need.
    """
    body = part.get("body") or {}
    if body.get("attachmentId"):
        return True
    return bool(part.get("filename"))


def walk_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Depth-first flatten of the MIME tree, parents before children."""
    out: list[dict[str, Any]] = []

    def _walk(part: dict[str, Any]) -> None:
        out.append(part)
        for child in part.get("parts") or []:
            _walk(child)

    if payload:
        _walk(payload)
    return out


def extract_bodies(payload: dict[str, Any]) -> tuple[str, str]:
    """
    Return ``(text_plain, text_html)``.

    Attachment parts are skipped so a .txt or .html attachment never gets
    mistaken for the message body.
    """
    texts: list[str] = []
    htmls: list[str] = []
    for part in walk_parts(payload):
        mime = str(part.get("mimeType") or "")
        data = (part.get("body") or {}).get("data")
        if not data or _is_attachment(part):
            continue
        if mime.startswith("text/plain"):
            texts.append(_decode_text(data, _charset_of(part)))
        elif mime.startswith("text/html"):
            htmls.append(_decode_text(data, _charset_of(part)))
    return ("\n".join(texts).strip(), "\n".join(htmls).strip())


def strip_body_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy of the MIME tree with ``body.data`` removed, structure intact."""
    if not payload:
        return {}
    node: dict[str, Any] = {
        k: v for k, v in payload.items() if k not in {"parts", "body"}
    }
    body = payload.get("body") or {}
    node["body"] = {k: v for k, v in body.items() if k != "data"}
    node["body"]["has_data"] = bool(body.get("data"))
    if payload.get("parts"):
        node["parts"] = [strip_body_data(p) for p in payload["parts"]]
    return node


def collect_attachment_specs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Attachment parts needing byte hydration, in MIME order.

    ``attachment_id`` is None for small parts Gmail already inlined in
    ``body.data`` — those need no extra API call.
    """
    specs: list[dict[str, Any]] = []
    for part in walk_parts(payload):
        if not _is_attachment(part):
            continue
        body = part.get("body") or {}
        disposition = (_header_value(part, "content-disposition") or "").lower()
        specs.append(
            {
                "part_id": part.get("partId"),
                "filename": part.get("filename") or "",
                "mime_type": part.get("mimeType") or "application/octet-stream",
                "size_bytes": int(body.get("size") or 0),
                "attachment_id": body.get("attachmentId"),
                "inline_data": body.get("data"),
                "content_id": (_header_value(part, "content-id") or "").strip("<>") or None,
                "is_inline": disposition.startswith("inline"),
            }
        )
    return specs


def build_attachment_entry(
    spec: dict[str, Any],
    raw_bytes: bytes | None,
    *,
    max_bytes: int,
    error: str | None = None,
) -> dict[str, Any]:
    """
    One attachment record. Oversized or failed fetches keep their metadata and
    set ``truncated``/``error`` rather than silently vanishing.
    """
    entry: dict[str, Any] = {
        "part_id": spec.get("part_id"),
        "filename": spec.get("filename") or "",
        "mime_type": spec.get("mime_type"),
        "size_bytes": int(spec.get("size_bytes") or 0),
        "content_id": spec.get("content_id"),
        "is_inline": bool(spec.get("is_inline")),
        "attachment_id": spec.get("attachment_id"),
        "sha256": None,
        "data_base64": None,
        "truncated": False,
        "error": error,
    }
    if raw_bytes is None:
        if error is None and int(spec.get("size_bytes") or 0) > max_bytes:
            entry["truncated"] = True
            entry["error"] = f"exceeds gmail_raw_max_attachment_bytes ({max_bytes})"
        return entry
    entry["size_bytes"] = len(raw_bytes)
    entry["sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    if len(raw_bytes) > max_bytes:
        entry["truncated"] = True
        entry["error"] = f"exceeds gmail_raw_max_attachment_bytes ({max_bytes})"
        return entry
    entry["data_base64"] = base64.b64encode(raw_bytes).decode("ascii")
    return entry


def build_envelope(
    raw_message: dict[str, Any],
    *,
    account_id: str,
    attachments: list[dict[str, Any]] | None = None,
    ingested_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the JSON document written to the raw bucket."""
    payload = raw_message.get("payload") or {}
    headers_raw = [
        {"name": str(h.get("name", "")), "value": str(h.get("value", ""))}
        for h in (payload.get("headers") or [])
        if h.get("name") is not None
    ]
    headers: dict[str, str] = {}
    for header in headers_raw:
        key = header["name"].lower()
        if key not in headers:  # first value wins
            headers[key] = header["value"]

    text_body, html_body = extract_bodies(payload)
    internal_raw = raw_message.get("internalDate")
    internal_ms = int(internal_raw) if internal_raw is not None else None
    atts = attachments or []

    # Top-level keys mirror handover doc section 6 exactly (source, message_id,
    # thread_id, from, to, subject, body, received_at) so a consumer written
    # against that example works unchanged. Everything after them is additive.
    document: dict[str, Any] = {
        "source": "gmail",
        "message_id": raw_message.get("id"),
        "thread_id": raw_message.get("threadId"),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "body": text_body or _strip_tags(html_body) or (raw_message.get("snippet") or ""),
        "received_at": datetime.fromtimestamp(internal_ms / 1000.0, tz=timezone.utc).isoformat()
        if internal_ms is not None
        else None,
        # ── everything below is extra fidelity, beyond the doc's example ──
        "cc": headers.get("cc", ""),
        "bcc": headers.get("bcc", ""),
        "reply_to": headers.get("reply-to", ""),
        "body_text": text_body,
        "body_html": html_body,
        "has_text": bool(text_body),
        "has_html": bool(html_body),
        "snippet": raw_message.get("snippet") or "",
        "label_ids": list(raw_message.get("labelIds") or []),
        "internal_date_ms": internal_ms,
        "history_id": str(raw_message["historyId"])
        if raw_message.get("historyId") is not None
        else None,
        "size_estimate": raw_message.get("sizeEstimate"),
        "headers": {k: v for k, v in headers.items() if k in _INTERESTING_HEADERS},
        "headers_all": headers,
        "headers_raw": headers_raw,
        "attachments": atts,
        "attachment_count": len(atts),
        "mime_tree": strip_body_data(payload),
        "account_id": account_id,
        "schema_version": SCHEMA_VERSION,
        "ingested_at": (ingested_at or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat(),
    }
    document["content_sha256"] = content_fingerprint(document)
    return document


def _strip_tags(html: str) -> str:
    """Plain-text fallback for HTML-only mail, so ``body`` is never empty."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def content_fingerprint(document: dict[str, Any]) -> str:
    """
    Stable hash of message content, excluding ingest-run metadata.

    Two ingests of the same Gmail message produce the same value, which is
    what makes it usable as a duplicate check rather than just an audit field.
    """
    material = {
        "message_id": document.get("message_id"),
        "internal_date_ms": document.get("internal_date_ms"),
        "headers_raw": document.get("headers_raw"),
        "body": {
            "text": document.get("body_text"),
            "html": document.get("body_html"),
        },
        "attachments": [
            {
                "filename": a.get("filename"),
                "mime_type": a.get("mime_type"),
                "sha256": a.get("sha256"),
                "size_bytes": a.get("size_bytes"),
            }
            for a in document.get("attachments") or []
        ],
    }
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def serialise(document: dict[str, Any]) -> bytes:
    """UTF-8 JSON bytes for the object body."""
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
