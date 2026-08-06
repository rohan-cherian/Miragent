"""
scout/connectors/gusto.py — Production Gusto HCM Connector (Sprint 37)

Gusto is the dominant payroll + HR platform for SMB companies ($1M–$50M ARR).
In PE portfolios, it appears in consumer, media, and early-stage tech companies
that haven't migrated to enterprise HRIS (Workday, ADP, Rippling).

For Miragent:
  - Employee roster (headcount, compensation, tenure)
  - Offboarding: verify termination reflected in Gusto payroll
  - Compensation benchmarking signals (salary vs. market)
  - Contractor vs. employee classification risk

Authentication:
  Gusto uses OAuth 2.0 with a refresh token (standard authorization code flow).
  For partner integrations, Gusto issues refresh tokens via their partner API.
  Token endpoint: https://api.gusto.com/oauth/token

API structure:
  Base: https://api.gusto.com/v1
  - /companies/{company_id}/employees   → all employees
  - /companies/{company_id}/contractors → contractors
  - /companies/{company_id}/payrolls    → payroll runs
  - /companies/{company_id}/jobs        → job/positions

Pagination:
  Gusto uses page + per parameter.
  Response includes: X-Total-Count header and { "employees": [...] }

Rate limits:
  Gusto: No published hard limit; throttles around 120/min.
  We use 1.5/sec (90/min) as a safe default.

Entity types:
  - employee    → Gusto employee records
  - contractor  → Gusto contractor records
  - payroll     → payroll run summaries
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

_TOKEN_URL = "https://api.gusto.com/oauth/token"
_API_BASE = "https://api.gusto.com/v1"
_PAGE_SIZE = 100


class GustoConnector(ConnectorBase):
    """
    Production Gusto payroll + HR connector.

    Credentials (auth_data keys):
        client_id      — Gusto OAuth client ID
        client_secret  — Gusto OAuth client secret
        refresh_token  — Pre-issued refresh token
        company_id     — Gusto company UUID
    """

    CONNECTOR_ID = "gusto"
    DISPLAY_NAME = "Gusto Payroll & HR (Production)"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 1.5

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._company_id: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        refresh_token = auth.get("refresh_token", "")
        self._company_id = auth.get("company_id", "")

        if not all([client_id, client_secret, refresh_token, self._company_id]):
            logger.error(
                "GustoConnector: missing 'client_id', 'client_secret', "
                "'refresh_token', or 'company_id'"
            )
            return False

        try:
            resp = self._http_client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("GustoConnector: no access_token in response")
                return False
            self._access_token = token
            self._token_expires_at = time.time() + data.get("expires_in", 7200)
            logger.info(
                "GustoConnector authenticated: company=%s tenant=%s",
                self._company_id, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("GustoConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("GustoConnector auth error: %s", exc)
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
                entity_type="employee",
                display_name="Gusto Employees",
                supports_incremental=False,
                fields=[
                    "id", "uuid", "first_name", "last_name", "email",
                    "start_date", "termination_date",
                    "department", "manager_id", "job_title",
                    "onboarded", "terminated",
                    "jobs", "compensations",
                ],
            ),
            EntitySchema(
                entity_type="contractor",
                display_name="Gusto Contractors",
                supports_incremental=False,
                fields=[
                    "id", "uuid", "first_name", "last_name", "email",
                    "type", "wage_type", "start_date",
                    "is_active",
                ],
            ),
            EntitySchema(
                entity_type="payroll",
                display_name="Gusto Payroll Runs",
                supports_incremental=True,
                fields=[
                    "payroll_uuid", "company_id",
                    "pay_period", "check_date",
                    "processed", "totals",
                    "employee_compensations",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        if entity_type in ("employee", "contractor"):
            endpoint = self._entity_endpoint(entity_type)
            yield from self._paginate_gusto(endpoint=endpoint, entity_type=entity_type)
        elif entity_type == "payroll":
            yield from self._paginate_gusto(
                endpoint=f"/companies/{self._company_id}/payrolls",
                entity_type="payroll",
            )
        else:
            raise ValueError(
                f"GustoConnector does not support entity_type='{entity_type}'. "
                f"Supported: employee, contractor, payroll"
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
        Incremental for payroll: filter by processed date.
        Employees/contractors: full refresh (no filter support).
        """
        if entity_type == "payroll":
            since_iso = cursor.last_extracted_at.strftime("%Y-%m-%d")

            def _generate() -> Iterator[RawRecord]:
                yield from self._paginate_gusto(
                    endpoint=f"/companies/{self._company_id}/payrolls",
                    entity_type="payroll",
                    processed_after=since_iso,
                )
        else:
            def _generate() -> Iterator[RawRecord]:
                yield from self.extract_full(entity_type)

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
            checkpoint={"since": cursor.last_extracted_at.isoformat()},
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
                f"{_API_BASE}/companies/{self._company_id}/employees",
                params={"page": 1, "per": 1},
                headers=self._headers(),
            )
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
            "Content-Type": "application/json",
        }

    def _entity_endpoint(self, entity_type: str) -> str:
        endpoints = {
            "employee":   f"/companies/{self._company_id}/employees",
            "contractor": f"/companies/{self._company_id}/contractors",
            "payroll":    f"/companies/{self._company_id}/payrolls",
        }
        if entity_type not in endpoints:
            raise ValueError(f"GustoConnector: unknown entity_type '{entity_type}'")
        return endpoints[entity_type]

    def _paginate_gusto(
        self,
        endpoint: str,
        entity_type: str,
        processed_after: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate Gusto API using page/per parameters.
        Response is a JSON array directly (no wrapper key).
        """
        self._refresh_if_needed()
        page = 1

        while True:
            params: dict[str, Any] = {"page": page, "per": _PAGE_SIZE}
            if processed_after:
                params["processed_after"] = processed_after

            try:
                resp = self._get(
                    f"{_API_BASE}{endpoint}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("GustoConnector pagination error (endpoint=%s page=%d): %s", endpoint, page, exc)
                break

            # Gusto returns an array directly
            records = resp if isinstance(resp, list) else []
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            page += 1

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("uuid") or record.get("payroll_uuid") or record.get("id") or "")
        email = record.get("email")
        first = record.get("first_name", "")
        last = record.get("last_name", "")
        name = (
            f"{first} {last}".strip()
            or record.get("payroll_uuid")
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
