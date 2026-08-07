"""
tests/emulators/test_zendesk_emulator.py — W1-SRC-05 Zendesk emulator API

Covers:
  - Incremental export with cursor + end_of_stream (ordered by generated_timestamp)
  - Sideloads (users, organizations)
  - Single ticket GET
  - Ticket PUT write-back
  - Webhook HMAC emission on update
  - Account-wide rate limiting that depletes
  - Auth 401 + chaos switches via scout.shared
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from scout.emulators.zendesk import ZendeskStore, create_zendesk_app
from scout.emulators.zendesk.export import decode_export_cursor, encode_export_cursor
from scout.emulators.zendesk.factory import create_store
from scout.emulators.zendesk.webhooks import verify_signature


AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def store() -> ZendeskStore:
    s = ZendeskStore()
    s.seed_defaults()
    return s


@pytest.fixture
def client(store: ZendeskStore) -> TestClient:
    app = create_zendesk_app(store=store, rate_limit_max=1000)
    return TestClient(app)


@pytest.fixture
def tight_client(store: ZendeskStore) -> TestClient:
    """Client with a tiny account-wide budget so rate-limit tests are fast."""
    app = create_zendesk_app(
        store=store,
        rate_limit_max=3,
        rate_limit_window_seconds=60,
    )
    return TestClient(app)


# ── Auth ─────────────────────────────────────────────────────────────────────


class TestAuth:
    def test_missing_token_returns_zendesk_401(self, client: TestClient):
        res = client.get("/api/v2/tickets/1")
        assert res.status_code == 401
        body = res.json()
        assert body["error"] == "invalid_token"
        assert "description" in body

    def test_bearer_token_accepted(self, client: TestClient):
        res = client.get("/api/v2/tickets/1", headers=AUTH)
        assert res.status_code == 200


# ── Incremental export ───────────────────────────────────────────────────────


class TestIncrementalExport:
    def test_requires_start_time_or_cursor(self, client: TestClient):
        res = client.get("/api/v2/incremental/tickets/cursor", headers=AUTH)
        assert res.status_code == 400

    def test_orders_by_generated_timestamp(self, client: TestClient, store: ZendeskStore):
        res = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"start_time": 0, "per_page": 25},
            headers=AUTH,
        )
        assert res.status_code == 200
        tickets = res.json()["tickets"]
        assert len(tickets) == 25
        timestamps = [t["generated_timestamp"] for t in tickets]
        assert timestamps == sorted(timestamps)

    def test_cursor_pagination_and_end_of_stream(self, client: TestClient):
        first = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"start_time": 0, "per_page": 10},
            headers=AUTH,
        ).json()
        assert len(first["tickets"]) == 10
        assert first["end_of_stream"] is False
        assert first["after_cursor"]
        assert "cursor=" in first["after_url"]

        second = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"cursor": first["after_cursor"], "per_page": 10},
            headers=AUTH,
        ).json()
        assert len(second["tickets"]) == 10
        assert second["end_of_stream"] is False

        # No overlap between pages
        first_ids = {t["id"] for t in first["tickets"]}
        second_ids = {t["id"] for t in second["tickets"]}
        assert first_ids.isdisjoint(second_ids)

        third = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"cursor": second["after_cursor"], "per_page": 10},
            headers=AUTH,
        ).json()
        assert len(third["tickets"]) == 5
        assert third["end_of_stream"] is True
        # Zendesk still returns after_cursor on the final page for next export
        assert third["after_cursor"]

    def test_start_time_filters_generated_timestamp(self, client: TestClient, store: ZendeskStore):
        mid = store.get_ticket(10)["generated_timestamp"]
        res = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"start_time": mid, "per_page": 100},
            headers=AUTH,
        ).json()
        assert res["end_of_stream"] is True
        assert all(t["generated_timestamp"] >= mid for t in res["tickets"])
        assert res["tickets"][0]["id"] == 10

    def test_export_cursor_roundtrip(self):
        encoded = encode_export_cursor(ts=1700000060, ticket_id=7)
        assert decode_export_cursor(encoded) == (1700000060, 7)


# ── Sideloads ────────────────────────────────────────────────────────────────


class TestSideloads:
    def test_export_include_users_and_organizations(self, client: TestClient):
        res = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={
                "start_time": 0,
                "per_page": 5,
                "include": "users,organizations",
            },
            headers=AUTH,
        ).json()
        assert "users" in res
        assert "organizations" in res
        assert len(res["users"]) >= 1
        assert len(res["organizations"]) >= 1
        user_ids = {u["id"] for u in res["users"]}
        for ticket in res["tickets"]:
            assert ticket["requester_id"] in user_ids or ticket["assignee_id"] in user_ids

    def test_single_ticket_sideloads(self, client: TestClient):
        res = client.get(
            "/api/v2/tickets/2",
            params={"include": "users,organizations"},
            headers=AUTH,
        ).json()
        assert "ticket" in res
        assert res["users"]
        assert res["organizations"]


# ── Single ticket + update ───────────────────────────────────────────────────


class TestTicketEndpoints:
    def test_get_ticket(self, client: TestClient):
        res = client.get("/api/v2/tickets/1", headers=AUTH)
        assert res.status_code == 200
        assert res.json()["ticket"]["id"] == 1
        assert res.json()["ticket"]["subject"] == "Ticket 1"

    def test_get_missing_ticket(self, client: TestClient):
        res = client.get("/api/v2/tickets/99999", headers=AUTH)
        assert res.status_code == 404
        assert res.json()["error"] == "RecordNotFound"

    def test_update_ticket_write_path(self, client: TestClient, store: ZendeskStore):
        before = store.get_ticket(1)
        res = client.put(
            "/api/v2/tickets/1",
            headers=AUTH,
            json={"ticket": {"status": "solved", "priority": "high"}},
        )
        assert res.status_code == 200
        ticket = res.json()["ticket"]
        assert ticket["status"] == "solved"
        assert ticket["priority"] == "high"
        assert ticket["generated_timestamp"] >= before["generated_timestamp"]
        assert ticket["subject"] == before["subject"]  # unchanged fields kept


# ── Webhooks + HMAC ──────────────────────────────────────────────────────────


class TestWebhooks:
    def test_update_emits_hmac_signed_webhook(self, client: TestClient, store: ZendeskStore):
        client.put(
            "/api/v2/tickets/3",
            headers=AUTH,
            json={"ticket": {"status": "closed"}},
        )
        assert len(store.emitted_webhooks) == 1
        delivery = store.emitted_webhooks[0]
        headers = delivery["headers"]
        assert "X-Zendesk-Webhook-Signature" in headers
        assert "X-Zendesk-Webhook-Signature-Timestamp" in headers
        assert verify_signature(
            body=delivery["body"],
            timestamp=headers["X-Zendesk-Webhook-Signature-Timestamp"],
            signature=headers["X-Zendesk-Webhook-Signature"],
            secret=store.webhook_secret,
        )
        payload = json.loads(delivery["body"])
        assert payload["type"].startswith("zen:event-type:ticket")
        assert payload["detail"]["status"] == "closed"

    def test_tampered_body_fails_verification(self, client: TestClient, store: ZendeskStore):
        client.put(
            "/api/v2/tickets/4",
            headers=AUTH,
            json={"ticket": {"status": "hold"}},
        )
        delivery = store.emitted_webhooks[0]
        assert not verify_signature(
            body=delivery["body"] + "tamper",
            timestamp=delivery["headers"]["X-Zendesk-Webhook-Signature-Timestamp"],
            signature=delivery["headers"]["X-Zendesk-Webhook-Signature"],
            secret=store.webhook_secret,
        )


# ── Rate limiting ────────────────────────────────────────────────────────────


class TestRateLimit:
    def test_account_wide_rate_limit_depletes(self, tight_client: TestClient):
        # Budget is 3 — fourth request must 429 with Retry-After
        for _ in range(3):
            res = tight_client.get("/api/v2/tickets/1", headers=AUTH)
            assert res.status_code == 200

        limited = tight_client.get("/api/v2/tickets/1", headers=AUTH)
        assert limited.status_code == 429
        assert limited.headers.get("Retry-After")
        assert limited.json()["error"] == "APIRateLimitExceeded"

        # Depletion is account-wide (different endpoint still blocked)
        other = tight_client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"start_time": 0},
            headers=AUTH,
        )
        assert other.status_code == 429


# ── Chaos ────────────────────────────────────────────────────────────────────


class TestChaos:
    def test_chaos_429(self, client: TestClient):
        res = client.get(
            "/api/v2/tickets/1",
            params={"chaos": "429"},
            headers=AUTH,
        )
        assert res.status_code == 429
        assert res.headers.get("Retry-After")

    def test_chaos_500(self, client: TestClient):
        res = client.get(
            "/api/v2/tickets/1",
            params={"chaos": "500"},
            headers=AUTH,
        )
        assert res.status_code == 500
        assert res.json()["error"] == "InternalServerError"

    def test_chaos_partial_keeps_stream_open(self, client: TestClient):
        res = client.get(
            "/api/v2/incremental/tickets/cursor",
            params={"start_time": 0, "per_page": 10, "chaos": "partial"},
            headers=AUTH,
        ).json()
        # Partial page is shorter than per_page but still has more data
        assert len(res["tickets"]) < 10
        assert res["end_of_stream"] is False
        assert res["after_cursor"]


class TestStoreFactory:
    def test_create_store_requires_postgres_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ZENDESK_DATABASE_URL", raising=False)
        with pytest.raises(ValueError, match="requires live Postgres"):
            create_store()

    def test_health_reports_injected_store_backend(self, client: TestClient):
        # Unit tests inject in-memory store; production uses postgres only.
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["backend"] == "memory"
