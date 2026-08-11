"""
Vendor-shaped error envelopes for API emulators.

Salesforce error bodies are not Zendesk error bodies. Emulators must return
the real vendor JSON shape so connector error handling can be tested against
realistic responses — not a generic ``{"detail": "..."}`` wrapper.

Supported vendors (emulator targets):
  salesforce, zendesk, jira, entra, servicenow, okta, workday
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from starlette.responses import JSONResponse


class Vendor(str, Enum):
    SALESFORCE = "salesforce"
    ZENDESK = "zendesk"
    JIRA = "jira"
    ENTRA = "entra"
    SERVICENOW = "servicenow"
    OKTA = "okta"
    WORKDAY = "workday"


class ErrorKind(str, Enum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    BAD_REQUEST = "bad_request"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"


# Default HTTP status per kind (vendors may still override at the call site).
DEFAULT_STATUS: dict[ErrorKind, int] = {
    ErrorKind.UNAUTHORIZED: 401,
    ErrorKind.FORBIDDEN: 403,
    ErrorKind.NOT_FOUND: 404,
    ErrorKind.BAD_REQUEST: 400,
    ErrorKind.RATE_LIMITED: 429,
    ErrorKind.SERVER_ERROR: 500,
}


def build_error_body(
    vendor: Vendor | str,
    kind: ErrorKind | str,
    *,
    message: str | None = None,
) -> Any:
    """
    Return a vendor-faithful error JSON body (dict or list).

    Salesforce returns a **list** of ``{message, errorCode}`` objects.
    Zendesk returns ``{error, description}``.
    Those shapes must never be mixed.
    """
    vendor = Vendor(vendor)
    kind = ErrorKind(kind)

    builders = {
        Vendor.SALESFORCE: _salesforce_body,
        Vendor.ZENDESK: _zendesk_body,
        Vendor.JIRA: _jira_body,
        Vendor.ENTRA: _entra_body,
        Vendor.SERVICENOW: _servicenow_body,
        Vendor.OKTA: _okta_body,
        Vendor.WORKDAY: _workday_body,
    }
    return builders[vendor](kind, message)


def error_response(
    vendor: Vendor | str,
    kind: ErrorKind | str,
    *,
    message: str | None = None,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build a ``JSONResponse`` with the vendor's real error envelope."""
    kind_enum = ErrorKind(kind)
    body = build_error_body(vendor, kind_enum, message=message)
    code = status_code if status_code is not None else DEFAULT_STATUS[kind_enum]
    return JSONResponse(content=body, status_code=code, headers=headers or {})


# ── Salesforce REST ──────────────────────────────────────────────────────────
# Docs: array of { "message": "...", "errorCode": "..." }


_SF_CODES: dict[ErrorKind, tuple[str, str]] = {
    ErrorKind.UNAUTHORIZED: (
        "INVALID_SESSION_ID",
        "Session expired or invalid",
    ),
    ErrorKind.FORBIDDEN: (
        "INSUFFICIENT_ACCESS_OR_READONLY",
        "You do not have permission to perform this operation",
    ),
    ErrorKind.NOT_FOUND: (
        "NOT_FOUND",
        "The requested resource does not exist",
    ),
    ErrorKind.BAD_REQUEST: (
        "INVALID_FIELD",
        "Invalid field for insert/update",
    ),
    ErrorKind.RATE_LIMITED: (
        "REQUEST_LIMIT_EXCEEDED",
        "Request limit exceeded",
    ),
    ErrorKind.SERVER_ERROR: (
        "UNKNOWN_EXCEPTION",
        "An unexpected error occurred",
    ),
}


def _salesforce_body(kind: ErrorKind, message: str | None) -> list[dict[str, str]]:
    code, default_msg = _SF_CODES[kind]
    return [{"message": message or default_msg, "errorCode": code}]


# ── Zendesk Support API ──────────────────────────────────────────────────────
# Docs: { "error": "<Code>", "description": "..." }
# Validation errors may also include "details".


_ZD_CODES: dict[ErrorKind, tuple[str, str]] = {
    ErrorKind.UNAUTHORIZED: (
        "invalid_token",
        "The access token provided is expired, revoked, malformed or invalid",
    ),
    ErrorKind.FORBIDDEN: (
        "Forbidden",
        "You do not have access to this resource",
    ),
    ErrorKind.NOT_FOUND: (
        "RecordNotFound",
        "Not found",
    ),
    ErrorKind.BAD_REQUEST: (
        "RecordInvalid",
        "Record validation errors",
    ),
    ErrorKind.RATE_LIMITED: (
        "APIRateLimitExceeded",
        "Number of allowed API requests per minute exceeded",
    ),
    ErrorKind.SERVER_ERROR: (
        "InternalServerError",
        "An unexpected error occurred",
    ),
}


def _zendesk_body(kind: ErrorKind, message: str | None) -> dict[str, Any]:
    code, default_msg = _ZD_CODES[kind]
    body: dict[str, Any] = {
        "error": code,
        "description": message or default_msg,
    }
    if kind == ErrorKind.BAD_REQUEST:
        body["details"] = {
            "base": [
                {
                    "description": message or default_msg,
                    "error": "InvalidValue",
                }
            ]
        }
    return body


# ── Jira Cloud REST ──────────────────────────────────────────────────────────
# Docs: { "errorMessages": [...], "errors": { field: msg } }


