"""
scout/connectors/google_workspace.py — Production Google Workspace Connector (Sprint 37)

Google Workspace (formerly G Suite) is used by the majority of PE-backed tech
companies as their identity and productivity platform. For Miragent:
  - Employee directory (Google Directory API → all users + their status)
  - App access: which third-party apps have OAuth access?
  - Offboarding verification: is suspended user's Google account deactivated?
  - Group membership: org chart and security group signals

Authentication:
  Google Workspace uses OAuth 2.0 Service Account (domain-wide delegation).
  The service account JSON key is stored in credentials.
  Scopes: https://www.googleapis.com/auth/admin.directory.user.readonly
          https://www.googleapis.com/auth/admin.directory.group.readonly

  Token endpoint: https://oauth2.googleapis.com/token

API structure:
  Base: https://admin.googleapis.com
  - /admin/directory/v1/users               → directory users
  - /admin/directory/v1/groups              → Google Groups
  - /admin/directory/v1/users/{email}/tokens → OAuth app tokens per user

Pagination:
  Google uses pageToken-based cursor pagination.
  Response: { "users": [...], "nextPageToken": "..." }

Rate limits:
  Google Workspace: 2400 queries/minute for Directory API.
  We use 20/sec (1200/min) as a safe default.

Entity types:
  - user         → Google Workspace users (all employees)
  - group        → Google Groups (security groups, distribution lists)
  - app_token    → OAuth app authorizations per user
"""

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import httpx

from scout.connectors.base import ConnectorBase
from scout.connectors.models import (
    ConnectorCategory,
    ConnectorCredentials,
    ConnectorHealth,
    EntitySchema,
    ExtractionCursor,
    RawRecord,
)

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API_BASE = "https://admin.googleapis.com"
_PAGE_SIZE = 500  # Directory API max


