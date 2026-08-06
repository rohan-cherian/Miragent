"""
tests/test_connectors_sprint29.py — Sprint 29 Connector Tests

Tests for the four new production connectors:
  - BambooHRConnector
  - RipplingConnector
  - SageIntacctConnector
  - NetSuiteConnector

All tests use mock HTTP responses (via unittest.mock) — no real API calls.
The test structure mirrors the existing connector test pattern: auth tests,
schema discovery, full/incremental extraction, health checks, edge cases.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from scout.connectors.bamboohr import BambooHRConnector
from scout.connectors.rippling import RipplingConnector
from scout.connectors.sage_intacct import SageIntacctConnector
from scout.connectors.netsuite import NetSuiteConnector
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ExtractionCursor,
    RawRecord,
)
from scout.connectors.registry import get_connector, CONNECTOR_REGISTRY


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _cursor(connector_id: str, entity_type: str) -> ExtractionCursor:
    return ExtractionCursor(
        connector_id=connector_id,
        entity_type=entity_type,
        last_extracted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        checkpoint={},
    )


def _bamboohr_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="bamboohr",
        tenant_id=tenant_id,
        auth_data={"api_key": "test-key-abc123", "subdomain": "acmecorp"},
    )


def _rippling_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="rippling",
        tenant_id=tenant_id,
        auth_data={"api_key": "rip-test-key-xyz"},
    )


def _sage_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="sage_intacct",
        tenant_id=tenant_id,
        auth_data={
            "company_id": "ACME_CORP",
            "user_id": "int_user",
            "user_password": "int_pass",
            "sender_id": "miragent_sender",
            "sender_password": "sender_pass",
        },
    )


def _netsuite_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="netsuite",
        tenant_id=tenant_id,
        auth_data={
            "account_id": "1234567",
            "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
            "token_id": "ti_test",
            "token_secret": "ts_test",
            "auth_mode": "tba",
        },
    )


def _mock_http_response(status_code: int = 200, json_body: dict | list | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = text or (json.dumps(json_body) if json_body else "")
    if status_code >= 400:
        from httpx import HTTPStatusError, Response, Request
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ═════════════════════════════════════════════════════════════════════════════
# REGISTRY TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestRegistrySprint29:
    def test_bamboohr_in_registry(self):
        assert "bamboohr" in CONNECTOR_REGISTRY

    def test_rippling_in_registry(self):
        assert "rippling" in CONNECTOR_REGISTRY

    def test_sage_intacct_in_registry(self):
        assert "sage_intacct" in CONNECTOR_REGISTRY

    def test_netsuite_in_registry(self):
        assert "netsuite" in CONNECTOR_REGISTRY

    def test_get_bamboohr_connector(self):
        conn = get_connector("bamboohr", _bamboohr_creds())
        # In test env USE_MOCK_CONNECTORS=true → returns mock
        assert conn.CONNECTOR_ID == "bamboohr"

    def test_get_netsuite_connector(self):
        conn = get_connector("netsuite", _netsuite_creds())
        assert conn.CONNECTOR_ID == "netsuite"

    def test_all_sprint29_connectors_have_correct_category(self):
        from scout.connectors.bamboohr import BambooHRConnector
        from scout.connectors.rippling import RipplingConnector
        from scout.connectors.sage_intacct import SageIntacctConnector
        from scout.connectors.netsuite import NetSuiteConnector
        assert BambooHRConnector.CATEGORY == ConnectorCategory.HCM
        assert RipplingConnector.CATEGORY == ConnectorCategory.HCM
        assert SageIntacctConnector.CATEGORY == ConnectorCategory.ERP
        assert NetSuiteConnector.CATEGORY == ConnectorCategory.ERP


# ═════════════════════════════════════════════════════════════════════════════
# BAMBOOHR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestBambooHRConnector:

    def _make(self, tenant_id: str = "acme") -> BambooHRConnector:
        return BambooHRConnector(_bamboohr_creds(tenant_id))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(200, {"employees": []})):
            assert conn.authenticate() is True

    def test_authenticate_sets_subdomain(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(200, {"employees": []})):
            conn.authenticate()
        assert conn._subdomain == "acmecorp"

    def test_authenticate_builds_basic_auth_header(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(200, {"employees": []})):
            conn.authenticate()
        expected = "Basic " + base64.b64encode(b"test-key-abc123:x").decode()
        assert conn._auth_header == expected

    def test_authenticate_missing_api_key_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="bamboohr", tenant_id="t",
            auth_data={"subdomain": "acmecorp"},  # no api_key
        )
        conn = BambooHRConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_subdomain_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="bamboohr", tenant_id="t",
            auth_data={"api_key": "key"},  # no subdomain
        )
        conn = BambooHRConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_403_returns_false(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(403)):
            assert conn.authenticate() is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_returns_two_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"employee", "time_off"}

    def test_discover_schema_employee_has_required_fields(self):
        schema = self._make().discover_schema()
        emp = next(s for s in schema if s.entity_type == "employee")
        assert "workEmail" in emp.fields
        assert "employmentStatus" in emp.fields
        assert "terminationDate" in emp.fields

    def test_discover_schema_employee_supports_incremental(self):
        schema = self._make().discover_schema()
        emp = next(s for s in schema if s.entity_type == "employee")
        assert emp.supports_incremental is True

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_employees_yields_raw_records(self):
        conn = self._make()
        conn._subdomain = "acmecorp"
        conn._auth_header = "Basic test"

        # _get returns plain dicts (response.json() is already parsed)
        directory_data = {
            "employees": [
                {"id": "1", "displayName": "Alice Smith"},
                {"id": "2", "displayName": "Bob Jones"},
            ]
        }
        detail_alice = {
            "id": "1", "firstName": "Alice", "lastName": "Smith",
            "workEmail": "alice@acme.com", "employmentStatus": "Active",
        }
        detail_bob = {
            "id": "2", "firstName": "Bob", "lastName": "Jones",
            "workEmail": "bob@acme.com", "employmentStatus": "Active",
        }

        def mock_get(url, **kwargs):
            if "directory" in url:
                return directory_data
            elif "/employees/1" in url:
                return detail_alice
            else:
                return detail_bob

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("employee"))

        assert len(records) == 2
        assert all(isinstance(r, RawRecord) for r in records)
        assert records[0].connector_id == "bamboohr"
        assert records[0].tenant_id == "acme"

    def test_extract_full_sets_email_hint(self):
        conn = self._make()
        conn._subdomain = "acmecorp"
        conn._auth_header = "Basic test"

        directory_data = {"employees": [{"id": "1"}]}
        detail = {"id": "1", "firstName": "Alice", "lastName": "Smith",
                  "workEmail": "alice@acme.com", "employmentStatus": "Active"}

        def mock_get(url, **kwargs):
            if "directory" in url:
                return directory_data
            return detail

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("employee"))

        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_unsupported_entity_type_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="BambooHR"):
            list(conn.extract_full("opportunity"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_returns_generator_and_cursor(self):
        conn = self._make()
        conn._subdomain = "acmecorp"
        conn._auth_header = "Basic test"

        changed_data = {
            "lastChanged": "2026-01-15T10:00:00Z",
            "employees": {"1": {"action": "updated"}},
        }
        detail = {"id": "1", "firstName": "Alice", "lastName": "Smith",
                  "workEmail": "a@acme.com", "employmentStatus": "Active"}

        def mock_get(url, **kwargs):
            if "changed" in url:
                return changed_data
            return detail

        cursor = _cursor("bamboohr", "employee")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, new_cursor = conn.extract_incremental("employee", cursor)
            records = list(gen)

        assert len(records) == 1
        assert new_cursor.connector_id == "bamboohr"
        assert new_cursor.checkpoint["since"] == "2026-01-01"

    def test_extract_incremental_terminated_employee_includes_action(self):
        conn = self._make()
        conn._subdomain = "acmecorp"
        conn._auth_header = "Basic test"

        changed_data = {
            "employees": {"99": {"action": "deleted"}},
        }
        detail = {"id": "99", "firstName": "Ex", "lastName": "Employee",
                  "workEmail": "ex@acme.com", "employmentStatus": "Terminated"}

        def mock_get(url, **kwargs):
            if "changed" in url:
                return changed_data
            return detail

        cursor = _cursor("bamboohr", "employee")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("employee", cursor)
            records = list(gen)

        assert len(records) == 1
        assert records[0].payload["_bamboohr_action"] == "deleted"
        assert records[0].payload["employmentStatus"] == "Terminated"

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make()
        conn._auth_header = "Basic test"
        conn._subdomain = "acmecorp"
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(200, {"employees": []})):
            health = conn.health_check()
        assert health.is_healthy is True
        assert health.connector_id == "bamboohr"

    def test_health_check_unhealthy_on_error(self):
        conn = self._make()
        conn._auth_header = "Basic test"
        conn._subdomain = "acmecorp"
        with patch.object(conn._http_client, "get", side_effect=Exception("network timeout")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "network timeout" in health.error_message


# ═════════════════════════════════════════════════════════════════════════════
# RIPPLING TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestRipplingConnector:

    def _make(self, tenant_id: str = "acme") -> RipplingConnector:
        return RipplingConnector(_rippling_creds(tenant_id))

    def test_authenticate_success(self):
        conn = self._make()
        me_resp = {"company": {"name": "Acme Corp"}, "id": "u1"}
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(200, me_resp)):
            assert conn.authenticate() is True
        assert conn._api_key == "rip-test-key-xyz"

    def test_authenticate_missing_api_key_returns_false(self):
        creds = ConnectorCredentials(connector_id="rippling", tenant_id="t", auth_data={})
        conn = RipplingConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_401_returns_false(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(401)):
            assert conn.authenticate() is False

    def test_discover_schema_has_three_entities(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"employee", "department", "device"}

    def test_discover_schema_device_has_assigned_to(self):
        schema = self._make().discover_schema()
        device = next(s for s in schema if s.entity_type == "device")
        assert "assignedTo" in device.fields
        assert "serialNumber" in device.fields

    def test_extract_full_employees_paginates(self):
        conn = self._make()
        conn._api_key = "rip-test-key-xyz"

        page1 = {
            "data": [
                {"id": "e1", "firstName": "Alice", "lastName": "S", "workEmail": "a@co.com",
                 "employmentStatus": "ACTIVE", "title": "Engineer"},
                {"id": "e2", "firstName": "Bob", "lastName": "J", "workEmail": "b@co.com",
                 "employmentStatus": "ACTIVE", "title": "Manager"},
            ],
            "next": "cursor_page2",
        }
        page2 = {
            "data": [
                {"id": "e3", "firstName": "Carol", "lastName": "K", "workEmail": "c@co.com",
                 "employmentStatus": "TERMINATED", "title": "Designer"},
            ],
            "next": None,
        }

        # _get returns plain dicts — no response wrapper
        responses = [page1, page2]
        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            result = responses[call_count]
            call_count += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("employee"))

        assert len(records) == 3
        assert records[2].payload["employmentStatus"] == "TERMINATED"

    def test_extract_full_no_next_cursor_stops(self):
        conn = self._make()
        conn._api_key = "key"

        single_page = {
            "data": [{"id": "e1", "firstName": "A", "lastName": "B",
                      "workEmail": "a@b.com", "employmentStatus": "ACTIVE"}],
            "next": None,
        }

        with patch.object(conn, "_get", return_value=single_page):
            records = list(conn.extract_full("employee"))

        assert len(records) == 1

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError):
            list(conn.extract_full("opportunity"))

    def test_extract_incremental_passes_updated_after(self):
        conn = self._make()
        conn._api_key = "key"

        captured_params = {}

        def mock_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return {"data": [], "next": None}

        cursor = _cursor("rippling", "employee")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("employee", cursor)
            list(gen)

        assert "updatedAfter" in captured_params
        assert "2026-01-01" in captured_params["updatedAfter"]

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make()
        conn._api_key = "key"
        cursor = _cursor("rippling", "department")

        with patch.object(conn, "_get", return_value={"data": [], "next": None}):
            gen, new_cursor = conn.extract_incremental("department", cursor)
            list(gen)

        assert new_cursor.connector_id == "rippling"
        assert new_cursor.entity_type == "department"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    def test_health_check_healthy(self):
        conn = self._make()
        conn._api_key = "key"
        with patch.object(conn._http_client, "get", return_value=_mock_http_response(200, {"id": "u1"})):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_health_check_unhealthy(self):
        conn = self._make()
        conn._api_key = "key"
        with patch.object(conn._http_client, "get", side_effect=Exception("timeout")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert health.error_message is not None

    def test_headers_include_bearer_token(self):
        conn = self._make()
        conn._api_key = "my-secret-key"
        headers = conn._headers()
        assert headers["Authorization"] == "Bearer my-secret-key"


# ═════════════════════════════════════════════════════════════════════════════
# SAGE INTACCT TESTS
# ═════════════════════════════════════════════════════════════════════════════

SAGE_SESSION_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <operation>
    <result>
      <status>success</status>
      <data>
        <api>
          <sessionid>abc123sessionid</sessionid>
          <endpoint>https://api.intacct.com</endpoint>
        </api>
      </data>
    </result>
  </operation>
</response>"""

