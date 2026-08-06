"""
scout/connectors/bamboohr.py — Production BambooHR HRIS Connector (Sprint 29)

BambooHR is the most common HRIS in PE-backed companies under 500 employees.
It competes directly with Workday in the $25M–$150M ARR mid-market segment.

Authentication:
  BambooHR uses HTTP Basic Auth with the API key as the username and the
  literal string "x" as the password. The API key is generated per-user
  in BambooHR Settings → API Keys. Keys are scoped to the generating user's
  permissions — use a dedicated integration user.

  Header: Authorization: Basic base64("{api_key}:x")

API structure:
  Base URL: https://api.bamboohr.com/api/gateway.php/{subdomain}/v1/
  - /employees/directory          → lightweight list of all employees
  - /employees/changed?since=...  → incremental changes (terminated + modified)
  - /employees/{id}?fields=...    → full detail per employee

Rate limits:
  BambooHR enforces a per-subdomain limit of ~100 requests/minute.
  We use 1.5 calls/second (90/min) to stay well below the limit with
  headroom for concurrent operations.

Entity types:
  - employee     → all current and terminated employees
  - time_off     → approved leave requests (for absence/attendance analysis)
"""

import base64
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

_API_VERSION = "v1"
_EMPLOYEE_FIELDS = ",".join([
    "id", "firstName", "lastName", "workEmail", "personalEmail",
    "jobTitle", "department", "division", "location",
    "supervisorId", "supervisorEmail",
    "employmentStatus", "employeeNumber",
    "hireDate", "originalHireDate", "terminationDate",
    "mobilePhone", "workPhone",
    "payType", "payRate", "payPer",
    "flsaCode", "exempt",
    "preferredName", "pronouns",
    "country", "state",
])


