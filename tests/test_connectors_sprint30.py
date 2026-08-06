"""
tests/test_connectors_sprint30.py — Sprint 30 Connector Tests

Tests for the two new production HRIS connectors:
  - ADPConnector      (ADP Workforce Now)
  - UKGConnector      (UKG Pro / UltiPro)

All tests use mock HTTP responses — no real API calls.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from scout.connectors.adp import ADPConnector
from scout.connectors.ukg import UKGConnector
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


def _adp_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="adp",
        tenant_id=tenant_id,
        auth_data={
            "client_id": "adp-client-id-test",
            "client_secret": "adp-secret-test",
        },
    )


def _ukg_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="ukg",
        tenant_id=tenant_id,
        auth_data={
            "username": "ukg_svc_user",
            "password": "ukg_svc_pass",
            "company_name": "acmecorp",
            "customer_api_key": "cust-api-key-xyz",
        },
    )


def _mock_response(status_code: int = 200, json_body=None) -> MagicMock:
    """Create a mock httpx response that raise_for_status is configured on."""
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

class TestRegistrySprint30:

    def test_adp_in_registry(self):
        assert "adp" in CONNECTOR_REGISTRY

    def test_ukg_in_registry(self):
        assert "ukg" in CONNECTOR_REGISTRY

    def test_adp_has_correct_category(self):
        assert ADPConnector.CATEGORY == ConnectorCategory.HCM

    def test_ukg_has_correct_category(self):
        assert UKGConnector.CATEGORY == ConnectorCategory.HCM

    def test_get_adp_connector(self):
        conn = get_connector("adp", _adp_creds())
        assert conn.CONNECTOR_ID == "adp"

    def test_get_ukg_connector(self):
        conn = get_connector("ukg", _ukg_creds())
        assert conn.CONNECTOR_ID == "ukg"


# ═════════════════════════════════════════════════════════════════════════════
# ADP CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestADPConnector:

    def _make(self, tenant_id: str = "acme") -> ADPConnector:
        return ADPConnector(_adp_creds(tenant_id))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make()
        with patch.object(conn, "_fetch_token", return_value="bearer-token-abc"):
            assert conn.authenticate() is True
        assert conn._access_token == "bearer-token-abc"

    def test_authenticate_missing_client_id_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="adp", tenant_id="t",
            auth_data={"client_secret": "sec"},  # no client_id
        )
        conn = ADPConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_client_secret_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="adp", tenant_id="t",
            auth_data={"client_id": "cid"},  # no client_secret
        )
        conn = ADPConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_token_fetch_returns_none_returns_false(self):
        conn = self._make()
        with patch.object(conn, "_fetch_token", return_value=None):
            assert conn.authenticate() is False

    def test_fetch_token_posts_to_adp_token_url(self):
        """_fetch_token must POST client credentials to ADP's token endpoint."""
        conn = self._make()
        mock_resp = _mock_response(200, {"access_token": "tok123"})
        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_ctx
            mock_ctx.post.return_value = mock_resp
            token = conn._fetch_token("cid", "csec")
        assert token == "tok123"
        call_args = mock_ctx.post.call_args
        assert "grant_type" in call_args.kwargs.get("data", call_args[1].get("data", {}))

    def test_fetch_token_http_error_returns_none(self):
        conn = self._make()
        import httpx
        mock_resp_err = MagicMock(status_code=401)
        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_ctx
            mock_ctx.post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401", request=MagicMock(), response=mock_resp_err
            )
            token = conn._fetch_token("cid", "csec")
        assert token is None

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_two_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"worker", "time_off"}

    def test_discover_schema_worker_has_key_fields(self):
        schema = self._make().discover_schema()
        worker = next(s for s in schema if s.entity_type == "worker")
        assert "associateOID" in worker.fields
        assert "workerStatus" in worker.fields
        assert "workerDates.terminationDate" in worker.fields

    def test_discover_schema_worker_supports_incremental(self):
        schema = self._make().discover_schema()
        worker = next(s for s in schema if s.entity_type == "worker")
        assert worker.supports_incremental is True

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_workers_yields_raw_records(self):
        conn = self._make()
        conn._access_token = "tok"

        page_data = {
            "workers": [
                {
                    "associateOID": "W001",
                    "workerStatus": {"statusCode": {"codeValue": "Active"}},
                    "person": {
                        "legalName": {"givenName": "Alice", "familyName": "Smith"}
                    },
                    "businessCommunication": {
                        "emails": [{"emailUri": "alice@acme.com"}]
                    },
                },
                {
                    "associateOID": "W002",
                    "workerStatus": {"statusCode": {"codeValue": "Active"}},
                    "person": {
                        "legalName": {"givenName": "Bob", "familyName": "Jones"}
                    },
                    "businessCommunication": {"emails": []},
                },
            ]
        }

        with patch.object(conn, "_get", return_value=page_data):
            records = list(conn.extract_full("worker"))

        assert len(records) == 2
        assert all(isinstance(r, RawRecord) for r in records)
        assert records[0].connector_id == "adp"
        assert records[0].source_id == "W001"

    def test_extract_full_sets_email_hint(self):
        conn = self._make()
        conn._access_token = "tok"
        page = {
            "workers": [{
                "associateOID": "W001",
                "person": {"legalName": {"givenName": "Alice", "familyName": "Smith"}},
                "businessCommunication": {"emails": [{"emailUri": "alice@acme.com"}]},
            }]
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("worker"))
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_paginates_until_short_page(self):
        conn = self._make()
        conn._access_token = "tok"

        # First page has 100 workers, second has 50 → stops
        page1 = {"workers": [{"associateOID": f"W{i:03d}"} for i in range(100)]}
        page2 = {"workers": [{"associateOID": f"W{i:03d}"} for i in range(100, 150)]}
        pages = [page1, page2]
        call_idx = 0

        def mock_get(url, **kwargs):
            nonlocal call_idx
            result = pages[call_idx]
            call_idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("worker"))

        assert len(records) == 150
        assert call_idx == 2  # stopped after second (short) page

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="ADP"):
            list(conn.extract_full("department"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_passes_odata_filter(self):
        conn = self._make()
        conn._access_token = "tok"
        captured_params = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured_params.update(params)
            return {"workers": []}

        cursor = _cursor("adp", "worker")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("worker", cursor)
            list(gen)

        assert "$filter" in captured_params
        assert "lastModifiedDate" in captured_params["$filter"]
        assert "2026-01-01" in captured_params["$filter"]

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make()
        conn._access_token = "tok"
        cursor = _cursor("adp", "worker")

        with patch.object(conn, "_get", return_value={"workers": []}):
            gen, new_cursor = conn.extract_incremental("worker", cursor)
            list(gen)

        assert new_cursor.connector_id == "adp"
        assert new_cursor.entity_type == "worker"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    def test_extract_incremental_unsupported_entity_raises(self):
        conn = self._make()
        cursor = _cursor("adp", "department")
        with pytest.raises(ValueError):
            conn.extract_incremental("department", cursor)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make()
        conn._access_token = "tok"
        with patch.object(conn, "_get", return_value={"workers": []}):
            health = conn.health_check()
        assert health.is_healthy is True
        assert health.connector_id == "adp"

    def test_health_check_unhealthy_on_error(self):
        conn = self._make()
        conn._access_token = "tok"
        with patch.object(conn, "_get", side_effect=Exception("connection refused")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "connection refused" in health.error_message


# ═════════════════════════════════════════════════════════════════════════════
# UKG CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestUKGConnector:

    def _make(self, tenant_id: str = "acme") -> UKGConnector:
        return UKGConnector(_ukg_creds(tenant_id))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make()
        login_resp = _mock_response(200, {"ApiKey": "session-key-xyz"})
        with patch.object(conn._http_client, "post", return_value=login_resp):
            assert conn.authenticate() is True
        assert conn._api_key == "session-key-xyz"
        assert conn._customer_api_key == "cust-api-key-xyz"
        assert conn._base_url == "https://acmecorp.ultipro.com"

    def test_authenticate_missing_username_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="ukg", tenant_id="t",
            auth_data={
                "password": "pass",
                "company_name": "acme",
                "customer_api_key": "key",
            },
        )
        conn = UKGConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_customer_api_key_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="ukg", tenant_id="t",
            auth_data={
                "username": "user",
                "password": "pass",
                "company_name": "acme",
                # missing customer_api_key
            },
        )
        conn = UKGConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_401_returns_false(self):
        conn = self._make()
        with patch.object(conn._http_client, "post", return_value=_mock_response(401)):
            assert conn.authenticate() is False

    def test_authenticate_no_api_key_in_response_returns_false(self):
        conn = self._make()
        # Response 200 but no ApiKey field
        login_resp = _mock_response(200, {"token": "something"})
        with patch.object(conn._http_client, "post", return_value=login_resp):
            assert conn.authenticate() is False

    def test_authenticate_sets_base_url(self):
        conn = self._make()
        login_resp = _mock_response(200, {"ApiKey": "key"})
        with patch.object(conn._http_client, "post", return_value=login_resp):
            conn.authenticate()
        assert conn._base_url == "https://acmecorp.ultipro.com"

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_two_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"employee", "time_entry"}

    def test_discover_schema_employee_has_key_fields(self):
        schema = self._make().discover_schema()
        emp = next(s for s in schema if s.entity_type == "employee")
        assert "EmployeeNumber" in emp.fields
        assert "TerminationDate" in emp.fields
        assert "WorkEmailAddress" in emp.fields
        assert "LastModifiedDate" in emp.fields

    def test_discover_schema_time_entry_has_hours_worked(self):
        schema = self._make().discover_schema()
        te = next(s for s in schema if s.entity_type == "time_entry")
        assert "HoursWorked" in te.fields
        assert "OvertimeHours" in te.fields

    def test_discover_schema_employee_supports_incremental(self):
        schema = self._make().discover_schema()
        emp = next(s for s in schema if s.entity_type == "employee")
        assert emp.supports_incremental is True

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_employees_yields_raw_records(self):
        conn = self._make()
        conn._api_key = "sess-key"
        conn._customer_api_key = "cust-key"
        conn._base_url = "https://acmecorp.ultipro.com"

        employees = [
            {"EmployeeNumber": "E001", "FirstName": "Alice", "LastName": "Smith",
             "WorkEmailAddress": "alice@acme.com", "EmploymentStatus": "A"},
            {"EmployeeNumber": "E002", "FirstName": "Bob", "LastName": "Jones",
             "WorkEmailAddress": "bob@acme.com", "EmploymentStatus": "A"},
        ]

        with patch.object(conn, "_get", return_value=employees):
            records = list(conn.extract_full("employee"))

        assert len(records) == 2
        assert records[0].connector_id == "ukg"
        assert records[0].source_id == "E001"

    def test_extract_full_sets_email_and_name_hint(self):
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"

        employees = [
            {"EmployeeNumber": "E001", "FirstName": "Alice", "LastName": "Smith",
             "WorkEmailAddress": "alice@acme.com", "EmploymentStatus": "A"},
        ]

        with patch.object(conn, "_get", return_value=employees):
            records = list(conn.extract_full("employee"))

        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_handles_wrapped_response(self):
        """UKG sometimes wraps response in a 'Data' key."""
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"

        wrapped = {
            "Data": [
                {"EmployeeNumber": "E001", "FirstName": "Alice", "LastName": "S",
                 "WorkEmailAddress": "a@a.com"},
            ]
        }

        with patch.object(conn, "_get", return_value=wrapped):
            records = list(conn.extract_full("employee"))

        assert len(records) == 1
        assert records[0].source_id == "E001"

    def test_extract_full_paginates_until_short_page(self):
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"

        page1 = [{"EmployeeNumber": f"E{i:03d}", "FirstName": "X", "LastName": "Y"} for i in range(200)]
        page2 = [{"EmployeeNumber": f"E{i:03d}", "FirstName": "X", "LastName": "Y"} for i in range(200, 250)]
        pages = [page1, page2]
        idx = 0

        def mock_get(url, **kwargs):
            nonlocal idx
            result = pages[idx]
            idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("employee"))

        assert len(records) == 250

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="UKG"):
            list(conn.extract_full("department"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_passes_lastmodifieddate_filter(self):
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"
        captured = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured.update(params)
            return []

        cursor = _cursor("ukg", "employee")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("employee", cursor)
            list(gen)

        assert "$filter" in captured
        assert "LastModifiedDate" in captured["$filter"]
        assert "2026-01-01" in captured["$filter"]

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"
        cursor = _cursor("ukg", "employee")

        with patch.object(conn, "_get", return_value=[]):
            gen, new_cursor = conn.extract_incremental("employee", cursor)
            list(gen)

        assert new_cursor.connector_id == "ukg"
        assert new_cursor.entity_type == "employee"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    def test_extract_incremental_unsupported_entity_raises(self):
        conn = self._make()
        cursor = _cursor("ukg", "payroll")
        with pytest.raises(ValueError):
            conn.extract_incremental("payroll", cursor)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"

        with patch.object(conn, "_get", return_value=[]):
            health = conn.health_check()

        assert health.is_healthy is True
        assert health.connector_id == "ukg"

    def test_health_check_unhealthy(self):
        conn = self._make()
        conn._api_key = "key"
        conn._customer_api_key = "ckey"
        conn._base_url = "https://acmecorp.ultipro.com"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "timeout" in health.error_message

    def test_headers_include_both_keys(self):
        """UKG requires both US-Customer-Api-Key and US-Api-Key in every request."""
        conn = self._make()
        conn._api_key = "sess-key"
        conn._customer_api_key = "cust-key"
        headers = conn._headers()
        assert headers["US-Customer-Api-Key"] == "cust-key"
        assert headers["US-Api-Key"] == "sess-key"
        assert "Authorization" in headers


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossConnectorSprint30:
    """Verify all Sprint 30 connectors satisfy the ConnectorBase contract."""

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (ADPConnector, _adp_creds),
        (UKGConnector, _ukg_creds),
    ])
    def test_connector_id_is_set(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert isinstance(conn.CONNECTOR_ID, str)
        assert len(conn.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (ADPConnector, _adp_creds),
        (UKGConnector, _ukg_creds),
    ])
    def test_display_name_contains_production(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert "Production" in conn.DISPLAY_NAME

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (ADPConnector, _adp_creds),
        (UKGConnector, _ukg_creds),
    ])
    def test_category_is_hcm(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert conn.CATEGORY == ConnectorCategory.HCM

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (ADPConnector, _adp_creds),
        (UKGConnector, _ukg_creds),
    ])
    def test_calls_per_second_is_conservative(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert conn.CALLS_PER_SECOND <= 25.0  # ADP's limit is 25/sec

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (ADPConnector, _adp_creds),
        (UKGConnector, _ukg_creds),
    ])
    def test_discover_schema_returns_list(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        schema = conn.discover_schema()
        assert isinstance(schema, list)
        assert len(schema) >= 1

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (ADPConnector, _adp_creds),
        (UKGConnector, _ukg_creds),
    ])
    def test_tenant_id_is_preserved(self, connector_class, creds_fn):
        conn = connector_class(creds_fn("my-tenant"))
        assert conn.tenant_id == "my-tenant"
