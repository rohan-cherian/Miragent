"""
Tests for scout/gmail/mime.py — Task 7.

Six real-world message shapes, stored as JSON fixtures alongside this file:
plain text, HTML-only, multipart/alternative, a reply with quoted history, an
Outlook forward chain, and a message with an inline image.

For each: body_text must be clean, quoted_stripped must be right, and
signature_block must be populated wherever a signature exists.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from scout.gmail.mime import (
    MimeParseError,
    ParsedMessage,
    parse_message,
    split_address,
    split_signature,
    strip_quoted,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def plain() -> ParsedMessage:
    return parse_message(load("plain_text"))


@pytest.fixture
def reply() -> ParsedMessage:
    return parse_message(load("reply_quoted"))


# ── the six shapes ───────────────────────────────────────────────────────────


def test_plain_text(plain: ParsedMessage):
    assert plain.body_text.startswith("Hi team,")
    assert "laptop will not boot" in plain.body_text
    assert plain.quoted_stripped is False
    assert plain.body_html_present is False
    assert plain.signature_block is not None
    assert "Priya Nair" in plain.signature_block
    assert "+44 20 7946 0958" in plain.signature_block
    # The signature must not remain in the body as well.
    assert "Operations Manager" not in plain.body_text


def test_html_only_is_converted_to_text():
    m = parse_message(load("html_only"))
    assert m.body_html_present is True
    assert "VPN" in m.body_text
    assert "<" not in m.body_text, "HTML tags must not survive into body_text"
    assert m.quoted_stripped is False


def test_multipart_alternative_prefers_text_plain():
    m = parse_message(load("multipart_alternative"))
    assert m.body_text == "The 3rd floor printer is offline again."
    assert m.body_html_present is True, "the HTML part still exists"
    assert "<i>" not in m.body_text


def test_reply_strips_quoted_history_but_keeps_signature(reply: ParsedMessage):
    assert reply.quoted_stripped is True
    assert "Safe mode did not help either." in reply.body_text
    # None of the quoted thread may survive.
    assert "safe mode?" not in reply.body_text.lower()
    assert ">" not in reply.body_text
    assert "wrote:" not in reply.body_text
    assert reply.signature_block is not None
    assert "Priya Nair" in reply.signature_block
    assert reply.in_reply_to == "<orig-1@mail.example>"
    assert reply.references_header == "<orig-1@mail.example>"


def test_outlook_forward_chain_is_stripped():
    m = parse_message(load("outlook_forward"))
    assert m.quoted_stripped is True
    assert "Forwarding this for your review." in m.body_text
    # The underscore rule, the From:/Sent:/To: block and the quoted body go.
    assert "____" not in m.body_text
    assert "Sent:" not in m.body_text
    assert "appears unpaid" not in m.body_text
    assert m.signature_block is not None
    assert "Dan Okafor" in m.signature_block


def test_inline_image_is_not_treated_as_body():
    m = parse_message(load("inline_image"))
    assert m.body_text == "Screenshot of the error is inline below."
    assert "error.png" not in m.body_text
    assert m.quoted_stripped is False


# ── addresses ────────────────────────────────────────────────────────────────


def test_display_name_split_from_address(plain: ParsedMessage):
    assert plain.from_address == "priya.nair@northwind.example"
    assert plain.from_display_name == "Priya Nair"


def test_reply_to_only_recorded_when_it_differs_from_from():
    raw = load("plain_text")
    headers = raw["payload"]["headers"]
    headers.append({"name": "Reply-To", "value": "priya.nair@northwind.example"})
    assert parse_message(raw).reply_to is None, "same as From -> not recorded"

    headers[-1] = {"name": "Reply-To", "value": "helpdesk@northwind.example"}
    assert parse_message(raw).reply_to == "helpdesk@northwind.example"


def test_recipient_lists_are_parsed():
    raw = load("plain_text")
    raw["payload"]["headers"].append(
        {"name": "Cc", "value": "A One <a@x.example>, b@y.example"}
    )
    m = parse_message(raw)
    assert m.to_addresses == ["support@motiveminds.com"]
    assert m.cc_addresses == ["a@x.example", "b@y.example"]


def test_split_address_handles_bare_and_quoted():
    assert split_address('"Priya Nair" <p@x.com>') == ("p@x.com", "Priya Nair")
    assert split_address("p@x.com") == ("p@x.com", None)
    assert split_address("") == (None, None)


# ── unit-level: signature and quote handling ─────────────────────────────────


def test_signature_delimiter_takes_precedence():
    body = "Body text.\n\n-- \nJo Smith\nCTO\njo@x.com"
    head, sig = split_signature(body)
    assert head == "Body text."
    assert sig is not None and "Jo Smith" in sig


def test_trailing_block_signature_without_delimiter():
    body = "Please advise.\n\nRavi Shah\nSupport Engineer\nravi@x.com"
    head, sig = split_signature(body)
    assert head == "Please advise."
    assert sig is not None and "Ravi Shah" in sig


def test_ordinary_closing_line_is_not_a_signature():
    body = "The printer is broken.\n\nIt has been broken since Tuesday morning."
    head, sig = split_signature(body)
    assert sig is None
    assert head == body


@pytest.mark.parametrize(
    "marker",
    [
        "On Tue, 12 Aug 2026 at 09:14, Sam <s@x.com> wrote:",
        "-----Original Message-----",
        "________________________",
        "> quoted line",
    ],
)
def test_each_quote_marker_is_recognised(marker: str):
    body = f"My own words.\n\n{marker}\nold content here"
    clean, stripped = strip_quoted(body)
    assert stripped is True
    assert clean == "My own words."
    assert "old content" not in clean


def test_body_without_quotes_is_untouched():
    clean, stripped = strip_quoted("Just one message.")
    assert stripped is False
    assert clean == "Just one message."


# ── failure mode ─────────────────────────────────────────────────────────────


def test_missing_id_raises_rather_than_returning_partial_data():
    with pytest.raises(MimeParseError, match="no id"):
        parse_message({"payload": {"mimeType": "text/plain", "body": {}}})


def test_missing_payload_raises():
    with pytest.raises(MimeParseError, match="no payload"):
        parse_message({"id": "m-1"})


def test_non_dict_raises():
    with pytest.raises(MimeParseError):
        parse_message("not a message")  # type: ignore[arg-type]


def test_bad_internal_date_raises():
    raw = load("plain_text")
    raw["internalDate"] = "not-a-number"
    with pytest.raises(MimeParseError, match="internalDate"):
        parse_message(raw)
