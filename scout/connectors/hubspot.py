"""
Production HubSpot connector.

Uses HubSpot Private App access token (long-lived Bearer token). Extracts
Contacts, Companies, and Deals via HubSpot CRM v3 API. Supports cursor-based
pagination via the `after` parameter returned in paging.next.after.

Authentication model: HubSpot Private Apps issue a single long-lived access
token that does not expire (unlike OAuth2 tokens). Store this token in
auth_data["access_token"]. No refresh logic is needed — if the token is
revoked, re-issue a new Private App token in the HubSpot portal.

Rate limits: HubSpot enforces burst limits (110 requests per 10 seconds for
most tiers) and daily limits. We use 9 calls/sec conservatively to stay within
the burst window without hitting the hard cap.
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

_BASE_URL = "https://api.hubapi.com"

# CRM object endpoints and the properties to fetch for each
_OBJECT_CONFIG: dict[str, dict[str, Any]] = {
    "contact": {
        "endpoint": "/crm/v3/objects/contacts",
        "properties": "firstname,lastname,email,jobtitle,department,hs_object_id",
    },
    "company": {
        "endpoint": "/crm/v3/objects/companies",
        "properties": "name,industry,annualrevenue,numberofemployees,hs_object_id",
    },
    "deal": {
        "endpoint": "/crm/v3/objects/deals",
        "properties": "dealname,dealstage,amount,closedate,hubspot_owner_id,hs_object_id",
    },
}


class HubSpotConnector(ConnectorBase):
    """
    Production HubSpot CRM connector.

    Authenticates with a HubSpot Private App access token.
    Paginates using the `after` cursor from response["paging"]["next"]["after"].
    Supports incremental extraction via the hs_lastmodifieddate filter.

    Credentials (auth_data keys):
        access_token — HubSpot Private App access token
    """

    CONNECTOR_ID = "hubspot"
    DISPLAY_NAME = "HubSpot CRM (Production)"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 9.0  # Conservative; HubSpot burst is ~110 req/10s

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._token: str = credentials.auth_data.get("access_token", "")

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Verify the Private App token is valid by making a lightweight API call.

        A GET to /crm/v3/objects/contacts?limit=1 is the cheapest way to
        confirm the token is active. Returns True on 200, False otherwise.
        """
        if not self._token:
            logger.error(
                "HubSpotConnector.authenticate: access_token not found in auth_data"
            )
            return False

        try:
            url = f"{_BASE_URL}/crm/v3/objects/contacts"
            response = self._http_client.get(
                url,
                params={"limit": 1},
                headers=self._headers(),
            )
            response.raise_for_status()
            logger.info(
                "HubSpotConnector authenticated successfully for tenant=%s",
                self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HubSpotConnector.authenticate failed (HTTP %d): %s",
                exc.response.status_code,
                exc,
            )
            return False
        except Exception as exc:
            logger.exception(
                "HubSpotConnector.authenticate unexpected error: %s", exc
            )
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        """Return entity types this connector can extract."""
        return [
            EntitySchema(
                entity_type="contact",
                display_name="HubSpot Contacts",
                supports_incremental=True,
                fields=[
                    "id", "firstname", "lastname", "email",
                    "jobtitle", "department", "hs_object_id",
                ],
            ),
            EntitySchema(
                entity_type="company",
                display_name="HubSpot Companies",
                supports_incremental=True,
                fields=[
                    "id", "name", "industry", "annualrevenue",
                    "numberofemployees", "hs_object_id",
                ],
            ),
            EntitySchema(
                entity_type="deal",
                display_name="HubSpot Deals",
                supports_incremental=True,
                fields=[
                    "id", "dealname", "dealstage", "amount",
                    "closedate", "hubspot_owner_id", "hs_object_id",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Extract all records of the given entity type.

        Paginates via the `after` cursor in response["paging"]["next"]["after"].
        Fetches 100 records per page (HubSpot maximum per request).

        Args:
            entity_type: One of "contact", "company", "deal".

        Yields:
            RawRecord for each HubSpot object. The payload contains the
            properties dict (not the top-level response object).
        """
        if entity_type not in _OBJECT_CONFIG:
            raise ValueError(
                f"HubSpotConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(_OBJECT_CONFIG.keys())}"
            )

        config = _OBJECT_CONFIG[entity_type]
        base_url = f"{_BASE_URL}{config['endpoint']}"
        params: dict[str, Any] = {
            "limit": 100,
            "properties": config["properties"],
        }

        logger.info(
            "HubSpotConnector.extract_full: entity_type=%s tenant=%s",
            entity_type,
            self.tenant_id,
        )

        yield from self._paginate_hubspot(
            base_url=base_url,
            params=params,
            entity_type=entity_type,
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

        Uses the hs_lastmodifieddate__gt filter supported by HubSpot's
        CRM search API. Falls back to full extraction for entity types
        that do not support this filter.

        Args:
            entity_type: One of "contact", "company", "deal".
            cursor:      Contains last_extracted_at for the since filter.

        Returns:
            A 2-tuple of (record_iterator, updated_cursor).
        """
        if entity_type not in _OBJECT_CONFIG:
            raise ValueError(
                f"HubSpotConnector does not support entity_type='{entity_type}'."
            )

        config = _OBJECT_CONFIG[entity_type]
        base_url = f"{_BASE_URL}{config['endpoint']}"

        # HubSpot expects milliseconds since epoch for date filters
        since_ms = int(cursor.last_extracted_at.timestamp() * 1000)
        params: dict[str, Any] = {
            "limit": 100,
            "properties": config["properties"],
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "hs_lastmodifieddate",
                            "operator": "GT",
                            "value": str(since_ms),
                        }
                    ]
                }
            ],
        }

        logger.info(
            "HubSpotConnector.extract_incremental: entity_type=%s since=%s tenant=%s",
            entity_type,
            cursor.last_extracted_at.isoformat(),
            self.tenant_id,
        )

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_hubspot(
                base_url=base_url,
                params=params,
                entity_type=entity_type,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since_ms": since_ms},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        """
        Verify connectivity by fetching a single contact record.

        GET /crm/v3/objects/contacts?limit=1 is the lightest possible
        authenticated request against the HubSpot CRM API.
        """
        start = time.monotonic()
        try:
            url = f"{_BASE_URL}/crm/v3/objects/contacts"
            response = self._http_client.get(
                url,
                params={"limit": 1},
                headers=self._headers(),
            )
            response.raise_for_status()
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "HubSpotConnector health check OK: latency=%.1fms", latency_ms
            )
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning("HubSpotConnector health check failed: %s", exc)
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
        """Return HTTP headers with the Private App Bearer token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _paginate_hubspot(
        self,
        base_url: str,
        params: dict[str, Any],
        entity_type: str,
    ) -> Iterator[RawRecord]:
        """
        Paginate through HubSpot CRM results using the `after` cursor.

        HubSpot's pagination model returns a paging.next.after value when
        more results exist. We pass this as the `after` query parameter on
        subsequent requests until no next cursor is returned.

        Args:
            base_url:    The CRM object endpoint URL.
            params:      Base query parameters (limit, properties, etc.).
            entity_type: Used to populate RawRecord.entity_type.

        Yields:
            RawRecord for each HubSpot result object.
        """
        request_params = dict(params)  # shallow copy to avoid mutating caller's dict

        while True:
            try:
                response = self._get(
                    base_url,
                    params=request_params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "HubSpotConnector pagination error on %s: %s", base_url, exc
                )
                break

            results = response.get("results", [])
            for record in results:
                props = record.get("properties", {})
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type=entity_type,
                    source_id=record["id"],
                    tenant_id=self.tenant_id,
                    payload=props,
                    email_hint=props.get("email"),
                    name_hint=(
                        props.get("name")
                        or f"{props.get('firstname', '')} {props.get('lastname', '')}".strip()
                        or None
                    ),
                )

            # Check for next page cursor
            paging = response.get("paging", {})
            next_cursor = paging.get("next", {}).get("after")
            if not next_cursor:
                break  # No more pages

            request_params["after"] = next_cursor
