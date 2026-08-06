"""
scout/connectors/brex.py — Production Brex Connector (Sprint 36)

Brex is a corporate card and spend management platform competing with Ramp,
targeted at startups and fast-growing companies. Common in PE-backed tech
portfolios, especially for companies with remote/distributed teams.

For Miragent:
  - Vendor spend visibility (who are we paying and how much?)
  - Offboarding: flag active Brex cards for departed employees
  - Department spend trends and anomalies
  - Expense policy compliance monitoring

Authentication:
  Brex uses OAuth 2.0. For machine-to-machine (service account) access,
  Brex issues a long-lived API token (not a standard OAuth flow).
  Header: Authorization: Bearer {api_token}

API structure:
  Base: https://platform.brexapis.com
  - /v2/users                → card holders
  - /v2/cards                → issued cards
  - /v2/transactions/card/primary → card transactions
  - /v2/expenses/card        → expense records with receipts

Pagination:
  Brex uses cursor-based pagination.
  Response: { "items": [...], "next_cursor": "cursor_token" }

Rate limits:
  Brex: No published hard limit; throttles at ~100/min with 429 responses.
  We use 1/sec (60/min) as a safe default.

Entity types:
  - user        → Brex card holders
  - card        → issued corporate cards
  - transaction → card transactions
  - expense     → expense records
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

_API_BASE = "https://platform.brexapis.com"
_PAGE_SIZE = 100


class BrexConnector(ConnectorBase):
    """
    Production Brex corporate card & expense connector.

    Uses a long-lived API token (Bearer) issued by Brex for service accounts.

    Credentials (auth_data keys):
        api_token  — Brex API token
    """

    CONNECTOR_ID = "brex"
    DISPLAY_NAME = "Brex Corporate Card (Production)"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 1.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_token: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        api_token = auth.get("api_token", "")

        if not api_token:
            logger.error("BrexConnector: missing required auth_data key 'api_token'")
            return False

        self._api_token = api_token

        # Validate token by fetching /v2/users
        try:
            resp = self._http_client.get(
                f"{_API_BASE}/v2/users",
                params={"limit": 1},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info("BrexConnector authenticated: tenant=%s", self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("BrexConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("BrexConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="Brex Users",
                supports_incremental=False,
                fields=[
                    "id", "first_name", "last_name", "email",
                    "status", "manager_id", "department_id",
                    "created_at",
                ],
            ),
            EntitySchema(
                entity_type="card",
                display_name="Brex Cards",
                supports_incremental=False,
                fields=[
                    "id", "owner", "last_four", "status",
                    "card_type", "limit_type", "spend_controls",
                    "created_at",
                ],
            ),
            EntitySchema(
                entity_type="transaction",
                display_name="Brex Transactions",
                supports_incremental=True,
                fields=[
                    "id", "card_id", "amount", "initiated_at",
                    "posted_at", "merchant", "category",
                    "user_id", "description",
                ],
            ),
            EntitySchema(
                entity_type="expense",
                display_name="Brex Expenses",
                supports_incremental=True,
                fields=[
                    "id", "memo", "amount", "category",
                    "merchant", "card_id", "user_id",
                    "receipts", "status",
                    "purchased_at", "updated_at",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        endpoint = self._entity_endpoint(entity_type)
        yield from self._paginate_brex(endpoint=endpoint, entity_type=entity_type)

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        endpoint = self._entity_endpoint(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_brex(
                endpoint=endpoint,
                entity_type=entity_type,
                from_date=since_iso,
            )

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": since_iso},
        )
        return _generate(), updated_cursor

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        start = time.monotonic()
        try:
            resp = self._get(
                f"{_API_BASE}/v2/users",
                params={"limit": 1},
                headers=self._headers(),
            )
            _ = resp.get("items", [])
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
            "Authorization": f"Bearer {self._api_token}",
            "Accept": "application/json",
        }

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "user":        "/v2/users",
            "card":        "/v2/cards",
            "transaction": "/v2/transactions/card/primary",
            "expense":     "/v2/expenses/card",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"BrexConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(endpoints)}"
            )
        return endpoints[entity_type]

    def _paginate_brex(
        self,
        endpoint: str,
        entity_type: str,
        from_date: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Brex API using cursor-based next_cursor pagination.
        Response: { "items": [...], "next_cursor": "token" }
        """
        params: dict[str, Any] = {"limit": _PAGE_SIZE}
        if from_date:
            params["initiated_at_start"] = from_date

        while True:
            try:
                resp = self._get(
                    f"{_API_BASE}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("BrexConnector pagination error (endpoint=%s): %s", endpoint, exc)
                break

            items = resp.get("items", [])
            for item in items:
                yield self._to_raw_record(entity_type, item)

            next_cursor = resp.get("next_cursor")
            if not next_cursor:
                break
            params = {"limit": _PAGE_SIZE, "cursor": next_cursor}
            if from_date:
                params["initiated_at_start"] = from_date

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = record.get("email")
        owner = record.get("owner", {})
        first = record.get("first_name", "") or owner.get("first_name", "")
        last = record.get("last_name", "") or owner.get("last_name", "")
        name = (
            f"{first} {last}".strip()
            or record.get("merchant", {}).get("raw_descriptor")
            or record.get("merchant")
            or record.get("description")
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
