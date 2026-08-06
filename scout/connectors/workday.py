"""
Production Workday connector.

Uses OAuth2 Client Credentials grant (ISU — Integration System User).
Extracts Workers and Organizations from Workday REST API v42. Note: Workday
REST API paths include the tenant name in the URL, e.g.:
  https://{subdomain}.workday.com/ccx/api/v42/{tenant}/workers

Authentication model: Workday ISU integration uses the Client Credentials
grant (no user involved). The ISU client_id and client_secret are generated
in the Workday tenant by a security administrator. Tokens expire after
3,600 seconds (1 hour).

Rate limits: Workday enforces strict per-tenant API limits. Conservative
baseline is 300 requests per 5 minutes (~1/sec). We use 3/sec to give
headroom for concurrent scans while staying safely below the limit.
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
from scout.connectors.oauth2 import OAuth2ClientCredentials

logger = logging.getLogger(__name__)

# Workday REST API version
_API_VERSION = "v42"

# Default page size for Workday pagination
_PAGE_SIZE = 100


class WorkdayConnector(ConnectorBase):
    """
    Production Workday HRIS connector.

    Authenticates via OAuth2 Client Credentials grant (ISU).
    Extracts Workers and Organizations via Workday REST API v42.
    Handles limit/offset pagination using the `total` field in responses.

    Credentials (auth_data keys):
        subdomain     — Workday subdomain, e.g. "acme" for acme.workday.com
        tenant        — Workday tenant name, e.g. "acmecorp_dpt1"
        client_id     — ISU OAuth2 client ID
        client_secret — ISU OAuth2 client secret
    """

    CONNECTOR_ID = "workday"
    DISPLAY_NAME = "Workday HRIS (Production)"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 3.0  # Workday is strict; 300 req/5min = 1/sec; use 3 with burst

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._oauth: OAuth2ClientCredentials | None = None
        self._subdomain: str = ""
        self._tenant: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain an OAuth2 token using the ISU Client Credentials grant.

        Reads subdomain, tenant, client_id, and client_secret from
        auth_data. Initializes OAuth2ClientCredentials and fetches a
        token immediately to verify the credentials are correct.

        Returns:
            True if a valid token was obtained.
            False if any credential is missing or the token request fails.
        """
        auth = self.credentials.auth_data
        subdomain = auth.get("subdomain", "")
        tenant = auth.get("tenant", "")
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")

        if not all([subdomain, tenant, client_id, client_secret]):
            logger.error(
                "WorkdayConnector.authenticate: missing required auth_data keys "
                "(subdomain, tenant, client_id, client_secret)"
            )
            return False

        token_url = (
            f"https://{subdomain}.workday.com/ccx/oauth2/{tenant}/token"
        )

        try:
            self._subdomain = subdomain
            self._tenant = tenant
            self._oauth = OAuth2ClientCredentials(
                token_url=token_url,
                client_id=client_id,
                client_secret=client_secret,
            )
            # Force an immediate token fetch to verify credentials
            token = self._oauth.get_valid_token()
            logger.info(
                "WorkdayConnector authenticated successfully for tenant=%s",
                self.tenant_id,
            )
            return bool(token)
        except Exception as exc:
            logger.exception(
                "WorkdayConnector.authenticate failed for tenant=%s: %s",
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
                entity_type="worker",
                display_name="Workday Workers",
                supports_incremental=True,
                fields=[
                    "id", "descriptor", "workerType", "primaryJob",
                    "businessTitle", "department", "manager", "location",
                    "startDate", "endEmploymentDate", "isActive",
                ],
            ),
            EntitySchema(
                entity_type="organization",
                display_name="Workday Organizations",
                supports_incremental=False,
                fields=[
                    "id", "descriptor", "orgType", "manager",
                    "parentOrg", "memberCount",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Extract all records of the given entity type using offset pagination.

        Workday REST API uses limit/offset pagination. The response includes
        a `total` field indicating the total number of available records.
        We paginate until all records have been fetched.

        Args:
            entity_type: One of "worker", "organization".

        Yields:
            RawRecord for each Workday record.
        """
        if entity_type not in {"worker", "organization"}:
            raise ValueError(
                f"WorkdayConnector does not support entity_type='{entity_type}'. "
                f"Supported: worker, organization"
            )

        endpoint = self._entity_endpoint(entity_type)
        url = f"{self._base_url()}/{endpoint}"

        logger.info(
            "WorkdayConnector.extract_full: entity_type=%s tenant=%s",
            entity_type,
            self.tenant_id,
        )

        yield from self._paginate_workday(url=url, entity_type=entity_type)

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Extract records updated since cursor.last_extracted_at.

        Passes the updatedFrom query parameter to filter Workday records.
        Workday's API accepts ISO 8601 datetime strings for this filter.

        Args:
            entity_type: One of "worker", "organization".
            cursor:      Contains last_extracted_at for the since filter.

        Returns:
            A 2-tuple of (record_iterator, updated_cursor).
        """
        if entity_type not in {"worker", "organization"}:
            raise ValueError(
                f"WorkdayConnector does not support entity_type='{entity_type}'."
            )

        endpoint = self._entity_endpoint(entity_type)
        url = f"{self._base_url()}/{endpoint}"
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "WorkdayConnector.extract_incremental: entity_type=%s since=%s tenant=%s",
            entity_type,
            since_iso,
            self.tenant_id,
        )

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_workday(
                url=url,
                entity_type=entity_type,
                extra_params={"updatedFrom": since_iso},
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"updated_from": since_iso},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        """
        Verify connectivity by fetching a single worker record.

        Uses limit=1 to minimize API cost while confirming both
        authentication and network connectivity to the Workday tenant.
        """
        start = time.monotonic()
        try:
            url = f"{self._base_url()}/workers"
            response = self._http_client.get(
                url,
                params={"limit": 1},
                headers=self._get_headers(),
            )
            response.raise_for_status()
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "WorkdayConnector health check OK: latency=%.1fms", latency_ms
            )
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning("WorkdayConnector health check failed: %s", exc)
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    # ─────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────

    def _base_url(self) -> str:
        """
        Build the Workday REST API base URL for this tenant.

        Workday includes the tenant name in every API path, which is
        unusual but required by their multi-tenant architecture.
        """
        return (
            f"https://{self._subdomain}.workday.com"
            f"/ccx/api/{_API_VERSION}/{self._tenant}"
        )

    def _entity_endpoint(self, entity_type: str) -> str:
        """Map entity_type to Workday REST path segment."""
        return {
            "worker": "workers",
            "organization": "organizations",
        }[entity_type]

    def _get_headers(self) -> dict[str, str]:
        """
        Return HTTP headers with a fresh Bearer token.

        Calls get_valid_token() which handles caching and automatic
        refresh — safe to call on every request.
        """
        if self._oauth is None:
            raise RuntimeError(
                "WorkdayConnector.authenticate() must be called before extraction."
            )
        return {
            "Authorization": f"Bearer {self._oauth.get_valid_token()}",
            "Content-Type": "application/json",
        }

    def _paginate_workday(
        self,
        url: str,
        entity_type: str,
        extra_params: dict[str, Any] | None = None,
    ) -> Iterator[RawRecord]:
        """
        Paginate through Workday results using limit/offset.

        Workday's response schema:
            {
                "data": [...records...],
                "total": 1250,
                "start": 0,
                "count": 100
            }

        We increment `offset` by `_PAGE_SIZE` until all records are fetched
        (offset >= total).

        Args:
            url:          Full API endpoint URL.
            entity_type:  Used to determine the source_id field name.
            extra_params: Additional query parameters (e.g. updatedFrom).

        Yields:
            RawRecord for each Workday data item.
        """
        offset = 0

        while True:
            params: dict[str, Any] = {
                "limit": _PAGE_SIZE,
                "offset": offset,
            }
            if extra_params:
                params.update(extra_params)

            try:
                response = self._get(url, params=params, headers=self._get_headers())
            except Exception as exc:
                logger.error(
                    "WorkdayConnector pagination error at offset=%d: %s", offset, exc
                )
                break

            records = response.get("data", [])
            total = response.get("total", 0)

            for record in records:
                source_id = record.get("id", "") or record.get("workerId", "")
                name = record.get("descriptor", "") or record.get("name", "")
                # Workers have a primaryWork section with email; orgs do not
                email = None
                primary_work = record.get("primaryWork", {})
                if isinstance(primary_work, dict):
                    email = primary_work.get("workEmail")

                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=str(source_id),
                    tenant_id=self.tenant_id,
                    payload=record,
                    email_hint=email,
                    name_hint=name or None,
                )

            offset += len(records)
            if not records or offset >= total:
                break
