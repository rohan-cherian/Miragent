"""
Allowed customer senders for Gmail → ticket sync.

Only messages From these addresses become tickets.
Override via env ``GMAIL_CUSTOMER_SENDERS`` (comma-separated emails).
"""

from __future__ import annotations

import re

# Default PE demo / MotiveMinds customer mailboxes
DEFAULT_CUSTOMER_SENDERS: tuple[str, ...] = (
    "motiveminds.vihaan@gmail.com",
    "motiveminds.jennifer@gmail.com",
    "motiveminds.ojasvi@gmail.com",
)

# Optional display names (documentation / logging only)
CUSTOMER_DIRECTORY: dict[str, str] = {
    "motiveminds.vihaan@gmail.com": "Vihaan Banerjee",
    "motiveminds.jennifer@gmail.com": "Jennifer Carter",
    "motiveminds.ojasvi@gmail.com": "Ojasvi Goda",
}


def parse_sender_list(raw: str | None) -> frozenset[str]:
    """Parse comma/semicolon/whitespace separated emails into a lowercase set."""
    if not raw or not str(raw).strip():
        return frozenset(DEFAULT_CUSTOMER_SENDERS)
    parts = re.split(r"[,;\s]+", str(raw).strip())
    emails = {p.strip().lower() for p in parts if p.strip() and "@" in p}
    return frozenset(emails) if emails else frozenset(DEFAULT_CUSTOMER_SENDERS)


def extract_email_address(from_header: str | None) -> str | None:
    """Pull bare email from ``Name <user@host>`` or ``user@host``."""
    if not from_header:
        return None
    header = from_header.strip()
    match = re.search(r"<([^>]+)>", header)
    if match:
        return match.group(1).strip().lower()
    if "@" in header:
        return header.strip().lower().strip("<>")
    return None


def is_customer_sender(from_header: str | None, allowed: frozenset[str]) -> bool:
    email = extract_email_address(from_header)
    if not email:
        return False
    return email in allowed


def gmail_from_query(allowed: frozenset[str]) -> str:
    """
    Gmail search clause limiting to allowlisted From addresses.

    Example: ``in:inbox (from:a@x.com OR from:b@x.com)``
    """
    if not allowed:
        return "in:inbox"
    ors = " OR ".join(f"from:{addr}" for addr in sorted(allowed))
    return f"in:inbox ({ors})"
