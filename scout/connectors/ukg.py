"""
scout/connectors/ukg.py — Production UKG Pro (Kronos/Ultimate) Connector (Sprint 30)

UKG Pro (formerly UltiPro / Ultimate Software) is the #2 HRIS in the PE mid-market
behind ADP. It's especially prevalent in PE-backed healthcare, retail, and logistics
companies. UKG is unique because it combines HRIS + Workforce Management (time &
attendance, scheduling) — giving Miragent access to both employee records AND
shift/scheduling data for workforce optimization insights.

Authentication:
  UKG Pro uses a two-step authentication:
  1. POST /api/login with username/password → receive an API key (session token)
  2. All subsequent requests use: US-Customer-Api-Key header + Authorization: Basic

  The API key from step 1 expires after 60 minutes. Miragent re-authenticates
  on each scan and refreshes proactively if the token is near expiry.

API structure:
  Base URL: https://{company_name}.ultipro.com
  - /api/employees/v1/employee-jobs          → employees with job assignments
  - /api/employees/v1/employee-bio           → biographical details
  - /api/attendance/v1/attendance-locations  → shift scheduling
  - /api/payroll/v1/payroll-runs             → payroll run metadata

Rate limits:
  UKG enforces 100 requests/minute per API key. We use 1.5/sec (90/min).

Entity types:
  - employee     → full employee record with job and org data
  - time_entry   → time and attendance records for workforce analysis
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

_PAGE_SIZE = 200  # UKG supports up to 200 per page


class UKGConnector(ConnectorBase):
    """
    Production UKG Pro HRIS + Workforce Management connector.

    Extracts employee records, job assignments, and time & attendance data.
    Unique value: time entry data enables workforce efficiency analysis
    that SFDC/Workday/NetSuite cannot provide.

    Credentials (auth_data keys):
        username      — UKG service account username
        password      — UKG service account password
        company_name  — UKG company short name (subdomain), e.g. "acmecorp"
        customer_api_key — UKG customer API key (from UKG Admin → Web Services)
    """

    CONNECTOR_ID = "ukg"
    DISPLAY_NAME = "UKG Pro HRIS + Workforce (Production)"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 1.5  # 90/min — below UKG's 100/min limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_key: str = ""           # session token from /api/login
        self._customer_api_key: str = ""  # permanent customer API key
        self._base_url: str = ""
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Authenticate with UKG Pro using the two-step API key flow.

        Step 1: POST /api/login → get session API key
        Step 2: Use session key + customer key in all requests
        """
        auth = self.credentials.auth_data
        username = auth.get("username", "")
        password = auth.get("password", "")
        company_name = auth.get("company_name", "")
        customer_api_key = auth.get("customer_api_key", "")

        if not all([username, password, company_name, customer_api_key]):
            logger.error(
                "UKGConnector: missing required auth_data keys "
                "(username, password, company_name, customer_api_key)"
            )
            return False

        self._base_url = f"https://{company_name}.ultipro.com"
        self._customer_api_key = customer_api_key

        # Build Basic Auth header for login
        basic = base64.b64encode(f"{username}:{password}".encode()).decode()

        try:
            resp = self._http_client.post(
                f"{self._base_url}/api/login",
                headers={
                    "Authorization": f"Basic {basic}",
                    "US-Customer-Api-Key": customer_api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._api_key = data.get("ApiKey", "")
            if not self._api_key:
                logger.error(
                    "UKGConnector: login succeeded but no ApiKey in response. "
                    "tenant=%s", self.tenant_id
                )
                return False

            self._token_expires_at = time.time() + 3300  # ~55 min (expire at 60)
            logger.info(
                "UKGConnector authenticated: company=%s tenant=%s",
                company_name, self.tenant_id,
            )
            return True

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                logger.error(
                    "UKGConnector: credentials rejected (401). "
                    "Verify username/password and customer_api_key. "
                    "tenant=%s", self.tenant_id
                )
            else:
                logger.error(
                    "UKGConnector.authenticate HTTP %d: %s",
                    exc.response.status_code, exc,
                )
            return False
        except Exception as exc:
            logger.exception("UKGConnector.authenticate error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        """Re-authenticate if session token is within 5 minutes of expiry."""
        if time.time() > self._token_expires_at - 300:
            logger.debug("UKGConnector: refreshing session token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="employee",
                display_name="UKG Pro Employees",
                supports_incremental=True,
                fields=[
                    # Identity
                    "EmployeeNumber", "FirstName", "LastName", "PreferredName",
                    # Employment
                    "EmploymentStatus", "EmploymentType", "HireDate", "TerminationDate",
                    "ReHireDate", "FullOrPartTime",
                    # Job
                    "JobCode", "JobTitle", "DepartmentCode", "DepartmentName",
                    "LocationCode", "LocationName",
                    # Org
                    "SupervisorEmployeeNumber", "SupervisorLastName", "SupervisorFirstName",
                    # Pay
                    "BasePay", "PayFrequency", "PayGrade", "PayGroup",
                    # Contact
                    "WorkEmailAddress", "MobilePhone",
                    # System
                    "LastModifiedDate", "ChangeReason",
                ],
            ),
            EntitySchema(
                entity_type="time_entry",
                display_name="UKG Time & Attendance",
                supports_incremental=True,
                fields=[
                    "EmployeeNumber", "Date", "StartTime", "EndTime",
                    "HoursWorked", "PayCode", "CostCenter",
                    "JobCode", "Location", "OvertimeHours",
                    "LastModifiedDate",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Full extraction via UKG Pro REST API with page-based pagination.
        """
        if entity_type == "employee":
            yield from self._extract_employees()
        elif entity_type == "time_entry":
            yield from self._extract_time_entries()
        else:
            raise ValueError(
                f"UKGConnector does not support entity_type='{entity_type}'. "
                f"Supported: employee, time_entry"
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
        Incremental extraction using UKG's lastModifiedDate filter.

        UKG supports `lastModifiedDate` as an OData-style filter on the
        employee-jobs endpoint, returning only workers changed since the date.
        """
        if entity_type not in ("employee", "time_entry"):
            raise ValueError(
                f"UKGConnector: unsupported entity_type '{entity_type}'"
            )

        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _generate() -> Iterator[RawRecord]:
            if entity_type == "employee":
                yield from self._extract_employees(since_iso=since_iso)
            else:
                yield from self._extract_time_entries(since_iso=since_iso)

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
        """Verify connectivity with a 1-record employee fetch."""
        start = time.monotonic()
        try:
            self._refresh_if_needed()
            resp = self._get(
                f"{self._base_url}/api/employees/v1/employee-jobs",
                params={"$top": 1, "$skip": 0},
                headers=self._headers(),
            )
            _ = resp  # successful parse is sufficient
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
        """
        UKG Pro requires both the session ApiKey and the permanent customer key
        in every request header.
        """
        basic = base64.b64encode(f"{self._api_key}:".encode()).decode()
        return {
            "Authorization": f"Basic {basic}",
            "US-Customer-Api-Key": self._customer_api_key,
            "US-Api-Key": self._api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _extract_employees(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        Paginate UKG employee-jobs endpoint.

        UKG response structure:
          [
            {"EmployeeNumber": "E001", "FirstName": "Alice", ...},
            ...
          ]

        UKG returns an array directly (no wrapper object). We use $top/$skip
        for pagination.
        """
        skip = 0
        while True:
            self._refresh_if_needed()
            params: dict[str, Any] = {"$top": _PAGE_SIZE, "$skip": skip}
            if since_iso:
                params["$filter"] = f"LastModifiedDate ge datetime'{since_iso}'"

            try:
                resp = self._get(
                    f"{self._base_url}/api/employees/v1/employee-jobs",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "UKGConnector employee-jobs fetch failed (skip=%d): %s",
                    skip, exc,
                )
                break

            # UKG returns array directly or wrapped in "Data"
            employees: list[dict] = []
            if isinstance(resp, list):
                employees = resp
            elif isinstance(resp, dict):
                employees = resp.get("Data", resp.get("employees", []))

            for emp in employees:
                yield self._to_raw_record("employee", emp)

            if len(employees) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE

    def _extract_time_entries(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        Extract time & attendance entries.

        UKG's time entry API is paginated with $top/$skip. For incremental,
        we filter by date range using the since_iso timestamp.
        """
        skip = 0
        while True:
            self._refresh_if_needed()
            params: dict[str, Any] = {"$top": _PAGE_SIZE, "$skip": skip}
            if since_iso:
                params["$filter"] = f"LastModifiedDate ge datetime'{since_iso}'"

            try:
                resp = self._get(
                    f"{self._base_url}/api/timekeeping/v1/time-entries",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "UKGConnector time-entries fetch failed (skip=%d): %s",
                    skip, exc,
                )
                break

            entries: list[dict] = []
            if isinstance(resp, list):
                entries = resp
            elif isinstance(resp, dict):
                entries = resp.get("Data", [])

            for entry in entries:
                yield RawRecord(
                    connector_id=self.CONNECTOR_ID,
                    entity_type="time_entry",
                    source_id=str(
                        entry.get("TimeEntryID")
                        or entry.get("id")
                        or f"{entry.get('EmployeeNumber', '')}_{entry.get('Date', '')}"
                    ),
                    tenant_id=self.tenant_id,
                    payload=entry,
                    email_hint=None,
                    name_hint=None,
                )

            if len(entries) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE

    def _to_raw_record(self, entity_type: str, emp: dict[str, Any]) -> RawRecord:
        """Convert a UKG employee dict to a RawRecord."""
        first = emp.get("FirstName", "")
        last = emp.get("LastName", "")
        name = f"{first} {last}".strip() or None
        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=str(emp.get("EmployeeNumber", emp.get("EmployeeId", ""))),
            tenant_id=self.tenant_id,
            payload=emp,
            email_hint=emp.get("WorkEmailAddress"),
            name_hint=name,
        )
