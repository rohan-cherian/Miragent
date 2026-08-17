"""Tests for the customer sender allowlist."""

from __future__ import annotations

import pytest

from scout.gmail.customers import (
    DEFAULT_CUSTOMER_SENDERS,
    extract_email_address,
    gmail_from_query,
    is_customer_sender,
    parse_sender_list,
)

CUSTOMERS = frozenset(DEFAULT_CUSTOMER_SENDERS)


def test_the_three_customers_are_the_default():
    assert CUSTOMERS == {
        "motiveminds.vihaan@gmail.com",
        "motiveminds.jennifer@gmail.com",
        "motiveminds.ojasvi@gmail.com",
    }


@pytest.mark.parametrize(
    "header,expected",
    [
        ("Vihaan Banerjee <motiveminds.vihaan@gmail.com>", "motiveminds.vihaan@gmail.com"),
        ("motiveminds.ojasvi@gmail.com", "motiveminds.ojasvi@gmail.com"),
        ("  MOTIVEMINDS.JENNIFER@GMAIL.COM  ", "motiveminds.jennifer@gmail.com"),
        ('"Quoted Name" <a@b.com>', "a@b.com"),
        ("", None),
        (None, None),
        ("not an address", None),
    ],
)
def test_extract_email_address(header, expected):
    assert extract_email_address(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        "Vihaan Banerjee <motiveminds.vihaan@gmail.com>",
        "Jennifer Carter <motiveminds.jennifer@gmail.com>",
        "motiveminds.ojasvi@gmail.com",
        "MotiveMinds.Vihaan@Gmail.com",  # case-insensitive
    ],
)
def test_customers_are_allowed(header):
    assert is_customer_sender(header, CUSTOMERS) is True


@pytest.mark.parametrize(
    "header",
    [
        "Rohan <rohancherian289@gmail.com>",          # personal address
        "Google <no-reply@google.com>",               # security alerts
        "MotiveMinds Demo <motiveminds.itsupport@gmail.com>",  # our own sent mail
        "mailer-daemon@googlemail.com",
        "",
        None,
    ],
)
def test_everyone_else_is_rejected(header):
    assert is_customer_sender(header, CUSTOMERS) is False


def test_lookalike_address_is_not_matched():
    """Substring similarity must not grant access."""
    assert is_customer_sender("evil.motiveminds.vihaan@gmail.com.attacker.net", CUSTOMERS) is False
    assert is_customer_sender("motiveminds.vihaan@gmail.com.evil.net", CUSTOMERS) is False


def test_domain_entries_match_any_sender_at_that_domain():
    allowed = frozenset({"@northwind.example"})
    assert is_customer_sender("Someone <a@northwind.example>", allowed) is True
    assert is_customer_sender("b@other.example", allowed) is False


def test_parse_sender_list_accepts_common_separators():
    got = parse_sender_list("a@x.com, b@x.com; c@x.com\nd@x.com")
    assert got == {"a@x.com", "b@x.com", "c@x.com", "d@x.com"}


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_config_falls_back_to_defaults_never_to_everyone(blank):
    """A blank env var must not silently widen ingestion to the whole mailbox."""
    assert parse_sender_list(blank) == CUSTOMERS


def test_gmail_query_pushes_filter_server_side():
    q = gmail_from_query(CUSTOMERS)
    for addr in CUSTOMERS:
        assert f"from:{addr}" in q
    assert q.startswith("(") and q.endswith(")")
    assert " OR " in q


def test_gmail_query_handles_domain_entries():
    q = gmail_from_query(frozenset({"@northwind.example"}))
    assert q == "(from:northwind.example)"


def test_empty_allowlist_yields_no_query_clause():
    assert gmail_from_query(frozenset()) == ""
