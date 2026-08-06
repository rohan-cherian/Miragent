"""
tests/connectors/test_oauth2_and_enrichment.py — Sprint 47

Covers the pure-logic (no-HTTP) surface of two previously untested modules:

  scout/connectors/oauth2.py:
    - OAuth2Token dataclass: default fields, is_expired() state machine
    - OAuth2AuthorizationCode.get_valid_token(): passthrough when valid,
      ValueError when token is expired with no refresh_token
    - build_auth_url(): query string construction

  scout/connectors/enrichment.py (ClearbitConnector + ZoomInfoConnector):
    - Class-level metadata (CONNECTOR_ID, DISPLAY_NAME, CATEGORY, CALLS_PER_SECOND)
    - discover_schema(): pure in-memory, no HTTP
    - extract_full(): yields nothing (enrichment connectors are point-lookup only)
    - extract_incremental(): returns empty iterator + valid cursor (no HTTP)
    - authenticate() fast-path when credentials are absent → returns False immediately

All tests run with NO external dependencies.
"""

import time
from datetime import datetime, timezone

import pytest

from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ExtractionCursor,
    RawRecord,
)
from scout.connectors.oauth2 import (
    OAuth2AuthorizationCode,
    OAuth2ClientCredentials,
    OAuth2Token,
    build_auth_url,
)
from scout.connectors.enrichment import ClearbitConnector, ZoomInfoConnector


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _clearbit_creds(api_key: str = "sk-test-key") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="clearbit",
        tenant_id="test-tenant",
        auth_data={"api_key": api_key},
    )


def _zoominfo_creds(username: str = "user@test.com", password: str = "pw") -> ConnectorCredentials:
    return ConnectorCredentials(
        connector_id="zoominfo",
        tenant_id="test-tenant",
        auth_data={"username": username, "password": password},
    )


# ─────────────────────────────────────────────────────────────────────────────
# OAuth2Token — DATACLASS AND is_expired()
# ─────────────────────────────────────────────────────────────────────────────

class TestOAuth2Token:

    def test_default_token_type_is_bearer(self):
        t = OAuth2Token(access_token="tok")
        assert t.token_type == "Bearer"

    def test_default_refresh_token_is_none(self):
        t = OAuth2Token(access_token="tok")
        assert t.refresh_token is None

    def test_default_expires_at_is_zero(self):
        t = OAuth2Token(access_token="tok")
        assert t.expires_at == 0.0

    def test_access_token_stored(self):
        t = OAuth2Token(access_token="abc-xyz")
        assert t.access_token == "abc-xyz"

    def test_is_expired_when_expires_at_zero(self):
        """expires_at = 0.0 (never set) must be treated as expired."""
        t = OAuth2Token(access_token="tok", expires_at=0.0)
        assert t.is_expired() is True

    def test_is_expired_false_for_far_future(self):
        """Token expiring in 1 hour must not be expired."""
        t = OAuth2Token(access_token="tok", expires_at=time.time() + 3600)
        assert t.is_expired() is False

    def test_is_expired_true_when_already_expired(self):
        """Token expired 10 minutes ago must be expired."""
        t = OAuth2Token(access_token="tok", expires_at=time.time() - 600)
        assert t.is_expired() is True

    def test_is_expired_within_60_second_buffer(self):
        """Token expiring in 30 seconds is within the 60-second safety buffer."""
        t = OAuth2Token(access_token="tok", expires_at=time.time() + 30)
        assert t.is_expired() is True

    def test_is_expired_just_outside_buffer(self):
        """Token expiring in 90 seconds is outside the 60-second buffer — still valid."""
        t = OAuth2Token(access_token="tok", expires_at=time.time() + 90)
        assert t.is_expired() is False

    def test_refresh_token_stored(self):
        t = OAuth2Token(access_token="tok", refresh_token="refresh-123")
        assert t.refresh_token == "refresh-123"

    def test_custom_token_type(self):
        t = OAuth2Token(access_token="tok", token_type="MAC")
        assert t.token_type == "MAC"

    def test_expired_token_with_future_set_to_exactly_60s(self):
        """Exactly 60 seconds: time.time() >= expires_at - 60 → True."""
        t = OAuth2Token(access_token="tok", expires_at=time.time() + 60)
        # At exactly 60s: time.time() >= expires_at - 60 ≈ time.time(), so True
        assert t.is_expired() is True


