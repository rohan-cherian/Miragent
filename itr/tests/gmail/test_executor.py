"""
Tests for the Gmail ActionExecutor — Task 21.

Two guarantees are worth more than the rest combined:

  1. Nothing sends without a matching approval. Every refusal path is checked,
     and each asserts no HTTP call was attempted — refusing *after* hitting the
     wire would be no refusal at all.
  2. A reply lands inside its original thread. Gmail needs threadId in the body
     AND In-Reply-To/References on the message; either alone makes the reply
     open a new conversation, which is the failure everyone sees.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scout.connectors.base import (
    ActionExecutor,
    ApprovedAction,
    DataReader,
    EventListener,
    MetadataReader,
    SendResult,
)
from scout.gmail import executor as ex
from scout.gmail.executor import ApprovalRequired, build_reply_message, send_reply

APPROVED_HASH = "a" * 64


class _Approval:
    def __init__(self, state="approved", payload_hash=APPROVED_HASH, case_id="case-1"):
        self.approval_id = "appr-1"
        self.case_id = case_id
        self.payload_hash = payload_hash
        self.state = state


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything reaches the wire during a refusal test."""
    calls = []

    def boom(*a, **kw):
        calls.append(a)
        raise AssertionError("network call attempted during a refusal")

    monkeypatch.setattr(ex, "_post_send", boom)
    monkeypatch.setattr(ex, "_access_token", boom)
    return calls


def _args(**over):
    base = dict(
        approval_id="appr-1",
        case_id="case-1",
        to_address="cust@example.com",
        subject="Broken laptop",
        body_text="We have shipped a replacement.",
        thread_external_id="thread-9",
        in_reply_to_message_id="msg-7",
        payload_hash=APPROVED_HASH,
    )
    base.update(over)
    return base


# -- refusal paths -----------------------------------------------------------


def test_no_approval_id_refuses(no_network):
    with pytest.raises(ApprovalRequired, match="no approval_id"):
        send_reply(**_args(approval_id=None))


def test_missing_approval_record_refuses(monkeypatch, no_network):
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: None)
    with pytest.raises(ApprovalRequired, match="no approval record"):
        send_reply(**_args())


def test_unapproved_state_refuses(monkeypatch, no_network):
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: _Approval(state="draft_pending"))
    with pytest.raises(ApprovalRequired, match="draft_pending"):
        send_reply(**_args())


def test_rejected_state_refuses(monkeypatch, no_network):
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: _Approval(state="rejected"))
    with pytest.raises(ApprovalRequired):
        send_reply(**_args())


def test_hash_mismatch_refuses(monkeypatch, no_network):
    """Text edited after approval must not go out under that approval."""
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: _Approval())
    with pytest.raises(ApprovalRequired, match="changed after it was approved"):
        send_reply(**_args(payload_hash="b" * 64))


def test_empty_hash_refuses(monkeypatch, no_network):
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: _Approval())
    with pytest.raises(ApprovalRequired):
        send_reply(**_args(payload_hash=""))


@pytest.mark.parametrize("state", ["approved", "edited_approved"])
def test_both_approved_states_are_accepted(monkeypatch, state):
    sent = {}
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: _Approval(state=state))
    monkeypatch.setattr(ex, "_access_token", lambda: "tok")
    monkeypatch.setattr(
        ex, "_post_send", lambda p, t: sent.update(p) or {"id": "m1", "threadId": "thread-9"}
    )
    result = send_reply(**_args())
    assert isinstance(result, SendResult)
    assert result.message_id == "m1"


# -- threading ---------------------------------------------------------------


def test_reply_sets_threadid_and_both_headers(monkeypatch):
    """threadId in the body AND In-Reply-To/References on the message."""
    captured = {}
    monkeypatch.setattr(ex, "_load_approval", lambda *a, **k: _Approval())
    monkeypatch.setattr(ex, "_access_token", lambda: "tok")
    monkeypatch.setattr(
        ex,
        "_post_send",
        lambda payload, token: captured.update(payload)
        or {"id": "m1", "threadId": "thread-9"},
    )

    result = send_reply(**_args())

    assert captured["threadId"] == "thread-9", "threadId must be in the request body"
    import base64

    raw = base64.urlsafe_b64decode(captured["raw"]).decode()
    assert "In-Reply-To: <msg-7>" in raw
    assert "References: <msg-7>" in raw
    assert result.thread_id == "thread-9"
    assert isinstance(result.sent_at, datetime)


