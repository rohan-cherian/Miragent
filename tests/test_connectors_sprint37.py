"""
tests/test_connectors_sprint37.py — Sprint 37 connector tests

Covers:
  - ConcurConnector         (SAP Concur Travel & Expense)
  - BillcomConnector        (Bill.com AP/AR)
  - GoogleWorkspaceConnector (Google Workspace)
  - JumpCloudConnector      (JumpCloud Directory)
  - QuickBooksConnector     (QuickBooks Online)
  - GustoConnector          (Gusto Payroll & HR)
  - PipedriveConnector      (Pipedrive CRM)
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK_CONNECTORS", "false")

from scout.connectors.billcom import BillcomConnector
from scout.connectors.concur import ConcurConnector
from scout.connectors.google_workspace import GoogleWorkspaceConnector
from scout.connectors.gusto import GustoConnector
from scout.connectors.jumpcloud import JumpCloudConnector
from scout.connectors.models import ConnectorCredentials, ExtractionCursor
from scout.connectors.pipedrive import PipedriveConnector
from scout.connectors.quickbooks import QuickBooksConnector


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


class TestRegistrySprint37:
    @pytest.mark.parametrize("connector_id", [
        "concur", "billcom", "google_workspace",
        "jumpcloud", "quickbooks", "gusto", "pipedrive",
    ])
    def test_connector_in_registry(self, connector_id):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert connector_id in CONNECTOR_REGISTRY

    def test_concur_category(self):
        from scout.connectors.models import ConnectorCategory
        assert ConcurConnector.CATEGORY == ConnectorCategory.FINANCE

    def test_billcom_category(self):
        from scout.connectors.models import ConnectorCategory
        assert BillcomConnector.CATEGORY == ConnectorCategory.FINANCE

    def test_google_workspace_category(self):
        from scout.connectors.models import ConnectorCategory
        assert GoogleWorkspaceConnector.CATEGORY == ConnectorCategory.IDENTITY

    def test_jumpcloud_category(self):
        from scout.connectors.models import ConnectorCategory
        assert JumpCloudConnector.CATEGORY == ConnectorCategory.IDENTITY

    def test_quickbooks_category(self):
        from scout.connectors.models import ConnectorCategory
        assert QuickBooksConnector.CATEGORY == ConnectorCategory.ERP

    def test_gusto_category(self):
        from scout.connectors.models import ConnectorCategory
        assert GustoConnector.CATEGORY == ConnectorCategory.HCM

    def test_pipedrive_category(self):
        from scout.connectors.models import ConnectorCategory
        assert PipedriveConnector.CATEGORY == ConnectorCategory.CRM


# ─────────────────────────────────────────────────────────────────────────────
# ConcurConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestConcurConnector:

    def _make_conn(self) -> ConcurConnector:
        return ConcurConnector(
            _creds("concur",
                   client_id="c-id", client_secret="c-sec",
                   company_uuid="company-uuid-123")
        )

    def test_authenticate_success(self):
        conn = self._make_conn()
        token_resp = _mock_http(200, {"access_token": "concur-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "concur-tok"

    def test_authenticate_uses_client_credentials_grant(self):
        conn = self._make_conn()
        captured = {}

        def _capture(url, **kwargs):
            captured["data"] = kwargs.get("data", {})
            return _mock_http(200, {"access_token": "t", "expires_in": 3600})

        with patch.object(conn._http_client, "post", side_effect=_capture):
            conn.authenticate()

        assert captured["data"].get("grant_type") == "client_credentials"
        assert captured["data"].get("company_uuid") == "company-uuid-123"

    def test_authenticate_missing_company_uuid_returns_false(self):
        conn = ConcurConnector(_creds("concur", client_id="c", client_secret="s"))
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(401)):
            assert conn.authenticate() is False

    def test_discover_schema_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"report", "entry", "user"}

    def test_entity_config_report_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("report")
        assert "expense/reports" in cfg["endpoint"]

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Concur"):
            conn._entity_config("payroll")

    def test_extract_full_reports_single_page(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://us.api.concursolutions.com"

        page = {
            "Items": [
                {"ID": "r1", "Name": "Q1 T&E", "OwnerName": "Alice Smith",
                 "OwnerLoginID": "alice@acme.com"},
            ],
            "NextPage": None,
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("report"))

        assert len(records) == 1
        assert records[0].source_id == "r1"
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_pagination_via_next_page(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://us.api.concursolutions.com"

        page1 = {
            "Items": [{"ID": f"r{i}", "Name": f"Report {i}"} for i in range(5)],
            "NextPage": "https://us.api.concursolutions.com/api/v3.0/expense/reports?offset=5",
        }
        page2 = {"Items": [{"ID": f"r{i}", "Name": f"Report {i}"} for i in range(3)], "NextPage": None}
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("report"))
        assert len(records) == 8

    def test_extract_incremental_date_filter(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://us.api.concursolutions.com"

        captured: dict = {}

        def _capture(url, **kwargs):
            captured.update(kwargs.get("params", {}))
            return {"Items": [], "NextPage": None}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("report", _cursor("concur", "report"))
            list(gen)

        assert "modifiedafterdate" in captured

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://us.api.concursolutions.com"

        with patch.object(conn, "_get", return_value={"Items": [], "NextPage": None}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._api_base = "https://us.api.concursolutions.com"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()
        assert health.is_healthy is False


# ─────────────────────────────────────────────────────────────────────────────
# BillcomConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBillcomConnector:

    def _make_conn(self) -> BillcomConnector:
        return BillcomConnector(
            _creds("billcom",
                   user_name="user@acme.com", password="pass",
                   org_id="org123", dev_key="dev-key-456")
        )

    def test_authenticate_success(self):
        conn = self._make_conn()
        login_resp = _mock_http(200, {
            "response_data": {"sessionId": "sess-abc"},
            "response_status": 0,
        })
        with patch.object(conn._http_client, "post", return_value=login_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._session_id == "sess-abc"

    def test_authenticate_missing_dev_key_returns_false(self):
        conn = BillcomConnector(_creds("billcom", user_name="u", password="p", org_id="o"))
        assert conn.authenticate() is False

    def test_authenticate_no_session_id_returns_false(self):
        conn = self._make_conn()
        resp = _mock_http(200, {"response_data": {}, "response_status": 1})
        with patch.object(conn._http_client, "post", return_value=resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(500)):
            assert conn.authenticate() is False

    def test_discover_schema_four_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"vendor", "bill", "invoice", "customer"}

    def test_entity_object_type_vendor(self):
        conn = self._make_conn()
        assert conn._entity_object_type("vendor") == "Vendor"

    def test_entity_object_type_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Billcom"):
            conn._entity_object_type("payroll")

    def test_extract_full_vendors(self):
        conn = self._make_conn()
        conn._session_id = "sess-abc"
        conn._dev_key = "dev-key"

        page = {
            "response_data": [
                {"id": "v1", "name": "ACME Supplies", "email": "ap@acme.com"},
                {"id": "v2", "name": "Beta Corp"},
            ]
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 2
        assert records[0].source_id == "v1"
        assert records[0].name_hint == "ACME Supplies"

    def test_extract_incremental_filter_format(self):
        conn = self._make_conn()
        conn._session_id = "sess"
        conn._dev_key = "key"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"response_data": []}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("bill", _cursor("billcom", "bill"))
            list(gen)

        assert "filters" in captured_params
        assert "updatedTime" in captured_params["filters"]

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._session_id = "sess"
        conn._dev_key = "key"

        with patch.object(conn, "_get", return_value={"response_data": []}):
            health = conn.health_check()
        assert health.is_healthy is True


# ─────────────────────────────────────────────────────────────────────────────
# GoogleWorkspaceConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGoogleWorkspaceConnector:

    def _make_conn(self) -> GoogleWorkspaceConnector:
        sa_json = json.dumps({
            "client_email": "svc@project.iam.gserviceaccount.com",
            "private_key": "FAKE_KEY",
        })
        return GoogleWorkspaceConnector(
            _creds("google_workspace",
                   service_account_json=sa_json,
                   subject_email="admin@acme.com")
        )

    def test_authenticate_missing_subject_email_returns_false(self):
        conn = GoogleWorkspaceConnector(
            _creds("google_workspace",
                   service_account_json=json.dumps({"client_email": "e", "private_key": "k"}))
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_private_key_returns_false(self):
        conn = GoogleWorkspaceConnector(
            _creds("google_workspace",
                   service_account_json=json.dumps({"client_email": "e"}),
                   subject_email="admin@acme.com")
        )
        result = conn.authenticate()
        assert result is False

    def test_discover_schema_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"user", "group", "app_token"}

    def test_extract_full_unknown_entity_raises(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        with pytest.raises(ValueError, match="Google"):
            list(conn.extract_full("deal"))

    def test_extract_full_users_pagination(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._customer_id = "my_customer"

        page1 = {
            "users": [{"id": f"u{i}", "primaryEmail": f"u{i}@acme.com", "name": {"fullName": f"User {i}"}}
                      for i in range(500)],
            "nextPageToken": "tok-page2",
        }
        page2 = {
            "users": [{"id": f"u{i}", "primaryEmail": f"u{i}@acme.com", "name": {"fullName": f"User {i}"}}
                      for i in range(10)],
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("user"))
        assert len(records) == 510

    def test_extract_incremental_is_full_refresh(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._customer_id = "my_customer"

        with patch.object(conn, "_get", return_value={"users": []}):
            gen, new_cursor = conn.extract_incremental("user", _cursor("google_workspace", "user"))
            list(gen)
        assert new_cursor.connector_id == "google_workspace"

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._customer_id = "my_customer"

        with patch.object(conn, "_get", return_value={"users": []}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._customer_id = "my_customer"

        with patch.object(conn, "_get", side_effect=Exception("403")):
            health = conn.health_check()
        assert health.is_healthy is False

    def test_to_raw_record_user(self):
        conn = self._make_conn()
        record = {
            "id": "guser-1",
            "primaryEmail": "alice@acme.com",
            "name": {"fullName": "Alice Smith"},
        }
        rr = conn._to_raw_record("user", record)
        assert rr.source_id == "guser-1"
        assert rr.email_hint == "alice@acme.com"
        assert rr.name_hint == "Alice Smith"


# ─────────────────────────────────────────────────────────────────────────────
# JumpCloudConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestJumpCloudConnector:

    def _make_conn(self) -> JumpCloudConnector:
        return JumpCloudConnector(_creds("jumpcloud", api_key="jc-api-key"))

    def test_authenticate_success(self):
        conn = self._make_conn()
        resp = _mock_http(200, {"results": [], "totalCount": 0})
        with patch.object(conn._http_client, "get", return_value=resp):
            result = conn.authenticate()
        assert result is True
        assert conn._api_key == "jc-api-key"

    def test_authenticate_missing_api_key_returns_false(self):
        conn = JumpCloudConnector(_creds("jumpcloud"))
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "get", return_value=_mock_http(401)):
            assert conn.authenticate() is False

    def test_headers_use_x_api_key(self):
        conn = self._make_conn()
        conn._api_key = "my-key"
        assert conn._headers()["x-api-key"] == "my-key"

    def test_discover_schema_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"user", "group", "application"}

    def test_entity_config_user_endpoint(self):
        conn = self._make_conn()
        cfg = conn._entity_config("user")
        assert "systemusers" in cfg["endpoint"]

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="JumpCloud"):
            conn._entity_config("deal")

    def test_extract_full_users_with_results_key(self):
        conn = self._make_conn()
        conn._api_key = "key"

        page = {"results": [
            {"id": "u1", "username": "alice", "email": "alice@acme.com",
             "firstname": "Alice", "lastname": "Smith"},
        ], "totalCount": 1}
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("user"))

        assert len(records) == 1
        assert records[0].source_id == "u1"
        assert records[0].email_hint == "alice@acme.com"

    def test_extract_full_applications_direct_array(self):
        conn = self._make_conn()
        conn._api_key = "key"

        apps = [{"id": "app1", "name": "Salesforce", "displayLabel": "Salesforce SSO"}]
        with patch.object(conn, "_get", return_value=apps):
            records = list(conn.extract_full("application"))

        assert len(records) == 1
        assert records[0].name_hint == "Salesforce SSO"

    def test_extract_incremental_is_full_refresh(self):
        conn = self._make_conn()
        conn._api_key = "key"

        with patch.object(conn, "_get", return_value={"results": []}):
            gen, new_cursor = conn.extract_incremental("user", _cursor("jumpcloud", "user"))
            list(gen)
        assert new_cursor.connector_id == "jumpcloud"

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._api_key = "key"

        with patch.object(conn, "_get", return_value={"results": []}):
            health = conn.health_check()
        assert health.is_healthy is True


# ─────────────────────────────────────────────────────────────────────────────
# QuickBooksConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestQuickBooksConnector:

    def _make_conn(self) -> QuickBooksConnector:
        return QuickBooksConnector(
            _creds("quickbooks",
                   client_id="qb-cid", client_secret="qb-sec",
                   refresh_token="qb-refresh", realm_id="1234567890")
        )

    def test_authenticate_success(self):
        conn = self._make_conn()
        token_resp = _mock_http(200, {"access_token": "qb-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "qb-tok"
        assert conn._realm_id == "1234567890"

    def test_authenticate_uses_refresh_grant(self):
        conn = self._make_conn()
        captured = {}

        def _capture(url, **kwargs):
            captured["data"] = kwargs.get("data", {})
            return _mock_http(200, {"access_token": "t", "expires_in": 3600})

        with patch.object(conn._http_client, "post", side_effect=_capture):
            conn.authenticate()

        assert captured["data"].get("grant_type") == "refresh_token"

    def test_authenticate_uses_basic_auth_header(self):
        conn = self._make_conn()
        captured = {}

        def _capture(url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return _mock_http(200, {"access_token": "t", "expires_in": 3600})

        with patch.object(conn._http_client, "post", side_effect=_capture):
            conn.authenticate()

        auth_header = captured["headers"].get("Authorization", "")
        assert auth_header.startswith("Basic ")
        encoded = auth_header.replace("Basic ", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "qb-cid:qb-sec"

    def test_authenticate_missing_realm_id_returns_false(self):
        conn = QuickBooksConnector(
            _creds("quickbooks", client_id="c", client_secret="s", refresh_token="r")
        )
        assert conn.authenticate() is False

    def test_discover_schema_five_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {
            "vendor", "customer", "bill", "invoice", "employee"
        }

    def test_entity_qbo_name_vendor(self):
        conn = self._make_conn()
        assert conn._entity_qbo_name("vendor") == "Vendor"

    def test_entity_qbo_name_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="QuickBooks"):
            conn._entity_qbo_name("payroll")

    def test_extract_full_vendors(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._realm_id = "123"

        qr = {
            "QueryResponse": {
                "Vendor": [
                    {"Id": "1", "DisplayName": "ACME Supplies",
                     "PrimaryEmailAddr": {"Address": "ap@acme.com"}},
                ]
            }
        }
        with patch.object(conn, "_get", return_value=qr):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 1
        assert records[0].source_id == "1"
        assert records[0].email_hint == "ap@acme.com"
        assert records[0].name_hint == "ACME Supplies"

    def test_extract_incremental_query_contains_where(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._realm_id = "123"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"QueryResponse": {"Customer": []}}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("customer", _cursor("quickbooks", "customer"))
            list(gen)

        query = captured_params.get("query", "")
        assert "WHERE MetaData.LastUpdatedTime" in query
        assert "2026-01-01" in query

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._realm_id = "123"

        with patch.object(conn, "_get", return_value={"QueryResponse": {}}):
            health = conn.health_check()
        assert health.is_healthy is True


# ─────────────────────────────────────────────────────────────────────────────
# GustoConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGustoConnector:

    def _make_conn(self) -> GustoConnector:
        return GustoConnector(
            _creds("gusto",
                   client_id="g-cid", client_secret="g-sec",
                   refresh_token="g-refresh", company_id="co-uuid-123")
        )

    def test_authenticate_success(self):
        conn = self._make_conn()
        token_resp = _mock_http(200, {"access_token": "gusto-tok", "expires_in": 7200})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "gusto-tok"
        assert conn._company_id == "co-uuid-123"

    def test_authenticate_missing_company_id_returns_false(self):
        conn = GustoConnector(
            _creds("gusto", client_id="c", client_secret="s", refresh_token="r")
        )
        assert conn.authenticate() is False

    def test_authenticate_no_token_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", return_value=_mock_http(200, {})):
            assert conn.authenticate() is False

    def test_discover_schema_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"employee", "contractor", "payroll"}

    def test_extract_full_employees_array_response(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._company_id = "co-uuid-123"

        employees = [
            {"uuid": "emp-1", "first_name": "Alice", "last_name": "Smith", "email": "alice@acme.com"},
            {"uuid": "emp-2", "first_name": "Bob", "last_name": "Jones", "email": "bob@acme.com"},
        ]
        with patch.object(conn, "_get", return_value=employees):
            records = list(conn.extract_full("employee"))

        assert len(records) == 2
        assert records[0].source_id == "emp-1"
        assert records[0].email_hint == "alice@acme.com"

    def test_extract_full_unknown_entity_raises(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._company_id = "co-uuid-123"

        with pytest.raises(ValueError, match="Gusto"):
            list(conn.extract_full("invoice"))

    def test_extract_incremental_payroll_passes_processed_after(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._company_id = "co-uuid-123"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return []

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("payroll", _cursor("gusto", "payroll"))
            list(gen)

        assert "processed_after" in captured_params
        assert "2026-01-01" in captured_params["processed_after"]

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._company_id = "co-uuid-123"

        with patch.object(conn, "_get", return_value=[]):
            health = conn.health_check()
        assert health.is_healthy is True


# ─────────────────────────────────────────────────────────────────────────────
# PipedriveConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPipedriveConnector:

    def _make_conn(self, auth_mode="api_token") -> PipedriveConnector:
        kwargs: dict = {"auth_mode": auth_mode}
        if auth_mode == "api_token":
            kwargs["api_token"] = "pd-api-tok"
        elif auth_mode == "oauth":
            kwargs["access_token"] = "pd-oauth-tok"
        return PipedriveConnector(_creds("pipedrive", **kwargs))

    def _me_resp(self):
        return _mock_http(200, {"success": True, "data": {"id": 1, "email": "admin@acme.com"}})

    def test_authenticate_api_token_success(self):
        conn = self._make_conn("api_token")
        with patch.object(conn._http_client, "get", return_value=self._me_resp()):
            result = conn.authenticate()
        assert result is True
        assert conn._api_token == "pd-api-tok"

    def test_authenticate_oauth_success(self):
        conn = self._make_conn("oauth")
        with patch.object(conn._http_client, "get", return_value=self._me_resp()):
            result = conn.authenticate()
        assert result is True
        assert conn._api_token == "pd-oauth-tok"

    def test_authenticate_missing_api_token_returns_false(self):
        conn = PipedriveConnector(_creds("pipedrive", auth_mode="api_token"))
        assert conn.authenticate() is False

    def test_authenticate_api_success_false_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "get",
                          return_value=_mock_http(200, {"success": False})):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_unknown_mode_returns_false(self):
        conn = PipedriveConnector(_creds("pipedrive", auth_mode="saml"))
        assert conn.authenticate() is False

    def test_discover_schema_five_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {
            "deal", "person", "organization", "user", "activity"
        }

    def test_entity_endpoint_deal(self):
        conn = self._make_conn()
        assert conn._entity_endpoint("deal") == "/deals"

    def test_entity_endpoint_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="Pipedrive"):
            conn._entity_endpoint("invoice")

    def test_extract_full_deals_single_page(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        resp = {
            "data": [
                {"id": 1, "title": "Big Deal", "status": "open"},
                {"id": 2, "title": "Small Deal", "status": "won"},
            ],
            "additional_data": {"pagination": {"more_items_in_collection": False}},
        }
        with patch.object(conn, "_get", return_value=resp):
            records = list(conn.extract_full("deal"))

        assert len(records) == 2
        assert records[0].source_id == "1"
        assert records[0].name_hint == "Big Deal"

    def test_extract_full_pagination(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        page1 = {
            "data": [{"id": i, "title": f"Deal {i}"} for i in range(500)],
            "additional_data": {"pagination": {
                "more_items_in_collection": True, "next_start": 500
            }},
        }
        page2 = {
            "data": [{"id": i, "title": f"Deal {i}"} for i in range(50)],
            "additional_data": {"pagination": {"more_items_in_collection": False}},
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("deal"))
        assert len(records) == 550

    def test_extract_full_handles_none_data(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        # Pipedrive returns data: null when no results
        resp = {"data": None, "additional_data": {"pagination": {"more_items_in_collection": False}}}
        with patch.object(conn, "_get", return_value=resp):
            records = list(conn.extract_full("deal"))
        assert records == []

    def test_extract_incremental_passes_updated_since(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"data": None, "additional_data": {"pagination": {"more_items_in_collection": False}}}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("deal", _cursor("pipedrive", "deal"))
            list(gen)

        assert "updated_since" in captured_params
        assert "2026-01-01" in captured_params["updated_since"]

    def test_to_raw_record_person_email_from_list(self):
        conn = self._make_conn()
        record = {
            "id": 10,
            "name": "Alice Smith",
            "email": [
                {"value": "secondary@acme.com", "primary": False, "label": "work"},
                {"value": "alice@acme.com", "primary": True, "label": "personal"},
            ],
        }
        rr = conn._to_raw_record("person", record)
        assert rr.email_hint == "alice@acme.com"

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        with patch.object(conn, "_get", return_value={"data": {"id": 1}}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._api_token = "tok"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()
        assert health.is_healthy is False


# ─────────────────────────────────────────────────────────────────────────────
# Cross-connector contract tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossConnectorSprint37:
    _GW_CREDS = {"service_account_json": json.dumps({"client_email": "e", "private_key": "k"}),
                 "subject_email": "admin@acme.com"}

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ConcurConnector,   {"client_id": "c", "client_secret": "s", "company_uuid": "u"}),
        (BillcomConnector,  {"user_name": "u", "password": "p", "org_id": "o", "dev_key": "k"}),
        (GoogleWorkspaceConnector, {"service_account_json": json.dumps({"client_email": "e", "private_key": "k"}),
                                    "subject_email": "admin@acme.com"}),
        (JumpCloudConnector, {"api_key": "k"}),
        (QuickBooksConnector, {"client_id": "c", "client_secret": "s",
                               "refresh_token": "r", "realm_id": "1"}),
        (GustoConnector,    {"client_id": "c", "client_secret": "s",
                             "refresh_token": "r", "company_id": "co"}),
        (PipedriveConnector, {"api_token": "t"}),
    ])
    def test_connector_id_nonempty(self, cls, creds_kwargs):
        assert isinstance(cls.CONNECTOR_ID, str) and len(cls.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ConcurConnector,   {"client_id": "c", "client_secret": "s", "company_uuid": "u"}),
        (BillcomConnector,  {"user_name": "u", "password": "p", "org_id": "o", "dev_key": "k"}),
        (GoogleWorkspaceConnector, {"service_account_json": json.dumps({"client_email": "e", "private_key": "k"}),
                                    "subject_email": "admin@acme.com"}),
        (JumpCloudConnector, {"api_key": "k"}),
        (QuickBooksConnector, {"client_id": "c", "client_secret": "s",
                               "refresh_token": "r", "realm_id": "1"}),
        (GustoConnector,    {"client_id": "c", "client_secret": "s",
                             "refresh_token": "r", "company_id": "co"}),
        (PipedriveConnector, {"api_token": "t"}),
    ])
    def test_discover_schema_nonempty(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        assert len(conn.discover_schema()) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ConcurConnector,   {"client_id": "c", "client_secret": "s", "company_uuid": "u"}),
        (BillcomConnector,  {"user_name": "u", "password": "p", "org_id": "o", "dev_key": "k"}),
        (GoogleWorkspaceConnector, {"service_account_json": json.dumps({"client_email": "e", "private_key": "k"}),
                                    "subject_email": "admin@acme.com"}),
        (JumpCloudConnector, {"api_key": "k"}),
        (QuickBooksConnector, {"client_id": "c", "client_secret": "s",
                               "refresh_token": "r", "realm_id": "1"}),
        (GustoConnector,    {"client_id": "c", "client_secret": "s",
                             "refresh_token": "r", "company_id": "co"}),
        (PipedriveConnector, {"api_token": "t"}),
    ])
    def test_calls_per_second_positive(self, cls, creds_kwargs):
        assert cls.CALLS_PER_SECOND > 0