# ─────────────────────────────────────────────────────────────────────────────
# build_auth_url()
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildAuthUrl:

    def _url(self, **overrides) -> str:
        kwargs = dict(
            auth_url="https://login.salesforce.com/services/oauth2/authorize",
            client_id="3MVG9abc",
            redirect_uri="https://scout.example.com/oauth/callback",
            scope="api refresh_token",
            state="csrf-state-xyz",
        )
        kwargs.update(overrides)
        return build_auth_url(**kwargs)

    def test_returns_string(self):
        assert isinstance(self._url(), str)

    def test_starts_with_auth_url(self):
        url = self._url()
        assert url.startswith("https://login.salesforce.com/services/oauth2/authorize")

    def test_contains_response_type_code(self):
        url = self._url()
        assert "response_type=code" in url

    def test_contains_client_id(self):
        url = self._url(client_id="3MVG9testclient")
        assert "3MVG9testclient" in url

    def test_contains_redirect_uri(self):
        url = self._url()
        assert "redirect_uri=" in url

    def test_contains_scope(self):
        url = self._url(scope="api offline_access")
        assert "api" in url or "scope=" in url

    def test_contains_state(self):
        url = self._url(state="mycsrftoken42")
        assert "mycsrftoken42" in url

    def test_contains_question_mark_separator(self):
        url = self._url()
        assert "?" in url

    def test_different_states_produce_different_urls(self):
        url1 = self._url(state="state-aaa")
        url2 = self._url(state="state-bbb")
        assert url1 != url2

    def test_different_auth_urls_produce_different_results(self):
        url1 = self._url(auth_url="https://login.salesforce.com/authorize")
        url2 = self._url(auth_url="https://accounts.google.com/o/oauth2/auth")
        assert url1 != url2


# ─────────────────────────────────────────────────────────────────────────────
# OAuth2AuthorizationCode — pure-logic paths (no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestOAuth2AuthorizationCodePureLogic:

    def _flow(self) -> OAuth2AuthorizationCode:
        return OAuth2AuthorizationCode(
            token_url="https://login.salesforce.com/services/oauth2/token",
            client_id="client-abc",
            client_secret="secret-xyz",
            redirect_uri="https://scout.example.com/callback",
        )

    def test_get_valid_token_returns_existing_when_not_expired(self):
        """If the stored token is still valid, no HTTP call is made."""
        flow = self._flow()
        valid_token = OAuth2Token(
            access_token="valid-access",
            refresh_token="refresh-abc",
            expires_at=time.time() + 3600,
        )
        access_str, returned_token = flow.get_valid_token(valid_token)
        assert access_str == "valid-access"
        assert returned_token is valid_token  # same object — no refresh happened

    def test_get_valid_token_raises_when_expired_no_refresh_token(self):
        """Expired token + no refresh_token → ValueError (no HTTP attempted)."""
        flow = self._flow()
        expired_token = OAuth2Token(
            access_token="expired-access",
            refresh_token=None,
            expires_at=time.time() - 600,  # expired 10 minutes ago
        )
        with pytest.raises(ValueError, match="refresh_token"):
            flow.get_valid_token(expired_token)

    def test_get_valid_token_raises_when_unset_expires_no_refresh(self):
        """expires_at=0.0 (never set) + no refresh_token → ValueError."""
        flow = self._flow()
        never_set_token = OAuth2Token(
            access_token="tok",
            refresh_token=None,
            expires_at=0.0,
        )
        with pytest.raises(ValueError):
            flow.get_valid_token(never_set_token)


# ─────────────────────────────────────────────────────────────────────────────
# OAuth2ClientCredentials — class structure (no HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestOAuth2ClientCredentials:

    def test_can_be_instantiated(self):
        cc = OAuth2ClientCredentials(
            token_url="https://auth.example.com/token",
            client_id="id-123",
            client_secret="secret-456",
        )
        assert cc is not None

    def test_scope_defaults_to_empty_string(self):
        cc = OAuth2ClientCredentials(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
        )
        assert cc._scope == ""

    def test_custom_scope_stored(self):
        cc = OAuth2ClientCredentials(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
            scope="read write",
        )
        assert cc._scope == "read write"

    def test_has_threading_lock(self):
        """Thread-safety: the instance must hold a threading.Lock."""
        import threading
        cc = OAuth2ClientCredentials(
            token_url="https://auth.example.com/token",
            client_id="id",
            client_secret="secret",
        )
        assert isinstance(cc._lock, type(threading.Lock()))


# ─────────────────────────────────────────────────────────────────────────────
# ClearbitConnector — pure-logic surface
# ─────────────────────────────────────────────────────────────────────────────

class TestClearbitConnectorMetadata:

    def test_connector_id(self):
        c = ClearbitConnector(_clearbit_creds())
        assert c.CONNECTOR_ID == "clearbit"

    def test_display_name_nonempty(self):
        c = ClearbitConnector(_clearbit_creds())
        assert isinstance(c.DISPLAY_NAME, str) and len(c.DISPLAY_NAME) > 0

    def test_category_is_connector_category(self):
        c = ClearbitConnector(_clearbit_creds())
        assert isinstance(c.CATEGORY, ConnectorCategory)

    def test_calls_per_second_positive(self):
        c = ClearbitConnector(_clearbit_creds())
        assert c.CALLS_PER_SECOND > 0

    def test_tenant_id_stored(self):
        c = ClearbitConnector(_clearbit_creds())
        assert c.tenant_id == "test-tenant"


