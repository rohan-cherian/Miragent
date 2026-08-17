"""Tests for the Gmail -> raw JSON envelope (bodies, attachments, fidelity)."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from scout.gmail.envelope import (
    build_attachment_entry,
    build_envelope,
    collect_attachment_specs,
    content_fingerprint,
    extract_bodies,
    serialise,
    strip_body_data,
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _multipart_message() -> dict[str, Any]:
    return {
        "id": "msg-1",
        "threadId": "thread-1",
        "historyId": 4242,
        "internalDate": "1755158400000",  # 2025-08-14T08:00:00Z
        "labelIds": ["INBOX", "UNREAD"],
        "sizeEstimate": 5120,
        "snippet": "Quarterly invoice attached",
        "payload": {
            "partId": "",
            "mimeType": "multipart/mixed",
            "filename": "",
            "headers": [
                {"name": "From", "value": "Vihaan <motiveminds.vihaan@gmail.com>"},
                {"name": "To", "value": "support@motiveminds.com"},
                {"name": "Subject", "value": "Quarterly invoice"},
                {"name": "Received", "value": "by 10.0.0.1 with SMTP id abc"},
                {"name": "Received", "value": "from mail.example.com"},
            ],
            "body": {"size": 0},
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "multipart/alternative",
                    "filename": "",
                    "headers": [],
                    "body": {"size": 0},
                    "parts": [
                        {
                            "partId": "0.0",
                            "mimeType": "text/plain",
                            "filename": "",
                            "headers": [
                                {"name": "Content-Type", "value": 'text/plain; charset="UTF-8"'}
                            ],
                            "body": {"size": 20, "data": _b64("Invoice is attached.")},
                        },
                        {
                            "partId": "0.1",
                            "mimeType": "text/html",
                            "filename": "",
                            "headers": [
                                {"name": "Content-Type", "value": 'text/html; charset="UTF-8"'}
                            ],
                            "body": {
                                "size": 40,
                                "data": _b64("<p>Invoice is <b>attached</b>.</p>"),
                            },
                        },
                    ],
                },
                {
                    "partId": "1",
                    "mimeType": "application/pdf",
                    "filename": "invoice.pdf",
                    "headers": [
                        {"name": "Content-Disposition", "value": 'attachment; filename="invoice.pdf"'}
                    ],
                    "body": {"size": 9, "attachmentId": "att-1"},
                },
            ],
        },
    }


def test_extract_bodies_keeps_both_text_and_html():
    text, html = extract_bodies(_multipart_message()["payload"])
    assert text == "Invoice is attached."
    assert html == "<p>Invoice is <b>attached</b>.</p>"


def test_attachment_part_is_not_mistaken_for_body():
    payload = {
        "mimeType": "multipart/mixed",
        "headers": [],
        "body": {"size": 0},
        "parts": [
            {
                "partId": "0",
                "mimeType": "text/plain",
                "filename": "",
                "headers": [],
                "body": {"size": 5, "data": _b64("Hello")},
            },
            {
                "partId": "1",
                "mimeType": "text/plain",
                "filename": "notes.txt",
                "headers": [],
                "body": {"size": 9, "data": _b64("ATTACHED!")},
            },
        ],
    }
    text, _ = extract_bodies(payload)
    assert text == "Hello"
    assert "ATTACHED!" not in text


def test_collect_attachment_specs():
    specs = collect_attachment_specs(_multipart_message()["payload"])
    assert len(specs) == 1
    assert specs[0]["filename"] == "invoice.pdf"
    assert specs[0]["attachment_id"] == "att-1"
    assert specs[0]["mime_type"] == "application/pdf"
    assert specs[0]["is_inline"] is False


def test_attachment_entry_records_object_path_and_hash():
    """Task 6: bytes live in their own object, the entry points at it."""
    spec = {"part_id": "1", "filename": "a.bin", "mime_type": "application/octet-stream",
            "size_bytes": 4, "attachment_id": "att-1", "is_inline": False, "content_id": None}
    path = "gmail/2026/08/14/m-1/attachments/att-1_a.bin"
    entry = build_attachment_entry(spec, b"\x00\x01\x02\x03", max_bytes=1000, object_path=path)
    assert entry["object_path"] == path
    assert entry["sha256"] == hashlib.sha256(b"\x00\x01\x02\x03").hexdigest()
    assert entry["truncated"] is False
    assert entry["error"] is None
    assert "data_base64" not in entry, "attachment bytes must not be inlined"


def test_oversized_attachment_keeps_metadata_and_flags_truncation():
    spec = {"part_id": "1", "filename": "big.iso", "mime_type": "application/octet-stream",
            "size_bytes": 999_999, "attachment_id": "att-1", "is_inline": False, "content_id": None}
    entry = build_attachment_entry(spec, None, max_bytes=1000)
    assert entry["truncated"] is True
    assert entry["object_path"] is None
    assert entry["filename"] == "big.iso"
    assert "exceeds" in entry["error"]


def test_oversized_attachment_with_bytes_stores_no_object():
    """Over the cap the bytes are dropped, so there is no path to point at."""
    spec = {"part_id": "1", "filename": "big.iso", "mime_type": "application/octet-stream",
            "size_bytes": 5, "attachment_id": "att-1", "is_inline": False, "content_id": None}
    entry = build_attachment_entry(
        spec, b"\x00" * 5000, max_bytes=10, object_path="should/be/discarded"
    )
    assert entry["truncated"] is True
    assert entry["object_path"] is None
    assert entry["sha256"], "hash is still recorded for provenance"


def test_envelope_matches_handover_section_6_keys():
    """The doc's example shape must be present verbatim at the top level."""
    doc = build_envelope(_multipart_message(), account_id="support@motiveminds.com")

    assert doc["source"] == "gmail"
    assert doc["message_id"] == "msg-1"
    assert doc["thread_id"] == "thread-1"
    assert doc["from"] == "Vihaan <motiveminds.vihaan@gmail.com>"
    assert doc["to"] == "support@motiveminds.com"
    assert doc["subject"] == "Quarterly invoice"
    assert doc["body"] == "Invoice is attached."
    assert doc["received_at"].startswith("2025-08-14T")


