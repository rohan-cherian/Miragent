"""
scout/connectors/pipedrive.py — Production Pipedrive CRM Connector (Sprint 37)

Pipedrive is a pipeline-centric CRM popular with sales-led SMB and growth-stage
companies ($5M–$50M ARR). Common in PE portfolios as an alternative to Salesforce
for companies that prioritize simplicity and deal-stage visibility.

For Miragent:
  - Pipeline health: deal velocity, stage conversion rates, stalled deals
  - Sales rep activity signals: low activity = churn/departure risk
  - Revenue forecast accuracy: deal close dates vs. actual
  - Offboarding: deals assigned to departed reps need reassignment

Authentication:
  Pipedrive supports:
    - API token: simple key passed as query param or header
    - OAuth 2.0: access + refresh token for user-delegated access

  API token auth: ?api_token={token} on every request (or header)

API structure:
  Base: https://api.pipedrive.com/v1
  - /deals              → deal records
  - /persons            → contact/person records
  - /organizations      → company records
  - /users              → Pipedrive user accounts (sales reps)
  - /activities         → activities/calls/meetings

Pagination:
  Pipedrive uses start + limit with a pagination object.
  Response: { "data": [...], "additional_data": { "pagination": { "more_items_in_collection": true, "next_start": 100 } } }

Rate limits:
  Pipedrive: 10 requests/second (Enterprise), 2/second (others).
  We use 2/sec as a safe default.

Entity types:
  - deal         → Pipedrive deal records
  - person       → contact/person records
  - organization → company records
  - user         → Pipedrive user accounts
  - activity     → activities (calls, meetings, tasks)
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

_API_BASE = "https://api.pipedrive.com/v1"
_PAGE_SIZE = 500  # Pipedrive max per request


class PipedriveConnector(ConnectorBase):
    """
    Production Pipedrive CRM connector.

    Credentials (auth_data keys — API Token):
        auth_mode   — "api_token" (default) or "oauth"
        api_token   — Pipedrive API token

    Credentials (auth_data keys — OAuth):
        auth_mode     — "oauth"
        access_token  — OAuth access token
    """

    CONNECTOR_ID = "pipedrive"
    DISPLAY_NAME = "Pipedrive CRM (Production)"
    CATEGORY = ConnectorCategory.CRM
    CALLS_PER_SECOND = 2.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_token: str = ""
        self._auth_mode: str = "api_token"

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "api_token")

        if self._auth_mode == "api_token":
            api_token = auth.get("api_token", "")
            if not api_token:
                logger.error("PipedriveConnector: missing 'api_token'")
                return False
            self._api_token = api_token
        elif self._auth_mode == "oauth":
            access_token = auth.get("access_token", "")
            if not access_token:
                logger.error("PipedriveConnector: missing 'access_token' for OAuth mode")
                return False
            self._api_token = access_token
        else:
            logger.error("PipedriveConnector: unknown auth_mode '%s'", self._auth_mode)
            return False

        # Validate by fetching the current user
        try:
            resp = self._http_client.get(
                f"{_API_BASE}/users/me",
                params={"api_token": self._api_token},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                logger.error("PipedriveConnector: API returned success=false")
                return False
            user = data.get("data", {})
            logger.info(
                "PipedriveConnector authenticated: user=%s tenant=%s",
                user.get("email", "?"), self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("PipedriveConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("PipedriveConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="deal",
                display_name="Pipedrive Deals",
                supports_incremental=True,
                fields=[
                    "id", "title", "status", "stage_id", "pipeline_id",
                    "value", "currency", "probability",
                    "expected_close_date", "close_time",
                    "owner_id", "person_id", "org_id",
                    "add_time", "update_time", "won_time", "lost_time",
                ],
            ),
            EntitySchema(
                entity_type="person",
                display_name="Pipedrive Persons",
                supports_incremental=True,
                fields=[
                    "id", "name", "email", "phone",
                    "org_id", "owner_id",
                    "label", "active_flag",
                    "add_time", "update_time",
                ],
            ),
            EntitySchema(
                entity_type="organization",
                display_name="Pipedrive Organizations",
                supports_incremental=True,
                fields=[
                    "id", "name", "address", "owner_id",
                    "open_deals_count", "closed_deals_count",
                    "won_deals_count", "lost_deals_count",
                    "active_flag", "add_time", "update_time",
                ],
            ),
            EntitySchema(
                entity_type="user",
                display_name="Pipedrive Users",
                supports_incremental=False,
                fields=[
                    "id", "name", "email", "phone", "role_id",
                    "active_flag", "default_currency",
                    "created", "modified",
                ],
            ),
            EntitySchema(
                entity_type="activity",
                display_name="Pipedrive Activities",
                supports_incremental=True,
                fields=[
                    "id", "type", "subject", "done",
                    "due_date", "due_time", "duration",
                    "deal_id", "person_id", "org_id",
                    "user_id", "note",
                    "add_time", "update_time",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        endpoint = self._entity_endpoint(entity_type)
        yield from self._paginate_pipedrive(endpoint=endpoint, entity_type=entity_type)

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Incremental via Pipedrive's filter: updated_since parameter.
        Format: ?updated_since=2026-01-01+00:00:00
        """
        endpoint = self._entity_endpoint(entity_type)
        since_str = cursor.last_extracted_at.strftime("%Y-%m-%d %H:%M:%S")

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_pipedrive(
                endpoint=endpoint,
                entity_type=entity_type,
                updated_since=since_str,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since_str},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{_API_BASE}/users/me",
                params={"api_token": self._api_token},
                headers={"Accept": "application/json"},
            )
            _ = resp.get("data", {})
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

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "deal":         "/deals",
            "person":       "/persons",
            "organization": "/organizations",
            "user":         "/users",
            "activity":     "/activities",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"PipedriveConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(endpoints)}"
            )
        return endpoints[entity_type]

    def _paginate_pipedrive(
        self,
        endpoint: str,
        entity_type: str,
        updated_since: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Pipedrive using start/limit with additional_data.pagination.
        Response: {
          "data": [...],
          "additional_data": { "pagination": { "more_items_in_collection": true, "next_start": 100 } }
        }
        """
        start = 0

        while True:
            params: dict[str, Any] = {
                "api_token": self._api_token,
                "start": start,
                "limit": _PAGE_SIZE,
            }
            if updated_since:
                params["updated_since"] = updated_since

            try:
                resp = self._get(
                    f"{_API_BASE}{endpoint}",
                    params=params,
                    headers={"Accept": "application/json"},
                )
            except Exception as exc:
                logger.error("PipedriveConnector pagination error (endpoint=%s): %s", endpoint, exc)
                break

            records = resp.get("data") or []
            for record in records:
                yield self._to_raw_record(entity_type, record)

            pagination = resp.get("additional_data", {}).get("pagination", {})
            if not pagination.get("more_items_in_collection"):
                break
            start = pagination.get("next_start", start + len(records))

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        # Email can be a list of {value, primary, label} objects or a string
        email_raw = record.get("email")
        if isinstance(email_raw, list):
            primary = next((e["value"] for e in email_raw if e.get("primary")), None)
            email = primary or (email_raw[0]["value"] if email_raw else None)
        else:
            email = email_raw

        name = (
            record.get("name")
            or record.get("title")
            or record.get("subject")
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
