"""
Object key layout for the raw lake.

Single-mailbox POC (``layout="flat"``):

    raw/
    └── gmail/
        └── 2026/08/14/
            ├── email_18abc123.json
            └── email_18abc456.json

Multi-mailbox (``layout="account"``) inserts an account segment, so the
existing paths never need restructuring when a second persona is added:

    gmail/<account_id>/2026/08/14/email_18abc123.json

The Gmail message ID is the object name (handover doc sections 3, 7, 15).
Because the key is fully derived from the message, a HEAD on the path is a
complete duplicate check — no tracking table is needed for correctness.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

_UNSAFE = re.compile(r"[^a-z0-9._-]+")
# Gmail message ids are lowercase hex, but never trust an id straight into a
# path: a stray "/" would silently relocate the object into another prefix.
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class InvalidMessageId(ValueError):
    """Raised when a Gmail message id cannot form a safe object name."""


def account_segment(account_id: str) -> str:
    """
    Filesystem/URL-safe form of a mailbox address.

    ``Support.Team@Gmail.com`` -> ``support.team-at-gmail.com``
    """
    text = (account_id or "unknown").strip().lower().replace("@", "-at-")
    text = _UNSAFE.sub("-", text).strip("-")
    return text or "unknown"


def safe_message_id(message_id: str | None) -> str:
    """
    Validate a Gmail message id for use in an object name.

    Handover doc section 16: malformed data must be skipped and logged rather
    than written under a broken or blank name.
    """
    text = (message_id or "").strip()
    if not text:
        raise InvalidMessageId("empty Gmail message id")
    cleaned = _UNSAFE_ID.sub("", text)
    if not cleaned:
        raise InvalidMessageId(f"Gmail message id has no usable characters: {message_id!r}")
    if cleaned != text:
        raise InvalidMessageId(
            f"Gmail message id contains unsafe characters for a path: {message_id!r}"
        )
    return cleaned


def partition_date(
    *,
    internal_date_ms: int | None,
    partition_by: str = "received",
    now: datetime | None = None,
) -> date:
    """
    Pick the YYYY/MM/DD folder date, in UTC.

    ``received`` uses the message's Gmail internalDate so a message always
    lands in the same folder no matter when it is synced — that is what makes
    re-syncs and backfills idempotent. Falls back to now when Gmail gave us
    no internalDate.
    """
    if partition_by == "received" and internal_date_ms is not None:
        return datetime.fromtimestamp(internal_date_ms / 1000.0, tz=timezone.utc).date()
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()


def build_object_key(
    *,
    partition: date,
    message_id: str,
    prefix: str = "gmail",
    layout: str = "flat",
    account_id: str = "",
    pattern: str = "email_{message_id}.json",
) -> str:
    """
    Assemble the full object key for one email JSON document.

    Raises ``InvalidMessageId`` for an id that cannot form a safe name.
    """
    safe = safe_message_id(message_id)
    parts = [prefix.strip("/")]
    if layout == "account":
        parts.append(account_segment(account_id))
    parts.append(f"{partition.year:04d}")
    parts.append(f"{partition.month:02d}")
    parts.append(f"{partition.day:02d}")
    parts.append(pattern.format(message_id=safe))
    return "/".join(parts)


def build_attachment_key(
    *,
    partition: date,
    message_id: str,
    attachment_id: str,
    filename: str = "",
    prefix: str = "gmail",
    layout: str = "flat",
    account_id: str = "",
) -> str:
    """
    Object key for one attachment's bytes, stored beside its message.

    Slice-1 doc Task 6 puts attachments at
    ``…/{messageId}/attachments/{attachmentId}_{filename}``. The date segments
    keep the handover doc's ``YYYY/MM/DD`` form so a message and its
    attachments always share one day folder.

    Attachments are separate objects rather than base64 inside the message
    JSON, because ``src_gmail.attachment.object_path`` is NOT NULL and needs a
    real path to point at.
    """
    safe_message = safe_message_id(message_id)
    safe_attachment = _UNSAFE_ID.sub("-", (attachment_id or "").strip()) or "unknown"
    # The filename is user-controlled, so it is sanitised rather than validated:
    # an attachment must never be dropped just because it was named oddly.
    safe_name = _UNSAFE.sub("-", (filename or "").strip().lower()).strip("-")
    tail = f"{safe_attachment}_{safe_name}" if safe_name else safe_attachment

    parts = [prefix.strip("/")]
    if layout == "account":
        parts.append(account_segment(account_id))
    parts.append(f"{partition.year:04d}")
    parts.append(f"{partition.month:02d}")
    parts.append(f"{partition.day:02d}")
    parts.extend([safe_message, "attachments", tail])
    return "/".join(parts)


def day_prefix(
    *,
    partition: date,
    prefix: str = "gmail",
    layout: str = "flat",
    account_id: str = "",
) -> str:
    """Prefix for one day's objects — handy for listing and verification."""
    parts = [prefix.strip("/")]
    if layout == "account":
        parts.append(account_segment(account_id))
    parts.append(f"{partition.year:04d}")
    parts.append(f"{partition.month:02d}")
    parts.append(f"{partition.day:02d}")
    return "/".join(parts) + "/"