def test_subject_gets_re_prefix_once():
    m = build_reply_message(
        to_address="a@b.com", from_address="s@x.com", subject="Broken laptop",
        body_text="hi", in_reply_to_message_id=None,
    )
    assert m["Subject"] == "Re: Broken laptop"


@pytest.mark.parametrize("subject", ["Re: Broken laptop", "RE: Broken laptop"])
def test_existing_re_prefix_is_not_doubled(subject):
    m = build_reply_message(
        to_address="a@b.com", from_address="s@x.com", subject=subject,
        body_text="hi", in_reply_to_message_id=None,
    )
    assert m["Subject"] == subject
    assert not m["Subject"].lower().startswith("re: re:")


def test_message_id_gets_angle_brackets_if_missing():
    m = build_reply_message(
        to_address="a@b.com", from_address="s@x.com", subject="s",
        body_text="hi", in_reply_to_message_id="bare-id",
    )
    assert m["In-Reply-To"] == "<bare-id>"
    assert m["References"] == "<bare-id>"


def test_already_bracketed_id_is_left_alone():
    m = build_reply_message(
        to_address="a@b.com", from_address="s@x.com", subject="s",
        body_text="hi", in_reply_to_message_id="<already>",
    )
    assert m["In-Reply-To"] == "<already>"


# -- the protocol surface ----------------------------------------------------


def test_adapter_implements_all_four_protocols():
    from scout.connectors.gmail import GmailAdapter

    a = GmailAdapter(client=object())
    for proto in (MetadataReader, DataReader, EventListener, ActionExecutor):
        assert isinstance(a, proto), proto.__name__


def test_event_listener_raises_rather_than_pretending():
    """A stub returning [] would look like 'no events' forever."""
    from scout.connectors.gmail import GmailAdapter

    a = GmailAdapter(client=object())
    with pytest.raises(NotImplementedError):
        a.verify({}, b"{}")
    with pytest.raises(NotImplementedError):
        a.to_events(b"{}")


def test_approved_action_carries_the_approval():
    """execute() cannot be called without an approval record in the type."""
    action = ApprovedAction(
        approval_id="appr-1", case_id="case-1", action_type="send_reply",
        payload_hash=APPROVED_HASH, approved_by="rohan",
        approved_at=datetime.now(timezone.utc),
    )
    assert action.payload_hash == APPROVED_HASH
    with pytest.raises(TypeError):
        ApprovedAction(approval_id="appr-1")  # type: ignore[call-arg]


def test_adapter_refuses_unknown_action_type():
    from scout.connectors.gmail import GmailAdapter

    a = GmailAdapter(client=object())
    action = ApprovedAction(
        approval_id="x", case_id="c", action_type="delete_everything",
        payload_hash=APPROVED_HASH,
    )
    with pytest.raises(ValueError, match="cannot execute"):
        a.execute(action)


# -- rate limiting -----------------------------------------------------------


def test_429_is_retried_with_growing_jittered_delay(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(ex.time, "sleep", slept.append)

    attempts = {"n": 0}

    class Res:
        def __init__(self, code): self.status_code = code; self.text = "rate"
        def json(self): return {"id": "m1", "threadId": "t1"}

    class Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **kw):
            attempts["n"] += 1
            return Res(429 if attempts["n"] < 3 else 200)

    monkeypatch.setattr(ex.httpx, "Client", lambda **kw: Client())
    out = ex._post_send({"raw": "x"}, "tok")

    assert out["id"] == "m1"
    assert attempts["n"] == 3
    assert len(slept) == 2
    assert slept[1] > slept[0], "backoff must grow"
    assert slept[0] != ex._BASE_DELAY_SECONDS, "jitter must perturb the delay"


def test_non_rate_limit_error_is_not_retried(monkeypatch):
    attempts = {"n": 0}

    class Res:
        status_code = 400
        text = "bad request"
        def json(self): return {}

    class Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **kw):
            attempts["n"] += 1
            return Res()

    monkeypatch.setattr(ex.httpx, "Client", lambda **kw: Client())
    with pytest.raises(ex.GmailSendError):
        ex._post_send({"raw": "x"}, "tok")
    assert attempts["n"] == 1, "a 400 is a real answer, not worth retrying"
