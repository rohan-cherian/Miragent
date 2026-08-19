"""
Task 17 — tests for parent/child chunking.

No database and no network: chunk_message() is a pure function over a
canonical message dict, so these run everywhere.
"""

from __future__ import annotations

import uuid

import pytest

from scout.context.chunk import (
    Chunk,
    UnredactedTextError,
    build_acl_tags,
    chunk_message,
    looks_unredacted,
)

TENANT_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()
CASE_ID = uuid.uuid4()
PERSON_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()


def make_message(body: str) -> dict:
    """A canonical itr360.message row, already redacted (Task 12/13)."""
    return {
        "id": MESSAGE_ID,
        "case_id": CASE_ID,
        "person_id": PERSON_ID,
        "tenant_id": TENANT_ID,
        "subject": "Licence key not working after renewal",
        "body_redacted": body,
        "pii_status": "redacted",
    }


SHORT_BODY = (
    "Hi team, my licence key stopped working after the renewal went through "
    "last Tuesday. Could someone reissue it? Reference PII_EMAIL_01 on the "
    "original order."
)

MULTI_PARAGRAPH_BODY = (
    "Hi team, my licence key stopped working after the renewal went through.\n"
    "I have tried it on two machines.\n"
    "\n"
    "The order confirmation says the subscription is active until March. "
    "Billing has already taken the payment, so I do not think this is a "
    "payment problem.\n"
    "\n"
    "Could someone reissue the key today? We have a release scheduled on "
    "Friday and the build machine cannot sign without it.\n"
    "\n"
    "Thanks,\nPII_PERSON_01"
)


# ── Offsets and basic shape ───────────────────────────────────────────────


def test_short_message_produces_at_least_one_chunk():
    chunks = chunk_message(make_message(SHORT_BODY), org_id=ORG_ID)

    assert len(chunks) >= 1
    assert all(isinstance(chunk, Chunk) for chunk in chunks)
    assert all(chunk.child_text.strip() for chunk in chunks)


def test_offsets_slice_back_to_child_text_exactly():
    """The citation guarantee: body[start:end] is the child, character for character."""
    body = MULTI_PARAGRAPH_BODY
    chunks = chunk_message(make_message(body), org_id=ORG_ID)

    assert chunks
    for chunk in chunks:
        assert 0 <= chunk.start_offset < chunk.end_offset <= len(body)
        assert body[chunk.start_offset:chunk.end_offset] == chunk.child_text


def test_parent_text_contains_child_text():
    chunks = chunk_message(make_message(MULTI_PARAGRAPH_BODY), org_id=ORG_ID)

    for chunk in chunks:
        assert chunk.child_text in chunk.parent_text


def test_every_chunk_traces_back_to_its_source_message():
    chunks = chunk_message(make_message(MULTI_PARAGRAPH_BODY), org_id=ORG_ID)

    assert chunks
    for chunk in chunks:
        assert chunk.message_id == MESSAGE_ID
        assert chunk.case_id == CASE_ID
        assert chunk.person_id == PERSON_ID
        assert isinstance(chunk.chunk_id, uuid.UUID)


def test_chunk_ids_are_unique():
    chunks = chunk_message(make_message(MULTI_PARAGRAPH_BODY), org_id=ORG_ID)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


# ── Parent segmentation ───────────────────────────────────────────────────


def test_paragraph_breaks_produce_multiple_parent_chunks():
    chunks = chunk_message(make_message(MULTI_PARAGRAPH_BODY), org_id=ORG_ID)

    parents = {chunk.parent_text for chunk in chunks}
    assert len(parents) >= 2, f"expected multiple parents, got {parents}"
    assert max(chunk.parent_index for chunk in chunks) >= 1


def test_message_without_paragraph_breaks_has_one_parent():
    chunks = chunk_message(make_message(SHORT_BODY), org_id=ORG_ID)

    assert len({chunk.parent_text for chunk in chunks}) == 1


def test_long_body_produces_multiple_children_within_a_parent():
    sentence = "The build machine cannot sign the release without a valid key. "
    body = sentence * 120  # comfortably past the ~1200-char child window
    chunks = chunk_message(make_message(body), org_id=ORG_ID)

    assert len(chunks) > 1
    for chunk in chunks:
        assert body[chunk.start_offset:chunk.end_offset] == chunk.child_text


def test_wall_of_text_without_sentence_ends_still_chunks():
    body = "renewal " * 800  # no terminators at all
    chunks = chunk_message(make_message(body), org_id=ORG_ID)

    assert len(chunks) > 1
    for chunk in chunks:
        assert body[chunk.start_offset:chunk.end_offset] == chunk.child_text


# ── ACL tags (Task 18 filters on these at query time) ─────────────────────


def test_acl_tags_carry_tenant_and_org():
    chunks = chunk_message(make_message(SHORT_BODY), org_id=ORG_ID)

    assert chunks
    for chunk in chunks:
        assert f"tenant:{TENANT_ID}" in chunk.acl_tags
        assert f"org:{ORG_ID}" in chunk.acl_tags


def test_acl_tags_omit_org_when_unknown():
    assert build_acl_tags(TENANT_ID, None) == [f"tenant:{TENANT_ID}"]


# ── Empty / degenerate input ──────────────────────────────────────────────


@pytest.mark.parametrize("body", ["", "   ", "\n\n\t\n"])
def test_empty_body_produces_no_chunks(body):
    assert chunk_message(make_message(body)) == []


def test_bare_string_input_is_rejected():
    with pytest.raises(TypeError):
        chunk_message(SHORT_BODY)  # type: ignore[arg-type]


# ── The "already-redacted input only" contract ────────────────────────────
#
# LIMITATION, documented deliberately: this contract cannot be enforced
# generically. looks_unredacted() catches the two unambiguous signals — a
# bare email address (pii.redact() masks EMAIL_ADDRESS unconditionally) and
# an unmasked 13-19 digit run. It CANNOT detect an unredacted personal name,
# street address, or free-text disclosure; those are indistinguishable from
# ordinary prose without re-running the analyser, which this pure function
# deliberately does not do. The real guarantee is upstream: callers pass
# itr360.message.body_redacted, and pii.redact() fails closed (Task 12).
# These tests pin the part that IS enforceable and document the rest.


def test_bare_email_address_is_rejected():
    body = "Please reissue the key and copy priya.sharma@northwind.example on it."

    with pytest.raises(UnredactedTextError) as excinfo:
        chunk_message(make_message(body))

    assert "unredacted" in str(excinfo.value).lower()


def test_unmasked_long_digit_run_is_rejected():
    body = "The card on file ends 4111111111111111, please check billing."

    with pytest.raises(UnredactedTextError):
        chunk_message(make_message(body))


def test_redacted_placeholders_pass_the_contract_check():
    body = (
        "Please reissue the key and copy PII_EMAIL_01 on it. "
        "Card PII_CREDIT_CARD_01 is the one on file."
    )

    assert looks_unredacted(body) is None
    assert chunk_message(make_message(body))


def test_strict_false_documents_the_escape_hatch():
    """strict=False exists for callers with their own proof of redaction."""
    body = "Contact priya.sharma@northwind.example about the renewal."

    assert chunk_message(make_message(body), strict=False)


def test_contract_limitation_unredacted_name_is_not_detected():
    """Documents what the heuristic cannot do — this is a known gap, not a bug."""
    body = "Priya Sharma from Northwind called about the renewal on Tuesday."

    assert looks_unredacted(body) is None  # a real name slips through
    assert chunk_message(make_message(body))  # and so does chunking
