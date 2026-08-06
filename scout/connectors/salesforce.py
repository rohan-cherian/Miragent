"""
Production Salesforce connector.

Uses OAuth2 Connected App credentials. Extracts Users, Accounts, and
Opportunities via SOQL REST API. Supports both full and incremental
extraction using SystemModstamp for precise change detection.

Authentication model: Scout assumes the initial OAuth2 authorization
code flow has already been completed and a refresh_token is stored in
the connector's auth_data. This connector uses that refresh_token on
every authenticate() call to obtain a fresh access_token.

Rate limits: Salesforce enforces per-user API limits (typically 1,000,000
API calls per 24 hours, with a concurrent limit of 25). We use 5 calls/sec
as a conservative default; adjust CALLS_PER_SECOND for high-volume tenants.
"""

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone

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
from scout.connectors.oauth2 import OAuth2AuthorizationCode, OAuth2Token

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# SOQL QUERIES
# Each query selects the fields Scout needs for entity resolution
# and graph construction. SystemModstamp tracks changes at the
# record level — it updates whenever any field is modified.
# ─────────────────────────────────────────────────────────

_SOQL_QUERIES: dict[str, str] = {
    "user": (
        "SELECT Id, Name, Email, Title, Department, IsActive, "
        "LastLoginDate, CreatedDate, UserRoleId "
        "FROM User WHERE IsActive = true"
    ),
    "account": (
        "SELECT Id, Name, Industry, AnnualRevenue, NumberOfEmployees, "
        "OwnerId, Type, CreatedDate "
        "FROM Account"
    ),
    "opportunity": (
        "SELECT Id, Name, StageName, Amount, CloseDate, AccountId, "
        "OwnerId, Probability, CreatedDate, IsClosed, IsWon "
        "FROM Opportunity"
    ),
}

_SOQL_QUERIES_INCREMENTAL: dict[str, str] = {
    "user": (
        "SELECT Id, Name, Email, Title, Department, IsActive, "
        "LastLoginDate, CreatedDate, UserRoleId "
        "FROM User WHERE IsActive = true AND SystemModstamp > {since}"
    ),
    "account": (
        "SELECT Id, Name, Industry, AnnualRevenue, NumberOfEmployees, "
        "OwnerId, Type, CreatedDate "
        "FROM Account WHERE SystemModstamp > {since}"
    ),
    "opportunity": (
        "SELECT Id, Name, StageName, Amount, CloseDate, AccountId, "
        "OwnerId, Probability, CreatedDate, IsClosed, IsWon "
        "FROM Opportunity WHERE SystemModstamp > {since}"
    ),
}

# Salesforce API version to use
_API_VERSION = "v59.0"


