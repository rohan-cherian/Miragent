"""
tests/test_connectors_sprint36.py — Sprint 36 connector tests

Covers:
  - RampConnector   (Ramp corporate card)
  - BrexConnector   (Brex corporate card)
  - CoupaConnector  (Coupa Business Spend Management)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK_CONNECTORS", "false")

from scout.connectors.brex import BrexConnector
from scout.connectors.coupa import CoupaConnector
from scout.connectors.models import ConnectorCredentials, ExtractionCursor
from scout.connectors.ramp import RampConnector


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _creds(connector_id: str, **kwargs) -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id=connector_id,
        tenant_id="test-tenant",
        auth_data=kwargs,
    )


def _mock_http(status_code: int = 200, body=None) -> MagicMock:
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


class TestRegistrySprint36:
    def test_ramp_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "ramp" in CONNECTOR_REGISTRY

    def test_brex_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "brex" in CONNECTOR_REGISTRY

    def test_coupa_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "coupa" in CONNECTOR_REGISTRY

    def test_all_are_finance(self):
        from scout.connectors.models import ConnectorCategory
        assert RampConnector.CATEGORY == ConnectorCategory.FINANCE
        assert BrexConnector.CATEGORY == ConnectorCategory.FINANCE
        assert CoupaConnector.CATEGORY == ConnectorCategory.FINANCE


# ─────────────────────────────────────────────────────────────────────────────
# RampConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestRampConnector:

    def _make_conn(self) -> RampConnector:
        return RampConnector(_creds("ramp", client_id="ramp-cid", client_secret="ramp-secret"))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make_conn()
        token_resp = _mock_http(200, {"access_token": "ramp-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "ramp-tok"

    def test_authenticate_uses_client_credentials_grant(self):
        conn = self._make_conn()
        captured = {}

        def _capture(url, **kwargs):
            captured["data"] = kwargs.get("data", {})
            return _mock_http(200, {"access_token": "t", "expires_in": 3600})

        with patch.object(conn._http_client, "post", side_effect=_capture):
            conn.authenticate()

        assert captured["data"].get("grant_type") == "client_credentials"
        assert captured["data"].get("client_id") == "ramp-cid"

    def test_authenticate_missing_client_id_returns_false(self):
        conn = RampConnector(_creds("ramp", client_secret="s"))
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(401)):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_no_token_in_response_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(200, {})):
            result = conn.authenticate()
        assert result is False

    # ── Schema ─────────────────────────────────────────────────────────────

    def test_discover_schema_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"user", "card", "transaction"}

    def test_transaction_supports_incremental(self):
        conn = self._make_conn()
        txn_schema = next(s for s in conn.discover_schema() if s.entity_type == "transaction")
        assert txn_schema.supports_incremental is True

    # ── Entity Endpoint ────────────────────────────────────────────────────

    def test_entity_endpoint_transaction(self):
        conn = self._make_conn()
        assert conn._entity_endpoint("transaction") == "/transactions"

    def test_entity_endpoint_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Ramp"):
            conn._entity_endpoint("invoice")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_users_single_page(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        page = {
            "data": [
                {"id": "u1", "first_name": "Alice", "last_name": "Smith", "email": "alice@acme.com"},
                {"id": "u2", "first_name": "Bob", "last_name": "Jones"},
            ],
            "page": {"next": None},
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("user"))

        assert len(records) == 2
        assert records[0].source_id == "u1"
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_cursor_pagination(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        page1 = {
            "data": [{"id": f"t{i}"} for i in range(100)],
            "page": {"next": "cursor-abc"},
        }
        page2 = {
            "data": [{"id": f"t{i}"} for i in range(100, 130)],
            "page": {"next": None},
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("transaction"))

        assert len(records) == 130

    def test_extract_full_stops_when_no_next(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        page = {"data": [{"id": "c1"}], "page": {}}  # no "next" key
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("card"))
        assert len(records) == 1

    # ── Incremental ────────────────────────────────────────────────────────

    def test_extract_incremental_passes_from_date(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"data": [], "page": {}}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("transaction", _cursor("ramp", "transaction"))
            list(gen)

        assert "from_date" in captured_params
        assert "2026-01-01" in captured_params["from_date"]

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", return_value={"data": [], "page": {}}):
            gen, new_cursor = conn.extract_incremental("transaction", _cursor("ramp", "transaction"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", return_value={"data": []}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", side_effect=Exception("rate_limited")):
            health = conn.health_check()
        assert health.is_healthy is False


# ─────────────────────────────────────────────────────────────────────────────
# BrexConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBrexConnector:

    def _make_conn(self) -> BrexConnector:
        return BrexConnector(_creds("brex", api_token="brex-api-tok"))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make_conn()
        resp = _mock_http(200, {"items": []})
        with patch.object(conn._http_client, "get", return_value=resp):
            result = conn.authenticate()
        assert result is True
        assert conn._api_token == "brex-api-tok"

    def test_authenticate_missing_api_token_returns_false(self):
        conn = BrexConnector(_creds("brex"))
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "get", return_value=_mock_http(403)):
            result = conn.authenticate()
        assert result is False

    def test_headers_include_bearer(self):
        conn = self._make_conn()
        conn._api_token = "my-token"
        assert conn._headers()["Authorization"] == "Bearer my-token"

    # ── Schema ─────────────────────────────────────────────────────────────

    def test_discover_schema_four_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"user", "card", "transaction", "expense"}

    # ── Entity Endpoint ────────────────────────────────────────────────────

    def test_entity_endpoint_transaction(self):
        conn = self._make_conn()
        assert conn._entity_endpoint("transaction") == "/v2/transactions/card/primary"

    def test_entity_endpoint_expense(self):
        conn = self._make_conn()
        assert conn._entity_endpoint("expense") == "/v2/expenses/card"

    def test_entity_endpoint_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Brex"):
            conn._entity_endpoint("invoice")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_single_page(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        page = {
            "items": [
                {"id": "u1", "first_name": "Alice", "last_name": "Smith", "email": "alice@co.com"},
            ],
            "next_cursor": None,
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("user"))

        assert len(records) == 1
        assert records[0].source_id == "u1"
        assert records[0].email_hint == "alice@co.com"

    def test_extract_full_cursor_pagination(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        page1 = {"items": [{"id": f"t{i}"} for i in range(100)], "next_cursor": "next-cursor-xyz"}
        page2 = {"items": [{"id": f"t{i}"} for i in range(100, 140)], "next_cursor": None}
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("transaction"))
        assert len(records) == 140

    # ── Incremental ────────────────────────────────────────────────────────

    def test_extract_incremental_passes_initiated_at_start(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"items": [], "next_cursor": None}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("transaction", _cursor("brex", "transaction"))
            list(gen)

        assert "initiated_at_start" in captured_params

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        with patch.object(conn, "_get", return_value={"items": []}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        with patch.object(conn, "_get", side_effect=Exception("network")):
            health = conn.health_check()
        assert health.is_healthy is False

    # ── RawRecord ─────────────────────────────────────────────────────────

    def test_to_raw_record_transaction_merchant_name(self):
        conn = self._make_conn()
        record = {
            "id": "tx-1",
            "merchant": {"raw_descriptor": "AWS"},
            "amount": {"amount": 5000, "currency": "USD"},
        }
        rr = conn._to_raw_record("transaction", record)
        assert rr.source_id == "tx-1"
        assert rr.name_hint == "AWS"


# ─────────────────────────────────────────────────────────────────────────────
# CoupaConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCoupaConnector:

    def _make_conn(self) -> CoupaConnector:
        return CoupaConnector(
            _creds("coupa", instance="acme", client_id="c-id", client_secret="c-secret")
        )

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make_conn()
        token_resp = _mock_http(200, {"access_token": "coupa-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "coupa-tok"
        assert conn._base_url == "https://acme.coupahost.com"

    def test_authenticate_missing_instance_returns_false(self):
        conn = CoupaConnector(_creds("coupa", client_id="c", client_secret="s"))
        assert conn.authenticate() is False

    def test_authenticate_missing_client_id_returns_false(self):
        conn = CoupaConnector(_creds("coupa", instance="acme", client_secret="s"))
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(401)):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_no_token_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(200, {"error": "x"})):
            result = conn.authenticate()
        assert result is False

    # ── Schema ─────────────────────────────────────────────────────────────

    def test_discover_schema_four_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"supplier", "purchase_order", "invoice", "user"}

    # ── Entity Endpoint ────────────────────────────────────────────────────

    def test_entity_endpoint_supplier(self):
        conn = self._make_conn()
        assert conn._entity_endpoint("supplier") == "/api/suppliers"

    def test_entity_endpoint_purchase_order(self):
        conn = self._make_conn()
        assert conn._entity_endpoint("purchase_order") == "/api/purchase_orders"

    def test_entity_endpoint_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Coupa"):
            conn._entity_endpoint("transaction")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_suppliers_array_response(self):
        """Coupa returns an array directly (not wrapped in a key)."""
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        # Array response with 2 records (< PAGE_SIZE → stops)
        suppliers = [
            {"id": 1, "name": "ACME Supplies", "status": "active"},
            {"id": 2, "name": "Beta Corp", "status": "active"},
        ]
        with patch.object(conn, "_get", return_value=suppliers):
            records = list(conn.extract_full("supplier"))

        assert len(records) == 2
        assert records[0].source_id == "1"
        assert records[0].name_hint == "ACME Supplies"

    def test_extract_full_paginate_multiple_pages(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        from scout.connectors.coupa import _PAGE_SIZE

        page1 = [{"id": i, "name": f"Supplier {i}"} for i in range(_PAGE_SIZE)]
        page2 = [{"id": i, "name": f"Supplier {i}"} for i in range(10)]
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("supplier"))
        assert len(records) == _PAGE_SIZE + 10

    def test_extract_full_dict_response_with_data_key(self):
        """Also handles wrapped response with data key."""
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        wrapped = {"data": [{"id": 1, "name": "Test Vendor"}]}
        with patch.object(conn, "_get", return_value=wrapped):
            records = list(conn.extract_full("supplier"))
        assert len(records) == 1

    # ── Incremental ────────────────────────────────────────────────────────

    def test_extract_incremental_filter_format(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return []

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("invoice", _cursor("coupa", "invoice"))
            list(gen)

        assert "filters[updated_at][gt]" in captured_params
        assert "2026-01-01" in captured_params["filters[updated_at][gt]"]

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        with patch.object(conn, "_get", return_value=[]):
            gen, new_cursor = conn.extract_incremental("user", _cursor("coupa", "user"))
            list(gen)
        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        with patch.object(conn, "_get", return_value=[]):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.coupahost.com"

        with patch.object(conn, "_get", side_effect=Exception("auth_expired")):
            health = conn.health_check()
        assert health.is_healthy is False

    # ── RawRecord ─────────────────────────────────────────────────────────

    def test_to_raw_record_invoice_number_as_name(self):
        conn = self._make_conn()
        record = {"id": 5, "invoice_number": "INV-2026-001", "gross_total": 10000}
        rr = conn._to_raw_record("invoice", record)
        assert rr.name_hint == "INV-2026-001"

    def test_to_raw_record_user_login_as_email(self):
        conn = self._make_conn()
        record = {"id": 10, "login": "jdoe@acme.com", "firstname": "John", "lastname": "Doe"}
        rr = conn._to_raw_record("user", record)
        assert rr.email_hint == "jdoe@acme.com"
        assert rr.name_hint == "John Doe"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-connector contract tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossConnectorSprint36:
    @pytest.mark.parametrize("cls,creds_kwargs", [
        (RampConnector,  {"client_id": "c", "client_secret": "s"}),
        (BrexConnector,  {"api_token": "t"}),
        (CoupaConnector, {"instance": "acme", "client_id": "c", "client_secret": "s"}),
    ])
    def test_connector_id_nonempty(self, cls, creds_kwargs):
        assert isinstance(cls.CONNECTOR_ID, str) and len(cls.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (RampConnector,  {"client_id": "c", "client_secret": "s"}),
        (BrexConnector,  {"api_token": "t"}),
        (CoupaConnector, {"instance": "acme", "client_id": "c", "client_secret": "s"}),
    ])
    def test_discover_schema_nonempty(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        assert len(conn.discover_schema()) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (RampConnector,  {"client_id": "c", "client_secret": "s"}),
        (BrexConnector,  {"api_token": "t"}),
        (CoupaConnector, {"instance": "acme", "client_id": "c", "client_secret": "s"}),
    ])
    def test_calls_per_second_positive(self, cls, creds_kwargs):
        assert cls.CALLS_PER_SECOND > 0
