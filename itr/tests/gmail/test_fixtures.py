"""
Tests for the offline fixture client — Task 9.

The promise is that a dead token, a rate limit or dropped wifi does not stop
the pipeline: the same sync runs against exported JSON. So these tests build a
fixture directory from scratch and drive the real GmailRawSync through it, with
no network and no credentials.
"""

from __future__ import annotations

import base64
import json

import pytest

from scout.gmail.client import get_client
from scout.gmail.fixtures import FixtureClient, FixtureError
from scout.gmail.mime import parse_message

pytest_plugins: list[str] = []


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(mid: str, thread: str, history_id: int, ms: int) -> dict:
    return {
        "id": mid,
        "threadId": thread,
        "historyId": str(history_id),
        "internalDate": str(ms),
        "labelIds": ["INBOX"],
        "snippet": f"snippet {mid}",
        "payload": {
            "partId": "",
            "mimeType": "text/plain",
            "filename": "",
            "headers": [
                {"name": "From", "value": f"Cust {mid} <{mid}@northwind.example>"},
                {"name": "To", "value": "support@motiveminds.com"},
                {"name": "Subject", "value": f"Subject {mid}"},
            ],
            "body": {"size": 10, "data": _b64(f"Body of {mid}.")},
        },
    }


@pytest.fixture
def fixture_dir(tmp_path):
    """A small exported-fixture directory, shaped exactly as the exporter writes."""
    msgs = [
        ("m1", "t1", 10, 1_755_158_400_000),
        ("m2", "t1", 20, 1_755_158_500_000),
        ("m3", "t2", 30, 1_755_158_600_000),
        ("m4", "t3", 40, 1_755_158_700_000),
        ("m5", "t4", 50, 1_755_158_800_000),
    ]
    files, thread_of, threads, history = {}, {}, {}, []
    for i, (mid, thread, hid, ms) in enumerate(msgs, start=1):
        name = f"{i:04d}_{mid}.json"
        (tmp_path / name).write_text(json.dumps(_message(mid, thread, hid, ms)), encoding="utf-8")
        files[mid] = name
        thread_of[mid] = thread
        threads.setdefault(thread, []).append(mid)
        history.append({"history_id": hid, "message_id": mid, "thread_id": thread})

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "account_id": "support@motiveminds.com",
                "message_count": len(msgs),
                "message_order": [m[0] for m in msgs],
                "files": files,
                "thread_of": thread_of,
                "threads": threads,
                "history": history,
                "final_history_id": 50,
                "attachments": {},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def client(fixture_dir) -> FixtureClient:
    return FixtureClient(fixture_dir)


# -- the GmailClient surface -------------------------------------------------


def test_profile_reports_the_fixture_mailbox(client: FixtureClient):
    p = client.get_profile()
    assert p["emailAddress"] == "support@motiveminds.com"
    assert p["messagesTotal"] == 5
    assert p["threadsTotal"] == 4
    assert p["historyId"] == "50"


def test_pagination_uses_page_tokens_and_ends_cleanly(client: FixtureClient):
    """Same response shape as Gmail: messages[] plus an optional nextPageToken."""
    seen, token, pages = [], None, 0
    while True:
        data = client.list_message_refs(max_results=2, page_token=token)
        pages += 1
        seen.extend(r["id"] for r in data["messages"])
        token = data.get("nextPageToken")
        if token is None:
            break
    assert seen == ["m1", "m2", "m3", "m4", "m5"]
    assert pages == 3, "5 messages at 2 per page"
    assert len(set(seen)) == len(seen), "no message served twice"
    assert "nextPageToken" not in client.list_message_refs(max_results=99), "last page has no token"


def test_client_surface_matches_gmailclient_exactly():
    """The doc asks for the same method surface as the existing GmailClient."""
    import inspect

    from scout.gmail.client import GmailClient

    gm = {n for n, _ in inspect.getmembers(GmailClient, inspect.isfunction)
          if not n.startswith("_")}
    fm = {n for n, _ in inspect.getmembers(FixtureClient, inspect.isfunction)
          if not n.startswith("_")}
    assert not (gm - fm), f"FixtureClient is missing {sorted(gm - fm)}"
    mismatched = [
        n for n in sorted(gm & fm)
        if str(inspect.signature(getattr(GmailClient, n)))
        != str(inspect.signature(getattr(FixtureClient, n)))
    ]
    assert not mismatched, f"signatures differ: {mismatched}"