class SalesforceConnector(ConnectorBase):
    """
    Production Salesforce CRM connector.

    Authenticates via OAuth2 refresh_token flow (Connected App).
    Executes SOQL queries against the Salesforce REST API.
    Handles Salesforce's cursor-based pagination (nextRecordsUrl).

    Credentials (auth_data keys):
        instance_url   — e.g. "https://acmecorp.my.salesforce.com"
        client_id      — Connected App consumer key
        client_secret  — Connected App consumer secret
        refresh_token  — stored from initial OAuth2 authorization
        token_url      — optional override; defaults to instance_url + /services/oauth2/token
    """

    CONNECTOR_ID = "salesforce"
    DISPLAY_NAME = "Salesforce CRM (Production)"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 5.0  # Conservative; Salesforce allows ~100 req/min per user

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._token: str = ""
        self._instance_url: str = ""
        self._oauth: OAuth2AuthorizationCode | None = None
        self._stored_token: OAuth2Token | None = None

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain a valid access token using the stored refresh_token.

        Reads instance_url, client_id, client_secret, and refresh_token
        from credentials.auth_data. Builds an OAuth2AuthorizationCode
        helper and immediately refreshes to get a live access_token.

        Returns:
            True if a valid access token was obtained.
            False if any credential is missing or the refresh fails.
        """
        auth = self.credentials.auth_data
        instance_url = auth.get("instance_url", "").rstrip("/")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        refresh_token = auth.get("refresh_token", "")
        token_url = auth.get(
            "token_url",
            f"{instance_url}/services/oauth2/token",
        )

        if not all([instance_url, client_id, client_secret, refresh_token]):
            logger.error(
                "SalesforceConnector.authenticate: missing required auth_data keys "
                "(instance_url, client_id, client_secret, refresh_token)"
            )
            return False

        try:
            self._oauth = OAuth2AuthorizationCode(
                token_url=token_url,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri="",  # Not needed for refresh flow
            )
            # Build a token with the stored refresh_token so get_valid_token
            # will trigger a refresh (expires_at=0.0 means "treat as expired")
            self._stored_token = OAuth2Token(
                access_token="",
                refresh_token=refresh_token,
                expires_at=0.0,
            )
            access_token, updated_token = self._oauth.get_valid_token(
                self._stored_token
            )
            self._token = access_token
            self._stored_token = updated_token
            self._instance_url = instance_url
            logger.info(
                "SalesforceConnector authenticated successfully for tenant=%s",
                self.tenant_id,
            )
            return True
        except Exception as exc:
            logger.exception(
                "SalesforceConnector.authenticate failed for tenant=%s: %s",
                self.tenant_id,
                exc,
            )
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        """Return entity types this connector can extract."""
        return [
            EntitySchema(
                entity_type="user",
                display_name="Salesforce Users",
                supports_incremental=True,
                fields=[
                    "Id", "Name", "Email", "Title", "Department",
                    "IsActive", "LastLoginDate", "CreatedDate", "UserRoleId",
                ],
            ),
            EntitySchema(
                entity_type="account",
                display_name="Salesforce Accounts",
                supports_incremental=True,
                fields=[
                    "Id", "Name", "Industry", "AnnualRevenue",
                    "NumberOfEmployees", "OwnerId", "Type", "CreatedDate",
                ],
            ),
            EntitySchema(
                entity_type="opportunity",
                display_name="Salesforce Opportunities",
                supports_incremental=True,
                fields=[
                    "Id", "Name", "StageName", "Amount", "CloseDate",
                    "AccountId", "OwnerId", "Probability", "CreatedDate",
                    "IsClosed", "IsWon",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Extract all records of the given entity type using SOQL.

        Uses _paginate() to follow Salesforce's nextRecordsUrl pagination.
        Each page returns up to 2,000 records by default (Salesforce max).

        Args:
            entity_type: One of "user", "account", "opportunity".

        Yields:
            RawRecord for each Salesforce record.

        Raises:
            ValueError for unsupported entity types.
        """
        if entity_type not in _SOQL_QUERIES:
            raise ValueError(
                f"SalesforceConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(_SOQL_QUERIES.keys())}"
            )

        self._ensure_valid_token()
        query = _SOQL_QUERIES[entity_type]
        first_url = self._soql_url(query)

        logger.info(
            "SalesforceConnector.extract_full: entity_type=%s tenant=%s",
            entity_type,
            self.tenant_id,
        )

        for record in self._paginate(
            first_url=first_url,
            next_url_key="nextRecordsUrl",
            records_key="records",
            headers=self._get_headers(),
        ):
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=record["Id"],
                tenant_id=self.tenant_id,
                payload=record,
                email_hint=record.get("Email"),
                name_hint=record.get("Name"),
            )

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Extract records modified since cursor.last_extracted_at.

        Appends a WHERE SystemModstamp > {iso_timestamp} clause to the base
        SOQL query. SystemModstamp is updated on every field change,
        including field-level and relationship changes.

        Args:
            entity_type: One of "user", "account", "opportunity".
            cursor:      Contains last_extracted_at for the since filter.

        Returns:
            A 2-tuple of (record_iterator, updated_cursor).
        """
        if entity_type not in _SOQL_QUERIES_INCREMENTAL:
            raise ValueError(
                f"SalesforceConnector does not support incremental for '{entity_type}'."
            )

        self._ensure_valid_token()

        # Salesforce SOQL requires ISO 8601 with no microseconds
        since = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        query = _SOQL_QUERIES_INCREMENTAL[entity_type].format(since=since)
        first_url = self._soql_url(query)

        logger.info(
            "SalesforceConnector.extract_incremental: entity_type=%s since=%s tenant=%s",
            entity_type,
            since,
            self.tenant_id,
        )

        def _generate() -> Iterator[RawRecord]:
            for record in self._paginate(
                first_url=first_url,
                next_url_key="nextRecordsUrl",
                records_key="records",
                headers=self._get_headers(),
            ):
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=record["Id"],
                    tenant_id=self.tenant_id,
                    payload=record,
                    email_hint=record.get("Email"),
                    name_hint=record.get("Name"),
                )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since_filter": since},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        """
        Verify connectivity by calling the Salesforce API versions endpoint.

        GET /services/data/ is a lightweight, unauthenticated endpoint that
        lists available API versions. We authenticate first to test token
        validity as well.
        """
        start = time.monotonic()
        try:
            self._ensure_valid_token()
            url = f"{self._instance_url}/services/data/"
            response = self._http_client.get(url, headers=self._get_headers())
            response.raise_for_status()
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "SalesforceConnector health check OK: latency=%.1fms", latency_ms
            )
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning(
                "SalesforceConnector health check failed: %s", exc
            )
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    # ─────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────

    def _soql_url(self, query: str) -> str:
        """Build the full REST API URL for a SOQL query."""
        from urllib.parse import quote
        encoded = quote(query)
        return (
            f"{self._instance_url}/services/data/{_API_VERSION}"
            f"/query?q={encoded}"
        )

    def _get_headers(self) -> dict[str, str]:
        """Return HTTP headers with the current Bearer token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _ensure_valid_token(self) -> None:
        """
        Refresh the access token if it has expired.

        Called before every API operation. No-op if the token is still valid.
        Updates self._token and self._stored_token in place.
        """
        if self._oauth is None or self._stored_token is None:
            raise RuntimeError(
                "SalesforceConnector.authenticate() must be called before extraction."
            )
        if self._stored_token.is_expired():
            logger.info("Salesforce access token expired — refreshing")
            access_token, updated = self._oauth.get_valid_token(self._stored_token)
            self._token = access_token
            self._stored_token = updated
