"""
tests/test_connectors_sprint32.py — Sprint 32 Connector Tests

Tests for the three enterprise ERP connectors:
  - SAPConnector          (SAP Business One + S/4HANA)
  - OracleERPConnector    (Oracle ERP Cloud / Fusion)
  - Dynamics365Connector  (Microsoft Dynamics 365 F&O + Business Central)

All tests use mock HTTP responses — no real API calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from scout.connectors.sap import SAPConnector
from scout.connectors.oracle_erp import OracleERPConnector
from scout.connectors.dynamics_365 import Dynamics365Connector
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ExtractionCursor,
    RawRecord,
)
from scout.connectors.registry import CONNECTOR_REGISTRY


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


def _sap_b1_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="sap",
        tenant_id=tenant_id,
        auth_data={
            "auth_mode": "b1",
            "host": "sap-server.acme.com",
            "port": "50000",
            "company_db": "ACME_PROD",
            "username": "svc_miragent",
            "password": "svc_password",
        },
    )


def _sap_s4_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="sap",
        tenant_id=tenant_id,
        auth_data={
            "auth_mode": "s4hana",
            "host": "my-api.s4hana.ondemand.com",
            "client_id": "s4-client-id",
            "client_secret": "s4-secret",
            "token_url": "https://acme.authentication.us10.hana.ondemand.com/oauth/token",
        },
    )


def _oracle_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="oracle_erp",
        tenant_id=tenant_id,
        auth_data={
            "auth_mode": "basic",
            "instance": "acme-prod",
            "username": "oracle_svc",
            "password": "oracle_pass",
        },
    )


def _dynamics_fo_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="dynamics_365",
        tenant_id=tenant_id,
        auth_data={
            "auth_mode": "fo",
            "tenant_id": "aad-tenant-guid",
            "client_id": "d365-client-id",
            "client_secret": "d365-secret",
            "instance": "acme-prod",
        },
    )


def _dynamics_bc_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="dynamics_365",
        tenant_id=tenant_id,
        auth_data={
            "auth_mode": "bc",
            "tenant_id": "aad-tenant-guid",
            "client_id": "d365-client-id",
            "client_secret": "d365-secret",
            "instance": "acme-bc-instance",
            "company_id": "bc-company-guid",
        },
    )


def _mock_response(status_code: int = 200, json_body=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    if status_code >= 400:
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

class TestRegistrySprint32:
    """SAP has a mock, so it's always in the registry. Oracle/Dynamics are prod-only."""

    def test_sap_in_registry(self):
        assert "sap" in CONNECTOR_REGISTRY

    def test_sap_connector_id(self):
        assert SAPConnector.CONNECTOR_ID == "sap"

    def test_oracle_erp_connector_id(self):
        assert OracleERPConnector.CONNECTOR_ID == "oracle_erp"

    def test_dynamics_365_connector_id(self):
        assert Dynamics365Connector.CONNECTOR_ID == "dynamics_365"

    def test_all_sprint32_category_is_erp(self):
        assert SAPConnector.CATEGORY == ConnectorCategory.ERP
        assert OracleERPConnector.CATEGORY == ConnectorCategory.ERP
        assert Dynamics365Connector.CATEGORY == ConnectorCategory.ERP


