"""
tests/test_connectors_sprint33.py — Sprint 33 connector tests

Covers:
  - DynamicsCRMConnector  (Microsoft Dynamics 365 Sales / CRM)
  - ZohoConnector         (Zoho CRM)

Pattern: all tests run with USE_MOCK_CONNECTORS=false so the real connector
classes are exercised. HTTP calls are intercepted by patching conn._get (for
data-fetch operations) or conn._http_client (for auth POST/GET operations).
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK_CONNECTORS", "false")

from scout.connectors.dynamics_crm import DynamicsCRMConnector
from scout.connectors.models import ConnectorCredentials, ExtractionCursor
from scout.connectors.zoho import ZohoConnector


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _creds(connector_id: str, **kwargs) -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id=connector_id,
        tenant_id="test-tenant",
        auth_data=kwargs,
    )


def _mock_http_post(status_code: int = 200, body: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    if status_code >= 400:
        m.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        m.raise_for_status.return_value = None
    return m


def _mock_http_get(status_code: int = 200, body: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
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
# Registry / class attribute checks
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistrySprint33:
    def test_dynamics_crm_connector_id(self):
        assert DynamicsCRMConnector.CONNECTOR_ID == "dynamics_crm"

    def test_dynamics_crm_display_name(self):
        assert "Dynamics" in DynamicsCRMConnector.DISPLAY_NAME
        assert "CRM" in DynamicsCRMConnector.DISPLAY_NAME

    def test_dynamics_crm_category(self):
        from scout.connectors.models import ConnectorCategory
        assert DynamicsCRMConnector.CATEGORY == ConnectorCategory.CRM

    def test_zoho_connector_id(self):
        assert ZohoConnector.CONNECTOR_ID == "zoho"

    def test_zoho_display_name(self):
        assert "Zoho" in ZohoConnector.DISPLAY_NAME

    def test_zoho_category(self):
        from scout.connectors.models import ConnectorCategory
        assert ZohoConnector.CATEGORY == ConnectorCategory.CRM

    def test_dynamics_crm_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "dynamics_crm" in CONNECTOR_REGISTRY

    def test_zoho_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "zoho" in CONNECTOR_REGISTRY


# ─────────────────────────────────────────────────────────────────────────────
# DynamicsCRMConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDynamicsCRMConnector:

    def _make_conn(self, org="acme") -> DynamicsCRMConnector:
        return DynamicsCRMConnector(
            _creds(
                "dynamics_crm",
                tenant_id="aad-tenant-guid",
                client_id="app-client-id",
                client_secret="app-secret",
                org=org,
            )
        )

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success_short_org(self):
        conn = self._make_conn(org="acme")
        token_resp = _mock_http_post(200, {"access_token": "dyn-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "dyn-tok"
        assert conn._base_url == "https://acme.crm.dynamics.com/api/data/v9.2"

    def test_authenticate_base_url_from_full_hostname(self):
        conn = self._make_conn(org="acme.crm4.dynamics.com")
        token_resp = _mock_http_post(200, {"access_token": "tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            conn.authenticate()
        assert conn._base_url == "https://acme.crm4.dynamics.com/api/data/v9.2"

    def test_authenticate_scope_uses_org_hostname(self):
        conn = self._make_conn(org="myorg")
        captured = {}
        def _capture_post(url, **kwargs):
            captured["data"] = kwargs.get("data", {})
            return _mock_http_post(200, {"access_token": "t", "expires_in": 3600})
        with patch.object(conn._http_client, "post", side_effect=_capture_post):
            conn.authenticate()
        assert "myorg.crm.dynamics.com/.default" in captured["data"].get("scope", "")

    def test_authenticate_missing_org_returns_false(self):
        conn = DynamicsCRMConnector(
            _creds("dynamics_crm", tenant_id="t", client_id="c", client_secret="s")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_client_id_returns_false(self):
        conn = DynamicsCRMConnector(
            _creds("dynamics_crm", tenant_id="t", client_secret="s", org="acme")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        err_resp = _mock_http_post(401, {})
        with patch.object(conn._http_client, "post", return_value=err_resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_no_token_in_response_returns_false(self):
        conn = self._make_conn()
        empty_resp = _mock_http_post(200, {"expires_in": 3600})  # no access_token
        with patch.object(conn._http_client, "post", return_value=empty_resp):
            result = conn.authenticate()
        assert result is False

    def test_refresh_if_needed_triggers_when_expired(self):
        conn = self._make_conn()
        conn._token_expires_at = time.time() - 10  # already expired
        token_resp = _mock_http_post(200, {"access_token": "new-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            conn._refresh_if_needed()
        assert conn._access_token == "new-tok"

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_returns_five_entity_types(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        entity_types = {s.entity_type for s in schemas}
        assert entity_types == {"contact", "lead", "account", "opportunity", "activity"}

    def test_discover_schema_incremental_supported(self):
        conn = self._make_conn()
        for schema in conn.discover_schema():
            assert schema.supports_incremental is True

    # ── Entity Config ──────────────────────────────────────────────────────

    def test_entity_config_contact_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("contact")
        assert cfg["endpoint"] == "/contacts"

    def test_entity_config_opportunity_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("opportunity")
        assert cfg["endpoint"] == "/opportunities"

    def test_entity_config_activity_uses_activitypointers(self):
        conn = self._make_conn()
        cfg = conn._entity_config("activity")
        assert cfg["endpoint"] == "/activitypointers"

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="DynamicsCRM"):
            conn._entity_config("unknown_entity")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_contacts_single_page(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        page = {
            "value": [
                {"contactid": "c1", "fullname": "Alice Smith", "emailaddress1": "alice@acme.com"},
                {"contactid": "c2", "fullname": "Bob Jones", "emailaddress1": "bob@acme.com"},
            ]
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("contact"))

        assert len(records) == 2
        assert records[0].source_id == "c1"
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_leads_pagination(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        page1 = {
            "value": [{"leadid": f"l{i}", "fullname": f"Lead {i}"} for i in range(5)],
            "@odata.nextLink": "https://acme.crm.dynamics.com/api/data/v9.2/leads?$skiptoken=abc",
        }
        page2 = {
            "value": [{"leadid": f"l{i}", "fullname": f"Lead {i}"} for i in range(5, 8)],
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kwargs: next(responses)):
            records = list(conn.extract_full("lead"))

        assert len(records) == 8

    def test_extract_full_nextlink_stops_when_absent(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        page = {"value": [{"accountid": "a1", "name": "ACME Corp"}]}
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("account"))

        assert len(records) == 1

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_filter_format(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        captured_params: dict = {}

        def _capture_get(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"value": []}

        with patch.object(conn, "_get", side_effect=_capture_get):
            gen, new_cursor = conn.extract_incremental("contact", _cursor("dynamics_crm", "contact"))
            list(gen)

        assert "$filter" in captured_params
        assert "modifiedon ge" in captured_params["$filter"]
        assert "2026-01-01T00:00:00Z" in captured_params["$filter"]

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        with patch.object(conn, "_get", return_value={"value": []}):
            gen, new_cursor = conn.extract_incremental("lead", _cursor("dynamics_crm", "lead"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert new_cursor.entity_type == "lead"

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        with patch.object(conn, "_get", return_value={"value": [{"contactid": "x"}]}):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.latency_ms >= 0

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._base_url = "https://acme.crm.dynamics.com/api/data/v9.2"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "timeout" in health.error_message

    # ── RawRecord mapping ──────────────────────────────────────────────────

    def test_to_raw_record_opportunity(self):
        conn = self._make_conn()
        record = {
            "opportunityid": "opp-001",
            "name": "Big Deal",
            "estimatedvalue": 100000,
        }
        rr = conn._to_raw_record("opportunity", record)
        assert rr.source_id == "opp-001"
        assert rr.name_hint == "Big Deal"
        assert rr.connector_id == "dynamics_crm"

    def test_to_raw_record_uses_emailaddress2_as_fallback(self):
        conn = self._make_conn()
        record = {
            "contactid": "c-1",
            "emailaddress2": "alt@acme.com",
        }
        rr = conn._to_raw_record("contact", record)
        assert rr.email_hint == "alt@acme.com"

    def test_headers_include_odata_version(self):
        conn = self._make_conn()
        conn._access_token = "bearer-tok"
        headers = conn._headers()
        assert headers["OData-Version"] == "4.0"
        assert "Bearer bearer-tok" in headers["Authorization"]


# ─────────────────────────────────────────────────────────────────────────────
# ZohoConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestZohoConnector:

    def _make_conn(self, region="com") -> ZohoConnector:
        return ZohoConnector(
            _creds(
                "zoho",
                client_id="zoho-client-id",
                client_secret="zoho-secret",
                refresh_token="zoho-refresh-tok",
                region=region,
            )
        )

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make_conn()
        token_resp = _mock_http_post(200, {"access_token": "zoho-acc-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "zoho-acc-tok"

    def test_authenticate_sets_api_base_us(self):
        conn = self._make_conn(region="com")
        token_resp = _mock_http_post(200, {"access_token": "t", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            conn.authenticate()
        assert conn._api_base == "https://www.zohoapis.com/crm/v3"

    def test_authenticate_sets_api_base_eu(self):
        conn = self._make_conn(region="eu")
        token_resp = _mock_http_post(200, {"access_token": "t", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            conn.authenticate()
        assert conn._api_base == "https://www.zohoapis.eu/crm/v3"

    def test_authenticate_uses_refresh_token_grant(self):
        conn = self._make_conn()
        captured = {}

        def _capture(url, **kwargs):
            captured["params"] = kwargs.get("params", {})
            return _mock_http_post(200, {"access_token": "t", "expires_in": 3600})

        with patch.object(conn._http_client, "post", side_effect=_capture):
            conn.authenticate()

        assert captured["params"].get("grant_type") == "refresh_token"
        assert captured["params"].get("refresh_token") == "zoho-refresh-tok"

    def test_authenticate_missing_refresh_token_returns_false(self):
        conn = ZohoConnector(
            _creds("zoho", client_id="c", client_secret="s")  # no refresh_token
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_client_id_returns_false(self):
        conn = ZohoConnector(
            _creds("zoho", client_secret="s", refresh_token="r")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_no_token_in_response_returns_false(self):
        conn = self._make_conn()
        err_resp = _mock_http_post(200, {"error": "invalid_client"})
        with patch.object(conn._http_client, "post", return_value=err_resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        err_resp = _mock_http_post(400, {})
        with patch.object(conn._http_client, "post", return_value=err_resp):
            result = conn.authenticate()
        assert result is False

    def test_refresh_if_needed_triggers_when_expired(self):
        conn = self._make_conn()
        conn._token_expires_at = time.time() - 10
        token_resp = _mock_http_post(200, {"access_token": "refreshed", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            conn._refresh_if_needed()
        assert conn._access_token == "refreshed"

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_returns_five_entity_types(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        entity_types = {s.entity_type for s in schemas}
        assert entity_types == {"lead", "contact", "account", "deal", "activity"}

    def test_discover_schema_all_support_incremental(self):
        conn = self._make_conn()
        for schema in conn.discover_schema():
            assert schema.supports_incremental is True

    # ── Entity Config ──────────────────────────────────────────────────────

    def test_entity_config_lead_module(self):
        conn = self._make_conn()
        cfg = conn._entity_config("lead")
        assert cfg["module"] == "Leads"

    def test_entity_config_deal_module(self):
        conn = self._make_conn()
        cfg = conn._entity_config("deal")
        assert cfg["module"] == "Deals"

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Zoho"):
            conn._entity_config("invoice")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_contacts_single_page(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        page = {
            "data": [
                {"id": "1", "First_Name": "Alice", "Last_Name": "Smith", "Email": "alice@acme.com"},
                {"id": "2", "First_Name": "Bob", "Last_Name": "Jones", "Email": "bob@acme.com"},
            ],
            "info": {"more_records": False, "page": 1, "per_page": 200},
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("contact"))

        assert len(records) == 2
        assert records[0].source_id == "1"
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_paginate_more_records(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        page1 = {
            "data": [{"id": f"{i}", "Account_Name": f"Company {i}"} for i in range(5)],
            "info": {"more_records": True, "page": 1, "per_page": 200},
        }
        page2 = {
            "data": [{"id": f"{i}", "Account_Name": f"Company {i}"} for i in range(5, 8)],
            "info": {"more_records": False, "page": 2, "per_page": 200},
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("account"))

        assert len(records) == 8

    def test_extract_full_stops_when_more_records_false(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        page = {
            "data": [{"id": "d1", "Deal_Name": "Q1 Deal"}],
            "info": {"more_records": False},
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("deal"))

        assert len(records) == 1

    def test_extract_full_handles_empty_data(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        with patch.object(conn, "_get", return_value={"data": [], "info": {"more_records": False}}):
            records = list(conn.extract_full("lead"))

        assert records == []

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_uses_search_endpoint(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        captured_url: list[str] = []

        def _capture(url, **kwargs):
            captured_url.append(url)
            return {"data": [], "info": {"more_records": False}}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("contact", _cursor("zoho", "contact"))
            list(gen)

        assert any("search" in u for u in captured_url)

    def test_extract_incremental_criteria_format(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"data": [], "info": {"more_records": False}}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("lead", _cursor("zoho", "lead"))
            list(gen)

        criteria = captured_params.get("criteria", "")
        assert "Modified_Time" in criteria
        assert "greater_than" in criteria
        assert "2026-01-01" in criteria

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        with patch.object(conn, "_get", return_value={"data": [], "info": {"more_records": False}}):
            gen, new_cursor = conn.extract_incremental("deal", _cursor("zoho", "deal"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert new_cursor.entity_type == "deal"

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        resp = {"data": [{"id": "1", "First_Name": "Test"}], "info": {"more_records": False}}
        with patch.object(conn, "_get", return_value=resp):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.latency_ms >= 0

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://www.zohoapis.com/crm/v3"

        with patch.object(conn, "_get", side_effect=Exception("auth_failed")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "auth_failed" in health.error_message

    # ── RawRecord mapping ──────────────────────────────────────────────────

    def test_to_raw_record_deal(self):
        conn = self._make_conn()
        record = {"id": "d-001", "Deal_Name": "Mega Deal", "Amount": 500000}
        rr = conn._to_raw_record("deal", record)
        assert rr.source_id == "d-001"
        assert rr.name_hint == "Mega Deal"
        assert rr.connector_id == "zoho"

    def test_to_raw_record_activity_uses_subject_as_name(self):
        conn = self._make_conn()
        record = {"id": "act-1", "Subject": "Follow up call", "Activity_Type": "Call"}
        rr = conn._to_raw_record("activity", record)
        assert rr.name_hint == "Follow up call"

    def test_to_raw_record_contact_name_from_first_last(self):
        conn = self._make_conn()
        record = {
            "id": "c-1",
            "First_Name": "Jane",
            "Last_Name": "Doe",
            "Email": "jane@test.com",
        }
        rr = conn._to_raw_record("contact", record)
        assert rr.name_hint == "Jane Doe"
        assert rr.email_hint == "jane@test.com"

    def test_headers_use_zoho_oauth_prefix(self):
        conn = self._make_conn()
        conn._access_token = "my-token"
        headers = conn._headers()
        assert headers["Authorization"] == "Zoho-oauthtoken my-token"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-connector contract tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossConnectorSprint33:
    """Verify both Sprint 33 connectors satisfy the ConnectorBase contract."""

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (
            DynamicsCRMConnector,
            {"tenant_id": "aad-t", "client_id": "c", "client_secret": "s", "org": "acme"},
        ),
        (
            ZohoConnector,
            {"client_id": "c", "client_secret": "s", "refresh_token": "r"},
        ),
    ])
    def test_has_connector_id(self, cls, creds_kwargs):
        assert isinstance(cls.CONNECTOR_ID, str)
        assert len(cls.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (
            DynamicsCRMConnector,
            {"tenant_id": "aad-t", "client_id": "c", "client_secret": "s", "org": "acme"},
        ),
        (
            ZohoConnector,
            {"client_id": "c", "client_secret": "s", "refresh_token": "r"},
        ),
    ])
    def test_discover_schema_returns_list(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        schemas = conn.discover_schema()
        assert isinstance(schemas, list)
        assert len(schemas) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (
            DynamicsCRMConnector,
            {"tenant_id": "aad-t", "client_id": "c", "client_secret": "s", "org": "acme"},
        ),
        (
            ZohoConnector,
            {"client_id": "c", "client_secret": "s", "refresh_token": "r"},
        ),
    ])
    def test_extract_full_returns_iterator(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        if hasattr(conn, "_base_url"):
            conn._base_url = "https://example.com/api/data/v9.2"
        if hasattr(conn, "_api_base"):
            conn._api_base = "https://www.zohoapis.com/crm/v3"

        entity_type = conn.discover_schema()[0].entity_type

        # Return empty page
        if cls == DynamicsCRMConnector:
            empty = {"value": []}
        else:
            empty = {"data": [], "info": {"more_records": False}}

        with patch.object(conn, "_get", return_value=empty):
            result = conn.extract_full(entity_type)
            assert hasattr(result, "__iter__")
            assert hasattr(result, "__next__")

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (
            DynamicsCRMConnector,
            {"tenant_id": "aad-t", "client_id": "c", "client_secret": "s", "org": "acme"},
        ),
        (
            ZohoConnector,
            {"client_id": "c", "client_secret": "s", "refresh_token": "r"},
        ),
    ])
    def test_extract_incremental_returns_tuple(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        if hasattr(conn, "_base_url"):
            conn._base_url = "https://example.com/api/data/v9.2"
        if hasattr(conn, "_api_base"):
            conn._api_base = "https://www.zohoapis.com/crm/v3"

        entity_type = conn.discover_schema()[0].entity_type
        cursor = _cursor(cls.CONNECTOR_ID, entity_type)

        if cls == DynamicsCRMConnector:
            empty = {"value": []}
        else:
            empty = {"data": [], "info": {"more_records": False}}

        with patch.object(conn, "_get", return_value=empty):
            result = conn.extract_incremental(entity_type, cursor)
            assert isinstance(result, tuple)
            assert len(result) == 2
            gen, new_cursor = result
            list(gen)
            assert new_cursor.connector_id == cls.CONNECTOR_ID

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (
            DynamicsCRMConnector,
            {"tenant_id": "aad-t", "client_id": "c", "client_secret": "s", "org": "acme"},
        ),
        (
            ZohoConnector,
            {"client_id": "c", "client_secret": "s", "refresh_token": "r"},
        ),
    ])
    def test_calls_per_second_positive(self, cls, creds_kwargs):
        assert cls.CALLS_PER_SECOND > 0
