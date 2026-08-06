"""
scout/connectors/billcom.py — Production Bill.com Connector (Sprint 37)

Bill.com (now BILL) is a dominant accounts payable/receivable automation platform
for SMB and lower-mid-market companies ($5M–$100M ARR). Used heavily in professional
services, real estate, and non-profit PE portfolios.

For Miragent:
  - AP/AR visibility: who are we paying, what's outstanding?
  - Duplicate vendor detection (same vendor under multiple names)
  - Payment approval workflow gaps (unapproved bills)
  - Cash flow forecasting signals (upcoming due invoices)

Authentication:
  Bill.com uses a session-based API: login returns a sessionId that must
  be included in every subsequent request.
  POST /api/login.json → { sessionId: "..." }

API structure:
  Base: https://api.bill.com/api/v2
  - /List/Vendor.json            → vendor list
  - /List/Bill.json              → AP bills
  - /List/Invoice.json           → AR invoices
  - /List/Customer.json          → customer list

Pagination:
  Bill.com uses start + max parameters.
  Response: { "response_data": [...], "response_message": "Success" }
  When results < max, we've reached the end.

Rate limits:
  Bill.com: 1000 API calls/day for standard accounts.
  We use 0.25/sec (15/min) to be conservative.

Entity types:
  - vendor   → AP vendor/supplier records
  - bill     → AP bills (invoices received)
  - invoice  → AR invoices (invoices sent to customers)
  - customer → customer records
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

_API_BASE = "https://api.bill.com/api/v2"
_PAGE_SIZE = 999  # Bill.com max per request


class BillcomConnector(ConnectorBase):
    """
    Production Bill.com (BILL) AP/AR connector.

    Uses session-based auth: login to get a sessionId, pass it in every request.

    Credentials (auth_data keys):
        user_name      — Bill.com username (email)
        password       — Bill.com password
        org_id         — Bill.com organization ID
        dev_key        — Developer API key (required)
    """

    CONNECTOR_ID = "billcom"
    DISPLAY_NAME = "Bill.com AP/AR (Production)"
    CATEGORY = ConnectorCategory.FINANCE
    CALLS_PER_SECOND = 0.25

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._session_id: str = ""
        self._org_id: str = ""
        self._dev_key: str = ""

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        user_name = auth.get("user_name", "")
        password = auth.get("password", "")
        org_id = auth.get("org_id", "")
        dev_key = auth.get("dev_key", "")

        if not all([user_name, password, org_id, dev_key]):
            logger.error(
                "BillcomConnector: missing 'user_name', 'password', 'org_id', or 'dev_key'"
            )
            return False

        self._org_id = org_id
        self._dev_key = dev_key

        try:
            resp = self._http_client.post(
                f"{_API_BASE}/Login.json",
                data={
                    "userName": user_name,
                    "password": password,
                    "orgId": org_id,
                    "devKey": dev_key,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            session_id = data.get("response_data", {}).get("sessionId", "")
            if not session_id:
                logger.error(
                    "BillcomConnector: no sessionId in response. status=%s",
                    data.get("response_status"),
                )
                return False
            self._session_id = session_id
            logger.info("BillcomConnector authenticated: org=%s tenant=%s", org_id, self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("BillcomConnector auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("BillcomConnector auth error: %s", exc)
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Bill.com Vendors",
                supports_incremental=True,
                fields=[
                    "id", "name", "email", "phone", "address1",
                    "city", "state", "zipCode", "country",
                    "taxId", "paymentMethodPreference",
                    "isActive", "createdTime", "updatedTime",
                ],
            ),
            EntitySchema(
                entity_type="bill",
                display_name="Bill.com Bills (AP)",
                supports_incremental=True,
                fields=[
                    "id", "vendorId", "invoiceNumber", "invoiceDate",
                    "dueDate", "amount", "amountDue",
                    "paymentStatus", "approvalStatus",
                    "description", "isActive",
                    "createdTime", "updatedTime",
                ],
            ),
            EntitySchema(
                entity_type="invoice",
                display_name="Bill.com Invoices (AR)",
                supports_incremental=True,
                fields=[
                    "id", "customerId", "invoiceNumber", "invoiceDate",
                    "dueDate", "amount", "amountDue",
                    "paymentStatus", "description",
                    "isActive", "createdTime", "updatedTime",
                ],
            ),
            EntitySchema(
                entity_type="customer",
                display_name="Bill.com Customers",
                supports_incremental=True,
                fields=[
                    "id", "name", "email", "phone",
                    "address1", "city", "state", "zipCode",
                    "isActive", "createdTime", "updatedTime",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        object_type = self._entity_object_type(entity_type)
        yield from self._paginate_billcom(object_type=object_type, entity_type=entity_type)

    # ─────────────────────────────────────────────────────
    # INCREMENTAL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Incremental via Bill.com's filter on updatedTime.
        Bill.com filter format: [{"field":"updatedTime","op":">","value":"ISO"}]
        """
        object_type = self._entity_object_type(entity_type)
        since_iso = cursor.last_extracted_at.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
        filters = [{"field": "updatedTime", "op": ">", "value": since_iso}]

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_billcom(
                object_type=object_type,
                entity_type=entity_type,
                filters=filters,
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
                f"{_API_BASE}/List/Vendor.json",
                params={
                    "sessionId": self._session_id,
                    "devKey": self._dev_key,
                    "start": 0,
                    "max": 1,
                },
                headers=self._headers(),
            )
            _ = resp.get("response_data", [])
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
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def _entity_object_type(self, entity_type: str) -> str:
        types = {
            "vendor":   "Vendor",
            "bill":     "Bill",
            "invoice":  "Invoice",
            "customer": "Customer",
        }
        if entity_type not in types:
            raise ValueError(
                f"BillcomConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(types)}"
            )
        return types[entity_type]

    def _paginate_billcom(
        self,
        object_type: str,
        entity_type: str,
        filters: list | None = None,
    ) -> Iterator[RawRecord]:
        """
        Paginate Bill.com using start/max offset pagination.
        Response: { "response_data": [...], "response_message": "Success" }
        """
        import json as _json
        start = 0

        while True:
            params: dict[str, Any] = {
                "sessionId": self._session_id,
                "devKey": self._dev_key,
                "start": start,
                "max": _PAGE_SIZE,
            }
            if filters:
                params["filters"] = _json.dumps(filters)

            try:
                resp = self._get(
                    f"{_API_BASE}/List/{object_type}.json",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "BillcomConnector pagination error (type=%s start=%d): %s",
                    object_type, start, exc,
                )
                break

            records = resp.get("response_data", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            start += len(records)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("id", ""))
        email = record.get("email")
        name = (
            record.get("name")
            or record.get("invoiceNumber")
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
