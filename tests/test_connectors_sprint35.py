"""
tests/test_connectors_sprint35.py — Sprint 35 connector tests

Covers:
  - ZendeskConnector       (Zendesk Support)
  - FreshserviceConnector  (Freshservice ITSM)
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK_CONNECTORS", "false")

from scout.connectors.freshservice import FreshserviceConnector
from scout.connectors.models import ConnectorCredentials, ExtractionCursor
from scout.connectors.zendesk import ZendeskConnector


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _creds(connector_id: str, **kwargs) -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id=connector_id,
        tenant_id="test-tenant",
        auth_data=kwargs,
    )


def _mock_http(status_code: int = 200, body: dict | list | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body if body is not None else {}
    if status_code >= 400:
        m.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        m.raise_for_status.return_value = None
    return m


def _cursor(connector_id: str, entity_type: str) -> ExtractionCursor:
    return ExtractionCursor(
        connector_id=connector_id,
        entity_type=entity_type,
        last_extracted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registry checks
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistrySprint35:
    def test_zendesk_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "zendesk" in CONNECTOR_REGISTRY

    def test_freshservice_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "freshservice" in CONNECTOR_REGISTRY

    def test_zendesk_connector_id(self):
        assert ZendeskConnector.CONNECTOR_ID == "zendesk"

    def test_freshservice_connector_id(self):
        assert FreshserviceConnector.CONNECTOR_ID == "freshservice"

    def test_both_are_itsm(self):
        from scout.connectors.models import ConnectorCategory
        assert ZendeskConnector.CATEGORY == ConnectorCategory.ITSM
        assert FreshserviceConnector.CATEGORY == ConnectorCategory.ITSM


# ─────────────────────────────────────────────────────────────────────────────
# ZendeskConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestZendeskConnector:

    def _make_conn(self, auth_mode="api_token") -> ZendeskConnector:
        kwargs: dict = {"auth_mode": auth_mode, "subdomain": "acme"}
        if auth_mode == "api_token":
            kwargs["email"] = "admin@acme.com"
            kwargs["api_token"] = "zdtok123"
        elif auth_mode == "oauth":
            kwargs["access_token"] = "zd-oauth-token"
        return ZendeskConnector(_creds("zendesk", **kwargs))

    def _me_resp(self):
        return _mock_http(200, {"user": {"id": 1, "email": "admin@acme.com"}})

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_api_token_success(self):
        conn = self._make_conn("api_token")
        with patch.object(conn._http_client, "get", return_value=self._me_resp()):
            result = conn.authenticate()
        assert result is True
        assert "Basic " in conn._auth_header
        assert conn._base_url == "https://acme.zendesk.com"

    def test_authenticate_api_token_uses_email_slash_token_format(self):
        conn = self._make_conn("api_token")
        with patch.object(conn._http_client, "get", return_value=self._me_resp()):
            conn.authenticate()
        encoded = conn._auth_header.replace("Basic ", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "admin@acme.com/token:zdtok123"

    def test_authenticate_oauth_success(self):
        conn = self._make_conn("oauth")
        with patch.object(conn._http_client, "get", return_value=self._me_resp()):
            result = conn.authenticate()
        assert result is True
        assert conn._auth_header == "Bearer zd-oauth-token"

    def test_authenticate_missing_subdomain_returns_false(self):
        conn = ZendeskConnector(_creds("zendesk", email="e@e.com", api_token="t"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_api_token_missing_email_returns_false(self):
        conn = ZendeskConnector(_creds("zendesk", subdomain="acme", api_token="t"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_oauth_missing_token_returns_false(self):
        conn = ZendeskConnector(_creds("zendesk", subdomain="acme", auth_mode="oauth"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_unknown_mode_returns_false(self):
        conn = ZendeskConnector(_creds("zendesk", subdomain="acme", auth_mode="saml"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "get", return_value=_mock_http(401)):
            result = conn.authenticate()
        assert result is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"ticket", "user", "organization"}

    def test_discover_schema_all_incremental(self):
        conn = self._make_conn()
        for s in conn.discover_schema():
            assert s.supports_incremental is True

    # ── Entity Config ──────────────────────────────────────────────────────

    def test_entity_config_ticket_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("ticket")
        assert cfg["endpoint"] == "/api/v2/tickets"
        assert cfg["key"] == "tickets"

    def test_entity_config_organization_has_incremental_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("organization")
        assert "incremental" in cfg["incremental_endpoint"]

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Zendesk"):
            conn._entity_config("chat")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_tickets_single_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        page = {
            "tickets": [
                {"id": 1, "subject": "Can't login", "status": "open"},
                {"id": 2, "subject": "Slow perf", "status": "pending"},
            ],
            "meta": {"has_more": False},
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("ticket"))

        assert len(records) == 2
        assert records[0].source_id == "1"
        assert records[0].name_hint == "Can't login"

    def test_extract_full_cursor_pagination(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        page1 = {
            "tickets": [{"id": i, "subject": f"T{i}"} for i in range(100)],
            "meta": {"has_more": True, "after_cursor": "cursor-abc"},
        }
        page2 = {
            "tickets": [{"id": i, "subject": f"T{i}"} for i in range(100, 130)],
            "meta": {"has_more": False},
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("ticket"))

        assert len(records) == 130

    def test_extract_full_legacy_next_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        page1 = {
            "tickets": [{"id": 1, "subject": "T1"}],
            "next_page": "https://acme.zendesk.com/api/v2/tickets?page=2",
        }
        page2 = {
            "tickets": [{"id": 2, "subject": "T2"}],
            "next_page": None,
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("ticket"))

        assert len(records) == 2

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_uses_start_time(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"tickets": [], "end_of_stream": True}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("ticket", _cursor("zendesk", "ticket"))
            list(gen)

        assert "start_time" in captured_params
        # 2026-01-01 00:00:00 UTC = 1767225600
        assert captured_params["start_time"] == int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())

    def test_extract_incremental_end_of_stream_stops(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        resp = {
            "tickets": [{"id": 99, "subject": "Latest"}],
            "end_of_stream": True,
            "end_time": 1234567890,
        }
        with patch.object(conn, "_get", return_value=resp):
            gen, new_cursor = conn.extract_incremental("ticket", _cursor("zendesk", "ticket"))
            records = list(gen)

        assert len(records) == 1

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        with patch.object(conn, "_get", return_value={"tickets": [], "end_of_stream": True}):
            gen, new_cursor = conn.extract_incremental("user", _cursor("zendesk", "user"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert new_cursor.entity_type == "user"

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        with patch.object(conn, "_get", return_value={"user": {"id": 1}}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.zendesk.com"

        with patch.object(conn, "_get", side_effect=Exception("DNS")):
            health = conn.health_check()
        assert health.is_healthy is False

    # ── RawRecord ─────────────────────────────────────────────────────────

    def test_to_raw_record_org(self):
        conn = self._make_conn()
        record = {"id": 55, "name": "ACME Corp"}
        rr = conn._to_raw_record("organization", record)
        assert rr.source_id == "55"
        assert rr.name_hint == "ACME Corp"
        assert rr.connector_id == "zendesk"

    def test_to_raw_record_user_email(self):
        conn = self._make_conn()
        record = {"id": 10, "name": "Alice", "email": "alice@acme.com"}
        rr = conn._to_raw_record("user", record)
        assert rr.email_hint == "alice@acme.com"


# ─────────────────────────────────────────────────────────────────────────────
# FreshserviceConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFreshserviceConnector:

    def _make_conn(self) -> FreshserviceConnector:
        return FreshserviceConnector(
            _creds("freshservice", domain="acme", api_key="fs-api-key-123")
        )

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make_conn()
        validation = _mock_http(200, {"tickets": []})
        with patch.object(conn._http_client, "get", return_value=validation):
            result = conn.authenticate()
        assert result is True
        assert conn._base_url == "https://acme.freshservice.com"

    def test_authenticate_auth_header_format(self):
        """API key goes in username field, password is literal 'X'."""
        conn = self._make_conn()
        validation = _mock_http(200, {"tickets": []})
        with patch.object(conn._http_client, "get", return_value=validation):
            conn.authenticate()
        encoded = conn._auth_header.replace("Basic ", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "fs-api-key-123:X"

    def test_authenticate_missing_domain_returns_false(self):
        conn = FreshserviceConnector(_creds("freshservice", api_key="k"))
        assert conn.authenticate() is False

    def test_authenticate_missing_api_key_returns_false(self):
        conn = FreshserviceConnector(_creds("freshservice", domain="acme"))
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "get", return_value=_mock_http(403)):
            result = conn.authenticate()
        assert result is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_four_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"ticket", "requester", "agent", "asset"}

    def test_discover_schema_all_incremental(self):
        conn = self._make_conn()
        for s in conn.discover_schema():
            assert s.supports_incremental is True

    # ── Entity Config ──────────────────────────────────────────────────────

    def test_entity_config_ticket_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("ticket")
        assert cfg["endpoint"] == "/api/v2/tickets"
        assert cfg["key"] == "tickets"

    def test_entity_config_asset_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("asset")
        assert cfg["endpoint"] == "/api/v2/assets"

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Freshservice"):
            conn._entity_config("employee")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_tickets_single_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        page = {
            "tickets": [
                {"id": 1, "subject": "New laptop request", "status": 2,
                 "requester_id": 101},
                {"id": 2, "subject": "VPN access", "status": 2,
                 "requester_id": 102},
            ]
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("ticket"))

        assert len(records) == 2
        assert records[0].source_id == "1"
        assert records[0].name_hint == "New laptop request"

    def test_extract_full_pagination_stops_on_partial_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        page = {"requesters": [{"id": i, "first_name": "R", "last_name": f"{i}"} for i in range(5)]}
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("requester"))
        assert len(records) == 5

    def test_extract_full_paginate_multiple_pages(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        from scout.connectors.freshservice import _PAGE_SIZE

        page1 = {"agents": [{"id": i, "first_name": "A", "last_name": f"{i}"} for i in range(_PAGE_SIZE)]}
        page2 = {"agents": [{"id": i, "first_name": "A", "last_name": f"{i}"} for i in range(20)]}
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("agent"))
        assert len(records) == _PAGE_SIZE + 20

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_updated_since_param(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"tickets": []}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("ticket", _cursor("freshservice", "ticket"))
            list(gen)

        assert "updated_since" in captured_params
        assert "2026-01-01" in captured_params["updated_since"]

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        with patch.object(conn, "_get", return_value={"assets": []}):
            gen, new_cursor = conn.extract_incremental("asset", _cursor("freshservice", "asset"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        with patch.object(conn, "_get", return_value={"tickets": []}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.freshservice.com"

        with patch.object(conn, "_get", side_effect=Exception("auth_fail")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "auth_fail" in health.error_message

    # ── RawRecord ─────────────────────────────────────────────────────────

    def test_to_raw_record_agent(self):
        conn = self._make_conn()
        record = {"id": 42, "first_name": "Jane", "last_name": "Doe", "email": "jane@acme.com"}
        rr = conn._to_raw_record("agent", record)
        assert rr.source_id == "42"
        assert rr.email_hint == "jane@acme.com"
        assert rr.name_hint == "Jane Doe"

    def test_to_raw_record_asset_uses_name(self):
        conn = self._make_conn()
        record = {"id": 10, "name": "MacBook Pro #5", "asset_tag": "A-00005"}
        rr = conn._to_raw_record("asset", record)
        assert rr.name_hint == "MacBook Pro #5"

    def test_to_raw_record_ticket_subject_as_name(self):
        conn = self._make_conn()
        record = {"id": 99, "subject": "Access request for Jira"}
        rr = conn._to_raw_record("ticket", record)
        assert rr.name_hint == "Access request for Jira"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-connector contract tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossConnectorSprint35:
    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ZendeskConnector, {"subdomain": "acme", "email": "a@b.com", "api_token": "t"}),
        (FreshserviceConnector, {"domain": "acme", "api_key": "k"}),
    ])
    def test_connector_id_nonempty(self, cls, creds_kwargs):
        assert isinstance(cls.CONNECTOR_ID, str) and len(cls.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ZendeskConnector, {"subdomain": "acme", "email": "a@b.com", "api_token": "t"}),
        (FreshserviceConnector, {"domain": "acme", "api_key": "k"}),
    ])
    def test_discover_schema_nonempty(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        assert len(conn.discover_schema()) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ZendeskConnector, {"subdomain": "acme", "email": "a@b.com", "api_token": "t"}),
        (FreshserviceConnector, {"domain": "acme", "api_key": "k"}),
    ])
    def test_calls_per_second_positive(self, cls, creds_kwargs):
        assert cls.CALLS_PER_SECOND > 0
