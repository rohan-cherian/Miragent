"""
tests/test_connectors_sprint38.py — Sprint 38 connector tests

Covers:
  - AcumaticaConnector       (Acumatica Cloud ERP)
  - EpicorConnector          (Epicor Manufacturing/Distribution ERP)
  - DynamicsFinanceConnector (Microsoft Dynamics 365 Finance & Operations)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK_CONNECTORS", "false")

from scout.connectors.acumatica import AcumaticaConnector
from scout.connectors.dynamics_finance import DynamicsFinanceConnector
from scout.connectors.epicor import EpicorConnector
from scout.connectors.models import ConnectorCredentials, ExtractionCursor


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
# AcumaticaConnector
# ─────────────────────────────────────────────────────────────────────────────

class TestAcumaticaConnector:

    def _make_conn(self) -> AcumaticaConnector:
        return AcumaticaConnector(
            _creds("acumatica",
                   instance_url="https://acme.acumatica.com",
                   username="admin",
                   password="secret123")
        )

    # ── Authentication ────────────────────────────────────

    def test_authenticate_missing_instance_url_returns_false(self):
        conn = AcumaticaConnector(
            _creds("acumatica", username="u", password="p")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_username_returns_false(self):
        conn = AcumaticaConnector(
            _creds("acumatica", instance_url="https://acme.acumatica.com", password="p")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_password_returns_false(self):
        conn = AcumaticaConnector(
            _creds("acumatica", instance_url="https://acme.acumatica.com", username="u")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_success_via_cookie(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200)
        mock_resp.headers = {"Set-Cookie": "ASPxRouteHandlerCookie=abc123; Path=/; HttpOnly"}
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()
        assert result is True
        assert "abc123" in conn._session_cookie

    def test_authenticate_success_via_body_token(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200, body={"access_token": "tok-body"})
        mock_resp.headers = {}
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()
        assert result is True

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        mock_resp = _mock_http(401)
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_exception_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", side_effect=Exception("network")):
            result = conn.authenticate()
        assert result is False

    # ── Schema ────────────────────────────────────────────

    def test_discover_schema_two_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"vendor", "employee"}

    def test_discover_schema_vendor_fields(self):
        conn = self._make_conn()
        schema = next(s for s in conn.discover_schema() if s.entity_type == "vendor")
        assert "VendorID" in schema.fields
        assert "VendorName" in schema.fields

    def test_discover_schema_employee_fields(self):
        conn = self._make_conn()
        schema = next(s for s in conn.discover_schema() if s.entity_type == "employee")
        assert "EmployeeID" in schema.fields

    # ── Full extraction ───────────────────────────────────

    def test_extract_full_unknown_entity_raises(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"
        with pytest.raises(ValueError, match="Acumatica"):
            list(conn.extract_full("deal"))

    def test_extract_full_vendor_pagination(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        page1 = [{"VendorID": {"value": f"V{i}"}, "VendorName": {"value": f"Vendor {i}"}}
                 for i in range(100)]
        page2 = [{"VendorID": {"value": "V100"}, "VendorName": {"value": "Vendor 100"}}]
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 101

    def test_extract_full_vendor_odata_wrapped(self):
        """OData response with {"value": [...]} wrapper."""
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        response = {"value": [
            {"VendorID": {"value": "V001"}, "VendorName": {"value": "Acme Supplies"}},
        ]}
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 1
        assert records[0].source_id == "V001"

    def test_extract_full_vendor_direct_list(self):
        """Acumatica can also return a direct list."""
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        response = [{"VendorID": "V-DIRECT", "VendorName": "Direct Vendor"}]
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 1
        assert records[0].source_id == "V-DIRECT"

    def test_extract_full_employee(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        response = [{"EmployeeID": {"value": "E001"}, "DepartmentID": {"value": "ENG"}}]
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("employee"))
        assert len(records) == 1
        assert records[0].entity_type == "employee"

    def test_extract_full_empty_stops_immediately(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        with patch.object(conn, "_get", return_value=[]):
            records = list(conn.extract_full("vendor"))
        assert records == []

    def test_extract_full_get_exception_stops_gracefully(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            records = list(conn.extract_full("vendor"))
        assert records == []

    # ── Incremental extraction ────────────────────────────

    def test_extract_incremental_vendor_passes_filter(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        captured: list[dict] = []

        def fake_get(url, **kwargs):
            captured.append(kwargs.get("params", {}))
            return []

        with patch.object(conn, "_get", side_effect=fake_get):
            gen, cursor = conn.extract_incremental("vendor", _cursor("acumatica", "vendor"))
            list(gen)

        assert any("$filter" in p for p in captured)
        filter_val = next(p["$filter"] for p in captured if "$filter" in p)
        assert "LastModifiedDateTime" in filter_val

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        with patch.object(conn, "_get", return_value=[]):
            gen, cursor = conn.extract_incremental("vendor", _cursor("acumatica", "vendor"))
            list(gen)
        assert cursor.connector_id == "acumatica"
        assert cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health check ──────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        with patch.object(conn, "_get", return_value=[]):
            health = conn.health_check()
        assert health.is_healthy is True
        assert health.latency_ms is not None

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._api_base = "https://acme.acumatica.com/entity/Default/22.200.001"

        with patch.object(conn, "_get", side_effect=Exception("503")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "503" in health.error_message

    # ── _to_raw_record ────────────────────────────────────

    def test_to_raw_record_vendor_unwraps_fields(self):
        conn = self._make_conn()
        record = {
            "VendorID": {"value": "V-001", "type": "string"},
            "VendorName": {"value": "Acme Corp", "type": "string"},
        }
        rr = conn._to_raw_record("vendor", record)
        assert rr.source_id == "V-001"
        assert rr.name_hint == "Acme Corp"
        assert rr.connector_id == "acumatica"

    def test_to_raw_record_vendor_plain_string_id(self):
        conn = self._make_conn()
        record = {"VendorID": "V-PLAIN", "VendorName": "Plain Vendor"}
        rr = conn._to_raw_record("vendor", record)
        assert rr.source_id == "V-PLAIN"

    def test_to_raw_record_employee(self):
        conn = self._make_conn()
        record = {"EmployeeID": {"value": "E-001"}, "DepartmentID": {"value": "ENG"}}
        rr = conn._to_raw_record("employee", record)
        assert rr.source_id == "E-001"
        assert rr.entity_type == "employee"

    # ── Custom version ────────────────────────────────────

    def test_custom_api_version_in_base_url(self):
        conn = AcumaticaConnector(
            _creds("acumatica",
                   instance_url="https://acme.acumatica.com",
                   username="u",
                   password="p",
                   api_version="23.200.001")
        )
        mock_resp = _mock_http(200)
        mock_resp.headers = {"Set-Cookie": "ASPxRouteHandlerCookie=xyz; Path=/"}
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            conn.authenticate()
        assert "23.200.001" in conn._api_base


# ─────────────────────────────────────────────────────────────────────────────
# EpicorConnector
# ─────────────────────────────────────────────────────────────────────────────

class TestEpicorConnector:

    def _make_conn(self) -> EpicorConnector:
        return EpicorConnector(
            _creds("epicor",
                   server_url="https://epicor.acme.com",
                   company="ACME",
                   username="svc_user",
                   password="svc_pass")
        )

    # ── Authentication ────────────────────────────────────

    def test_authenticate_missing_server_url_returns_false(self):
        conn = EpicorConnector(
            _creds("epicor", company="ACME", username="u", password="p")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_company_returns_false(self):
        conn = EpicorConnector(
            _creds("epicor", server_url="https://epicor.acme.com", username="u", password="p")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_basic_missing_username_returns_false(self):
        conn = EpicorConnector(
            _creds("epicor",
                   server_url="https://epicor.acme.com",
                   company="ACME",
                   password="p")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_basic_missing_password_returns_false(self):
        conn = EpicorConnector(
            _creds("epicor",
                   server_url="https://epicor.acme.com",
                   company="ACME",
                   username="u")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_basic_success(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200, body={"value": []})
        with patch.object(conn._http_client, "get", return_value=mock_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._auth_header.startswith("Basic ")

    def test_authenticate_bearer_success(self):
        conn = EpicorConnector(
            _creds("epicor",
                   server_url="https://epicor.acme.com",
                   company="ACME",
                   access_token="bearer-tok",
                   auth_mode="bearer")
        )
        mock_resp = _mock_http(200, body={"value": []})
        with patch.object(conn._http_client, "get", return_value=mock_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._auth_header == "Bearer bearer-tok"

    def test_authenticate_unknown_auth_mode_returns_false(self):
        conn = EpicorConnector(
            _creds("epicor",
                   server_url="https://epicor.acme.com",
                   company="ACME",
                   auth_mode="oauth3")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        mock_resp = _mock_http(401)
        with patch.object(conn._http_client, "get", return_value=mock_resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_sets_api_base(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200, body={"value": []})
        with patch.object(conn._http_client, "get", return_value=mock_resp):
            conn.authenticate()
        assert "ACME" in conn._api_base
        assert "epicor.acme.com" in conn._api_base

    # ── Schema ────────────────────────────────────────────

    def test_discover_schema_two_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"vendor", "employee"}

    def test_discover_schema_vendor_fields(self):
        conn = self._make_conn()
        schema = next(s for s in conn.discover_schema() if s.entity_type == "vendor")
        assert "VendorNum" in schema.fields
        assert "Name" in schema.fields

    def test_discover_schema_employee_fields(self):
        conn = self._make_conn()
        schema = next(s for s in conn.discover_schema() if s.entity_type == "employee")
        assert "EmpID" in schema.fields
        assert "EMailAddress" in schema.fields

    # ── Full extraction ───────────────────────────────────

    def test_extract_full_unknown_entity_raises(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        with pytest.raises(ValueError, match="Epicor"):
            list(conn.extract_full("deal"))

    def test_extract_full_vendor_odata_value_wrapper(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic dXNlcjpwYXNz"

        response = {"value": [
            {"VendorNum": 5001, "Name": "Parker Hannifin Corp"},
            {"VendorNum": 5002, "Name": "Grainger"},
        ]}
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 2
        assert records[0].source_id == "5001"
        assert records[0].name_hint == "Parker Hannifin Corp"

    def test_extract_full_vendor_direct_array(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        response = [{"VendorNum": 9001, "Name": "Direct Vendor"}]
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 1

    def test_extract_full_vendor_pagination(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        page1 = {"value": [{"VendorNum": i, "Name": f"V{i}"} for i in range(100)]}
        page2 = {"value": [{"VendorNum": 100, "Name": "V100"}]}
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 101

    def test_extract_full_employee(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        response = {"value": [
            {"EmpID": "E001", "FirstName": "Alice", "LastName": "Smith",
             "EMailAddress": "alice@acme.com", "EmpRoleCode": "ENG"},
        ]}
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("employee"))
        assert len(records) == 1
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_employee_name_fallback(self):
        """Employee with a Name field directly."""
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        response = {"value": [
            {"EmpID": "E002", "Name": "Bob Jones", "EMailAddress": "bob@acme.com"},
        ]}
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("employee"))
        assert records[0].name_hint == "Bob Jones"

    def test_extract_full_get_exception_stops_gracefully(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            records = list(conn.extract_full("vendor"))
        assert records == []

    # ── Incremental extraction ────────────────────────────

    def test_extract_incremental_vendor_passes_filter(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        captured: list[dict] = []

        def fake_get(url, **kwargs):
            captured.append(kwargs.get("params", {}))
            return {"value": []}

        with patch.object(conn, "_get", side_effect=fake_get):
            gen, cursor = conn.extract_incremental("vendor", _cursor("epicor", "vendor"))
            list(gen)

        assert any("$filter" in p for p in captured)
        filter_val = next(p["$filter"] for p in captured if "$filter" in p)
        assert "ChangeDate" in filter_val

    def test_extract_incremental_employee_passes_filter(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        captured: list[dict] = []

        def fake_get(url, **kwargs):
            captured.append(kwargs.get("params", {}))
            return {"value": []}

        with patch.object(conn, "_get", side_effect=fake_get):
            gen, cursor = conn.extract_incremental("employee", _cursor("epicor", "employee"))
            list(gen)

        assert any("ChangeDate" in p.get("$filter", "") for p in captured)

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        with patch.object(conn, "_get", return_value={"value": []}):
            gen, cursor = conn.extract_incremental("vendor", _cursor("epicor", "vendor"))
            list(gen)
        assert cursor.connector_id == "epicor"
        assert cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health check ──────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        with patch.object(conn, "_get", return_value={"value": []}):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._api_base = "https://epicor.acme.com/api/erp/v2/ACME"
        conn._auth_header = "Basic x"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "timeout" in health.error_message

    # ── _to_raw_record ────────────────────────────────────

    def test_to_raw_record_vendor(self):
        conn = self._make_conn()
        record = {"VendorNum": 5001, "Name": "Parker Hannifin Corp", "VendorType": "MANUF"}
        rr = conn._to_raw_record("vendor", record)
        assert rr.source_id == "5001"
        assert rr.name_hint == "Parker Hannifin Corp"
        assert rr.email_hint is None
        assert rr.connector_id == "epicor"

    def test_to_raw_record_employee_full_name(self):
        conn = self._make_conn()
        record = {
            "EmpID": "EPC-E001",
            "FirstName": "Gerald",
            "LastName": "Kowalski",
            "EMailAddress": "g.kowalski@lakeview.com",
            "EmpRoleCode": "PLANTMGR",
        }
        rr = conn._to_raw_record("employee", record)
        assert rr.source_id == "EPC-E001"
        assert rr.name_hint == "Gerald Kowalski"
        assert rr.email_hint == "g.kowalski@lakeview.com"

    def test_to_raw_record_employee_name_field(self):
        conn = self._make_conn()
        record = {"EmpID": "E99", "Name": "Composite Name"}
        rr = conn._to_raw_record("employee", record)
        assert rr.name_hint == "Composite Name"


# ─────────────────────────────────────────────────────────────────────────────
# DynamicsFinanceConnector
# ─────────────────────────────────────────────────────────────────────────────

class TestDynamicsFinanceConnector:

    def _make_conn(self) -> DynamicsFinanceConnector:
        return DynamicsFinanceConnector(
            _creds("dynamics_finance",
                   tenant_id="aad-tenant-uuid",
                   client_id="app-client-id",
                   client_secret="app-secret",
                   environment_url="https://acme.operations.dynamics.com")
        )

    # ── Authentication ────────────────────────────────────

    def test_authenticate_missing_tenant_id_returns_false(self):
        conn = DynamicsFinanceConnector(
            _creds("dynamics_finance",
                   client_id="c", client_secret="s",
                   environment_url="https://acme.operations.dynamics.com")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_client_id_returns_false(self):
        conn = DynamicsFinanceConnector(
            _creds("dynamics_finance",
                   tenant_id="t", client_secret="s",
                   environment_url="https://acme.operations.dynamics.com")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_client_secret_returns_false(self):
        conn = DynamicsFinanceConnector(
            _creds("dynamics_finance",
                   tenant_id="t", client_id="c",
                   environment_url="https://acme.operations.dynamics.com")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_missing_environment_url_returns_false(self):
        conn = DynamicsFinanceConnector(
            _creds("dynamics_finance",
                   tenant_id="t", client_id="c", client_secret="s")
        )
        result = conn.authenticate()
        assert result is False

    def test_authenticate_success(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200, body={"access_token": "tok-dyn", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._access_token == "tok-dyn"
        assert conn._token_expires_at > time.time()

    def test_authenticate_no_token_in_response_returns_false(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200, body={})
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_conn()
        mock_resp = _mock_http(401)
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_exception_returns_false(self):
        conn = self._make_conn()
        with patch.object(conn._http_client, "post", side_effect=Exception("network")):
            result = conn.authenticate()
        assert result is False

    def test_authenticate_sets_environment_url(self):
        conn = self._make_conn()
        mock_resp = _mock_http(200, body={"access_token": "t", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            conn.authenticate()
        assert conn._environment_url == "https://acme.operations.dynamics.com"

    # ── Schema ────────────────────────────────────────────

    def test_discover_schema_two_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"vendor", "worker"}

    def test_discover_schema_vendor_fields(self):
        conn = self._make_conn()
        schema = next(s for s in conn.discover_schema() if s.entity_type == "vendor")
        assert "AccountNum" in schema.fields
        assert "Name" in schema.fields

    def test_discover_schema_worker_fields(self):
        conn = self._make_conn()
        schema = next(s for s in conn.discover_schema() if s.entity_type == "worker")
        assert "PersonnelNumber" in schema.fields
        assert "PrimaryEmailAddress" in schema.fields

    def test_discover_schema_supports_incremental(self):
        conn = self._make_conn()
        for schema in conn.discover_schema():
            assert schema.supports_incremental is True

    # ── Full extraction ───────────────────────────────────

    def test_extract_full_unknown_entity_raises(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        with pytest.raises(ValueError, match="Dynamics"):
            list(conn.extract_full("deal"))

    def test_extract_full_vendor_single_page(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        response = {"value": [
            {"AccountNum": "DYNF-V001", "Name": "Capgemini US LLC",
             "VendorGroupId": "CONSULT"},
        ]}
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 1
        assert records[0].source_id == "DYNF-V001"
        assert records[0].name_hint == "Capgemini US LLC"

    def test_extract_full_vendor_odata_next_link_pagination(self):
        """Dynamics uses @odata.nextLink for cursor-based pagination."""
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        page1 = {
            "value": [{"AccountNum": f"V{i}", "Name": f"Vendor {i}"} for i in range(1000)],
            "@odata.nextLink": "https://acme.operations.dynamics.com/data/Vendors?$skiptoken=...",
        }
        page2 = {"value": [{"AccountNum": "V1000", "Name": "Last Vendor"}]}
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("vendor"))
        assert len(records) == 1001

    def test_extract_full_worker(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        response = {"value": [
            {"PersonnelNumber": "W001", "PrimaryEmailAddress": "alice@acme.com",
             "PrimaryWorkerName": "Alice Smith"},
        ]}
        with patch.object(conn, "_get", return_value=response):
            records = list(conn.extract_full("worker"))
        assert len(records) == 1
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_get_exception_stops_gracefully(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", side_effect=Exception("service unavailable")):
            records = list(conn.extract_full("vendor"))
        assert records == []

    # ── Incremental extraction ────────────────────────────

    def test_extract_incremental_vendor_passes_filter(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        captured: list[dict] = []

        def fake_get(url, **kwargs):
            captured.append(kwargs.get("params", {}))
            return {"value": []}

        with patch.object(conn, "_get", side_effect=fake_get):
            gen, cursor = conn.extract_incremental(
                "vendor", _cursor("dynamics_finance", "vendor")
            )
            list(gen)

        assert any("$filter" in p for p in captured if p)
        filter_val = next(p["$filter"] for p in captured if "$filter" in p)
        assert "ModifiedDateTime" in filter_val
        assert "2026-01-01" in filter_val

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", return_value={"value": []}):
            gen, cursor = conn.extract_incremental(
                "worker", _cursor("dynamics_finance", "worker")
            )
            list(gen)
        assert cursor.connector_id == "dynamics_finance"
        assert cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health check ──────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", return_value={"value": []}):
            health = conn.health_check()
        assert health.is_healthy is True
        assert health.latency_ms is not None

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._environment_url = "https://acme.operations.dynamics.com"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600

        with patch.object(conn, "_get", side_effect=Exception("403 Forbidden")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "403" in health.error_message

    # ── _to_raw_record ────────────────────────────────────

    def test_to_raw_record_vendor(self):
        conn = self._make_conn()
        record = {
            "AccountNum": "DYNF-V001",
            "Name": "Capgemini US LLC",
            "VendorGroupId": "CONSULT",
            "CurrencyCode": "USD",
        }
        rr = conn._to_raw_record("vendor", record)
        assert rr.source_id == "DYNF-V001"
        assert rr.name_hint == "Capgemini US LLC"
        assert rr.email_hint is None
        assert rr.connector_id == "dynamics_finance"

    def test_to_raw_record_worker(self):
        conn = self._make_conn()
        record = {
            "PersonnelNumber": "W-001",
            "PrimaryWorkerName": "Alice Smith",
            "PrimaryEmailAddress": "alice@acme.com",
            "WorkerType": "Employee",
        }
        rr = conn._to_raw_record("worker", record)
        assert rr.source_id == "W-001"
        assert rr.name_hint == "Alice Smith"
        assert rr.email_hint == "alice@acme.com"

    def test_to_raw_record_worker_name_fallback(self):
        """Worker without PrimaryWorkerName falls back to PersonnelNumber."""
        conn = self._make_conn()
        record = {"PersonnelNumber": "W-002", "PrimaryEmailAddress": "bob@acme.com"}
        rr = conn._to_raw_record("worker", record)
        assert rr.name_hint == "W-002"

    # ── Token refresh ─────────────────────────────────────

    def test_refresh_if_needed_triggers_when_token_expired(self):
        conn = self._make_conn()
        conn._access_token = "old-tok"
        conn._token_expires_at = time.time() - 1  # already expired

        with patch.object(conn, "authenticate", return_value=True) as mock_auth:
            conn._refresh_if_needed()
        mock_auth.assert_called_once()

    def test_refresh_if_needed_skips_when_token_valid(self):
        conn = self._make_conn()
        conn._access_token = "valid-tok"
        conn._token_expires_at = time.time() + 7200  # 2 hours to go

        with patch.object(conn, "authenticate", return_value=True) as mock_auth:
            conn._refresh_if_needed()
        mock_auth.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Cross-connector tests (Sprint 38)
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossConnectorSprint38:

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (AcumaticaConnector, {"instance_url": "https://acme.acumatica.com",
                              "username": "u", "password": "p"}),
        (EpicorConnector,    {"server_url": "https://epicor.acme.com",
                              "company": "ACME", "username": "u", "password": "p"}),
        (DynamicsFinanceConnector, {"tenant_id": "t", "client_id": "c",
                                    "client_secret": "s",
                                    "environment_url": "https://acme.operations.dynamics.com"}),
    ])
    def test_connector_id_nonempty(self, cls, creds_kwargs):
        assert isinstance(cls.CONNECTOR_ID, str) and len(cls.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (AcumaticaConnector, {"instance_url": "https://acme.acumatica.com",
                              "username": "u", "password": "p"}),
        (EpicorConnector,    {"server_url": "https://epicor.acme.com",
                              "company": "ACME", "username": "u", "password": "p"}),
        (DynamicsFinanceConnector, {"tenant_id": "t", "client_id": "c",
                                    "client_secret": "s",
                                    "environment_url": "https://acme.operations.dynamics.com"}),
    ])
    def test_discover_schema_nonempty(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        assert len(conn.discover_schema()) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (AcumaticaConnector, {"instance_url": "https://acme.acumatica.com",
                              "username": "u", "password": "p"}),
        (EpicorConnector,    {"server_url": "https://epicor.acme.com",
                              "company": "ACME", "username": "u", "password": "p"}),
        (DynamicsFinanceConnector, {"tenant_id": "t", "client_id": "c",
                                    "client_secret": "s",
                                    "environment_url": "https://acme.operations.dynamics.com"}),
    ])
    def test_calls_per_second_positive(self, cls, creds_kwargs):
        assert cls.CALLS_PER_SECOND > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (AcumaticaConnector, {"instance_url": "https://acme.acumatica.com",
                              "username": "u", "password": "p"}),
        (EpicorConnector,    {"server_url": "https://epicor.acme.com",
                              "company": "ACME", "username": "u", "password": "p"}),
        (DynamicsFinanceConnector, {"tenant_id": "t", "client_id": "c",
                                    "client_secret": "s",
                                    "environment_url": "https://acme.operations.dynamics.com"}),
    ])
    def test_category_is_erp(self, cls, creds_kwargs):
        from scout.connectors.models import ConnectorCategory
        assert cls.CATEGORY == ConnectorCategory.ERP

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (AcumaticaConnector, {"instance_url": "https://acme.acumatica.com",
                              "username": "u", "password": "p"}),
        (EpicorConnector,    {"server_url": "https://epicor.acme.com",
                              "company": "ACME", "username": "u", "password": "p"}),
        (DynamicsFinanceConnector, {"tenant_id": "t", "client_id": "c",
                                    "client_secret": "s",
                                    "environment_url": "https://acme.operations.dynamics.com"}),
    ])
    def test_schema_entity_types_match_extract_full(self, cls, creds_kwargs):
        """Every entity_type in discover_schema() must be extractable."""
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        # Set up minimal state so extract_full can reach the endpoint check
        conn._api_base = "https://fake.url/api"
        conn._auth_header = "Basic dXNlcjpwYXNz"
        conn._access_token = "tok"
        conn._token_expires_at = time.time() + 3600
        conn._environment_url = "https://fake.operations.dynamics.com"

        for schema in conn.discover_schema():
            # Each entity type should be supported (not raise ValueError)
            with patch.object(conn, "_get", return_value={"value": []}):
                records = list(conn.extract_full(schema.entity_type))
            assert isinstance(records, list)
