"""
tests/test_connectors_sprint34.py — Sprint 34 connector tests

Covers:
  - ServiceNowConnector  (ServiceNow ITSM)
  - JiraConnector        (Atlassian Jira)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("USE_MOCK_CONNECTORS", "false")

from scout.connectors.jira import JiraConnector
from scout.connectors.models import ConnectorCredentials, ExtractionCursor
from scout.connectors.servicenow import ServiceNowConnector


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
# Registry / class attribute checks
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistrySprint34:
    def test_servicenow_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "servicenow" in CONNECTOR_REGISTRY

    def test_jira_in_registry(self):
        from scout.connectors.registry import CONNECTOR_REGISTRY
        assert "jira" in CONNECTOR_REGISTRY

    def test_servicenow_connector_id(self):
        assert ServiceNowConnector.CONNECTOR_ID == "servicenow"

    def test_jira_connector_id(self):
        assert JiraConnector.CONNECTOR_ID == "jira"

    def test_servicenow_category(self):
        from scout.connectors.models import ConnectorCategory
        assert ServiceNowConnector.CATEGORY == ConnectorCategory.ITSM

    def test_jira_category(self):
        from scout.connectors.models import ConnectorCategory
        assert JiraConnector.CATEGORY == ConnectorCategory.ITSM


# ─────────────────────────────────────────────────────────────────────────────
# ServiceNowConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestServiceNowConnector:

    def _make_conn(self, auth_mode="basic") -> ServiceNowConnector:
        kwargs = {"auth_mode": auth_mode, "instance": "acme"}
        if auth_mode in ("basic", "oauth2"):
            kwargs["username"] = "svc-acct"
            kwargs["password"] = "s3cr3t"
        if auth_mode == "oauth2":
            kwargs["client_id"] = "sn-client-id"
            kwargs["client_secret"] = "sn-secret"
        return ServiceNowConnector(_creds("servicenow", **kwargs))

    # ── Authentication — Basic ─────────────────────────────────────────────

    def test_authenticate_basic_success(self):
        conn = self._make_conn("basic")
        validation = _mock_http(200, {"result": []})
        with patch.object(conn._http_client, "get", return_value=validation):
            result = conn.authenticate()
        assert result is True
        assert "Basic " in conn._auth_header
        assert conn._base_url == "https://acme.service-now.com"

    def test_authenticate_basic_credentials_are_base64(self):
        import base64
        conn = self._make_conn("basic")
        validation = _mock_http(200, {"result": []})
        with patch.object(conn._http_client, "get", return_value=validation):
            conn.authenticate()
        # Decode and verify
        encoded = conn._auth_header.replace("Basic ", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "svc-acct:s3cr3t"

    def test_authenticate_basic_missing_instance_returns_false(self):
        conn = ServiceNowConnector(_creds("servicenow", username="u", password="p"))
        assert conn.authenticate() is False

    def test_authenticate_basic_missing_password_returns_false(self):
        conn = ServiceNowConnector(_creds("servicenow", instance="acme", username="u"))
        assert conn.authenticate() is False

    def test_authenticate_basic_http_error_returns_false(self):
        conn = self._make_conn("basic")
        err = _mock_http(401)
        with patch.object(conn._http_client, "get", return_value=err):
            result = conn.authenticate()
        assert result is False

    # ── Authentication — OAuth2 ────────────────────────────────────────────

    def test_authenticate_oauth2_success(self):
        conn = self._make_conn("oauth2")
        token_resp = _mock_http(200, {"access_token": "sn-tok", "expires_in": 1800})
        with patch.object(conn._http_client, "post", return_value=token_resp):
            result = conn.authenticate()
        assert result is True
        assert conn._auth_header == "Bearer sn-tok"

    def test_authenticate_oauth2_uses_password_grant(self):
        conn = self._make_conn("oauth2")
        captured = {}

        def _capture(url, **kwargs):
            captured["data"] = kwargs.get("data", {})
            return _mock_http(200, {"access_token": "t", "expires_in": 1800})

        with patch.object(conn._http_client, "post", side_effect=_capture):
            conn.authenticate()

        assert captured["data"].get("grant_type") == "password"
        assert captured["data"].get("username") == "svc-acct"

    def test_authenticate_oauth2_missing_client_id_returns_false(self):
        conn = ServiceNowConnector(
            _creds("servicenow", auth_mode="oauth2", instance="acme",
                   client_secret="s", username="u", password="p")
        )
        assert conn.authenticate() is False

    def test_authenticate_unknown_mode_returns_false(self):
        conn = ServiceNowConnector(
            _creds("servicenow", auth_mode="saml", instance="acme")
        )
        assert conn.authenticate() is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_four_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"user", "request", "incident", "change_request"}

    def test_discover_schema_all_incremental(self):
        conn = self._make_conn()
        for schema in conn.discover_schema():
            assert schema.supports_incremental is True

    # ── Entity Config ──────────────────────────────────────────────────────

    def test_entity_config_user_table(self):
        conn = self._make_conn()
        cfg = conn._entity_config("user")
        assert cfg["table"] == "sys_user"

    def test_entity_config_incident_table(self):
        conn = self._make_conn()
        cfg = conn._entity_config("incident")
        assert cfg["table"] == "incident"

    def test_entity_config_change_request_table(self):
        conn = self._make_conn()
        cfg = conn._entity_config("change_request")
        assert cfg["table"] == "change_request"

    def test_entity_config_unknown_raises(self):
        conn = self._make_conn()
        with pytest.raises(ValueError, match="ServiceNow"):
            conn._entity_config("purchase_order")

    # ── Full Extraction ────────────────────────────────────────────────────

    def test_extract_full_users_single_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        page = {
            "result": [
                {"sys_id": "u1", "user_name": "alice", "email": "alice@acme.com",
                 "first_name": "Alice", "last_name": "Smith"},
                {"sys_id": "u2", "user_name": "bob", "email": "bob@acme.com",
                 "first_name": "Bob", "last_name": "Jones"},
            ]
        }
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("user"))

        assert len(records) == 2
        assert records[0].source_id == "u1"
        assert records[0].email_hint == "alice@acme.com"
        assert records[0].name_hint == "Alice Smith"

    def test_extract_full_pagination_stops_when_partial_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        # Return fewer records than PAGE_SIZE → stop
        page = {"result": [{"sys_id": f"i{i}", "first_name": "", "last_name": ""} for i in range(5)]}
        with patch.object(conn, "_get", return_value=page):
            records = list(conn.extract_full("incident"))

        assert len(records) == 5

    def test_extract_full_paginate_multiple_pages(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        from scout.connectors.servicenow import _PAGE_SIZE

        page1 = {"result": [{"sys_id": f"u{i}", "first_name": "", "last_name": ""} for i in range(_PAGE_SIZE)]}
        page2 = {"result": [{"sys_id": f"u{i}", "first_name": "", "last_name": ""} for i in range(10)]}
        responses = iter([page1, page2])

        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("user"))

        assert len(records) == _PAGE_SIZE + 10

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_sysparm_query_format(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"result": []}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("incident", _cursor("servicenow", "incident"))
            list(gen)

        query = captured_params.get("sysparm_query", "")
        assert "sys_updated_on>" in query
        assert "2026-01-01" in query

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        with patch.object(conn, "_get", return_value={"result": []}):
            gen, new_cursor = conn.extract_incremental("user", _cursor("servicenow", "user"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        with patch.object(conn, "_get", return_value={"result": [{"sys_id": "x"}]}):
            health = conn.health_check()

        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.service-now.com"

        with patch.object(conn, "_get", side_effect=Exception("timeout")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "timeout" in health.error_message

    # ── RawRecord mapping ──────────────────────────────────────────────────

    def test_to_raw_record_reference_field_as_dict(self):
        """ServiceNow reference fields come as {value, display_value} dicts."""
        conn = self._make_conn()
        record = {
            "sys_id": "req-1",
            "number": "REQ0001",
            "short_description": "Laptop request",
            "requested_for": {"value": "u123", "display_value": "Alice Smith"},
            "first_name": "",
            "last_name": "",
            "email": "",
        }
        rr = conn._to_raw_record("request", record)
        assert rr.source_id == "req-1"
        assert rr.name_hint == "Alice Smith"

    def test_to_raw_record_email_as_string(self):
        conn = self._make_conn()
        record = {
            "sys_id": "u-1",
            "email": "user@acme.com",
            "first_name": "John",
            "last_name": "Doe",
        }
        rr = conn._to_raw_record("user", record)
        assert rr.email_hint == "user@acme.com"
        assert rr.name_hint == "John Doe"


# ─────────────────────────────────────────────────────────────────────────────
# JiraConnector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestJiraConnector:

    def _make_conn(self, auth_mode="cloud") -> JiraConnector:
        kwargs: dict = {"auth_mode": auth_mode, "instance": "acme"}
        if auth_mode == "cloud":
            kwargs["email"] = "admin@acme.com"
            kwargs["api_token"] = "jira-api-tok"
        elif auth_mode == "server":
            kwargs["username"] = "admin"
            kwargs["api_token"] = "jira-server-pass"
        elif auth_mode == "pat":
            kwargs["token"] = "jira-pat-token"
        return JiraConnector(_creds("jira", **kwargs))

    def _myself_resp(self) -> MagicMock:
        return _mock_http(200, {"accountId": "acct-123", "displayName": "Admin"})

    # ── Authentication — Cloud ─────────────────────────────────────────────

    def test_authenticate_cloud_success(self):
        conn = self._make_conn("cloud")
        with patch.object(conn._http_client, "get", return_value=self._myself_resp()):
            result = conn.authenticate()
        assert result is True
        assert "Basic " in conn._auth_header
        assert conn._base_url == "https://acme.atlassian.net"

    def test_authenticate_cloud_encodes_email_token(self):
        import base64
        conn = self._make_conn("cloud")
        with patch.object(conn._http_client, "get", return_value=self._myself_resp()):
            conn.authenticate()
        encoded = conn._auth_header.replace("Basic ", "")
        decoded = base64.b64decode(encoded).decode()
        assert decoded == "admin@acme.com:jira-api-tok"

    def test_authenticate_cloud_missing_email_returns_false(self):
        conn = JiraConnector(_creds("jira", auth_mode="cloud", instance="acme", api_token="tok"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_cloud_missing_instance_returns_false(self):
        conn = JiraConnector(_creds("jira", auth_mode="cloud", email="e@e.com", api_token="tok"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_cloud_http_error_returns_false(self):
        conn = self._make_conn("cloud")
        err = _mock_http(401)
        with patch.object(conn._http_client, "get", return_value=err):
            result = conn.authenticate()
        assert result is False

    # ── Authentication — Server ────────────────────────────────────────────

    def test_authenticate_server_success(self):
        conn = self._make_conn("server")
        with patch.object(conn._http_client, "get", return_value=self._myself_resp()):
            result = conn.authenticate()
        assert result is True
        assert conn._base_url == "https://acme"

    def test_authenticate_server_missing_username_returns_false(self):
        conn = JiraConnector(
            _creds("jira", auth_mode="server", instance="acme", api_token="tok")
        )
        result = conn.authenticate()
        assert result is False

    # ── Authentication — PAT ───────────────────────────────────────────────

    def test_authenticate_pat_success(self):
        conn = self._make_conn("pat")
        with patch.object(conn._http_client, "get", return_value=self._myself_resp()):
            result = conn.authenticate()
        assert result is True
        assert conn._auth_header == "Bearer jira-pat-token"

    def test_authenticate_pat_missing_token_returns_false(self):
        conn = JiraConnector(_creds("jira", auth_mode="pat", instance="acme"))
        result = conn.authenticate()
        assert result is False

    def test_authenticate_unknown_mode_returns_false(self):
        conn = JiraConnector(_creds("jira", auth_mode="oauth3", instance="acme"))
        result = conn.authenticate()
        assert result is False

    # ── Schema Discovery ───────────────────────────────────────────────────

    def test_discover_schema_has_three_entities(self):
        conn = self._make_conn()
        schemas = conn.discover_schema()
        assert {s.entity_type for s in schemas} == {"issue", "project", "user"}

    def test_discover_schema_issue_supports_incremental(self):
        conn = self._make_conn()
        issue_schema = next(s for s in conn.discover_schema() if s.entity_type == "issue")
        assert issue_schema.supports_incremental is True

    def test_discover_schema_project_no_incremental(self):
        conn = self._make_conn()
        project_schema = next(s for s in conn.discover_schema() if s.entity_type == "project")
        assert project_schema.supports_incremental is False

    # ── Full Extraction — Issues ───────────────────────────────────────────

    def test_extract_full_issues_single_page(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        resp = {
            "issues": [
                {"id": "10001", "key": "PROJ-1", "fields": {
                    "summary": "Bug fix",
                    "assignee": {"emailAddress": "dev@acme.com", "displayName": "Dev One"},
                }},
                {"id": "10002", "key": "PROJ-2", "fields": {
                    "summary": "New feature",
                    "assignee": None,
                    "reporter": {"emailAddress": "pm@acme.com", "displayName": "PM One"},
                }},
            ],
            "startAt": 0,
            "maxResults": 100,
            "total": 2,
        }
        with patch.object(conn, "_get", return_value=resp):
            records = list(conn.extract_full("issue"))

        assert len(records) == 2
        assert records[0].source_id == "10001"
        assert records[0].email_hint == "dev@acme.com"
        assert records[0].name_hint == "Dev One"

    def test_extract_full_issues_pagination_by_total(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        page1 = {
            "issues": [{"id": f"{i}", "key": f"P-{i}", "fields": {}} for i in range(100)],
            "startAt": 0, "maxResults": 100, "total": 150,
        }
        page2 = {
            "issues": [{"id": f"{i}", "key": f"P-{i}", "fields": {}} for i in range(100, 150)],
            "startAt": 100, "maxResults": 100, "total": 150,
        }
        responses = iter([page1, page2])
        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("issue"))

        assert len(records) == 150

    def test_extract_full_issues_stops_at_total(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        resp = {
            "issues": [{"id": "1", "key": "P-1", "fields": {}}],
            "startAt": 0, "maxResults": 100, "total": 1,
        }
        with patch.object(conn, "_get", return_value=resp):
            records = list(conn.extract_full("issue"))
        assert len(records) == 1

    # ── Full Extraction — Projects ─────────────────────────────────────────

    def test_extract_full_projects(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        resp = {
            "values": [
                {"id": "10000", "key": "PROJ", "name": "Main Project", "lead": {}},
                {"id": "10001", "key": "OPS", "name": "Ops Project", "lead": {}},
            ]
        }
        with patch.object(conn, "_get", return_value=resp):
            records = list(conn.extract_full("project"))

        assert len(records) == 2
        assert records[0].source_id == "10000"
        assert records[0].name_hint == "Main Project"

    def test_extract_full_projects_fallback_to_projects_key(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        # Older Jira returns "projects" key
        resp = {"projects": [{"id": "1", "key": "A", "name": "Alpha", "lead": {}}]}
        with patch.object(conn, "_get", return_value=resp):
            records = list(conn.extract_full("project"))
        assert len(records) == 1

    # ── Full Extraction — Users ────────────────────────────────────────────

    def test_extract_full_users(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        # users/search returns a list directly
        page1 = [
            {"accountId": "uid1", "displayName": "Alice", "emailAddress": "alice@acme.com", "active": True},
            {"accountId": "uid2", "displayName": "Bob", "emailAddress": "bob@acme.com", "active": True},
        ]
        with patch.object(conn, "_get", return_value=page1):
            records = list(conn.extract_full("user"))

        assert len(records) == 2
        assert records[0].source_id == "uid1"
        assert records[0].email_hint == "alice@acme.com"

    def test_extract_full_users_pagination(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        from scout.connectors.jira import _USER_PAGE_SIZE

        page1 = [{"accountId": f"u{i}", "displayName": f"User {i}"} for i in range(_USER_PAGE_SIZE)]
        page2 = [{"accountId": f"u{i}", "displayName": f"User {i}"} for i in range(5)]
        responses = iter([page1, page2])

        with patch.object(conn, "_get", side_effect=lambda url, **kw: next(responses)):
            records = list(conn.extract_full("user"))

        assert len(records) == _USER_PAGE_SIZE + 5

    def test_extract_full_unknown_entity_raises(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        with pytest.raises(ValueError, match="Jira"):
            list(conn.extract_full("sprint"))

    # ── Incremental Extraction ─────────────────────────────────────────────

    def test_extract_incremental_issues_jql_format(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        captured_params: dict = {}

        def _capture(url, **kwargs):
            captured_params.update(kwargs.get("params", {}))
            return {"issues": [], "startAt": 0, "total": 0, "maxResults": 100}

        with patch.object(conn, "_get", side_effect=_capture):
            gen, _ = conn.extract_incremental("issue", _cursor("jira", "issue"))
            list(gen)

        jql = captured_params.get("jql", "")
        assert "updated >=" in jql
        assert "2026-01-01" in jql

    def test_extract_incremental_project_falls_back_to_full(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        resp = {"values": [{"id": "1", "key": "P", "name": "Project", "lead": {}}]}
        with patch.object(conn, "_get", return_value=resp):
            gen, new_cursor = conn.extract_incremental("project", _cursor("jira", "project"))
            records = list(gen)

        assert len(records) == 1
        assert new_cursor.entity_type == "project"

    def test_extract_incremental_cursor_updated(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        with patch.object(conn, "_get", return_value={"issues": [], "startAt": 0, "total": 0, "maxResults": 100}):
            gen, new_cursor = conn.extract_incremental("issue", _cursor("jira", "issue"))
            list(gen)

        assert new_cursor.last_extracted_at > datetime(2026, 1, 1, tzinfo=timezone.utc)

    # ── Health Check ───────────────────────────────────────────────────────

    def test_health_check_success(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        with patch.object(conn, "_get", return_value={"accountId": "me"}):
            health = conn.health_check()

        assert health.is_healthy is True

    def test_health_check_failure(self):
        conn = self._make_conn()
        conn._auth_header = "Basic abc"
        conn._base_url = "https://acme.atlassian.net"

        with patch.object(conn, "_get", side_effect=Exception("network error")):
            health = conn.health_check()

        assert health.is_healthy is False
        assert "network error" in health.error_message

    # ── RawRecord mapping ──────────────────────────────────────────────────

    def test_issue_raw_record_falls_back_to_reporter_email(self):
        conn = self._make_conn()
        issue = {
            "id": "999",
            "key": "PROJ-99",
            "fields": {
                "summary": "Crash on login",
                "assignee": None,
                "reporter": {"emailAddress": "reporter@acme.com", "displayName": "Reporter"},
            },
        }
        rr = conn._issue_to_raw_record(issue)
        assert rr.email_hint == "reporter@acme.com"
        assert rr.name_hint == "Crash on login"

    def test_issue_raw_record_uses_key_as_name_fallback(self):
        conn = self._make_conn()
        issue = {"id": "1", "key": "P-1", "fields": {}}
        rr = conn._issue_to_raw_record(issue)
        assert rr.name_hint == "P-1"

    def test_user_raw_record(self):
        conn = self._make_conn()
        user = {
            "accountId": "acct-1",
            "displayName": "Dev User",
            "emailAddress": "dev@acme.com",
            "active": True,
        }
        rr = conn._user_to_raw_record(user)
        assert rr.source_id == "acct-1"
        assert rr.email_hint == "dev@acme.com"
        assert rr.name_hint == "Dev User"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-connector contract tests
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossConnectorSprint34:
    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ServiceNowConnector, {"instance": "acme", "username": "u", "password": "p"}),
        (JiraConnector, {"instance": "acme", "auth_mode": "cloud",
                         "email": "a@b.com", "api_token": "tok"}),
    ])
    def test_connector_id_is_string(self, cls, creds_kwargs):
        assert isinstance(cls.CONNECTOR_ID, str)
        assert len(cls.CONNECTOR_ID) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ServiceNowConnector, {"instance": "acme", "username": "u", "password": "p"}),
        (JiraConnector, {"instance": "acme", "auth_mode": "cloud",
                         "email": "a@b.com", "api_token": "tok"}),
    ])
    def test_discover_schema_non_empty(self, cls, creds_kwargs):
        conn = cls(_creds(cls.CONNECTOR_ID, **creds_kwargs))
        assert len(conn.discover_schema()) > 0

    @pytest.mark.parametrize("cls,creds_kwargs", [
        (ServiceNowConnector, {"instance": "acme", "username": "u", "password": "p"}),
        (JiraConnector, {"instance": "acme", "auth_mode": "cloud",
                         "email": "a@b.com", "api_token": "tok"}),
    ])
    def test_calls_per_second_positive(self, cls, creds_kwargs):
        assert cls.CALLS_PER_SECOND > 0
