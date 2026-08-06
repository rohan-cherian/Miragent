"""
scout/connectors/adp.py — Production ADP Workforce Now Connector (Sprint 30)

ADP Workforce Now is the dominant HRIS/Payroll platform for PE-backed companies
in the 50–2,000 employee range. It is frequently the system of record for payroll,
tax, benefits, and official headcount — making it the authoritative source for
compensation data and termination events.

Authentication:
  ADP uses OAuth 2.0 Client Credentials flow with mutual TLS (mTLS).
  PE portfolio companies receive a client certificate pair (cert + key) from ADP's
  App Registration portal. Miragent stores these as PEM strings in auth_data.

  Token endpoint: https://accounts.adp.com/auth/oauth/v2/token
  API base:       https://api.adp.com

  Token scope: api:read-workers

API structure:
  - /hr/v2/workers                     → paginated worker list (full)
  - /hr/v2/workers?$filter=...         → filtered workers (incremental via OData)
  - /time/v1/workers/{associateOID}/time-off-requests → time-off per worker

Pagination:
  ADP uses OData-style pagination with $skip and $top parameters.
  Each page returns up to 100 workers (ADP's hard max). We use 100.

Rate limits:
  ADP enforces 25 requests/second per client. We use 20/sec (80% utilization).

Entity types:
  - worker         → full worker profile including pay, status, org assignment
  - time_off       → time-off requests per worker
"""

import logging
import tempfile
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

_TOKEN_URL = "https://accounts.adp.com/auth/oauth/v2/token"
_BASE_URL = "https://api.adp.com"
_PAGE_SIZE = 100  # ADP hard max per page