# ═════════════════════════════════════════════════════════════════════════════
# SAP CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestSAPConnector:

    def _make_b1(self, tenant_id: str = "acme") -> SAPConnector:
        return SAPConnector(_sap_b1_creds(tenant_id))

    def _make_s4(self, tenant_id: str = "acme") -> SAPConnector:
        return SAPConnector(_sap_s4_creds(tenant_id))

    # ── Authentication — B1 ────────────────────────────────────────────────

    def test_b1_authenticate_success(self):
        conn = self._make_b1()
        login_resp = _mock_response(200, {"SessionId": "sess-abc123"})
        with patch.object(conn._http_client, "post", return_value=login_resp):
            assert conn.authenticate() is True
        assert conn._session_id == "sess-abc123"
        assert conn._auth_mode == "b1"

    def test_b1_authenticate_missing_host_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="sap", tenant_id="t",
            auth_data={"auth_mode": "b1", "company_db": "DB",
                       "username": "u", "password": "p"},
        )
        conn = SAPConnector(creds)
        assert conn.authenticate() is False

    def test_b1_authenticate_401_returns_false(self):
        conn = self._make_b1()
        with patch.object(conn._http_client, "post", return_value=_mock_response(401)):
            assert conn.authenticate() is False

    def test_b1_authenticate_no_session_id_returns_false(self):
        conn = self._make_b1()
        # Response OK but no SessionId
        login_resp = _mock_response(200, {"Status": "ok"})
        with patch.object(conn._http_client, "post", return_value=login_resp):
            assert conn.authenticate() is False

    def test_b1_headers_use_cookie(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "my-session"
        headers = conn._headers()
        assert "B1SESSION=my-session" in headers["Cookie"]

    # ── Authentication — S/4HANA ───────────────────────────────────────────

    def test_s4_authenticate_success(self):
        conn = self._make_s4()
        token_resp = _mock_response(200, {"access_token": "bearer-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            assert conn.authenticate() is True
        assert conn._access_token == "bearer-tok"
        assert conn._auth_mode == "s4hana"

    def test_s4_authenticate_missing_token_url_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="sap", tenant_id="t",
            auth_data={"auth_mode": "s4hana", "host": "h.com",
                       "client_id": "cid", "client_secret": "csec"},
        )
        conn = SAPConnector(creds)
        assert conn.authenticate() is False

    def test_s4_headers_use_bearer(self):
        conn = self._make_s4()
        conn._auth_mode = "s4hana"
        conn._access_token = "tok"
        headers = conn._headers()
        assert headers["Authorization"] == "Bearer tok"

    def test_unknown_auth_mode_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="sap", tenant_id="t",
            auth_data={"auth_mode": "unknown", "host": "h"},
        )
        conn = SAPConnector(creds)
        assert conn.authenticate() is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_five_entity_types(self):
        schema = self._make_b1().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"vendor", "customer", "employee", "purchase_order", "invoice"}

    def test_discover_schema_vendor_has_key_fields(self):
        schema = self._make_b1().discover_schema()
        vendor = next(s for s in schema if s.entity_type == "vendor")
        assert "CardCode" in vendor.fields
        assert "CardName" in vendor.fields
        assert "UpdateDate" in vendor.fields

    def test_discover_schema_all_support_incremental(self):
        schema = self._make_b1().discover_schema()
        for s in schema:
            assert s.supports_incremental is True

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_vendors_yields_raw_records(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"

        page = {"value": [
            {"CardCode": "V001", "CardName": "Acme Supplies",
             "CardType": "cSupplier", "EmailAddress": "v@acme.com"},
            {"CardCode": "V002", "CardName": "Beta Services",
             "CardType": "cSupplier", "EmailAddress": None},
        ]}

        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 2
        assert records[0].connector_id == "sap"
        assert records[0].source_id == "V001"
        assert records[0].name_hint == "Acme Supplies"

    def test_extract_full_employees_yields_records(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"

        page = {"value": [
            {"EmployeeID": 1001, "FirstName": "Alice", "LastName": "Smith",
             "Email": "alice@acme.com", "EmployeeStatus": "A"},
        ]}

        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("employee"))

        assert len(records) == 1
        assert records[0].source_id == "1001"

    def test_extract_full_paginates_until_short_page(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"

        page1 = {"value": [{"CardCode": f"V{i:03d}", "CardName": f"Vendor {i}"} for i in range(100)]}
        page2 = {"value": [{"CardCode": f"V{i:03d}", "CardName": f"Vendor {i}"} for i in range(100, 140)]}
        pages = [page1, page2]
        idx = 0

        def mock_get(url, **kwargs):
            nonlocal idx
            result = pages[idx]
            idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 140

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make_b1()
        with pytest.raises(ValueError, match="SAP"):
            list(conn.extract_full("opportunity"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_b1_incremental_uses_yyyymmdd_date_format(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"value": []}

        cursor = _cursor("sap", "vendor")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, new_cursor = conn.extract_incremental("vendor", cursor)
            list(gen)

        assert "$filter" in captured
        # B1 uses YYYYMMDD (no dashes)
        assert "20260101" in captured["$filter"]
        assert new_cursor.checkpoint["mode"] == "b1"

    def test_s4_incremental_uses_iso_format(self):
        conn = self._make_s4()
        conn._auth_mode = "s4hana"
        conn._access_token = "tok"
        conn._base_url = "https://api.s4hana.com"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"value": []}

        cursor = _cursor("sap", "vendor")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("vendor", cursor)
            list(gen)

        assert "$filter" in captured
        # S/4HANA uses ISO with dashes
        assert "2026-01-01" in captured["$filter"]

    def test_vendor_filter_combines_card_type_and_date(self):
        """Vendor extraction always filters by CardType AND UpdateDate."""
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"value": []}

        cursor = _cursor("sap", "vendor")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("vendor", cursor)
            list(gen)

        filter_val = captured.get("$filter", "")
        assert "cSupplier" in filter_val
        assert "UpdateDate" in filter_val

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"
        cursor = _cursor("sap", "employee")

        with patch.object(conn, "_get", return_value={"value": []}):
            gen, new_cursor = conn.extract_incremental("employee", cursor)
            list(gen)

        assert new_cursor.connector_id == "sap"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"

        with patch.object(conn, "_get", return_value={"value": [{"EmployeeID": 1}]}):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.connector_id == "sap"

    def test_health_check_unhealthy(self):
        conn = self._make_b1()
        conn._auth_mode = "b1"
        conn._session_id = "sess"
        conn._base_url = "https://sap.acme.com/b1s/v1"

        with patch.object(conn, "_get", side_effect=Exception("connection refused")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "connection refused" in health.error_message


# ═════════════════════════════════════════════════════════════════════════════
# ORACLE ERP CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestOracleERPConnector:

    def _make(self, tenant_id: str = "acme") -> OracleERPConnector:
        return OracleERPConnector(_oracle_creds(tenant_id))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_basic_success(self):
        conn = self._make()
        verify_resp = _mock_response(200, {"items": [], "hasMore": False})
        with patch.object(conn._http_client, "get", return_value=verify_resp):
            assert conn.authenticate() is True
        assert "Basic" in conn._auth_header
        assert conn._base_url == "https://acme-prod.fa.us2.oraclecloud.com"

    def test_authenticate_basic_encodes_credentials(self):
        import base64
        conn = self._make()
        verify_resp = _mock_response(200, {"items": []})
        with patch.object(conn._http_client, "get", return_value=verify_resp):
            conn.authenticate()
        expected = "Basic " + base64.b64encode(b"oracle_svc:oracle_pass").decode()
        assert conn._auth_header == expected

    def test_authenticate_missing_instance_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="oracle_erp", tenant_id="t",
            auth_data={"auth_mode": "basic", "username": "u", "password": "p"},
        )
        conn = OracleERPConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_credentials_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="oracle_erp", tenant_id="t",
            auth_data={"auth_mode": "basic", "instance": "x"},
        )
        conn = OracleERPConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_401_returns_false(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_response(401)):
            assert conn.authenticate() is False

    def test_authenticate_oauth2_success(self):
        creds = ConnectorCredentials(
            connector_id="oracle_erp", tenant_id="acme",
            auth_data={
                "auth_mode": "oauth2",
                "instance": "acme-prod",
                "client_id": "cid",
                "client_secret": "csec",
                "token_url": "https://auth.oracle.com/token",
            },
        )
        conn = OracleERPConnector(creds)
        token_resp = _mock_response(200, {"access_token": "oracle-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            assert conn.authenticate() is True
        assert conn._auth_header == "Bearer oracle-tok"

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_five_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"supplier", "purchase_order", "invoice", "worker", "gl_journal"}

    def test_discover_schema_supplier_has_key_fields(self):
        schema = self._make().discover_schema()
        supplier = next(s for s in schema if s.entity_type == "supplier")
        assert "SupplierId" in supplier.fields
        assert "SupplierName" in supplier.fields
        assert "LastUpdateDate" in supplier.fields

    def test_discover_schema_worker_has_termination_date(self):
        schema = self._make().discover_schema()
        worker = next(s for s in schema if s.entity_type == "worker")
        assert "ActualTerminationDate" in worker.fields
        assert "PersonId" in worker.fields

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_suppliers_yields_raw_records(self):
        conn = self._make()
        conn._auth_header = "Basic dGVzdA=="
        conn._base_url = "https://acme-prod.fa.us2.oraclecloud.com"

        oracle_page = {
            "items": [
                {"SupplierId": "S001", "SupplierName": "Acme Supplies",
                 "PrimaryContactEmail": "contact@acme.com", "hasMore": False},
                {"SupplierId": "S002", "SupplierName": "Beta Corp",
                 "PrimaryContactEmail": None, "hasMore": False},
            ],
            "hasMore": False,
            "count": 2,
        }

        with patch.object(conn, "_get", return_value=oracle_page):
            records = list(conn.extract_full("supplier"))

        assert len(records) == 2
        assert records[0].connector_id == "oracle_erp"
        assert records[0].source_id == "S001"
        assert records[0].name_hint == "Acme Supplies"
        assert records[0].email_hint == "contact@acme.com"

    def test_extract_full_paginates_on_has_more(self):
        conn = self._make()
        conn._auth_header = "Basic dGVzdA=="
        conn._base_url = "https://acme-prod.fa.us2.oraclecloud.com"

        page1 = {
            "items": [{"SupplierId": f"S{i:03d}", "SupplierName": f"Sup {i}"} for i in range(500)],
            "hasMore": True, "count": 500,
        }
        page2 = {
            "items": [{"SupplierId": f"S{i:03d}", "SupplierName": f"Sup {i}"} for i in range(500, 620)],
            "hasMore": False, "count": 120,
        }
        pages = [page1, page2]
        idx = 0

        def mock_get(url, **kwargs):
            nonlocal idx
            result = pages[idx]
            idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("supplier"))

        assert len(records) == 620

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="Oracle"):
            list(conn.extract_full("department"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_adds_oracle_filter(self):
        conn = self._make()
        conn._auth_header = "Basic dGVzdA=="
        conn._base_url = "https://acme-prod.fa.us2.oraclecloud.com"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"items": [], "hasMore": False}

        cursor = _cursor("oracle_erp", "supplier")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, new_cursor = conn.extract_incremental("supplier", cursor)
            list(gen)

        assert "q" in captured
        assert "LastUpdateDate" in captured["q"]
        assert "2026-01-01" in captured["q"]
        assert new_cursor.connector_id == "oracle_erp"

    def test_extract_incremental_gl_journal_uses_creation_date(self):
        conn = self._make()
        conn._auth_header = "Basic dGVzdA=="
        conn._base_url = "https://acme-prod.fa.us2.oraclecloud.com"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"items": [], "hasMore": False}

        cursor = _cursor("oracle_erp", "gl_journal")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("gl_journal", cursor)
            list(gen)

        assert "CreationDate" in captured.get("q", "")

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make()
        conn._auth_header = "Basic dGVzdA=="
        conn._base_url = "https://acme-prod.fa.us2.oraclecloud.com"

        with patch.object(conn, "_get", return_value={"items": [], "hasMore": False}):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.connector_id == "oracle_erp"

    def test_health_check_unhealthy(self):
        conn = self._make()
        conn._auth_header = "Basic dGVzdA=="
        conn._base_url = "https://acme-prod.fa.us2.oraclecloud.com"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "timeout" in health.error_message


