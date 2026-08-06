"""
tests/shared/test_auth.py — W1-SRC-04 shared emulator auth stubs

Contract: a request with no token is rejected (HTTP 401 + vendor envelope).
"""

from __future__ import annotations

import json

import pytest

from scout.shared.auth import (
    AuthStub,
    has_token,
    parse_authorization,
    require_auth,
    unauthorized_response,
)
from scout.shared.errors import Vendor


class TestParseAuthorization:
    def test_bearer(self):
        cred = parse_authorization({"Authorization": "Bearer abc123"})
        assert cred is not None
        assert cred.scheme == "BEARER"
        assert cred.token == "abc123"

    def test_basic(self):
        cred = parse_authorization({"Authorization": "Basic dXNlcjpwYXNz"})
        assert cred is not None
        assert cred.scheme == "BASIC"
        assert cred.token == "dXNlcjpwYXNz"

    def test_ssws_okta(self):
        cred = parse_authorization({"Authorization": "SSWS okta-token"})
        assert cred is not None
        assert cred.scheme == "SSWS"
        assert cred.token == "okta-token"

    def test_missing_header(self):
        assert parse_authorization({}) is None

    def test_empty_header(self):
        assert parse_authorization({"Authorization": "   "}) is None

    def test_scheme_only_no_token(self):
        assert parse_authorization({"Authorization": "Bearer"}) is None
        assert parse_authorization({"Authorization": "Bearer "}) is None

    def test_unknown_scheme(self):
        assert parse_authorization({"Authorization": "Digest xyz"}) is None

    def test_header_name_case_insensitive(self):
        cred = parse_authorization({"authorization": "Bearer tok"})
        assert cred is not None
        assert cred.token == "tok"


class TestHasToken:
    def test_true_when_present(self):
        assert has_token({"Authorization": "Bearer x"}) is True

    def test_false_when_missing(self):
        assert has_token({}) is False


class TestRequireAuthRejectsNoToken:
    def test_no_header_returns_401(self):
        resp = require_auth({}, Vendor.ZENDESK)
        assert resp is not None
        assert resp.status_code == 401
        body = json.loads(resp.body)
        assert body["error"] == "invalid_token"

    def test_empty_bearer_returns_401(self):
        resp = require_auth({"Authorization": "Bearer "}, Vendor.SALESFORCE)
        assert resp is not None
        assert resp.status_code == 401

    def test_valid_token_returns_none(self):
        assert require_auth({"Authorization": "Bearer good"}, Vendor.JIRA) is None

    def test_salesforce_envelope_on_reject(self):
        resp = require_auth({}, Vendor.SALESFORCE)
        assert resp is not None
        body = json.loads(resp.body)
        assert isinstance(body, list)
        assert body[0]["errorCode"] == "INVALID_SESSION_ID"

    def test_entra_envelope_on_reject(self):
        resp = require_auth({}, Vendor.ENTRA)
        assert resp is not None
        body = json.loads(resp.body)
        assert body["error"]["code"] == "InvalidAuthenticationToken"

    def test_accepted_tokens_whitelist(self):
        headers = {"Authorization": "Bearer wrong"}
        resp = require_auth(
            headers, Vendor.OKTA, accepted_tokens={"right-token"}
        )
        assert resp is not None
        assert resp.status_code == 401

        ok = require_auth(
            {"Authorization": "Bearer right-token"},
            Vendor.OKTA,
            accepted_tokens={"right-token"},
        )
        assert ok is None


class TestAuthStub:
    def test_enforce_blocks_missing_token(self):
        stub = AuthStub(Vendor.SERVICENOW)
        resp = stub.enforce({})
        assert resp is not None
        assert resp.status_code == 401
        body = json.loads(resp.body)
        assert body["status"] == "failure"

    def test_check_true_with_token(self):
        stub = AuthStub(Vendor.JIRA)
        assert stub.check({"Authorization": "Basic YTpl"}) is True

    def test_check_false_without_token(self):
        stub = AuthStub(Vendor.JIRA)
        assert stub.check({}) is False

    def test_unauthorized_response_helper(self):
        resp = unauthorized_response(Vendor.ZENDESK)
        assert resp.status_code == 401


class TestAllVendorsRejectNoToken:
    @pytest.mark.parametrize("vendor", list(Vendor))
    def test_each_vendor_401(self, vendor: Vendor):
        resp = require_auth({}, vendor)
        assert resp is not None
        assert resp.status_code == 401