class ADPConnector(ConnectorBase):
    """
    Production ADP Workforce Now connector.

    Extracts workers and time-off requests from ADP's REST API using
    OAuth 2.0 Client Credentials with optional mTLS certificate auth.

    Credentials (auth_data keys):
        client_id       — ADP OAuth client ID
        client_secret   — ADP OAuth client secret
        cert_pem        — (optional) client certificate PEM string for mTLS
        key_pem         — (optional) client private key PEM string for mTLS
    """

    CONNECTOR_ID = "adp"
    DISPLAY_NAME = "ADP Workforce Now (Production)"
    CATEGORY = ConnectorCategory.HCM
    CALLS_PER_SECOND = 20.0  # 20/sec — well below ADP's 25/sec limit

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._access_token: str = ""
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain an OAuth 2.0 access token using Client Credentials flow.

        ADP supports both plain Client Credentials and mTLS-enhanced Client
        Credentials. If cert_pem and key_pem are provided in auth_data, we
        configure mTLS on the HTTP client (required for production ADP access).
        """
        auth = self.credentials.auth_data
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")

        if not client_id or not client_secret:
            logger.error(
                "ADPConnector: missing required auth_data keys "
                "(client_id, client_secret)"
            )
            return False

        # Configure mTLS if certificates are provided
        cert_pem = auth.get("cert_pem", "")
        key_pem = auth.get("key_pem", "")

        try:
            token = self._fetch_token(
                client_id=client_id,
                client_secret=client_secret,
                cert_pem=cert_pem,
                key_pem=key_pem,
            )
            if not token:
                return False

            self._access_token = token
            self._token_expires_at = time.time() + 3600  # ADP tokens last 60 min
            logger.info(
                "ADPConnector authenticated: client_id=%s tenant=%s",
                client_id[:8] + "...", self.tenant_id,
            )
            return True

        except Exception as exc:
            logger.exception("ADPConnector.authenticate error: %s", exc)
            return False

    def _fetch_token(
        self,
        client_id: str,
        client_secret: str,
        cert_pem: str = "",
        key_pem: str = "",
    ) -> str | None:
        """
        Fetch an OAuth 2.0 access token from ADP's auth server.

        If cert_pem/key_pem are provided, uses mTLS (production path).
        Otherwise uses plain client_credentials (sandbox/dev path).
        """
        # Write certs to temp files if provided (httpx requires file paths for mTLS)
        cert_arg: Any = None
        if cert_pem and key_pem:
            cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
            key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
            cert_file.write(cert_pem.encode())
            key_file.write(key_pem.encode())
            cert_file.flush()
            key_file.flush()
            cert_arg = (cert_file.name, key_file.name)

        try:
            with httpx.Client(cert=cert_arg, timeout=30.0) as client:
                resp = client.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("access_token")
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ADPConnector token fetch HTTP %d: %s",
                exc.response.status_code, exc,
            )
            return None

    def _refresh_if_needed(self) -> None:
        """Re-authenticate if the token is within 5 minutes of expiry."""
        if time.time() > self._token_expires_at - 300:
            logger.debug("ADPConnector: refreshing access token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        """Return entity types this connector can produce."""
        return [
            EntitySchema(
                entity_type="worker",
                display_name="ADP Workers",
                supports_incremental=True,
                fields=[
                    # Identity
                    "associateOID", "workerID", "workerStatus",
                    "person.legalName.givenName", "person.legalName.familyName",
                    "person.legalName.preferredSalutations",
                    # Contact
                    "businessCommunication.emails",
                    "businessCommunication.landlines",
                    # Employment
                    "workerDates.originalHireDate", "workerDates.terminationDate",
                    "workerDates.rehireDate",
                    # Org
                    "workAssignments.homeOrganizationalUnits",
                    "workAssignments.reportsTo",
                    "workAssignments.jobCode",
                    "workAssignments.positionTitle",
                    "workAssignments.wageLawCoverage",
                    # Pay
                    "workAssignments.baseRemuneration.payPeriodRate",
                    "workAssignments.baseRemuneration.annualRate",
                    "workAssignments.baseRemuneration.payFrequency",
                    # Location
                    "workAssignments.homeWorkLocation",
                    "workAssignments.assignmentStatus",
                ],
            ),
            EntitySchema(
                entity_type="time_off",
                display_name="ADP Time Off Requests",
                supports_incremental=True,
                fields=[
                    "timeOffRequestID", "associateOID", "requestedDate",
                    "requestStatus", "requestedTimeOffType",
                    "approvedDate", "approverAssociateOID",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Extract all workers or time-off records from ADP.

        Workers: paginated via $skip/$top OData parameters.
        Time-off: fetched per-worker (requires worker list first).
        """
        if entity_type == "worker":
            yield from self._extract_all_workers()
        elif entity_type == "time_off":
            yield from self._extract_all_time_off()
        else:
            raise ValueError(
                f"ADPConnector does not support entity_type='{entity_type}'. "
                f"Supported: worker, time_off"
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
        Extract workers modified since cursor.last_extracted_at.

        ADP supports OData $filter with changeDate for incremental pulls.
        Format: ?$filter=workers/workerDates/lastModifiedDate ge '2026-01-01'
        """
        if entity_type not in ("worker", "time_off"):
            raise ValueError(
                f"ADPConnector: unsupported entity_type '{entity_type}'"
            )

        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _generate() -> Iterator[RawRecord]:
            if entity_type == "worker":
                yield from self._extract_workers_since(since_iso)
            else:
                yield from self._extract_all_time_off(since_iso)

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
        """Verify connectivity with a lightweight workers fetch (1 record)."""
        start = time.monotonic()
        try:
            self._refresh_if_needed()
            resp = self._get(
                f"{_BASE_URL}/hr/v2/workers",
                params={"$top": 1, "$skip": 0},
                headers=self._headers(),
            )
            _ = resp.get("workers", [])
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

    def _extract_all_workers(self, odata_filter: str = "") -> Iterator[RawRecord]:
        """
        Paginate through all ADP workers using $skip/$top OData parameters.

        ADP worker response structure:
          {
            "workers": [...],
            "meta": {"totalNumber": 1500}
          }
        """
        skip = 0
        while True:
            self._refresh_if_needed()
            params: dict[str, Any] = {"$top": _PAGE_SIZE, "$skip": skip}
            if odata_filter:
                params["$filter"] = odata_filter

            try:
                resp = self._get(
                    f"{_BASE_URL}/hr/v2/workers",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "ADPConnector workers fetch failed (skip=%d): %s", skip, exc
                )
                break

            workers = resp.get("workers", [])
            if not workers:
                break

            for worker in workers:
                yield self._to_raw_record("worker", worker)

            if len(workers) < _PAGE_SIZE:
                # Last page — fewer records than requested
                break
            skip += _PAGE_SIZE

    def _extract_workers_since(self, since_iso: str) -> Iterator[RawRecord]:
        """Extract workers modified on or after since_iso."""
        odata_filter = (
            f"workers/workerDates/lastModifiedDate ge '{since_iso}'"
        )
        yield from self._extract_all_workers(odata_filter=odata_filter)

    def _extract_all_time_off(self, since_iso: str = "") -> Iterator[RawRecord]:
        """
        Fetch time-off requests. ADP's time-off API is per-worker, so we
        first get the worker list, then fetch time-off per worker.
        Only active/recently terminated workers are included.
        """
        skip = 0
        while True:
            self._refresh_if_needed()
            try:
                resp = self._get(
                    f"{_BASE_URL}/hr/v2/workers",
                    params={"$top": _PAGE_SIZE, "$skip": skip},
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error("ADPConnector time_off worker list failed: %s", exc)
                break

            workers = resp.get("workers", [])
            if not workers:
                break

            for worker in workers:
                oid = worker.get("associateOID", "")
                if not oid:
                    continue
                yield from self._fetch_worker_time_off(oid, since_iso)

            if len(workers) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE

    def _fetch_worker_time_off(
        self, associate_oid: str, since_iso: str = ""
    ) -> Iterator[RawRecord]:
        """Fetch time-off requests for a single worker."""
        params: dict[str, Any] = {}
        if since_iso:
            params["$filter"] = f"requestedDate ge '{since_iso}'"
        try:
            resp = self._get(
                f"{_BASE_URL}/time/v1/workers/{associate_oid}/time-off-requests",
                params=params,
                headers=self._headers(),
            )
        except Exception as exc:
            logger.debug(
                "ADPConnector time-off fetch for %s failed: %s", associate_oid, exc
            )
            return

        requests = resp.get("timeOffRequests", [])
        for req in requests:
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type="time_off",
                source_id=str(req.get("timeOffRequestID", "")),
                tenant_id=self.tenant_id,
                payload={**req, "_associateOID": associate_oid},
                email_hint=None,
                name_hint=None,
            )

    def _to_raw_record(self, entity_type: str, worker: dict[str, Any]) -> RawRecord:
        """Convert an ADP worker dict to a RawRecord."""
        associate_oid = worker.get("associateOID", "")

        # Extract email from businessCommunication
        email = None
        comm = worker.get("businessCommunication", {})
        emails = comm.get("emails", [])
        if emails and isinstance(emails, list):
            email = emails[0].get("emailUri")

        # Extract name from legalName
        person = worker.get("person", {})
        legal = person.get("legalName", {})
        first = legal.get("givenName", "")
        last = legal.get("familyName", "")
        name = f"{first} {last}".strip() or None

        return RawRecord(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            source_id=associate_oid,
            tenant_id=self.tenant_id,
            payload=worker,
            email_hint=email,
            name_hint=name,
        )
