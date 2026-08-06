"""
tests/test_connectors_sprint31.py — Sprint 31 Connector Tests

Tests for the two identity connectors:
  - OktaConnector      (Okta Identity / SSO)
  - AzureADConnector   (Azure Active Directory / Microsoft Entra)

All tests use mock HTTP responses — no real API calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

from scout.connectors.okta import OktaConnector
from scout.connectors.azure_ad import AzureADConnector
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


def _okta_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="okta",
        tenant_id=tenant_id,
        auth_data={
            "api_token": "ssws-token-abc123",
            "org_domain": "acmecorp",
        },
    )


def _azure_creds(tenant_id: str = "acme") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="azure_ad",
        tenant_id=tenant_id,
        auth_data={
            "tenant_id": "aad-tenant-guid-123",
            "client_id": "app-client-id",
            "client_secret": "app-client-secret",
        },
    )


def _mock_response(status_code: int = 200, json_body=None, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.headers = headers or {}
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

class TestRegistrySprint31:

    def test_okta_in_registry(self):
        assert "okta" in CONNECTOR_REGISTRY

    def test_azure_ad_in_registry(self):
        assert "azure_ad" in CONNECTOR_REGISTRY

    def test_okta_category_is_identity(self):
        assert OktaConnector.CATEGORY == ConnectorCategory.IDENTITY

    def test_azure_ad_category_is_identity(self):
        assert AzureADConnector.CATEGORY == ConnectorCategory.IDENTITY


# ═════════════════════════════════════════════════════════════════════════════
# OKTA CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestOktaConnector:

    def _make(self, tenant_id: str = "acme") -> OktaConnector:
        return OktaConnector(_okta_creds(tenant_id))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make()
        resp = _mock_response(200, [{"id": "u1", "status": "ACTIVE"}])
        with patch.object(conn._http_client, "get", return_value=resp):
            assert conn.authenticate() is True
        assert conn._api_token == "ssws-token-abc123"
        assert conn._org_domain == "acmecorp"

    def test_authenticate_sets_domain(self):
        conn = self._make()
        resp = _mock_response(200, [])
        with patch.object(conn._http_client, "get", return_value=resp):
            conn.authenticate()
        assert conn._org_domain == "acmecorp"

    def test_authenticate_missing_api_token_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="okta", tenant_id="t",
            auth_data={"org_domain": "acme"},  # no api_token
        )
        conn = OktaConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_org_domain_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="okta", tenant_id="t",
            auth_data={"api_token": "tok"},  # no org_domain
        )
        conn = OktaConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_401_returns_false(self):
        conn = self._make()
        with patch.object(conn._http_client, "get", return_value=_mock_response(401)):
            assert conn.authenticate() is False

    def test_headers_use_ssws_prefix(self):
        """Okta requires 'SSWS {token}' not 'Bearer {token}'."""
        conn = self._make()
        conn._api_token = "my-token"
        headers = conn._headers()
        assert headers["Authorization"] == "SSWS my-token"

    def test_base_url_uses_org_domain(self):
        conn = self._make()
        conn._org_domain = "acmecorp"
        assert "acmecorp.okta.com" in conn._base_url()

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_three_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"user", "app_user", "group"}

    def test_discover_schema_user_has_status_field(self):
        schema = self._make().discover_schema()
        user = next(s for s in schema if s.entity_type == "user")
        assert "status" in user.fields
        assert "profile.email" in user.fields
        assert "profile.employeeNumber" in user.fields

    def test_discover_schema_app_user_has_app_name(self):
        schema = self._make().discover_schema()
        app_user = next(s for s in schema if s.entity_type == "app_user")
        assert "appName" in app_user.fields
        assert "userId" in app_user.fields

    def test_discover_schema_user_supports_incremental(self):
        schema = self._make().discover_schema()
        user = next(s for s in schema if s.entity_type == "user")
        assert user.supports_incremental is True

    # ── Full Extraction — Users ────────────────────────────────────────────

    def test_extract_full_users_yields_raw_records(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"

        users = [
            {"id": "u1", "status": "ACTIVE",
             "profile": {"firstName": "Alice", "lastName": "Smith",
                         "email": "alice@acme.com", "login": "alice@acme.com"}},
            {"id": "u2", "status": "SUSPENDED",
             "profile": {"firstName": "Bob", "lastName": "Jones",
                         "email": "bob@acme.com", "login": "bob@acme.com"}},
        ]

        with patch.object(conn, "_get_with_link_header", return_value=(users, None)):
            records = list(conn.extract_full("user"))

        assert len(records) == 2
        assert all(isinstance(r, RawRecord) for r in records)
        assert records[0].connector_id == "okta"
        assert records[0].source_id == "u1"

    def test_extract_full_sets_email_and_name_hint(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"

        users = [{
            "id": "u1", "status": "ACTIVE",
            "profile": {"firstName": "Alice", "lastName": "Smith",
                        "email": "alice@acme.com", "login": "alice@acme.com"},
        }]

        with patch.object(conn, "_get_with_link_header", return_value=(users, None)):
            records = list(conn.extract_full("user"))

        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_users_paginates_via_link_header(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"

        page1_users = [{"id": f"u{i}", "status": "ACTIVE", "profile": {}} for i in range(200)]
        page2_users = [{"id": f"u{i}", "status": "ACTIVE", "profile": {}} for i in range(200, 350)]
        pages = [(page1_users, "https://acmecorp.okta.com/api/v1/users?after=cursor2"),
                 (page2_users, None)]
        call_idx = 0

        def mock_get_link(url, params=None):
            nonlocal call_idx
            result = pages[call_idx]
            call_idx += 1
            return result

        with patch.object(conn, "_get_with_link_header", side_effect=mock_get_link):
            records = list(conn.extract_full("user"))

        assert len(records) == 350

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="Okta"):
            list(conn.extract_full("ticket"))

    # ── Full Extraction — App Users ────────────────────────────────────────

    def test_extract_full_app_users_fetches_per_user_app_links(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"

        users = [{"id": "u1", "status": "ACTIVE", "profile": {}}]
        app_links = [
            {"appName": "salesforce", "appInstanceId": "app1", "label": "Salesforce",
             "id": "link1", "created": "2025-01-01"},
        ]

        def mock_get_link(url, params=None):
            return (users, None)

        with patch.object(conn, "_get_with_link_header", side_effect=mock_get_link):
            with patch.object(conn, "_get", return_value=app_links):
                records = list(conn.extract_full("app_user"))

        assert len(records) == 1
        assert records[0].entity_type == "app_user"
        assert records[0].payload["userId"] == "u1"
        assert records[0].payload["appName"] == "salesforce"

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_passes_filter_to_okta(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"
        captured_params = {}

        def mock_get_link(url, params=None):
            if params:
                captured_params.update(params)
            return ([], None)

        cursor = _cursor("okta", "user")
        with patch.object(conn, "_get_with_link_header", side_effect=mock_get_link):
            gen, _ = conn.extract_incremental("user", cursor)
            list(gen)

        assert "filter" in captured_params
        assert "lastUpdated" in captured_params["filter"]
        assert "2026-01-01" in captured_params["filter"]

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"
        cursor = _cursor("okta", "user")

        with patch.object(conn, "_get_with_link_header", return_value=([], None)):
            gen, new_cursor = conn.extract_incremental("user", cursor)
            list(gen)

        assert new_cursor.connector_id == "okta"
        assert new_cursor.entity_type == "user"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at
        assert "since" in new_cursor.checkpoint

    def test_extract_incremental_unsupported_entity_raises(self):
        conn = self._make()
        cursor = _cursor("okta", "device")
        with pytest.raises(ValueError):
            conn.extract_incremental("device", cursor)

    # ── Link Header Parsing ────────────────────────────────────────────────

    def test_get_with_link_header_parses_next_url(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"

        mock_resp = _mock_response(200, [{"id": "u1"}], headers={
            "Link": '<https://acmecorp.okta.com/api/v1/users?after=abc>; rel="next", '
                    '<https://acmecorp.okta.com/api/v1/users>; rel="self"'
        })
        with patch.object(conn._http_client, "get", return_value=mock_resp):
            data, next_url = conn._get_with_link_header(
                "https://acmecorp.okta.com/api/v1/users"
            )

        assert len(data) == 1
        assert next_url == "https://acmecorp.okta.com/api/v1/users?after=abc"

    def test_get_with_link_header_returns_none_when_no_next(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"

        mock_resp = _mock_response(200, [{"id": "u1"}], headers={
            "Link": '<https://acmecorp.okta.com/api/v1/users>; rel="self"'
        })
        with patch.object(conn._http_client, "get", return_value=mock_resp):
            _, next_url = conn._get_with_link_header(
                "https://acmecorp.okta.com/api/v1/users"
            )

        assert next_url is None

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"
        resp = _mock_response(200, [{"id": "u1"}])
        with patch.object(conn._http_client, "get", return_value=resp):
            health = conn.health_check()
        assert health.is_healthy is True
        assert health.connector_id == "okta"

    def test_health_check_unhealthy(self):
        conn = self._make()
        conn._api_token = "tok"
        conn._org_domain = "acmecorp"
        with patch.object(conn._http_client, "get", side_effect=Exception("timeout")):
            health = conn.health_check()
        assert health.is_healthy is False


# ═════════════════════════════════════════════════════════════════════════════
# AZURE AD CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestAzureADConnector:

    def _make(self, tenant_id: str = "acme") -> AzureADConnector:
        return AzureADConnector(_azure_creds(tenant_id))

    # ── Authentication ─────────────────────────────────────────────────────

    def test_authenticate_success(self):
        conn = self._make()
        token_resp = _mock_response(200, {"access_token": "bearer-xyz", "expires_in": 3600})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            assert conn.authenticate() is True
        assert conn._access_token == "bearer-xyz"
        assert conn._aad_tenant_id == "aad-tenant-guid-123"

    def test_authenticate_missing_tenant_id_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="azure_ad", tenant_id="t",
            auth_data={"client_id": "cid", "client_secret": "csec"},
        )
        conn = AzureADConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_missing_client_id_returns_false(self):
        creds = ConnectorCredentials(
            connector_id="azure_ad", tenant_id="t",
            auth_data={"tenant_id": "tid", "client_secret": "csec"},
        )
        conn = AzureADConnector(creds)
        assert conn.authenticate() is False

    def test_authenticate_http_error_returns_false(self):
        conn = self._make()
        with patch.object(conn._http_client, "post", return_value=_mock_response(401)):
            assert conn.authenticate() is False

    def test_authenticate_empty_token_returns_false(self):
        conn = self._make()
        # Response OK but no access_token
        token_resp = _mock_response(200, {"token_type": "Bearer"})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            assert conn.authenticate() is False

    def test_headers_use_bearer_prefix(self):
        conn = self._make()
        conn._access_token = "my-token"
        headers = conn._headers()
        assert headers["Authorization"] == "Bearer my-token"

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_three_entity_types(self):
        schema = self._make().discover_schema()
        types = {s.entity_type for s in schema}
        assert types == {"user", "app_assignment", "group"}

    def test_discover_schema_user_has_account_enabled(self):
        schema = self._make().discover_schema()
        user = next(s for s in schema if s.entity_type == "user")
        assert "accountEnabled" in user.fields
        assert "employeeId" in user.fields
        assert "userPrincipalName" in user.fields

    def test_discover_schema_user_supports_incremental(self):
        schema = self._make().discover_schema()
        user = next(s for s in schema if s.entity_type == "user")
        assert user.supports_incremental is True

    def test_discover_schema_app_assignment_has_resource_display_name(self):
        schema = self._make().discover_schema()
        app = next(s for s in schema if s.entity_type == "app_assignment")
        assert "resourceDisplayName" in app.fields

    # ── Full Extraction — Users ────────────────────────────────────────────

    def test_extract_full_users_yields_raw_records(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "tenant123"

        page = {
            "value": [
                {"id": "aad-u1", "userPrincipalName": "alice@acme.com",
                 "displayName": "Alice Smith", "givenName": "Alice", "surname": "Smith",
                 "mail": "alice@acme.com", "accountEnabled": True},
                {"id": "aad-u2", "userPrincipalName": "bob@acme.com",
                 "displayName": "Bob Jones", "givenName": "Bob", "surname": "Jones",
                 "mail": "bob@acme.com", "accountEnabled": False},
            ]
        }

        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("user"))

        assert len(records) == 2
        assert records[0].connector_id == "azure_ad"
        assert records[0].source_id == "aad-u1"
        assert records[1].payload["accountEnabled"] is False  # deactivated user

    def test_extract_full_sets_email_and_name_hint(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"

        page = {
            "value": [{
                "id": "aad-u1", "givenName": "Alice", "surname": "Smith",
                "mail": "alice@acme.com", "userPrincipalName": "alice@acme.com",
                "accountEnabled": True,
            }]
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("user"))

        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_follows_odata_next_link(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"

        users_a = [{"id": f"u{i}", "givenName": "A", "surname": "B"} for i in range(999)]
        users_b = [{"id": f"u{i}", "givenName": "C", "surname": "D"} for i in range(999, 1250)]

        page1 = {
            "value": users_a,
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/users?$skiptoken=abc",
        }
        page2 = {"value": users_b}
        pages = [page1, page2]
        idx = 0

        def mock_get(url, **kwargs):
            nonlocal idx
            result = pages[idx]
            idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("user"))

        assert len(records) == 1250

    def test_extract_full_unsupported_entity_raises(self):
        conn = self._make()
        with pytest.raises(ValueError, match="AzureAD"):
            list(conn.extract_full("device"))

    # ── Full Extraction — App Assignments ─────────────────────────────────

    def test_extract_full_app_assignments_fetches_per_user(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"

        users_page = {
            "value": [{"id": "aad-u1", "userPrincipalName": "alice@acme.com",
                        "displayName": "Alice", "accountEnabled": True}]
        }
        assignments = {
            "value": [
                {"id": "assign1", "appRoleId": "role1",
                 "resourceDisplayName": "Salesforce", "createdDateTime": "2025-01-01"},
            ]
        }

        pages = [users_page, assignments]
        idx = 0

        def mock_get(url, **kwargs):
            nonlocal idx
            result = pages[idx]
            idx += 1
            return result

        with patch.object(conn, "_get", side_effect=mock_get):
            records = list(conn.extract_full("app_assignment"))

        assert len(records) == 1
        assert records[0].entity_type == "app_assignment"
        assert records[0].payload["userId"] == "aad-u1"
        assert records[0].name_hint == "Salesforce"

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_passes_filter(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"
        captured_params = {}

        def mock_get(url, params=None, **kwargs):
            if params:
                captured_params.update(params)
            return {"value": []}

        cursor = _cursor("azure_ad", "user")
        with patch.object(conn, "_get", side_effect=mock_get):
            gen, _ = conn.extract_incremental("user", cursor)
            list(gen)

        assert "$filter" in captured_params
        assert "lastModifiedDateTime" in captured_params["$filter"]
        assert "2026-01-01" in captured_params["$filter"]

    def test_extract_incremental_returns_updated_cursor(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"
        cursor = _cursor("azure_ad", "user")

        with patch.object(conn, "_get", return_value={"value": []}):
            gen, new_cursor = conn.extract_incremental("user", cursor)
            list(gen)

        assert new_cursor.connector_id == "azure_ad"
        assert new_cursor.last_extracted_at > cursor.last_extracted_at

    def test_extract_incremental_unsupported_entity_raises(self):
        conn = self._make()
        cursor = _cursor("azure_ad", "license")
        with pytest.raises(ValueError):
            conn.extract_incremental("license", cursor)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_healthy(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"
        with patch.object(conn, "_get", return_value={"value": [{"id": "u1"}]}):
            health = conn.health_check()
        assert health.is_healthy is True
        assert health.connector_id == "azure_ad"

    def test_health_check_unhealthy(self):
        conn = self._make()
        conn._access_token = "tok"
        conn._aad_tenant_id = "t"
        with patch.object(conn, "_get", side_effect=Exception("network error")):
            health = conn.health_check()
        assert health.is_healthy is False
        assert "network error" in health.error_message


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-CONNECTOR TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestCrossConnectorSprint31:
    """Verify all Sprint 31 connectors satisfy the ConnectorBase contract."""

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (OktaConnector, _okta_creds),
        (AzureADConnector, _azure_creds),
    ])
    def test_connector_id_is_set(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert isinstance(conn.CONNECTOR_ID, str)
        assert len(conn.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (OktaConnector, _okta_creds),
        (AzureADConnector, _azure_creds),
    ])
    def test_display_name_contains_production(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert "Production" in conn.DISPLAY_NAME

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (OktaConnector, _okta_creds),
        (AzureADConnector, _azure_creds),
    ])
    def test_category_is_identity(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        assert conn.CATEGORY == ConnectorCategory.IDENTITY

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (OktaConnector, _okta_creds),
        (AzureADConnector, _azure_creds),
    ])
    def test_discover_schema_returns_list(self, connector_class, creds_fn):
        conn = connector_class(creds_fn())
        schema = conn.discover_schema()
        assert isinstance(schema, list)
        assert len(schema) >= 1

    @pytest.mark.parametrize("connector_class,creds_fn", [
        (OktaConnector, _okta_creds),
        (AzureADConnector, _azure_creds),
    ])
    def test_tenant_id_preserved(self, connector_class, creds_fn):
        conn = connector_class(creds_fn("portfolio-co-7"))
        assert conn.tenant_id == "portfolio-co-7"
