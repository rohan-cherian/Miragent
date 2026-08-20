"""
Tests for scout/gmail/filters.py — Task 8.

The point is that a Google security alert must never become a case, and that
nothing is ever dropped silently: every drop carries a machine-readable reason.
"""

from __future__ import annotations

import pytest

from scout.gmail.filters import (
    BOUNCE_SENDERS,
    DROP_LABELS,
    DROP_SENDERS,
    should_drop,
)
from scout.gmail.mime import ParsedMessage


def msg(**kw) -> ParsedMessage:
    base = dict(
        external_id="m-1",
        thread_external_id="t-1",
        from_address="priya@northwind.example",
        label_ids=["INBOX"],
    )
    base.update(kw)
    return ParsedMessage(**base)


# ── the four reason codes ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sender",
    [
        "no-reply@accounts.google.com",
        "noreply@google.com",
        "forms-receipts-noreply@google.com",
        "alerts@accounts.google.com",
        "noreply@somevendor.example",
        "do-not-reply@bank.example",
    ],
)
def test_system_senders_are_dropped(sender: str):
    drop, reason = should_drop(msg(from_address=sender))
    assert drop is True
    assert reason == "system_sender"


@pytest.mark.parametrize(
    "sender",
    ["mailer-daemon@googlemail.com", "postmaster@northwind.example", "bounces@vendor.example"],
)
def test_bounces_get_their_own_reason(sender: str):
    """A bounce is diagnostic, not just noise — it must not read system_sender."""
    drop, reason = should_drop(msg(from_address=sender))
    assert drop is True
    assert reason == "bounce"


def test_list_id_means_bulk():
    drop, reason = should_drop(msg(list_id="<newsletter.vendor.example>"))
    assert drop is True
    assert reason == "bulk_list_id"


@pytest.mark.parametrize("label", sorted(DROP_LABELS))
def test_each_dropped_category_label(label: str):
    drop, reason = should_drop(msg(label_ids=["INBOX", label]))
    assert drop is True
    assert reason == "category_label"


# ── what must survive ────────────────────────────────────────────────────────


def test_ordinary_customer_mail_is_kept():
    drop, reason = should_drop(msg())
    assert drop is False
    assert reason is None


def test_inbox_and_unread_labels_are_not_a_drop():
    drop, _ = should_drop(msg(label_ids=["INBOX", "UNREAD", "IMPORTANT", "CATEGORY_PERSONAL"]))
    assert drop is False


def test_missing_sender_does_not_crash_or_drop():
    drop, reason = should_drop(msg(from_address=None))
    assert drop is False and reason is None


def test_sender_matching_is_case_insensitive():
    drop, reason = should_drop(msg(from_address="No-Reply@Accounts.Google.COM"))
    assert drop is True and reason == "system_sender"


def test_lookalike_domain_is_not_dropped():
    """@accounts.google.com must not match accounts.google.com.evil.example."""
    drop, _ = should_drop(msg(from_address="alerts@accounts.google.com.evil.example"))
    assert drop is False


# ── precedence ───────────────────────────────────────────────────────────────


def test_bounce_wins_over_system_sender():
    drop, reason = should_drop(
        msg(from_address="mailer-daemon@accounts.google.com", label_ids=["SPAM"])
    )
    assert (drop, reason) == (True, "bounce")


def test_system_sender_wins_over_list_id():
    drop, reason = should_drop(
        msg(from_address="noreply@google.com", list_id="<list.google.com>")
    )
    assert (drop, reason) == (True, "system_sender")


# ── the constants themselves ─────────────────────────────────────────────────


def test_policy_is_reviewable_as_module_constants():
    """The doc requires both sets be module constants, in one place."""
    assert isinstance(DROP_SENDERS, frozenset) and DROP_SENDERS
    assert isinstance(DROP_LABELS, frozenset) and DROP_LABELS
    assert isinstance(BOUNCE_SENDERS, frozenset) and BOUNCE_SENDERS
    assert DROP_LABELS == {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM", "DRAFT"}
    # The doc describes DROP_SENDERS as containing "Google no-reply addresses,
    # mailer-daemon, forms receipts", so mailer-daemon must be a member of it.
    # BOUNCE_SENDERS is a subset that only selects the reason code.
    assert BOUNCE_SENDERS <= DROP_SENDERS
    assert any("mailer-daemon" in p for p in DROP_SENDERS)
    assert any("google" in p for p in DROP_SENDERS)
    assert any("forms" in p for p in DROP_SENDERS)


def test_should_drop_is_pure():
    """No I/O: the module must not reach for config, network or a database."""
    import inspect

    from scout.gmail import filters

    src = inspect.getsource(filters)
    assert "psycopg" not in src
    assert "httpx" not in src
    assert "settings" not in src
