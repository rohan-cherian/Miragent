"""Tests for raw-lake object key layout and partition dates."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from scout.raw.keys import (
    InvalidMessageId,
    account_segment,
    build_object_key,
    day_prefix,
    partition_date,
    safe_message_id,
)


def test_flat_layout_matches_handover_spec():
    """Handover doc sections 7/15: email_<message_id>.json"""
    key = build_object_key(partition=date(2026, 8, 14), message_id="18abc123")
    assert key == "gmail/2026/08/14/email_18abc123.json"


def test_key_is_fully_derived_from_message_and_date():
    """The HEAD-before-PUT dedup depends on this being reproducible."""
    a = build_object_key(partition=date(2026, 8, 14), message_id="18abc123")
    b = build_object_key(partition=date(2026, 8, 14), message_id="18abc123")
    assert a == b


def test_distinct_messages_get_distinct_keys_same_day():
    day = date(2026, 8, 14)
    keys = {build_object_key(partition=day, message_id=m) for m in ("m1", "m2", "m3")}
    assert len(keys) == 3


def test_account_layout_inserts_identifier_segment():
    key = build_object_key(
        partition=date(2026, 8, 14),
        message_id="18abc123",
        layout="account",
        account_id="Support.Team@Gmail.com",
    )
    assert key == "gmail/support.team-at-gmail.com/2026/08/14/email_18abc123.json"


def test_account_segment_is_path_safe():
    assert account_segment("a b/c@x.com") == "a-b-c-at-x.com"
    assert account_segment("") == "unknown"


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_blank_message_id_is_rejected(bad):
    """Section 16: never write a file with a broken/blank name."""
    with pytest.raises(InvalidMessageId):
        safe_message_id(bad)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a/b", "id with space", "id?x=1"])
def test_path_traversal_and_unsafe_ids_are_rejected(bad):
    with pytest.raises(InvalidMessageId):
        build_object_key(partition=date(2026, 8, 14), message_id=bad)


def test_normal_gmail_ids_pass():
    assert safe_message_id("1a00de43c2b02073") == "1a00de43c2b02073"


def test_partition_by_received_uses_message_date_not_today():
    ms = int(datetime(2026, 8, 14, 9, 20, tzinfo=timezone.utc).timestamp() * 1000)
    got = partition_date(
        internal_date_ms=ms,
        partition_by="received",
        now=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    assert got == date(2026, 8, 14)


def test_partition_by_ingested_uses_wall_clock():
    ms = int(datetime(2026, 8, 14, 9, 20, tzinfo=timezone.utc).timestamp() * 1000)
    got = partition_date(
        internal_date_ms=ms,
        partition_by="ingested",
        now=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    assert got == date(2026, 8, 17)


def test_partition_falls_back_to_now_when_no_internal_date():
    got = partition_date(
        internal_date_ms=None,
        partition_by="received",
        now=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )
    assert got == date(2026, 8, 17)


def test_day_prefix_for_listing():
    assert day_prefix(partition=date(2026, 8, 14)) == "gmail/2026/08/14/"
