"""
scout/connectors/sage_intacct.py — Production Sage Intacct ERP Connector (Sprint 29)

Sage Intacct is the most common ERP alternative to NetSuite in PE-backed
services, nonprofit, and professional services companies. It holds about 15%
of the mid-market ERP segment and is particularly common in companies that
switched away from QuickBooks but aren't large enough for NetSuite or SAP.

Authentication:
  Sage Intacct uses a two-step session-based auth model:
  1. POST /ia/xml/xmlgw.phtml with credentials → receive a session ID
  2. All subsequent requests use that session ID in the auth block

  The Sage Intacct REST API v2 (newer) uses OAuth2. We support both:
  - Session-based auth (XML gateway) for companies on the classic API
  - Bearer token (REST API v2) for companies on the modern stack

  XML gateway format:
  POST https://api.intacct.com/ia/xml/xmlgw.phtml
  Content-Type: application/xml

  Response: sessionid in the XML body

Entity types:
  - vendor      → all vendors (for Vendor Benchmark Worker)
  - ap_bill     → accounts payable invoices / bills
  - ar_invoice  → accounts receivable invoices
  - gl_account  → chart of accounts
  - employee    → Intacct employee records (if HR module is used)

Rate limits:
  Sage Intacct limits concurrent sessions (typically 5 per company).
  There is no per-second rate limit, but queries should be batched.
  We use 2.0/sec as a safe conservative limit.
"""

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

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

_XML_GATEWAY_URL = "https://api.intacct.com/ia/xml/xmlgw.phtml"
_PAGE_SIZE = 100  # Sage Intacct max pagesize for XML queries


