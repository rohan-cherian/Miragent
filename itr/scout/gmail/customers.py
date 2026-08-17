"""
Customer sender allowlist for Gmail -> MinIO raw ingestion.

Only mail **From** an allowlisted sender is stored. Everything else — the
support mailbox's own sent mail, Google security alerts, personal traffic — is
skipped and logged, never written.

Deliberate trade-off: this filters at the RAW layer, so non-customer mail is
not recoverable later (Gmail's history cursor only reaches back ~1 week).
That is the intent here — the raw bucket is customer mail by definition.
Set ``GMAIL_CUSTOMER_ONLY=false`` to ingest the whole mailbox instead.

Entries may be either a full address or a bare domain:

    motiveminds.vihaan@gmail.com     exact sender
    @northwind.example               anyone at that domain
"""

from __future__ import annotations

import re

# The PE demo customer mailboxes.
DEFAULT_CUSTOMER_SENDERS: tuple[str, ...] = (
    "motiveminds.vihaan@gmail.com",
    "motiveminds.jennifer@gmail.com",
    "motiveminds.ojasvi@gmail.com",
)

# Display names — logging and documentation only, never matching.
CUSTOMER_DIRECTORY: dict[str, str] = {
    "motiveminds.vihaan@gmail.com": "Vihaan Banerjee",
    "motiveminds.jennifer@gmail.com": "Jennifer Carter",
    "motiveminds.ojasvi@gmail.com": "Ojasvi Goda",
}


def parse_sender_list(raw: str | None) -> frozenset[str]:
    """
    Parse a comma / semicolon / whitespace separated allowlist.

    Falls back to the demo customers when unset, so a blank env var can never
    silently widen ingestion to the whole mailbox.
    """
    if not raw or not str(raw).strip():
        return frozenset(DEFAULT_CUSTOMER_SENDERS)
    parts = re.split(r"[,;\s]+", str(raw).strip())
    entries = {
        p.strip().lower()
        for p in parts
        if p.strip() and ("@" in p)
    }
    return frozenset(entries) if entries else frozenset(DEFAULT_CUSTOMER_SENDERS)


def extract_email_address(from_header: str | None) -> str | None:
    """
    Pull the bare address out of a From header.

    ``Vihaan Banerjee <a@b.com>`` -> ``a@b.com``
    """
    if not from_header:
        return None
    header = str(from_header).strip()
    match = re.search(r"<([^>]+)>", header)
    candidate = match.group(1) if match else header
    candidate = candidate.strip().strip("<>").lower()
    return candidate if "@" in candidate else None


def is_customer_sender(from_header: str | None, allowed: frozenset[str]) -> bool:
    """True when the sender is on the allowlist, by address or by domain."""
    email = extract_email_address(from_header)
    if not email:
        return False
    if email in allowed:
        return True
    domain = email.rsplit("@", 1)[-1]
    return f"@{domain}" in allowed


def gmail_from_query(allowed: frozenset[str]) -> str:
    """
    Gmail search clause restricting a listing to allowlisted senders.

    Pushed into ``messages.list`` so Gmail does the filtering server-side and
    a backfill never downloads mail it is going to discard.

        from:a@x.com OR from:b@x.com OR from:@domain
    """
    if not allowed:
        return ""
    terms = " OR ".join(f"from:{addr.lstrip('@') if addr.startswith('@') else addr}"
                        for addr in sorted(allowed))
    return f"({terms})"


def describe(allowed: frozenset[str]) -> str:
    """Human-readable allowlist for startup logs."""
    return ", ".join(
        f"{CUSTOMER_DIRECTORY[a]} <{a}>" if a in CUSTOMER_DIRECTORY else a
        for a in sorted(allowed)
    )
