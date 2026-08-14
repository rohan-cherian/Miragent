"""Customer sender allowlist helpers."""

from __future__ import annotations

from scout.gmail.customers import (
    extract_email_address,
    gmail_from_query,
    is_customer_sender,
    parse_sender_list,
)


def test_default_customer_list():
    allowed = parse_sender_list(None)
    assert "motiveminds.vihaan@gmail.com" in allowed
    assert "motiveminds.jennifer@gmail.com" in allowed
    assert "motiveminds.ojasvi@gmail.com" in allowed


def test_extract_email_from_header():
    assert (
        extract_email_address("Vihaan Banerjee <motiveminds.vihaan@gmail.com>")
        == "motiveminds.vihaan@gmail.com"
    )
    assert extract_email_address("motiveminds.jennifer@gmail.com") == (
        "motiveminds.jennifer@gmail.com"
    )


def test_is_customer_sender():
    allowed = parse_sender_list(
        "motiveminds.vihaan@gmail.com, motiveminds.jennifer@gmail.com"
    )
    assert is_customer_sender(
        "Vihaan Banerjee <motiveminds.vihaan@gmail.com>", allowed
    )
    assert not is_customer_sender("Rohan <rohancherian289@gmail.com>", allowed)
    assert not is_customer_sender("Google <no-reply@google.com>", allowed)


def test_gmail_from_query():
    q = gmail_from_query(
        frozenset({"motiveminds.vihaan@gmail.com", "motiveminds.ojasvi@gmail.com"})
    )
    assert q.startswith("in:inbox (")
    assert "from:motiveminds.vihaan@gmail.com" in q
    assert "from:motiveminds.ojasvi@gmail.com" in q
    assert " OR " in q
