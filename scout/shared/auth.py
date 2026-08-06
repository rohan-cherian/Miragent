"""
Auth stubs for vendor API emulators.

A request with no token is rejected with a genuine HTTP 401 and the
vendor's real unauthorized error envelope. Emulators call ``enforce``
(or ``require_auth``) before serving data.

Recognized Authorization schemes (vendor-typical):
  Bearer <token>   — Salesforce, Entra, Jira Cloud OAuth, Zendesk OAuth
  Basic <creds>    — Zendesk API token, ServiceNow, Jira basic
  SSWS <token>     — Okta API token
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from starlette.responses import JSONResponse

from scout.shared.errors import ErrorKind, Vendor, error_response


# Case-insensitive header lookup helpers work with plain dicts and Starlette Headers.
HeadersLike = Mapping[str, str]


@dataclass(frozen=True)
class AuthCredential:
    """Parsed credential from an Authorization header."""

    scheme: str
    token: str

    @property
    def is_empty(self) -> bool:
        return not self.token.strip()


def _header_get(headers: HeadersLike, name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def parse_authorization(headers: HeadersLike) -> AuthCredential | None:
    """
    Parse ``Authorization`` into scheme + token/credential.

    Returns ``None`` when the header is missing or not a recognized scheme
    with a non-empty credential.
    """
    raw = _header_get(headers, "Authorization")
    if raw is None:
        return None

    value = raw.strip()
    if not value:
        return None

    parts = value.split(None, 1)  # split on first whitespace
    if len(parts) != 2:
        return None

    scheme, credential = parts[0].strip(), parts[1].strip()
    if not scheme or not credential:
        return None

    scheme_upper = scheme.upper()
    if scheme_upper not in {"BEARER", "BASIC", "SSWS"}:
        return None

    return AuthCredential(scheme=scheme_upper, token=credential)


def has_token(headers: HeadersLike) -> bool:
    """True when a recognized non-empty Authorization credential is present."""
    cred = parse_authorization(headers)
    return cred is not None and not cred.is_empty


def unauthorized_response(vendor: Vendor | str) -> JSONResponse:
    """Vendor-shaped HTTP 401 for missing/invalid credentials."""
    return error_response(vendor, ErrorKind.UNAUTHORIZED)


def require_auth(
    headers: HeadersLike,
    vendor: Vendor | str,
    *,
    accepted_tokens: set[str] | frozenset[str] | None = None,
) -> JSONResponse | None:
    """
    Reject requests with no (or invalid) token.

    Returns:
        ``None`` if auth passes (caller continues).
        A vendor-shaped 401 ``JSONResponse`` if rejected.
    """
    cred = parse_authorization(headers)
    if cred is None or cred.is_empty:
        return unauthorized_response(vendor)

    if accepted_tokens is not None and cred.token not in accepted_tokens:
        return unauthorized_response(vendor)

    return None


class AuthStub:
    """
    Reusable auth gate for one emulator.

    Usage::

        auth = AuthStub(Vendor.ZENDESK)
        blocked = auth.enforce(request.headers)
        if blocked is not None:
            return blocked
    """

    def __init__(
        self,
        vendor: Vendor | str,
        *,
        accepted_tokens: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.vendor = Vendor(vendor)
        self.accepted_tokens = (
            frozenset(accepted_tokens) if accepted_tokens is not None else None
        )

    def enforce(self, headers: HeadersLike) -> JSONResponse | None:
        """Return 401 if unauthenticated; otherwise ``None``."""
        return require_auth(
            headers,
            self.vendor,
            accepted_tokens=self.accepted_tokens,
        )

    def check(self, headers: HeadersLike) -> bool:
        """True when the request is allowed through."""
        return self.enforce(headers) is None