class TestClearbitConnectorSchema:

    def test_discover_schema_returns_list(self):
        c = ClearbitConnector(_clearbit_creds())
        schema = c.discover_schema()
        assert isinstance(schema, list)

    def test_discover_schema_nonempty(self):
        c = ClearbitConnector(_clearbit_creds())
        assert len(c.discover_schema()) >= 1

    def test_company_enrichment_entity_present(self):
        c = ClearbitConnector(_clearbit_creds())
        types = [s.entity_type for s in c.discover_schema()]
        assert "company_enrichment" in types

    def test_person_enrichment_entity_present(self):
        c = ClearbitConnector(_clearbit_creds())
        types = [s.entity_type for s in c.discover_schema()]
        assert "person_enrichment" in types

    def test_schema_entries_have_display_name(self):
        c = ClearbitConnector(_clearbit_creds())
        for s in c.discover_schema():
            assert isinstance(s.display_name, str) and len(s.display_name) > 0


class TestClearbitConnectorExtraction:

    def test_extract_full_returns_empty_generator(self):
        c = ClearbitConnector(_clearbit_creds())
        records = list(c.extract_full("company_enrichment"))
        assert records == []

    def test_extract_full_does_not_raise(self):
        c = ClearbitConnector(_clearbit_creds())
        list(c.extract_full("person_enrichment"))  # no exception

    def test_extract_incremental_returns_tuple(self):
        c = ClearbitConnector(_clearbit_creds())
        cursor = ExtractionCursor(
            connector_id="clearbit",
            entity_type="company_enrichment",
            last_extracted_at=datetime.now(timezone.utc),
        )
        result = c.extract_incremental("company_enrichment", cursor)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_extract_incremental_iterator_is_empty(self):
        c = ClearbitConnector(_clearbit_creds())
        cursor = ExtractionCursor(
            connector_id="clearbit",
            entity_type="company_enrichment",
            last_extracted_at=datetime.now(timezone.utc),
        )
        records_iter, _ = c.extract_incremental("company_enrichment", cursor)
        assert list(records_iter) == []

    def test_extract_incremental_cursor_has_correct_connector_id(self):
        c = ClearbitConnector(_clearbit_creds())
        cursor = ExtractionCursor(
            connector_id="clearbit",
            entity_type="company_enrichment",
            last_extracted_at=datetime.now(timezone.utc),
        )
        _, new_cursor = c.extract_incremental("company_enrichment", cursor)
        assert new_cursor.connector_id == "clearbit"


class TestClearbitConnectorAuthFastPath:

    def test_authenticate_returns_false_when_api_key_missing(self):
        """Empty api_key → fast-path False, no HTTP attempted."""
        c = ClearbitConnector(_clearbit_creds(api_key=""))
        result = c.authenticate()
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# ZoomInfoConnector — pure-logic surface
# ─────────────────────────────────────────────────────────────────────────────

class TestZoomInfoConnectorMetadata:

    def test_connector_id(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        assert c.CONNECTOR_ID == "zoominfo"

    def test_display_name_nonempty(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        assert isinstance(c.DISPLAY_NAME, str) and len(c.DISPLAY_NAME) > 0

    def test_category_is_connector_category(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        assert isinstance(c.CATEGORY, ConnectorCategory)

    def test_calls_per_second_positive(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        assert c.CALLS_PER_SECOND > 0


class TestZoomInfoConnectorSchema:

    def test_discover_schema_returns_list(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        assert isinstance(c.discover_schema(), list)

    def test_company_intelligence_entity_present(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        types = [s.entity_type for s in c.discover_schema()]
        assert "company_intelligence" in types

    def test_contact_intelligence_entity_present(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        types = [s.entity_type for s in c.discover_schema()]
        assert "contact_intelligence" in types

    def test_schema_entries_have_fields(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        for s in c.discover_schema():
            assert isinstance(s.fields, list)
            assert len(s.fields) > 0


class TestZoomInfoConnectorExtraction:

    def test_extract_full_returns_empty_generator(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        records = list(c.extract_full("company_intelligence"))
        assert records == []

    def test_extract_full_does_not_raise(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        list(c.extract_full("contact_intelligence"))  # no exception

    def test_extract_incremental_returns_empty_iterator(self):
        c = ZoomInfoConnector(_zoominfo_creds())
        cursor = ExtractionCursor(
            connector_id="zoominfo",
            entity_type="company_intelligence",
            last_extracted_at=datetime.now(timezone.utc),
        )
        records_iter, new_cursor = c.extract_incremental("company_intelligence", cursor)
        assert list(records_iter) == []
        assert new_cursor.connector_id == "zoominfo"


class TestZoomInfoConnectorAuthFastPath:

    def test_authenticate_returns_false_when_username_missing(self):
        """Empty username → fast-path False, no HTTP attempted."""
        c = ZoomInfoConnector(_zoominfo_creds(username="", password="pw"))
        result = c.authenticate()
        assert result is False

    def test_authenticate_returns_false_when_password_missing(self):
        """Empty password → fast-path False, no HTTP attempted."""
        c = ZoomInfoConnector(_zoominfo_creds(username="user@x.com", password=""))
        result = c.authenticate()
        assert result is False

    def test_authenticate_returns_false_when_both_missing(self):
        c = ZoomInfoConnector(_zoominfo_creds(username="", password=""))
        result = c.authenticate()
        assert result is False
