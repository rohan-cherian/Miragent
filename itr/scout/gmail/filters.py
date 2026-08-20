"""
itr/scout/gmail/filters.py — drop system and bulk mail (Task 8).

Without this, every Google security alert becomes a case — a failure that is
very visible in front of an audience.

Dropping is never silent. The caller records the reason code against the run,
so we can always prove no real message was lost. That is the same principle as
the quarantine table at Task 16: the pipeline may decline to process
something, but it may not pretend it never arrived.

Pure functions, no I/O. Both sets are module constants so the whole drop
policy is reviewable in one place rather than scattered through the sync.
"""

from __future__ import annotations

from scout.gmail.mime import ParsedMessage

__all__ = [
    "DROP_SENDERS",
    "DROP_LABELS",
    "BOUNCE_SENDERS",
    "should_drop",
]

# Delivery failures. A subset of DROP_SENDERS, held separately only so it can
# select the ``bounce`` reason code — a bounce is diagnostic, not merely noise,
# and Task 16's quarantine will want to tell the two apart.
BOUNCE_SENDERS: frozenset[str] = frozenset(
    {
        "mailer-daemon@",
        "mailerdaemon@",
        "postmaster@",
        "bounce@",
        "bounces@",
        "@bounce.",
    }
)

# Senders whose mail is never a customer request. Entries are matched as a full
# address or, when they begin with "@", as a domain suffix.
_SYSTEM_SENDERS: frozenset[str] = frozenset(
    {
        # Google system mail — security alerts, policy notices, backups.
        "@accounts.google.com",
        "no-reply@accounts.google.com",
        "noreply@google.com",
        "no-reply@google.com",
        "googlecommunityteam-noreply@google.com",
        "workspace-noreply@google.com",
        "drive-shares-dm-noreply@google.com",
        "calendar-notification@google.com",
        "@docs.google.com",
        "@youtube.com",
        # Forms and survey receipts.
        "forms-receipts-noreply@google.com",
        "@formsubmit.co",
        "@surveymonkey.com",
        "@typeform.com",
        # Generic no-reply conventions.
        "noreply@",
        "no-reply@",
        "donotreply@",
        "do-not-reply@",
    }
)

# The doc's named constant: "Google no-reply addresses, mailer-daemon, forms
# receipts". Bounce senders are part of it, so membership here is the single
# question "is this sender system mail?" — the reason code is decided below.
DROP_SENDERS: frozenset[str] = _SYSTEM_SENDERS | BOUNCE_SENDERS

# Gmail categories that are never a support request.
DROP_LABELS: frozenset[str] = frozenset(
    {
        "CATEGORY_PROMOTIONS",
        "CATEGORY_SOCIAL",
        "SPAM",
        "DRAFT",
    }
)


def _matches(address: str, patterns: frozenset[str]) -> bool:
    """Match an address against exact addresses, "@domain" and "local@" rules."""
    if not address:
        return False
    addr = address.strip().lower()
    for pattern in patterns:
        if pattern.startswith("@"):
            # endswith only. A substring test would match
            # alerts@accounts.google.com.evil.example against
            # @accounts.google.com — dropping real mail on a lookalike domain.
            if addr.endswith(pattern):
                return True
        elif pattern.endswith("@"):
            if addr.startswith(pattern):
                return True
        elif addr == pattern:
            return True
    return False


def should_drop(parsed: ParsedMessage) -> tuple[bool, str | None]:
    """Whether to skip this message, and a machine-readable reason code.

    Reason codes: ``bounce``, ``system_sender``, ``bulk_list_id``,
    ``category_label``. Returns ``(False, None)`` for mail that should be
    processed.

    Bounces are checked before other system senders so a delivery failure is
    never mislabelled as generic noise.
    """
    sender = (parsed.from_address or "").strip().lower()

    if _matches(sender, BOUNCE_SENDERS):
        return True, "bounce"

    if _matches(sender, DROP_SENDERS):
        return True, "system_sender"

    # A List-Id header means the message went to a mailing list, not to us.
    if parsed.list_id:
        return True, "bulk_list_id"

    if DROP_LABELS.intersection(parsed.label_ids or []):
        return True, "category_label"

    return False, None