class BambooHRConnector(ConnectorBase):
    """
    Production BambooHR HRIS connector.

    Extracts employees and time-off requests from BambooHR's REST API.
    Uses API key Basic Auth. Handles cursor-based incremental extraction
    via the /employees/changed endpoint.

    Credentials (auth_data keys):
        api_key   — BambooHR API key (generate in Settings → API Keys)
        subdomain — BambooHR company subdomain, e.g. "acmecorp" for
                    acmecorp.bamboohr.com
    """

    CONNECTOR_ID = "bamboohr"
    DISPLAY_NAME = "BambooHR HRIS (Production)"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 1.5  # 90/min — well below BambooHR's 100/min limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._subdomain: str = ""
        self._auth_header: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Validate the API key by making a lightweight /meta/users request.

        BambooHR API keys don't expire, but they can be revoked or have
        insufficient scope. We verify by hitting a low-cost meta endpoint
        rather than pulling all employees during auth.
        """
        auth = self.credentials.auth_data
        api_key = auth.get("api_key", "")
        subdomain = auth.get("subdomain", "")

        if not api_key or not subdomain:
            logger.error(
                "BambooHRConnector: missing required auth_data keys "
                "(api_key, subdomain)"
            )
            return False

        self._subdomain = subdomain
        # BambooHR Basic Auth: base64("{api_key}:x")
        raw = f"{api_key}:x"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()

        try:
            # Lightweight validation — fetch 1 employee from directory
            url = f"{self._base_url()}/employees/directory"
            resp = self._http_client.get(
                url,
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(
                "BambooHRConnector authenticated: subdomain=%s tenant=%s",
                subdomain, self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.error(
                    "BambooHRConnector: API key rejected (403) — check "
                    "subdomain and key scope. tenant=%s", self.tenant_id
                )
            else:
                logger.error(
                    "BambooHRConnector.authenticate HTTP %d: %s",
                    exc.response.status_code, exc,
                )
            return False
        except Exception as exc:
            logger.exception(
                "BambooHRConnector.authenticate failed: %s", exc
            )
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        """Return entity types this connector can produce."""
        return [
            EntitySchema(
                entity_type="employee",
                display_name="BambooHR Employees",
                supports_incremental=True,
                fields=[
                    "id", "firstName", "lastName", "workEmail",
                    "jobTitle", "department", "division", "location",
                    "supervisorId", "employmentStatus", "employeeNumber",
                    "hireDate", "terminationDate", "payType", "payRate",
                ],
            ),
            EntitySchema(
                entity_type="time_off",
                display_name="BambooHR Time Off Requests",
                supports_incremental=True,
                fields=[
                    "id", "employeeId", "type", "status",
                    "startDate", "endDate", "amount", "notes",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Extract all records of the given entity type.

        For employees: uses the /employees/directory for the ID list, then
        fetches full detail per employee using the /employees/{id} endpoint.
        We use the directory as the pagination anchor since BambooHR doesn't
        support offset pagination on the full employee endpoint.

        For time_off: fetches all approved requests from the current year.
        """
        if entity_type == "employee":
            yield from self._extract_all_employees()
        elif entity_type == "time_off":
            yield from self._extract_time_off(since=None)
        else:
            raise ValueError(
                f"BambooHRConnector does not support entity_type='{entity_type}'. "
                f"Supported: employee, time_off"
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
        Extract only records changed since cursor.last_extracted_at.

        BambooHR's /employees/changed endpoint returns both modified and
        newly terminated employees since a given date — exactly what the
        Hire-to-Retire worker needs for real-time offboarding detection.
        """
        since_dt = cursor.last_extracted_at
        since_str = since_dt.strftime("%Y-%m-%d")

        if entity_type == "employee":
            def _generate() -> Iterator[RawRecord]:
                yield from self._extract_changed_employees(since=since_str)
        elif entity_type == "time_off":
            def _generate() -> Iterator[RawRecord]:
                yield from self._extract_time_off(since=since_str)
        else:
            raise ValueError(
                f"BambooHRConnector: unsupported entity_type '{entity_type}'"
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
        """Verify connectivity with a lightweight directory fetch."""
        start = time.monotonic()
        try:
            url = f"{self._base_url()}/employees/directory"
            resp = self._http_client.get(url, headers=self._headers())
            resp.raise_for_status()
            latency_ms = (time.monotonic() - start) * 1000
            logger.debug("BambooHR health OK: %.1fms", latency_ms)
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning("BambooHR health check failed: %s", exc)
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
        return (
            f"https://api.bamboohr.com/api/gateway.php"
            f"/{self._subdomain}/{_API_VERSION}"
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }

    def _extract_all_employees(self) -> Iterator[RawRecord]:
        """
        Fetch all employees using directory + per-employee detail calls.

        Strategy:
        1. GET /employees/directory → lightweight list with IDs and basic fields
        2. For each employee ID, GET /employees/{id}?fields=... → full detail

        BambooHR's directory response structure:
          {
            "fields": [...],
            "employees": [{"id": "123", "displayName": "...", ...}, ...]
          }
        """
        directory_url = f"{self._base_url()}/employees/directory"
        try:
            resp = self._get(directory_url, headers=self._headers())
        except Exception as exc:
            logger.error("BambooHR directory fetch failed: %s", exc)
            return

        employees = resp.get("employees", [])
        logger.info(
            "BambooHR: fetching detail for %d employees (tenant=%s)",
            len(employees), self.tenant_id,
        )

        for emp in employees:
            emp_id = str(emp.get("id", ""))
            if not emp_id:
                continue
            detail = self._fetch_employee_detail(emp_id)
            if detail:
                yield self._to_raw_record("employee", emp_id, detail)

    def _extract_changed_employees(self, since: str) -> Iterator[RawRecord]:
        """
        Fetch employees modified or terminated since the given date.

        BambooHR /employees/changed response:
          {
            "lastChanged": "2024-01-15T10:30:00+00:00",
            "employees": {
              "123": {"action": "updated"},
              "456": {"action": "deleted"}   ← terminated employees
            }
          }

        We fetch full detail for updated employees. For deleted (terminated)
        employees, BambooHR still returns data via /employees/{id} with
        employmentStatus=Terminated — we surface those too.
        """
        url = f"{self._base_url()}/employees/changed"
        params = {"since": since, "type": "inserted,updated,deleted"}
        try:
            resp = self._get(url, params=params, headers=self._headers())
        except Exception as exc:
            logger.error("BambooHR /employees/changed failed: %s", exc)
            return

        changed = resp.get("employees", {})
        logger.info(
            "BambooHR incremental: %d changed employees since=%s (tenant=%s)",
            len(changed), since, self.tenant_id,
        )

        for emp_id, meta in changed.items():
            detail = self._fetch_employee_detail(emp_id)
            if detail:
                # Surface deletion action in payload so H2R worker can act
                detail["_bamboohr_action"] = meta.get("action", "updated")
                yield self._to_raw_record("employee", emp_id, detail)

    def _fetch_employee_detail(self, emp_id: str) -> dict[str, Any] | None:
        """Fetch full employee detail including compensation fields."""
        url = f"{self._base_url()}/employees/{emp_id}"
        try:
            resp = self._get(
                url,
                params={"fields": _EMPLOYEE_FIELDS, "onlyCurrent": "false"},
                headers=self._headers(),
            )
            return resp
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                # Employee deleted entirely — log and skip
                logger.debug("BambooHR employee %s not found (404)", emp_id)
            else:
                logger.warning(
                    "BambooHR employee %s detail fetch failed: %s", emp_id, exc
                )
            return None
        except Exception as exc:
            logger.warning(
                "BambooHR employee %s detail fetch error: %s", emp_id, exc
            )
            return None

    def _extract_time_off(self, since: str | None) -> Iterator[RawRecord]:
        """
        Fetch approved time-off requests.

        Uses /time_off/requests/ with start/end date filters.
        If since is None, fetches current year's requests.
        """
        now = datetime.now(tz=timezone.utc)
        start = since or f"{now.year}-01-01"
        end = now.strftime("%Y-%m-%d")

        url = f"{self._base_url()}/time_off/requests/"
        params = {
            "start": start,
            "end": end,
            "status": "approved",
        }
        try:
            records = self._get(url, params=params, headers=self._headers())
        except Exception as exc:
            logger.error("BambooHR time_off fetch failed: %s", exc)
            return

        if isinstance(records, list):
            for record in records:
                req_id = str(record.get("id", ""))
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type="time_off",
                    source_id=req_id,
                    tenant_id=self.tenant_id,
                    payload=record,
                    email_hint=None,
                    name_hint=record.get("name"),
                )

    def _to_raw_record(
        self,
        entity_type: str,
        source_id: str,
        payload: dict[str, Any],
    ) -> RawRecord:
        """Convert a BambooHR employee dict to a RawRecord."""
        first = payload.get("firstName", "")
        last = payload.get("lastName", "")
        name = f"{first} {last}".strip() or None
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.tenant_id,
            payload=payload,
            email_hint=payload.get("workEmail") or payload.get("personalEmail"),
            name_hint=name,
        )
