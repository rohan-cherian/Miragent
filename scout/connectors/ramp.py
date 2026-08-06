"""
scout/connectors/ramp.py — Production Ramp Connector (Sprint 36)

Ramp is a fast-growing corporate card + expense management platform popular with
PE-backed tech and growth-stage companies ($10M–$500M ARR). For Miragent:
  - Track corporate spending by department, vendor, and category
  - Flag departing employees with active Ramp cards (offboarding risk)
  - Vendor spend benchmarking (are we overpaying vs. market?)
  - Detect anomalous spend spikes at the card or department level

Authentication:
  Ramp uses OAuth 2.0 Client Credentials.
  Token endpoint: https://api.ramp.com/developer/v1/token

API structure:
  Base: https://api.ramp.com/developer/v1
  - /users                 → card holders
  - /cards                 → issued cards
  - /transactions          → transaction records
  - /departments           → department list
  - /vendors               → vendor master

Pagination:
  Ramp uses cursor-based pagination.
  Response: { "data": [...], "page": { "next": "cursor_token" } }

Rate limits:
  Ramp: 1000 requests/hour per client.
  We use 0.25/sec (15/min) as a safe default.

Entity types:
  - user         → Ramp card holders
  - card         → issued corporate cards
  - transaction  → card transactions
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

_TOKEN_URL = "https://api.ramp.com/developer/v1/token"
_API_BASE = "https://api.ramp.com/developer/v1"
_PAGE_SIZE = 100


class RampConnector(ConnectorBase):
    """
    Production Ramp corporate card & expense connector.

    Credentials (auth_data keys):
        client_id      — Ramp OAuth client ID
        client_secret  — Ramp OAuth client secret
        scope          — OAuth scope (default: "transactions:read cards:read users:read")
    """

    CONNECTOR_ID = "ramp"
    DISPLAY_NAME = "Ramp Corporate Card (Production)"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 0.25

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        scope = auth.get("scope", "transactions:read cards:read users:read")

        if not client_id or not client_secret:
            logger.error("RampConnector: missing 'client_id' or 'client_secret'")
            return False

        try:
            resp = self._http_client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": scope,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("RampConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 3600)
            logger.info("RampConnector authenticated: tenant=%s", self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("RampConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("RampConnector auth error: %s", exc)
            return False

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
                display_name="Ramp Users",
                supports_incremental=False,
                fields=[
                    "id", "first_name", "last_name", "email",
                    "phone", "role", "status", "department_id",
                    "location_id", "manager_id",
                    "created_at", "updated_at",
                ],
            ),
            EntitySchema(
                entity_type="card",
                display_name="Ramp Cards",
                supports_incremental=False,
                fields=[
                    "id", "display_name", "last_four", "cardholder_id",
                    "status", "spending_restrictions",
                    "fulfillment", "created_at",
                ],
            ),
            EntitySchema(
                entity_type="transaction",
                display_name="Ramp Transactions",
                supports_incremental=True,
                fields=[
                    "id", "amount", "currency_code", "user_transaction_time",
                    "merchant_name", "merchant_category_code",
                    "card_id", "user_id", "department_id",
                    "memo", "receipts", "policy_violations",
                    "sk_category_name", "statement_descriptor",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        endpoint = self._entity_endpoint(entity_type)
        yield from self._paginate_ramp(endpoint=endpoint, entity_type=entity_type)

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
            yield from self._paginate_ramp(
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
            self._refresh_if_needed()
            resp = self._get(
                f"{_API_BASE}/users",
                params={"page_size": 1},
                headers=self._headers(),
            )
            _ = resp.get("data", [])
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

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "user":        "/users",
            "card":        "/cards",
            "transaction": "/transactions",
        }
        if entity_type not in endpoints:
            raise ValueError(
                f"RampConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(endpoints)}"
            )
        return endpoints[entity_type]

    def _paginate_ramp(
        self,
        endpoint: str,
        entity_type: str,
        from_date: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Ramp API using cursor-based pagination.
        Response: { "data": [...], "page": { "next": "cursor_string" } }
        """
        self._refresh_if_needed()
        params: dict[str, Any] = {"page_size": _PAGE_SIZE}
        if from_date:
            params["from_date"] = from_date

        while True:
            try:
                resp = self._get(
                    f"{_API_BASE}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("RampConnector pagination error (endpoint=%s): %s", endpoint, exc)
                break

            items = resp.get("data", [])
            for item in items:
                yield self._to_raw_record(entity_type, item)

            next_cursor = resp.get("page", {}).get("next")
            if not next_cursor:
                break
            params = {"page_size": _PAGE_SIZE, "start": next_cursor}
            if from_date:
                params["from_date"] = from_date

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = record.get("email")
        name = (
            f"{record.get('first_name', '')} {record.get('last_name', '')}".strip()
            or record.get("display_name")
            or record.get("merchant_name")
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
