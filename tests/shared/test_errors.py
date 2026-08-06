"""
tests/shared/test_errors.py — W1-SRC-04 vendor-shaped error envelopes

Salesforce bodies must not look like Zendesk bodies. Each vendor's shape is
asserted so connector error handling can rely on faithful emulator responses.
"""

from __future__ import annotations

import pytest
from starlette.responses import JSONResponse

from scout.shared.errors import (
    DEFAULT_STATUS,
    ErrorKind,
    Vendor,
    build_error_body,
    error_response,
)
from scout.shared.rate_limit import EmulatorRateLimiter


class TestSalesforceEnvelope:
    """Salesforce: list of {message, errorCode}."""

    def test_shape_is_list_not_dict(self):
        body = build_error_body(Vendor.SALESFORCE, ErrorKind.UNAUTHORIZED)
        assert isinstance(body, list)
        assert len(body) == 1
        assert set(body[0].keys()) == {"message", "errorCode"}

    def test_rate_limited_code(self):
        body = build_error_body(Vendor.SALESFORCE, ErrorKind.RATE_LIMITED)
        assert body[0]["errorCode"] == "REQUEST_LIMIT_EXCEEDED"

    def test_custom_message(self):
        body = build_error_body(
            Vendor.SALESFORCE, ErrorKind.NOT_FOUND, message="Account not found"
        )
        assert body[0]["message"] == "Account not found"
        assert body[0]["errorCode"] == "NOT_FOUND"


class TestZendeskEnvelope:
    """Zendesk Support: {error, description} — nothing like Salesforce."""

    def test_shape_is_dict_with_error_and_description(self):
        body = build_error_body(Vendor.ZENDESK, ErrorKind.RATE_LIMITED)
        assert isinstance(body, dict)
        assert body["error"] == "APIRateLimitExceeded"
        assert "description" in body
        assert "errorCode" not in body  # that is Salesforce, not Zendesk

    def test_not_found(self):
        body = build_error_body(Vendor.ZENDESK, ErrorKind.NOT_FOUND)
        assert body["error"] == "RecordNotFound"

    def test_validation_includes_details(self):
        body = build_error_body(Vendor.ZENDESK, ErrorKind.BAD_REQUEST)
        assert body["error"] == "RecordInvalid"
        assert "details" in body


class TestSalesforceVsZendeskDiffer:
    def test_same_kind_different_shapes(self):
        sf = build_error_body(Vendor.SALESFORCE, ErrorKind.UNAUTHORIZED)
        zd = build_error_body(Vendor.ZENDESK, ErrorKind.UNAUTHORIZED)
        assert type(sf) is not type(zd)
        assert isinstance(sf, list)
        assert isinstance(zd, dict)
        assert "errorCode" in sf[0]
        assert "error" in zd and "description" in zd


class TestJiraEnvelope:
    def test_error_messages_and_errors(self):
        body = build_error_body(Vendor.JIRA, ErrorKind.NOT_FOUND)
        assert body == {
            "errorMessages": ["Issue Does Not Exist"],
            "errors": {},
        }


class TestEntraEnvelope:
    def test_nested_error_object(self):
        body = build_error_body(Vendor.ENTRA, ErrorKind.UNAUTHORIZED)
        assert "error" in body
        assert body["error"]["code"] == "InvalidAuthenticationToken"
        assert "message" in body["error"]
        assert "innerError" in body["error"]
        assert "request-id" in body["error"]["innerError"]

    def test_rate_limited_code(self):
        body = build_error_body(Vendor.ENTRA, ErrorKind.RATE_LIMITED)
        assert body["error"]["code"] == "TooManyRequests"


class TestServiceNowEnvelope:
    def test_error_message_detail_status(self):
        body = build_error_body(Vendor.SERVICENOW, ErrorKind.UNAUTHORIZED)
        assert body["status"] == "failure"
        assert body["error"]["message"] == "User Not Authenticated"
        assert "detail" in body["error"]


class TestOktaEnvelope:
    def test_error_code_summary_causes(self):
        body = build_error_body(Vendor.OKTA, ErrorKind.RATE_LIMITED)
        assert body["errorCode"] == "E0000047"
        assert "errorSummary" in body
        assert body["errorLink"] == body["errorCode"]
        assert body["errorCauses"] == []
        assert "errorId" in body


class TestErrorResponse:
    def test_returns_json_response_with_default_status(self):
        resp = error_response(Vendor.ZENDESK, ErrorKind.RATE_LIMITED)
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 429

    def test_all_kinds_have_default_status(self):
        for kind in ErrorKind:
            assert kind in DEFAULT_STATUS

    def test_string_vendor_and_kind_accepted(self):
        body = build_error_body("salesforce", "unauthorized")
        assert body[0]["errorCode"] == "INVALID_SESSION_ID"

    def test_unknown_vendor_raises(self):
        with pytest.raises(ValueError):
            build_error_body("unknown_vendor", ErrorKind.NOT_FOUND)


class TestRateLimitUsesVendorEnvelope:
    """Rate limiter can return a vendor-faithful 429 body."""

    def test_salesforce_429_body(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=60)
        limiter.enforce("t")
        body = build_error_body(Vendor.SALESFORCE, ErrorKind.RATE_LIMITED)
        resp = limiter.enforce("t", body=body)
        assert resp is not None
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        # Body is Salesforce list shape, not Zendesk
        import json

        payload = json.loads(resp.body)
        assert isinstance(payload, list)
        assert payload[0]["errorCode"] == "REQUEST_LIMIT_EXCEEDED"

    def test_zendesk_429_body(self):
        limiter = EmulatorRateLimiter(max_requests=1, window_seconds=60)
        limiter.enforce("t")
        body = build_error_body(Vendor.ZENDESK, ErrorKind.RATE_LIMITED)
        resp = limiter.enforce("t", body=body)
        assert resp is not None
        import json

        payload = json.loads(resp.body)
        assert payload["error"] == "APIRateLimitExceeded"