SAGE_VENDOR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <operation>
    <result>
      <status>success</status>
      <data listtype="vendor" count="2" totalcount="2" numremaining="0">
        <vendor>
          <RECORDNO>1</RECORDNO>
          <VENDORID>V001</VENDORID>
          <NAME>Acme Supplies</NAME>
          <STATUS>active</STATUS>
        </vendor>
        <vendor>
          <RECORDNO>2</RECORDNO>
          <VENDORID>V002</VENDORID>
          <NAME>Beta Services</NAME>
          <STATUS>active</STATUS>
        </vendor>
      </data>
    </result>
  </operation>
</response>"""


class TestSageIntacctConnector:

    def _make(self, tenant_id: str = "acme") -> SageIntacctConnector:
        return SageIntacctConnector(_sage_creds(tenant_id))

    def test_authenticate_success(self):
        conn = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = SAGE_SESSION_XML
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            assert conn.authenticate() is True
        assert conn._session_id == "abc123sessionid"

    def test_authenticate_stores_company_id(self):
        conn = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = SAGE_SESSION_XML
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            conn.authenticate()
        assert conn._company_id == "ACME_CORP"

    def test_authenticate_missing_credentials_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="sage_intacct", tenant_id="t",
            auth_data={"company_id": "X"},  # missing other fields
        )
        conn = SageIntacctConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_bad_xml_returns_false(self):
        conn = self._make()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = "<invalid>no session here</invalid>"
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            assert conn.authenticate() is False

    def test_discover_schema_has_four_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"vendor", "ap_bill", "ar_invoice", "gl_account"}

    def test_discover_schema_vendor_has_key_fields(self):
        schema = self._make().discover_schema()
        vendor = next(s for s in schema if s.entity_type == "vendor")
        assert "VENDORID" in vendor.fields
        assert "WHENMODIFIED" in vendor.fields

    def test_extract_full_vendor_yields_records(self):
        conn = self._make()
        conn._session_id = "sess123"
        conn._sender_id = "sender"
        conn._sender_password = "pass"

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = SAGE_VENDOR_XML

        with patch.object(conn._http_client, "post", return_value=mock_resp):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 2
        assert records[0].connector_id == "sage_intacct"
        assert records[0].source_id in {"1", "2", "V001", "V002"}

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="SageIntacct"):
            list(conn.extract_full("worker"))

    def test_extract_incremental_adds_whenmodified_filter(self):
        conn = self._make()
        conn._session_id = "sess"
        conn._sender_id = "s"
        conn._sender_password = "p"

        captured_xml = []

        def mock_post(url, content=None, **kwargs):
            captured_xml.append(content.decode() if isinstance(content, bytes) else content)
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            # Return empty vendor list
            mock_resp.text = """<response><operation><result><status>success</status>
                <data listtype="vendor" count="0" totalcount="0" numremaining="0"/>
                </result></operation></response>"""
            return mock_resp

        cursor = _cursor("sage_intacct", "vendor")
        with patch.object(conn._http_client, "post", side_effect=mock_post):
            gen, new_cursor = conn.extract_incremental("vendor", cursor)
            list(gen)

        assert any("WHENMODIFIED" in xml for xml in captured_xml)
        assert new_cursor.connector_id == "sage_intacct"

    def test_parse_session_id_extracts_correctly(self):
        conn = self._make()
        session_id = conn._parse_session_id(SAGE_SESSION_XML)
        assert session_id == "abc123sessionid"

    def test_parse_session_id_returns_none_on_bad_xml(self):
        conn = self._make()
        assert conn._parse_session_id("<bad>") is None

    def test_health_check_healthy(self):
        conn = self._make()
        conn._session_id = "sess"
        conn._sender_id = "s"
        conn._sender_password = "p"

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.text = """<response><operation><result><status>success</status>
            <data listtype="vendor" count="1" totalcount="1" numremaining="0">
              <vendor><RECORDNO>1</RECORDNO><VENDORID>V001</VENDORID><NAME>X</NAME></vendor>
            </data></result></operation></response>"""

        with patch.object(conn._http_client, "post", return_value=mock_resp):
            health = conn.health_check()
        assert health.is_healthy is True

    def test_build_auth_xml_contains_credentials(self):
        conn = self._make()
        xml = conn._build_auth_xml("ACME", "user", "pass", "sender", "spass")
        assert "ACME" in xml
        assert "user" in xml
        assert "getAPISession" in xml


# ═════════════════════════════════════════════════════════════════════════════
# NETSUITE TESTS
# ═════════════════════════════════════════════════════════════════════════════

NETSUITE_SUITEQL_RESP = {
    "hasMore": False,
    "offset": 0,
    "count": 2,
    "totalResults": 2,
    "items": [
        {"id": "101", "entityid": "V101", "companyname": "Vendor Alpha",
         "email": "vendor@alpha.com", "isinactive": "F"},
        {"id": "102", "entityid": "V102", "companyname": "Vendor Beta",
         "email": "vendor@beta.com", "isinactive": "F"},
    ],
    "links": [],
}

NETSUITE_EMPLOYEE_RESP = {
    "hasMore": False,
    "offset": 0,
    "count": 1,
    "totalResults": 1,
    "items": [
        {"id": "E1", "firstname": "Alice", "lastname": "Corp",
         "email": "alice@corp.com", "title": "Engineer",
         "employeestatus": "ACTIVE", "hiredate": "2022-01-10"},
    ],
}


class TestNetSuiteConnector:

    def _make(self, tenant_id: str = "acme") -> NetSuiteConnector:
        return NetSuiteConnector(_netsuite_creds(tenant_id))

    def test_authenticate_tba_success(self):
        conn = self._make()
        with patch.object(conn, "_suiteql_page", return_value={"items": [{"id": "1"}]}):
            assert conn.authenticate() is True
        assert conn._account_id == "1234567"
        assert conn._consumer_key == "ck_test"

    def test_authenticate_missing_account_id_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="netsuite", tenant_id="t",
            auth_data={"consumer_key": "ck"},  # no account_id
        )
        conn = NetSuiteConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_tba_keys_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="netsuite", tenant_id="t",
            auth_data={"account_id": "123"},  # no TBA keys
        )
        conn = NetSuiteConnector(creds)
        conn._account_id = "123"
        # _suiteql_page will fail without TBA keys
        with patch.object(conn, "_suiteql_page", side_effect=Exception("auth failed")):
            assert conn.authenticate() is False

    def test_discover_schema_has_five_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"vendor", "customer", "employee", "purchase_order", "invoice"}

    def test_discover_schema_vendor_supports_incremental(self):
        schema = self._make().discover_schema()
        vendor = next(s for s in schema if s.entity_type == "vendor")
        assert vendor.supports_incremental is True

    def test_discover_schema_po_has_approvalstatus_field(self):
        schema = self._make().discover_schema()
        po = next(s for s in schema if s.entity_type == "purchase_order")
        assert "approvalstatus" in po.fields

    def test_extract_full_vendor_yields_raw_records(self):
        conn = self._make()
        conn._account_id = "1234567"
        conn._auth_mode = "tba"

        with patch.object(conn, "_suiteql_page", return_value=NETSUITE_SUITEQL_RESP):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 2
        assert records[0].connector_id == "netsuite"
        assert records[0].email_hint == "vendor@alpha.com"
        assert records[0].name_hint == "Vendor Alpha"

    def test_extract_full_employee_yields_name_hint(self):
        conn = self._make()
        conn._account_id = "1234567"
        conn._auth_mode = "tba"

        with patch.object(conn, "_suiteql_page", return_value=NETSUITE_EMPLOYEE_RESP):
            records = list(conn.extract_full("employee"))

        assert len(records) == 1
        assert records[0].name_hint == "Alice Corp"

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="NetSuite"):
            list(conn.extract_full("organization"))

    def test_extract_full_paginates_until_has_more_false(self):
        conn = self._make()
        conn._account_id = "1234567"

        page1 = {
            "hasMore": True, "offset": 0, "totalResults": 3,
            "items": [{"id": "1", "companyname": "A", "email": "a@a.com"}],
        }
        page2 = {
            "hasMore": False, "offset": 1, "totalResults": 3,
            "items": [
                {"id": "2", "companyname": "B", "email": "b@b.com"},
                {"id": "3", "companyname": "C", "email": "c@c.com"},
            ],
        }
        pages = [page1, page2]
        call_idx = 0

        def mock_page(query, offset):
            nonlocal call_idx
            result = pages[call_idx]
            call_idx += 1
            return result

        with patch.object(conn, "_suiteql_page", side_effect=mock_page):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 3

    def test_extract_incremental_adds_lastmodifieddate_filter(self):
        conn = self._make()
        conn._account_id = "1234567"

        captured_queries = []

        def mock_page(query, offset):
            captured_queries.append(query)
            return {"hasMore": False, "items": [], "totalResults": 0}

        cursor = _cursor("netsuite", "vendor")
        with patch.object(conn, "_suiteql_page", side_effect=mock_page):
            gen, new_cursor = conn.extract_incremental("vendor", cursor)
            list(gen)

        assert any("lastmodifieddate" in q.lower() for q in captured_queries)
        assert any("2026-01-01" in q for q in captured_queries)

    def test_extract_incremental_purchase_order_filter(self):
        conn = self._make()
        conn._account_id = "1234567"

        captured = []

        def mock_page(query, offset):
            captured.append(query)
            return {"hasMore": False, "items": [], "totalResults": 0}

        cursor = _cursor("netsuite", "purchase_order")
        with patch.object(conn, "_suiteql_page", side_effect=mock_page):
            gen, _ = conn.extract_incremental("purchase_order", cursor)
            list(gen)

        # Should have WHERE ... AND lastmodifieddate since PO query has WHERE
        assert any("AND lastmodifieddate" in q for q in captured)

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make()
        conn._account_id = "1234567"
        cursor = _cursor("netsuite", "invoice")

        with patch.object(conn, "_suiteql_page",
                          return_value={"hasMore": False, "items": [], "totalResults": 0}):
            gen, new_cursor = conn.extract_incremental("invoice", cursor)
            list(gen)

        assert new_cursor.entity_type == "invoice"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    def test_health_check_healthy(self):
        conn = self._make()
        conn._account_id = "1234567"
        conn._auth_mode = "tba"

        with patch.object(conn, "_suiteql_page", return_value={"items": [{"id": "1"}]}):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.connector_id == "netsuite"

    def test_health_check_unhealthy(self):
        conn = self._make()
        conn._account_id = "1234567"
        conn._auth_mode = "tba"

        with patch.object(conn, "_suiteql_page", side_effect=Exception("connection refused")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "connection refused" in health.error_message

    def test_tba_headers_include_oauth_authorization(self):
        conn = self._make()
        conn._account_id = "1234567"
        conn._consumer_key = "ck"
        conn._consumer_secret = "cs"
        conn._token_id = "ti"
        conn._token_secret = "ts"
        conn._auth_mode = "tba"

        headers = conn._tba_headers(method="POST", url="https://example.com/api")
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("OAuth ")
        assert "oauth_consumer_key" in headers["Authorization"]
        assert "HMAC-SHA256" in headers["Authorization"]

    def test_oauth2_authenticate_success(self):
        creds = ConnectorCredentials(
            connector_id="netsuite", tenant_id="acme",
            auth_data={
                "account_id": "1234567",
                "client_id": "cid",
                "client_secret": "csecret",
                "auth_mode": "oauth2",
            },
        )
        conn = NetSuiteConnector(creds)

        mock_resp = _mock_http_response(200, {"access_token": "my-bearer-token"})
        with patch.object(conn._http_client, "post", return_value=mock_resp):
            result = conn.authenticate()

        assert result is True
        assert conn._oauth2_token == "my-bearer-token"

    def test_suiteql_url_uses_account_id(self):
        conn = self._make()
        conn._account_id = "7654321"
        url = conn._suiteql_url()
        assert "7654321" in url
        assert "suiteql" in url


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossConnectorSprint29:
    """Tests that verify all new connectors satisfy the ConnectorBase contract."""

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (BambooHRConnector, _bamboohr_creds),
        (RipplingConnector, _rippling_creds),
        (SageIntacctConnector, _sage_creds),
        (NetSuiteConnector, _netsuite_creds),
    ])
    def test_connector_id_is_set(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert isinstance(conn.CONNECTOR_ID, str)
        assert len(conn.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (BambooHRConnector, _bamboohr_creds),
        (RipplingConnector, _rippling_creds),
        (SageIntacctConnector, _sage_creds),
        (NetSuiteConnector, _netsuite_creds),
    ])
    def test_display_name_is_set(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert isinstance(conn.DISPLAY_NAME, str)
        assert "Production" in conn.DISPLAY_NAME

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (BambooHRConnector, _bamboohr_creds),
        (RipplingConnector, _rippling_creds),
        (SageIntacctConnector, _sage_creds),
        (NetSuiteConnector, _netsuite_creds),
    ])
    def test_calls_per_second_is_conservative(self, connector_class, creds_fn):
        """All new connectors should self-limit to at most 10 calls/sec."""
        conn = connector_class(creds_fn())
        assert conn.CALLS_PER_SECOND <= 10.0

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (BambooHRConnector, _bamboohr_creds),
        (RipplingConnector, _rippling_creds),
        (SageIntacctConnector, _sage_creds),
        (NetSuiteConnector, _netsuite_creds),
    ])
    def test_discover_schema_returns_list(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        schema = conn.discover_schema()
        assert isinstance(schema, list)
        assert len(schema) >= 1

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (BambooHRConnector, _bamboohr_creds),
        (RipplingConnector, _rippling_creds),
        (SageIntacctConnector, _sage_creds),
        (NetSuiteConnector, _netsuite_creds),
    ])
    def test_tenant_id_is_preserved(self, connector_class, creds_fn):
        conn = connector_class(creds_fn("my-tenant"))
        assert conn.tenant_id == "my-tenant"