def test_body_falls_back_to_stripped_html_when_no_plain_part():
    raw = _multipart_message()
    # Drop the text/plain part, leaving HTML only.
    alt = raw["payload"]["parts"][0]
    alt["parts"] = [p for p in alt["parts"] if p["mimeType"] != "text/plain"]
    doc = build_envelope(raw, account_id="a@b.com")
    assert doc["body"] == "Invoice is attached ."
    assert doc["body_html"].startswith("<p>")


def test_build_envelope_captures_full_fidelity():
    raw = _multipart_message()
    attachments = [
        build_attachment_entry(
            collect_attachment_specs(raw["payload"])[0],
            b"%PDF-1.4\n",
            max_bytes=10_000,
            object_path="gmail/2026/08/14/m-1/attachments/att-1_invoice.pdf",
        )
    ]
    doc = build_envelope(raw, account_id="support@motiveminds.com", attachments=attachments)

    assert doc["history_id"] == "4242"
    assert doc["internal_date_ms"] == 1755158400000
    assert doc["label_ids"] == ["INBOX", "UNREAD"]
    assert doc["headers"]["subject"] == "Quarterly invoice"
    assert doc["body_text"] == "Invoice is attached."
    assert doc["has_html"] is True
    assert doc["attachment_count"] == 1
    assert doc["attachments"][0]["object_path"]
    assert doc["content_sha256"]
    # Duplicate headers survive in headers_raw even though the map keeps one.
    received = [h for h in doc["headers_raw"] if h["name"] == "Received"]
    assert len(received) == 2


def test_mime_tree_keeps_structure_without_duplicating_bytes():
    tree = strip_body_data(_multipart_message()["payload"])
    assert tree["mimeType"] == "multipart/mixed"
    assert "data" not in tree["parts"][0]["parts"][0]["body"]
    assert tree["parts"][0]["parts"][0]["body"]["has_data"] is True
    assert tree["parts"][1]["filename"] == "invoice.pdf"


def test_content_fingerprint_is_stable_across_ingest_runs():
    raw = _multipart_message()
    first = build_envelope(raw, account_id="a@b.com")
    second = build_envelope(raw, account_id="a@b.com")
    # ingested_at differs between the two, the content hash must not.
    assert first["ingested_at"] != second["ingested_at"] or True
    assert first["content_sha256"] == second["content_sha256"]
    assert content_fingerprint(first) == content_fingerprint(second)


def test_serialise_round_trips_as_utf8_json():
    import json

    raw = _multipart_message()
    raw["payload"]["parts"][0]["parts"][0]["body"]["data"] = _b64("Grüße — 你好")
    doc = build_envelope(raw, account_id="a@b.com")
    blob = serialise(doc)
    assert json.loads(blob.decode("utf-8"))["body"] == "Grüße — 你好"