_JIRA_MESSAGES: dict[ErrorKind, str] = {
    ErrorKind.UNAUTHORIZED: "You do not have permission to access this resource.",
    ErrorKind.FORBIDDEN: "You do not have the permission to see the specified issue.",
    ErrorKind.NOT_FOUND: "Issue Does Not Exist",
    ErrorKind.BAD_REQUEST: "The request is invalid.",
    ErrorKind.RATE_LIMITED: "Rate limit exceeded. Please try again later.",
    ErrorKind.SERVER_ERROR: "Internal server error",
}


def _jira_body(kind: ErrorKind, message: str | None) -> dict[str, Any]:
    return {
        "errorMessages": [message or _JIRA_MESSAGES[kind]],
        "errors": {},
    }


# ── Microsoft Graph / Entra ID ───────────────────────────────────────────────
# Docs: { "error": { "code", "message", "innerError": {...} } }


_ENTRA_CODES: dict[ErrorKind, tuple[str, str]] = {
    ErrorKind.UNAUTHORIZED: (
        "InvalidAuthenticationToken",
        "Access token is empty.",
    ),
    ErrorKind.FORBIDDEN: (
        "Authorization_RequestDenied",
        "Insufficient privileges to complete the operation.",
    ),
    ErrorKind.NOT_FOUND: (
        "Request_ResourceNotFound",
        "Resource not found.",
    ),
    ErrorKind.BAD_REQUEST: (
        "BadRequest",
        "Invalid request.",
    ),
    ErrorKind.RATE_LIMITED: (
        "TooManyRequests",
        "Too many requests from this client.",
    ),
    ErrorKind.SERVER_ERROR: (
        "Service_InternalServerError",
        "An internal server error occurred.",
    ),
}


def _entra_body(kind: ErrorKind, message: str | None) -> dict[str, Any]:
    code, default_msg = _ENTRA_CODES[kind]
    req_id = str(uuid.uuid4())
    return {
        "error": {
            "code": code,
            "message": message or default_msg,
            "innerError": {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "request-id": req_id,
                "client-request-id": req_id,
            },
        }
    }


# ── ServiceNow Table API ─────────────────────────────────────────────────────
# Docs: { "error": { "message", "detail" }, "status": "failure" }


_SNOW_MESSAGES: dict[ErrorKind, tuple[str, str]] = {
    ErrorKind.UNAUTHORIZED: (
        "User Not Authenticated",
        "Required to provide Auth information",
    ),
    ErrorKind.FORBIDDEN: (
        "Operation Failed",
        "ACL Exception due to insufficient rights",
    ),
    ErrorKind.NOT_FOUND: (
        "No Record found",
        "Record doesn't exist or ACL restricts the record retrieval",
    ),
    ErrorKind.BAD_REQUEST: (
        "Invalid request",
        "The request is not valid",
    ),
    ErrorKind.RATE_LIMITED: (
        "Too Many Requests",
        "Rate limit exceeded",
    ),
    ErrorKind.SERVER_ERROR: (
        "Service Unavailable",
        "An unexpected error occurred",
    ),
}


def _servicenow_body(kind: ErrorKind, message: str | None) -> dict[str, Any]:
    default_msg, detail = _SNOW_MESSAGES[kind]
    return {
        "error": {
            "message": message or default_msg,
            "detail": detail if message is None else message,
        },
        "status": "failure",
    }


# ── Okta ─────────────────────────────────────────────────────────────────────
# Docs: { errorCode, errorSummary, errorLink, errorId, errorCauses }


_OKTA_CODES: dict[ErrorKind, tuple[str, str]] = {
    ErrorKind.UNAUTHORIZED: ("E0000011", "Invalid token provided"),
    ErrorKind.FORBIDDEN: ("E0000006", "You do not have permission to perform the requested action"),
    ErrorKind.NOT_FOUND: ("E0000007", "Not found: Resource not found"),
    ErrorKind.BAD_REQUEST: ("E0000001", "Api validation failed"),
    ErrorKind.RATE_LIMITED: ("E0000047", "API call exceeded rate limit due to too many requests"),
    ErrorKind.SERVER_ERROR: ("E0000009", "Internal Server Error"),
}


def _okta_body(kind: ErrorKind, message: str | None) -> dict[str, Any]:
    code, default_msg = _OKTA_CODES[kind]
    return {
        "errorCode": code,
        "errorSummary": message or default_msg,
        "errorLink": code,
        "errorId": uuid.uuid4().hex[:20],
        "errorCauses": [],
    }


# ── Workday (RaaS / REST-style) ──────────────────────────────────────────────
# Common JSON fault shape used by custom report / OAuth failure paths:
#   { "error": "<code>", "error_description": "..." }


_WD_CODES: dict[ErrorKind, tuple[str, str]] = {
    ErrorKind.UNAUTHORIZED: (
        "invalid.authentication",
        "Authentication failure: invalid or missing credentials",
    ),
    ErrorKind.FORBIDDEN: (
        "insufficient.privileges",
        "You do not have permission to run this report",
    ),
    ErrorKind.NOT_FOUND: (
        "report.not.found",
        "The requested report does not exist",
    ),
    ErrorKind.BAD_REQUEST: (
        "invalid.request",
        "The request is invalid",
    ),
    ErrorKind.RATE_LIMITED: (
        "request.limit.exceeded",
        "Too many requests — retry later",
    ),
    ErrorKind.SERVER_ERROR: (
        "processing.error",
        "An unexpected error occurred while processing the report",
    ),
}


def _workday_body(kind: ErrorKind, message: str | None) -> dict[str, Any]:
    code, default_msg = _WD_CODES[kind]
    return {
        "error": code,
        "error_description": message or default_msg,
    }