def test_iter_all_message_ids_respects_limit(client: FixtureClient):
    assert [m for m, _ in client.iter_all_message_ids(limit=3)] == ["m1", "m2", "m3"]


def test_get_message_returns_a_parseable_full_message(client: FixtureClient):
    parsed = parse_message(client.get_message("m2"))
    assert parsed.external_id == "m2"
    assert parsed.thread_external_id == "t1"
    assert parsed.subject == "Subject m2"
    assert parsed.from_address == "m2@northwind.example"
    assert parsed.body_text == "Body of m2."


def test_minimal_format_omits_the_payload(client: FixtureClient):
    assert "payload" not in client.get_message("m1", format="minimal")


def test_unknown_message_raises(client: FixtureClient):
    with pytest.raises(FixtureError):
        client.get_message("nope")


# -- incremental replay ------------------------------------------------------


def test_history_returns_only_newer_messages(client: FixtureClient):
    newer, newest = client.list_history_message_ids(start_history_id="20")
    assert newer == ["m3", "m4", "m5"], "strictly newer than the cursor"
    assert newest == "50"


def test_history_from_zero_returns_everything(client: FixtureClient):
    newer, _ = client.list_history_message_ids(start_history_id="0")
    assert len(newer) == 5


def test_history_at_the_head_returns_nothing(client: FixtureClient):
    newer, _ = client.list_history_message_ids(start_history_id="50")
    assert newer == []


def test_doc_named_aliases_match(client: FixtureClient):
    """The doc calls these list_messages / history_list."""
    assert client.list_messages(page_token=None) == client.list_message_refs()
    assert client.history_list("20") == client.list_history_message_ids(start_history_id="20")


# -- failure modes -----------------------------------------------------------


def test_missing_directory_says_how_to_fix_it(tmp_path):
    with pytest.raises(FixtureError, match="export_fixtures"):
        FixtureClient(tmp_path / "does-not-exist")


def test_missing_manifest_is_reported(tmp_path):
    with pytest.raises(FixtureError, match="manifest"):
        FixtureClient(tmp_path)


# -- the factory -------------------------------------------------------------


def test_get_client_returns_a_fixture_client_when_asked(fixture_dir, monkeypatch):
    monkeypatch.setattr("scout.config.settings.gmail_fixtures_dir", str(fixture_dir))
    assert isinstance(get_client(use_fixtures=True), FixtureClient)


def test_get_client_follows_the_setting(fixture_dir, monkeypatch):
    monkeypatch.setattr("scout.config.settings.gmail_fixtures_dir", str(fixture_dir))
    monkeypatch.setattr("scout.config.settings.use_gmail_fixtures", True)
    assert isinstance(get_client(), FixtureClient)


# -- the whole point: a real sync, offline -----------------------------------


def test_full_sync_runs_offline_against_fixtures(fixture_dir):
    """GmailRawSync end to end with no network and no credentials."""
    from test_sync import FakeLake, FakeLedger, FakeRunStore  # noqa: E402
    from scout.gmail.sync import GmailRawSync

    lake, ledger, store = FakeLake(), FakeLedger(), FakeRunStore()
    result = GmailRawSync(
        client=FixtureClient(fixture_dir),
        lake=lake,
        ledger=ledger,
        run_store=store,
        account_id="support@motiveminds.com",
        customer_only=False,  # the fixtures are synthetic senders
        max_per_run=100,
    ).run()

    assert result.written == 5
    assert len(lake.objects) == 5
    assert store.last_run["status"] == "success"
    assert store.last_run["messages_written"] == 5
    # All seven stages still emit when running offline.
    assert set(store.stages) == {
        "connect", "discover", "extract", "redact", "normalise", "resolve", "index",
    }


def test_offline_sync_is_idempotent(fixture_dir):
    """Replay must not duplicate: the bucket HEAD is still the guard."""
    from test_sync import FakeLake, FakeLedger, FakeRunStore  # noqa: E402
    from scout.gmail.sync import GmailRawSync

    lake, ledger = FakeLake(), FakeLedger()

    def run_once():
        return GmailRawSync(
            client=FixtureClient(fixture_dir),
            lake=lake,
            ledger=ledger,
            run_store=FakeRunStore(),
            account_id="support@motiveminds.com",
            customer_only=False,
            max_per_run=100,
        ).run()

    first, second = run_once(), run_once()
    assert first.written == 5
    assert second.written == 0, "second pass writes nothing"
    assert len(lake.objects) == 5