class SageIntacctConnector(ConnectorBase):
    """
    Production Sage Intacct ERP connector.

    Uses the Sage Intacct XML gateway (classic API). Authenticates via
    user/company credentials to obtain a session ID, then queries vendor,
    AP, AR, and GL data using READBYQUERY operations.

    Credentials (auth_data keys):
        company_id    — Sage Intacct company ID
        user_id       — Integration user login ID
        user_password — Integration user password
        sender_id     — Web services sender ID (from Sage Intacct setup)
        sender_password — Web services sender password
    """

    CONNECTOR_ID = "sage_intacct"
    DISPLAY_NAME = "Sage Intacct ERP (Production)"
    CATEGORY = ConnectorCategory.ERP
    CALLS_PER_SECOND = 2.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._session_id: str = ""
        self._company_id: str = ""
        self._sender_id: str = ""
        self._sender_password: str = ""
        self._control_id: int = 0  # incremented per request

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain a Sage Intacct session ID via the XML gateway.

        Sends a getAPISession operation with user credentials. The response
        contains a sessionid that is valid for ~1 hour and must be included
        in all subsequent API calls.
        """
        auth = self.credentials.auth_data
        company_id = auth.get("company_id", "")
        user_id = auth.get("user_id", "")
        user_password = auth.get("user_password", "")
        sender_id = auth.get("sender_id", "")
        sender_password = auth.get("sender_password", "")

        if not all([company_id, user_id, user_password, sender_id, sender_password]):
            logger.error(
                "SageIntacctConnector: missing auth_data keys "
                "(company_id, user_id, user_password, sender_id, sender_password)"
            )
            return False

        self._company_id = company_id
        self._sender_id = sender_id
        self._sender_password = sender_password

        xml_body = self._build_auth_xml(
            company_id=company_id,
            user_id=user_id,
            user_password=user_password,
            sender_id=sender_id,
            sender_password=sender_password,
        )

        try:
            resp = self._http_client.post(
                _XML_GATEWAY_URL,
                content=xml_body,
                headers={"Content-Type": "application/xml"},
            )
            resp.raise_for_status()
            session_id = self._parse_session_id(resp.text)
            if not session_id:
                logger.error(
                    "SageIntacctConnector: could not parse session ID from "
                    "auth response. tenant=%s", self.tenant_id
                )
                return False

            self._session_id = session_id
            logger.info(
                "SageIntacctConnector authenticated: company=%s tenant=%s",
                company_id, self.tenant_id,
            )
            return True
        except Exception as exc:
            logger.exception(
                "SageIntacctConnector.authenticate failed: %s", exc
            )
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="vendor",
                display_name="Sage Intacct Vendors",
                supports_incremental=True,
                fields=[
                    "VENDORID", "NAME", "STATUS", "VENDTYPE",
                    "CURRENCY", "TOTALDUE", "TOTALENTERED", "TOTALDUE",
                    "WHENCREATED", "WHENMODIFIED",
                    "CONTACTINFO.CONTACT.CONTACTNAME",
                    "CONTACTINFO.CONTACT.EMAIL1",
                ],
            ),
            EntitySchema(
                entity_type="ap_bill",
                display_name="Sage Intacct AP Bills",
                supports_incremental=True,
                fields=[
                    "RECORDNO", "VENDORID", "VENDORNAME",
                    "RECORDID", "TOTALAMOUNT", "TOTALDUE",
                    "CURRENCY", "WHENCREATED", "WHENDUE",
                    "WHENPAID", "STATE", "DESCRIPTION",
                    "WHENMODIFIED",
                ],
            ),
            EntitySchema(
                entity_type="ar_invoice",
                display_name="Sage Intacct AR Invoices",
                supports_incremental=True,
                fields=[
                    "RECORDNO", "CUSTOMERID", "CUSTOMERNAME",
                    "RECORDID", "TOTALAMOUNT", "TOTALDUE",
                    "CURRENCY", "WHENCREATED", "WHENDUE",
                    "STATE", "DESCRIPTION", "WHENMODIFIED",
                ],
            ),
            EntitySchema(
                entity_type="gl_account",
                display_name="Sage Intacct GL Accounts",
                supports_incremental=False,
                fields=[
                    "RECORDNO", "ACCOUNTNO", "TITLE", "ACCOUNTTYPE",
                    "STATUS", "NORMALBALANCE", "CLOSINGTYPE",
                    "WHENCREATED",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Full extraction using Sage Intacct READBYQUERY with pagination.

        Sage Intacct uses a page-based query system where we request
        page 1, 2, ... until the returned numremaining is 0.
        """
        object_map = {
            "vendor": "VENDOR",
            "ap_bill": "APBILL",
            "ar_invoice": "ARINVOICE",
            "gl_account": "GLACCOUNT",
        }
        if entity_type not in object_map:
            raise ValueError(
                f"SageIntacctConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(object_map)}"
            )

        yield from self._query_all(
            object_name=object_map[entity_type],
            entity_type=entity_type,
            query=None,  # no filter = full extract
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
        Incremental extraction using WHENMODIFIED filter.

        Sage Intacct's READBYQUERY supports WHERE clause filtering.
        We filter on WHENMODIFIED >= since_date to get only changed records.
        """
        object_map = {
            "vendor": "VENDOR",
            "ap_bill": "APBILL",
            "ar_invoice": "ARINVOICE",
            "gl_account": "GLACCOUNT",
        }
        if entity_type not in object_map:
            raise ValueError(
                f"SageIntacctConnector: unsupported entity_type '{entity_type}'"
            )

        since_str = cursor.last_extracted_at.strftime("%m/%d/%Y")
        query = f"WHENMODIFIED >= '{since_str}'"

        def _generate() -> Iterator[RawRecord]:
            yield from self._query_all(
                object_name=object_map[entity_type],
                entity_type=entity_type,
                query=query,
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
        """Verify session is valid by fetching a single vendor record."""
        start = time.monotonic()
        try:
            # Try to read one vendor — fast and non-destructive
            records = list(self._query_page(
                object_name="VENDOR",
                entity_type="vendor",
                query=None,
                page=1,
                page_size=1,
            ))
            latency_ms = (time.monotonic() - start) * 1000
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=True,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning("SageIntacct health check failed: %s", exc)
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=str(exc),
            )

    # ─────────────────────────────────────────────────────
    # PRIVATE HELPERS — XML construction and parsing
    # ─────────────────────────────────────────────────────

    def _next_control_id(self) -> str:
        self._control_id += 1
        return f"miragent-{self._control_id}"

    def _build_auth_xml(
        self,
        company_id: str,
        user_id: str,
        user_password: str,
        sender_id: str,
        sender_password: str,
    ) -> str:
        """Build the XML body for a getAPISession auth request."""
        ctrl_id = self._next_control_id()
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<request>
  <control>
    <senderid>{sender_id}</senderid>
    <password>{sender_password}</password>
    <controlid>{ctrl_id}</controlid>
    <uniqueid>false</uniqueid>
    <dtdversion>3.0</dtdversion>
    <includewhitespace>false</includewhitespace>
  </control>
  <operation>
    <authentication>
      <login>
        <userid>{user_id}</userid>
        <companyid>{company_id}</companyid>
        <password>{user_password}</password>
      </login>
    </authentication>
    <content>
      <function controlid="{ctrl_id}-func">
        <getAPISession/>
      </function>
    </content>
  </operation>
</request>"""

    def _build_query_xml(
        self,
        object_name: str,
        query: str | None,
        fields: str,
        page: int,
        page_size: int,
    ) -> str:
        """Build the XML body for a READBYQUERY request."""
        ctrl_id = self._next_control_id()
        query_clause = f"<query>{query}</query>" if query else "<query></query>"
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<request>
  <control>
    <senderid>{self._sender_id}</senderid>
    <password>{self._sender_password}</password>
    <controlid>{ctrl_id}</controlid>
    <uniqueid>false</uniqueid>
    <dtdversion>3.0</dtdversion>
    <includewhitespace>false</includewhitespace>
  </control>
  <operation>
    <authentication>
      <sessionid>{self._session_id}</sessionid>
    </authentication>
    <content>
      <function controlid="{ctrl_id}-func">
        <readByQuery>
          <object>{object_name}</object>
          {query_clause}
          <fields>{fields}</fields>
          <pagesize>{page_size}</pagesize>
          <returnformat>json</returnformat>
          <docparid></docparid>
        </readByQuery>
      </function>
    </content>
  </operation>
</request>"""

    def _parse_session_id(self, xml_text: str) -> str | None:
        """Extract sessionid from a getAPISession XML response."""
        try:
            root = ET.fromstring(xml_text)
            # Sage Intacct response: /response/operation/result/data/api/sessionid
            for tag in ["sessionid", "SESSIONID"]:
                el = root.find(f".//{tag}")
                if el is not None and el.text:
                    return el.text.strip()
            return None
        except ET.ParseError as exc:
            logger.error("SageIntacct: failed to parse session XML: %s", exc)
            return None

    def _query_all(
        self,
        object_name: str,
        entity_type: str,
        query: str | None,
    ) -> Iterator[RawRecord]:
        """Paginate through all results for a given object/query."""
        page = 1
        while True:
            records = list(self._query_page(
                object_name=object_name,
                entity_type=entity_type,
                query=query,
                page=page,
                page_size=_PAGE_SIZE,
            ))
            yield from records
            if len(records) < _PAGE_SIZE:
                break
            page += 1

    def _query_page(
        self,
        object_name: str,
        entity_type: str,
        query: str | None,
        page: int,
        page_size: int,
    ) -> Iterator[RawRecord]:
        """Execute a single paginated READBYQUERY and yield RawRecords."""
        xml_body = self._build_query_xml(
            object_name=object_name,
            query=query,
            fields="*",
            page=page,
            page_size=page_size,
        )

        try:
            resp = self._http_client.post(
                _XML_GATEWAY_URL,
                content=xml_body,
                headers={"Content-Type": "application/xml"},
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error(
                "SageIntacct query failed (object=%s page=%d): %s",
                object_name, page, exc,
            )
            return

        # Sage Intacct returns JSON payload wrapped in XML response
        # when returnformat=json. Parse the data section.
        records = self._parse_query_response(resp.text, object_name)
        for record in records:
            source_id = (
                str(record.get("RECORDNO") or record.get("VENDORID") or
                    record.get("CUSTOMERID") or record.get("ACCOUNTNO") or "")
            )
            yield RawRecord(
                connector_id=self.CONNECTOR_ID,
                entity_type=entity_type,
                source_id=source_id,
                tenant_id=self.tenant_id,
                payload=record,
                email_hint=self._extract_email(record),
                name_hint=(
                    record.get("NAME") or record.get("VENDORNAME") or
                    record.get("CUSTOMERNAME") or record.get("TITLE")
                ),
            )

    def _parse_query_response(
        self, xml_text: str, object_name: str
    ) -> list[dict[str, Any]]:
        """
        Parse Sage Intacct XML response and extract record list.

        When returnformat=json, the data is embedded as JSON text inside
        the XML <data> element. We parse the outer XML, then parse the
        inner JSON to get the records list.
        """
        import json
        try:
            root = ET.fromstring(xml_text)
            # Check for error status
            status_el = root.find(".//status")
            if status_el is not None and status_el.text == "failure":
                error_el = root.find(".//errorno")
                desc_el = root.find(".//description")
                raise RuntimeError(
                    f"Sage Intacct API error: "
                    f"{error_el.text if error_el is not None else 'unknown'} — "
                    f"{desc_el.text if desc_el is not None else ''}"
                )

            # Find data element
            data_el = root.find(".//data")
            if data_el is None:
                return []

            # The data element may contain JSON text for returnformat=json
            raw_text = "".join(data_el.itertext()).strip()
            if raw_text.startswith("[") or raw_text.startswith("{"):
                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    return parsed
                return [parsed]

            # Fallback: parse XML child elements as key-value dicts
            records = []
            for child in data_el:
                rec: dict[str, Any] = {}
                for field in child:
                    rec[field.tag] = field.text
                if rec:
                    records.append(rec)
            return records

        except ET.ParseError as exc:
            logger.error("SageIntacct: XML parse error: %s", exc)
            return []
        except Exception as exc:
            logger.error("SageIntacct: response parse error: %s", exc)
            return []

    def _extract_email(self, record: dict[str, Any]) -> str | None:
        """Try to find an email in a Sage Intacct record."""
        for key in ["EMAIL1", "EMAIL", "CONTACTEMAIL", "CONTACTINFO.CONTACT.EMAIL1"]:
            val = record.get(key)
            if val and "@" in val:
                return val
        return None