class GoogleWorkspaceConnector(ConnectorBase):
    """
    Production Google Workspace (Admin SDK Directory API) connector.

    Uses service account with domain-wide delegation. The subject email
    must be a Workspace admin for delegation to work.

    Credentials (auth_data keys):
        service_account_json  — Full service account JSON key (as dict or string)
        subject_email         — Admin email to impersonate (domain-wide delegation)
        customer_id           — Google Workspace customer ID (default: "my_customer")
    """

    CONNECTOR_ID = "google_workspace"
    DISPLAY_NAME = "Google Workspace (Production)"
    CATEGORY = ConnectorCategory.IDENTITY
    CALLS_PER_SECOND = 20.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._customer_id: str = "my_customer"

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain an access token using a service account JWT assertion.
        Implements the Google OAuth2 JWT Bearer flow without external libraries.
        """
        import base64
        import hashlib
        import hmac
        import json as _json
        import struct

        auth = self.credentials.auth_data
        sa_json = auth.get("service_account_json", {})
        subject_email = auth.get("subject_email", "")
        self._customer_id = auth.get("customer_id", "my_customer")

        if isinstance(sa_json, str):
            try:
                sa_json = _json.loads(sa_json)
            except Exception:
                logger.error("GoogleWorkspaceConnector: invalid service_account_json (not valid JSON)")
                return False

        client_email = sa_json.get("client_email", "")
        private_key = sa_json.get("private_key", "")

        if not all([client_email, private_key, subject_email]):
            logger.error(
                "GoogleWorkspaceConnector: missing 'client_email', 'private_key', or 'subject_email'"
            )
            return False

        scope = (
            "https://www.googleapis.com/auth/admin.directory.user.readonly "
            "https://www.googleapis.com/auth/admin.directory.group.readonly"
        )

        # Build JWT assertion and exchange for access token
        try:
            jwt_token = self._build_jwt(
                client_email=client_email,
                private_key=private_key,
                subject_email=subject_email,
                scope=scope,
            )
            resp = self._http_client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": jwt_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("GoogleWorkspaceConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info(
                "GoogleWorkspaceConnector authenticated: subject=%s tenant=%s",
                subject_email, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("GoogleWorkspaceConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("GoogleWorkspaceConnector auth error: %s", exc)
            return False

    def _build_jwt(
        self, client_email: str, private_key: str, subject_email: str, scope: str
    ) -> str:
        """
        Build a signed JWT for the service account flow.
        Uses the cryptography library if available, falls back to error.
        """
        import base64
        import json as _json
        import time as _time

        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError:
            raise RuntimeError(
                "GoogleWorkspaceConnector requires 'cryptography' package. "
                "Install with: pip install cryptography"
            )

        now = int(_time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": client_email,
            "sub": subject_email,
            "scope": scope,
            "aud": _TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header_enc = _b64url(_json.dumps(header).encode())
        payload_enc = _b64url(_json.dumps(payload).encode())
        signing_input = f"{header_enc}.{payload_enc}".encode()

        private_key_obj = serialization.load_pem_private_key(
            private_key.encode(), password=None
        )
        signature = private_key_obj.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{header_enc}.{payload_enc}.{_b64url(signature)}"

    def _refresh_if_needed(self) -> None:
        if time.time() > self._token_expires_at - 300:
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Google Workspace Users",
                supports_incremental=False,
                fields=[
                    "id", "primaryEmail", "name",
                    "firstName", "lastName",
                    "suspended", "isAdmin", "isDelegatedAdmin",
                    "orgUnitPath", "departmentId", "lastLoginTime",
                    "creationTime", "phones", "aliases",
                ],
            ),
            EntitySchema(
                entity_type="group",
                display_name="Google Workspace Groups",
                supports_incremental=False,
                fields=[
                    "id", "email", "name", "description",
                    "directMembersCount", "adminCreated",
                ],
            ),
            EntitySchema(
                entity_type="app_token",
                display_name="Google Workspace OAuth App Tokens",
                supports_incremental=False,
                fields=[
                    "clientId", "displayText", "userKey",
                    "anonymous", "nativeApp", "scopes",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type == "user":
            yield from self._paginate_directory(
                endpoint=f"{_API_BASE}/admin/directory/v1/users",
                records_key="users",
                entity_type="user",
                extra_params={"customer": self._customer_id, "orderBy": "email"},
            )
        elif entity_type == "group":
            yield from self._paginate_directory(
                endpoint=f"{_API_BASE}/admin/directory/v1/groups",
                records_key="groups",
                entity_type="group",
                extra_params={"customer": self._customer_id},
            )
        elif entity_type == "app_token":
            yield from self._extract_all_app_tokens()
        else:
            raise ValueError(
                f"GoogleWorkspaceConnector does not support entity_type='{entity_type}'. "
                f"Supported: user, group, app_token"
            )

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """Google Directory API doesn't support delta/incremental natively — full refresh."""
        def _generate() -> Iterator[RawRecord]:
            yield from self.extract_full(entity_type)

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            self._refresh_if_needed()
            resp = self._get(
                f"{_API_BASE}/admin/directory/v1/users",
                params={"customer": self._customer_id, "maxResults": 1},
                headers=self._headers(),
            )
            _ = resp.get("users", [])
            latency_ms = (time.monotonic() - start) * 1000
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    # ─────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    def _paginate_directory(
        self,
        endpoint: str,
        records_key: str,
        entity_type: str,
        extra_params: dict | None = None,
    ) -> Iterator[RawRecord]:
        """
        Paginate Google Admin SDK Directory API using pageToken.
        Response: { "{records_key}": [...], "nextPageToken": "..." }
        """
        self._refresh_if_needed()
        params: dict[str, Any] = {"maxResults": _PAGE_SIZE}
        if extra_params:
            params.update(extra_params)

        while True:
            try:
                resp = self._get(endpoint, params=params, headers=self._headers())
            except Exception as exc:
                logger.error("GoogleWorkspaceConnector pagination error (endpoint=%s): %s", endpoint, exc)
                break

            records = resp.get(records_key, [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            next_token = resp.get("nextPageToken")
            if not next_token:
                break
            params = {**params, "pageToken": next_token}

    def _extract_all_app_tokens(self) -> Iterator[RawRecord]:
        """Fetch all users, then get OAuth tokens per user."""
        users = list(self._paginate_directory(
            endpoint=f"{_API_BASE}/admin/directory/v1/users",
            records_key="users",
            entity_type="user",
            extra_params={"customer": self._customer_id},
        ))

        for user_record in users:
            user_email = user_record.payload.get("primaryEmail", "")
            if not user_email:
                continue
            try:
                resp = self._get(
                    f"{_API_BASE}/admin/directory/v1/users/{user_email}/tokens",
                    headers=self._headers(),
                )
                tokens = resp.get("items", [])
                for token in tokens:
                    token["_user_email"] = user_email
                    yield self._to_raw_record("app_token", token)
            except Exception as exc:
                logger.debug(
                    "GoogleWorkspaceConnector: could not fetch tokens for %s: %s",
                    user_email, exc,
                )

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(
            record.get("id")
            or record.get("clientId")
            or ""
        )
        email = (
            record.get("primaryEmail")
            or record.get("email")
            or record.get("_user_email")
        )
        name_obj = record.get("name", {})
        name = (
            name_obj.get("fullName") if isinstance(name_obj, dict) else None
            or record.get("name") if isinstance(record.get("name"), str) else None
            or record.get("displayText")
            or None
        )
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=record,
            email_hint=email or None,
            name_hint=name or None,
        )
