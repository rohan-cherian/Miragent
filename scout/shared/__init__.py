"""Shared plumbing for vendor API emulators (W1-SRC-04)."""

from scout.shared.auth import (
    AuthCredential,
    AuthStub,
    has_token,
    parse_authorization,
    require_auth,
    unauthorized_response,
)
from scout.shared.chaos import (
    ChaosEffects,
    ChaosMode,
    ChaosResult,
    ChaosSwitch,
    parse_chaos,
    parse_chaos_from_params,
)
from scout.shared.errors import (
    DEFAULT_STATUS,
    ErrorKind,
    Vendor,
    build_error_body,
    error_response,
)
from scout.shared.pagination import (
    PageSlice,
    decode_odata_skiptoken,
    decode_zendesk_cursor,
    encode_odata_skiptoken,
    encode_zendesk_cursor,
    paginate_entra,
    paginate_jira,
    paginate_zendesk,
    parse_entra_skiptoken_from_url,
    slice_items,
)
from scout.shared.rate_limit import EmulatorRateLimiter, RateLimitResult

__all__ = [
    "AuthCredential",
    "AuthStub",
    "ChaosEffects",
    "ChaosMode",
    "ChaosResult",
    "ChaosSwitch",
    "DEFAULT_STATUS",
    "EmulatorRateLimiter",
    "ErrorKind",
    "PageSlice",
    "RateLimitResult",
    "Vendor",
    "build_error_body",
    "decode_odata_skiptoken",
    "decode_zendesk_cursor",
    "encode_odata_skiptoken",
    "encode_zendesk_cursor",
    "error_response",
    "has_token",
    "paginate_entra",
    "paginate_jira",
    "paginate_zendesk",
    "parse_authorization",
    "parse_chaos",
    "parse_chaos_from_params",
    "parse_entra_skiptoken_from_url",
    "require_auth",
    "slice_items",
    "unauthorized_response",
]