# ═════════════════════════════════════════════════════════════════════════════
# DYNAMICS 365 CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestDynamics365Connector:

    def _make_fo(self) -> Dynamics365Connector:
        return Dynamics365Connector(_dynamics_fo_creds())

    def _make_bc(self) -> Dynamics365Connector:
        return Dynamics365Connector(_dynamics_bc_creds())

    # ── Authentication ─────────────────────────────────────────────────────

    def test_fo_authenticate_success(self):
        conn = self._make_fo()
        token_resp = _mock_response(200, {"access_token": "d365-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            assert conn.authenticate() is True
        assert conn._access_token == "d365-tok"
        assert conn._auth_mode == "fo"
        assert "acme-prod.operations.dynamics.com" in conn._base_url

    def test_bc_authenticate_success(self):
        conn = self._make_bc()
        token_resp = _mock_response(200, {"access_token": "bc-tok", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            assert conn.authenticate() is True
        assert conn._auth_mode == "bc"
        assert "businesscentral.dynamics.com" in conn._base_url

    def test_authenticate_missing_tenant_id_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="dynamics_365", tenant_id="t",
            auth_data={"auth_mode": "fo", "client_id": "cid",
                       "client_secret": "csec", "instance": "inst"},
        )
        conn = Dynamics365Connector(creds)
        assert conn.authenticate() is False

    def test_authenticate_unknown_mode_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="dynamics_365", tenant_id="t",
            auth_data={"auth_mode": "unknown", "tenant_id": "tid",
                       "client_id": "cid", "client_secret": "csec",
                       "instance": "inst"},
        )
        conn = Dynamics365Connector(creds)
        with patch.object(conn._http_client, "post",
                          return_value=_mock_response(200, {"access_token": "tok"})):
            assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make_fo()
        with patch.object(conn._http_client, "post", return_value=_mock_response(401)):
            assert conn.authenticate() is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_five_entity_types(self):
        schema = self._make_fo().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"vendor", "customer", "purchase_order", "invoice", "worker"}

    def test_discover_schema_vendor_has_fo_fields(self):
        schema = self._make_fo().discover_schema()
        vendor = next(s for s in schema if s.entity_type == "vendor")
        assert "VendorAccountNumber" in vendor.fields

    def test_discover_schema_vendor_has_bc_fields(self):
        schema = self._make_fo().discover_schema()
        vendor = next(s for s in schema if s.entity_type == "vendor")
        # BC fields also present in unified schema
        assert "displayName" in vendor.fields

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_fo_extract_full_vendors_yields_records(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"

        page = {
            "value": [
                {"VendorAccountNumber": "V-1001", "OrganizationName": "Acme Supplies",
                 "PrimaryContactEmail": "v@acme.com", "CurrencyCode": "USD"},
                {"VendorAccountNumber": "V-1002", "OrganizationName": "Beta Corp",
                 "PrimaryContactEmail": None},
            ]
        }

        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 2
        assert records[0].connector_id == "dynamics_365"
        assert records[0].source_id == "V-1001"
        assert records[0].name_hint == "Acme Supplies"

    def test_bc_extract_full_uses_bc_endpoint(self):
        conn = self._make_bc()
        conn._access_token = "tok"
        conn._auth_mode = "bc"
        conn._base_url = "https://api.businesscentral.dynamics.com/v2.0/inst/production/api/v2.0/companies(cid)"

        captured_urls = []

        def mock_get(url, **kwargs):
            captured_urls.append(url)
            return {"value": []}

        with patch.object(conn, "_get", side_effect=mock_get):
            list(conn.extract_full("vendor"))

        assert any("/vendors" in url for url in captured_urls)
        assert all("/data/Vendors" not in url for url in captured_urls)

    def test_fo_extract_full_uses_fo_endpoint(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"

        captured_urls = []

        def mock_get(url, **kwargs):
            captured_urls.append(url)
            return {"value": []}

        with patch.object(conn, "_get", side_effect=mock_get):
            list(conn.extract_full("vendor"))

        assert any("/data/Vendors" in url for url in captured_urls)

    def test_extract_full_follows_odata_next_link(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"

        page1 = {
            "value": [{"VendorAccountNumber": f"V{i}", "OrganizationName": f"V{i}"} for i in range(1000)],
            "@odata.nextLink": "https://acme-prod.operations.dynamics.com/data/Vendors?$skiptoken=abc",
        }
        page2 = {
            "value": [{"VendorAccountNumber": f"V{i}", "OrganizationName": f"V{i}"} for i in range(1000, 1350)],
        }
        pages = [page1, page2]
        idx = 0

        def mock_get(url, **kwargs):
            nonlocal idx
            result = pages[idx]
            idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("vendor"))

        assert len(records) == 1350

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make_fo()
        with pytest.raises(ValueError, match="Dynamics365"):
            list(conn.extract_full("opportunity"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_fo_incremental_uses_modified_date_time(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"value": []}

        cursor = _cursor("dynamics_365", "vendor")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, new_cursor = conn.extract_incremental("vendor", cursor)
            list(gen)

        assert "$filter" in captured
        assert "modifiedDateTime" in captured["$filter"]
        assert "2026-01-01" in captured["$filter"]
        assert new_cursor.checkpoint["mode"] == "fo"

    def test_bc_incremental_uses_last_modified_date_time(self):
        conn = self._make_bc()
        conn._access_token = "tok"
        conn._auth_mode = "bc"
        conn._base_url = "https://api.businesscentral.dynamics.com/v2.0/test"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return {"value": []}

        cursor = _cursor("dynamics_365", "vendor")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("vendor", cursor)
            list(gen)

        assert "lastModifiedDateTime" in captured.get("$filter", "")

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"
        cursor = _cursor("dynamics_365", "invoice")

        with patch.object(conn, "_get", return_value={"value": []}):
            gen, new_cursor = conn.extract_incremental("invoice", cursor)
            list(gen)

        assert new_cursor.connector_id == "dynamics_365"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"

        with patch.object(conn, "_get", return_value={"value": [{"id": "v1"}]}):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.connector_id == "dynamics_365"

    def test_health_check_unhealthy(self):
        conn = self._make_fo()
        conn._access_token = "tok"
        conn._auth_mode = "fo"
        conn._base_url = "https://acme-prod.operations.dynamics.com"

        with patch.object(conn, "_get", side_effect=Exception("network error")):
            health = conn.health_check()

        assert health.is_healthy is False


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossConnectorSprint32:
    """Verify all Sprint 32 connectors satisfy the ConnectorBase contract."""

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (SAPConnector, _sap_b1_creds),
        (OracleERPConnector, _oracle_creds),
        (Dynamics365Connector, _dynamics_fo_creds),
    ])
    def test_connector_id_is_set(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert isinstance(conn.CONNECTOR_ID, str)
        assert len(conn.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (SAPConnector, _sap_b1_creds),
        (OracleERPConnector, _oracle_creds),
        (Dynamics365Connector, _dynamics_fo_creds),
    ])
    def test_display_name_contains_production(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert "Production" in conn.DISPLAY_NAME

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (SAPConnector, _sap_b1_creds),
        (OracleERPConnector, _oracle_creds),
        (Dynamics365Connector, _dynamics_fo_creds),
    ])
    def test_category_is_erp(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert conn.CATEGORY == ConnectorCategory.ERP

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (SAPConnector, _sap_b1_creds),
        (OracleERPConnector, _oracle_creds),
        (Dynamics365Connector, _dynamics_fo_creds),
    ])
    def test_discover_schema_returns_list(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        schema = conn.discover_schema()
        assert isinstance(schema, list)
        assert len(schema) >= 1

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (SAPConnector, _sap_b1_creds),
        (OracleERPConnector, _oracle_creds),
        (Dynamics365Connector, _dynamics_fo_creds),
    ])
    def test_tenant_id_preserved(self, connector_class, creds_fn):
        conn = connector_class(creds_fn("pe-portfolio-co-12"))
        assert conn.tenant_id == "pe-portfolio-co-12"
