"""
scout/connectors/servicenow.py — Production ServiceNow Connector (Sprint 34)

ServiceNow is the dominant ITSM platform in PE-backed mid-to-large enterprises.
For Miragent, ServiceNow is a signal source for:
  - Employee onboarding/offboarding tickets (HR Service Delivery)
  - System access requests (which systems a person has)
  - Change management records (infra changes that affect risk)
  - Incident records (recurring issues = operational risk signal)

Authentication:
  ServiceNow supports Basic Auth (username/password) and OAuth 2.0.
  Most integrations use Basic Auth with a dedicated service account.
  OAuth 2.0 uses the "Password" or "Client Credentials" grant.

  For Basic Auth:
    Header: Authorization: Basic base64("{username}:{password}")
  For OAuth:
    POST /oauth_token.do → access_token

API structure (ServiceNow Table API):
  Base: https://{instance}.service-now.com
  - /api/now/table/sys_user           → users
  - /api/now/table/sc_request         → service catalog requests
  - /api/now/table/incident           → incidents
  - /api/now/table/change_request     → change requests
  - /api/now/table/task               → generic tasks

Pagination:
  ServiceNow uses offset + limit with Link header (RFC 5988).
  Response headers include: Link: <url>; rel="next", <url>; rel="last"
  Also supports sysparm_offset / sysparm_limit query params.

Rate limits:
  ServiceNow: 250 concurrent sessions; no hard per-minute limit for Table API.
  We use 10/sec (600/min) as a safe default.

Entity types:
  - user            → ServiceNow sys_user records (employee directory)
  - request         → service catalog requests (HR, IT, access)
  - incident        → IT incident records
  - change_request  → change management records
"""

import base64
import logging
import re
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

_PAGE_SIZE = 1000  # ServiceNow Table API max


class ServiceNowConnector(ConnectorBase):
    """
    Production ServiceNow ITSM connector.

    Supports Basic Auth and OAuth 2.0 (password grant) for ServiceNow.
    Covers sys_user, service catalog requests, incidents, and change requests.

    Credentials (auth_data keys — Basic Auth):
        auth_mode  — "basic" (default) or "oauth2"
        instance   — ServiceNow instance name, e.g. "acme" (→ acme.service-now.com)
        username   — ServiceNow service account username
        password   — ServiceNow service account password

    Credentials (auth_data keys — OAuth2):
        auth_mode     — "oauth2"
        instance      — ServiceNow instance name
        client_id     — OAuth client ID
        client_secret — OAuth client secret
        username      — User for password grant
        password      — Password for password grant
    """

    CONNECTOR_ID = "servicenow"
    DISPLAY_NAME = "ServiceNow ITSM (Production)"
    CATEGORY = ConnectorCategory.ITSM
    CALLS_PER_SECOND = 10.0

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._auth_mode: str = "basic"
        self._auth_header: str = ""
        self._base_url: str = ""
        self._token_expires_at: float = 0.0

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        auth = self.credentials.auth_data
        self._auth_mode = auth.get("auth_mode", "basic")
        instance = auth.get("instance", "")

        if not instance:
            logger.error("ServiceNowConnector: missing required auth_data key 'instance'")
            return False

        self._base_url = f"https://{instance}.service-now.com"

        if self._auth_mode == "basic":
            return self._authenticate_basic(auth)
        elif self._auth_mode == "oauth2":
            return self._authenticate_oauth2(auth)
        else:
            logger.error(
                "ServiceNowConnector: unknown auth_mode '%s'. Use 'basic' or 'oauth2'.",
                self._auth_mode,
            )
            return False

    def _authenticate_basic(self, auth: dict) -> bool:
        username = auth.get("username", "")
        password = auth.get("password", "")
        if not username or not password:
            logger.error("ServiceNowConnector Basic: missing 'username' or 'password'")
            return False

        raw = f"{username}:{password}"
        self._auth_header = "Basic " + base64.b64encode(raw.encode()).decode()

        # Validate by fetching 1 user
        try:
            resp = self._http_client.get(
                f"{self._base_url}/api/now/table/sys_user",
                params={"sysparm_limit": 1, "sysparm_offset": 0},
                headers=self._headers(),
            )
            resp.raise_for_status()
            logger.info(
                "ServiceNowConnector Basic authenticated: instance=%s tenant=%s",
                auth.get("instance"), self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("ServiceNowConnector Basic auth HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("ServiceNowConnector Basic auth error: %s", exc)
            return False

    def _authenticate_oauth2(self, auth: dict) -> bool:
        client_id = auth.get("client_id", "")
        client_secret = auth.get("client_secret", "")
        username = auth.get("username", "")
        password = auth.get("password", "")

        if not all([client_id, client_secret, username, password]):
            logger.error(
                "ServiceNowConnector OAuth2: missing client_id, client_secret, username, or password"
            )
            return False

        try:
            resp = self._http_client.post(
                f"{self._base_url}/oauth_token.do",
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token", "")
            if not token:
                logger.error("ServiceNowConnector OAuth2: no access_token in response")
                return False
            self._auth_header = f"Bearer {token}"
            self._token_expires_at = time.time() + data.get("expires_in", 1800)
            logger.info("ServiceNowConnector OAuth2 authenticated: tenant=%s", self.tenant_id)
            return True
        except httpx.HTTPStatusError as exc:
            logger.error("ServiceNowConnector OAuth2 HTTP %d: %s", exc.response.status_code, exc)
            return False
        except Exception as exc:
            logger.exception("ServiceNowConnector OAuth2 error: %s", exc)
            return False

    def _refresh_if_needed(self) -> None:
        if self._auth_mode == "oauth2" and time.time() > self._token_expires_at - 300:
            logger.debug("ServiceNowConnector: refreshing OAuth2 token")
            self.authenticate()

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        return [
            EntitySchema(
                entity_type="user",
                display_name="ServiceNow Users",
                supports_incremental=True,
                fields=[
                    "sys_id", "user_name", "first_name", "last_name",
                    "email", "phone", "title", "department",
                    "manager", "location", "active",
                    "employee_number", "cost_center",
                    "sys_created_on", "sys_updated_on",
                ],
            ),
            EntitySchema(
                entity_type="request",
                display_name="ServiceNow Service Catalog Requests",
                supports_incremental=True,
                fields=[
                    "sys_id", "number", "short_description",
                    "requested_for", "opened_by", "state",
                    "priority", "category", "approval",
                    "opened_at", "closed_at",
                    "sys_created_on", "sys_updated_on",
                ],
            ),
            EntitySchema(
                entity_type="incident",
                display_name="ServiceNow Incidents",
                supports_incremental=True,
                fields=[
                    "sys_id", "number", "short_description",
                    "caller_id", "assigned_to", "assignment_group",
                    "state", "priority", "urgency", "impact",
                    "category", "subcategory", "cmdb_ci",
                    "opened_at", "resolved_at", "closed_at",
                    "sys_created_on", "sys_updated_on",
                ],
            ),
            EntitySchema(
                entity_type="change_request",
                display_name="ServiceNow Change Requests",
                supports_incremental=True,
                fields=[
                    "sys_id", "number", "short_description",
                    "requested_by", "assigned_to", "assignment_group",
                    "state", "type", "risk", "impact",
                    "start_date", "end_date",
                    "sys_created_on", "sys_updated_on",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # FULL EXTRACTION
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        config = self._entity_config(entity_type)
        yield from self._paginate_table(
            table=config["table"],
            entity_type=entity_type,
            fields=config.get("fields", ""),
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
        Incremental via ServiceNow's sysparm_query on sys_updated_on.
        Format: sys_updated_on>javascript:gs.dateGenerate('YYYY-MM-DD','HH:MM:SS')
        """
        config = self._entity_config(entity_type)
        since_str = cursor.last_extracted_at.strftime("%Y-%m-%d %H:%M:%S")
        query = f"sys_updated_on>{since_str}"

        def _generate() -> Iterator[RawRecord]:
            yield from self._paginate_table(
                table=config["table"],
                entity_type=entity_type,
                fields=config.get("fields", ""),
                sysparm_query=query,
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
            self._refresh_if_needed()
            resp = self._get(
                f"{self._base_url}/api/now/table/sys_user",
                params={"sysparm_limit": 1, "sysparm_offset": 0},
                headers=self._headers(),
            )
            _ = resp.get("result", [])
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
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _entity_config(self, entity_type: str) -> dict[str, str]:
        configs = {
            "user": {
                "table": "sys_user",
                "fields": (
                    "sys_id,user_name,first_name,last_name,email,phone,"
                    "title,department,manager,location,active,"
                    "employee_number,sys_created_on,sys_updated_on"
                ),
            },
            "request": {
                "table": "sc_request",
                "fields": (
                    "sys_id,number,short_description,requested_for,"
                    "opened_by,state,priority,category,approval,"
                    "opened_at,closed_at,sys_created_on,sys_updated_on"
                ),
            },
            "incident": {
                "table": "incident",
                "fields": (
                    "sys_id,number,short_description,caller_id,"
                    "assigned_to,assignment_group,state,priority,"
                    "urgency,impact,category,subcategory,"
                    "opened_at,resolved_at,closed_at,sys_created_on,sys_updated_on"
                ),
            },
            "change_request": {
                "table": "change_request",
                "fields": (
                    "sys_id,number,short_description,requested_by,"
                    "assigned_to,assignment_group,state,type,"
                    "risk,impact,start_date,end_date,sys_created_on,sys_updated_on"
                ),
            },
        }
        if entity_type not in configs:
            raise ValueError(
                f"ServiceNowConnector does not support entity_type='{entity_type}'. "
                f"Supported: {list(configs)}"
            )
        return configs[entity_type]

    def _paginate_table(
        self,
        table: str,
        entity_type: str,
        fields: str = "",
        sysparm_query: str = "",
    ) -> Iterator[RawRecord]:
        """
        Paginate ServiceNow Table API via sysparm_offset / sysparm_limit.

        Response structure:
          { "result": [...records...] }
        """
        self._refresh_if_needed()
        offset = 0

        while True:
            params: dict[str, Any] = {
                "sysparm_limit": _PAGE_SIZE,
                "sysparm_offset": offset,
            }
            if fields:
                params["sysparm_fields"] = fields
            if sysparm_query:
                params["sysparm_query"] = sysparm_query

            try:
                resp = self._get(
                    f"{self._base_url}/api/now/table/{table}",
                    params=params,
                    headers=self._headers(),
                )
            except Exception as exc:
                logger.error(
                    "ServiceNowConnector pagination error (table=%s offset=%d): %s",
                    table, offset, exc,
                )
                break

            records = resp.get("result", [])
            for record in records:
                yield self._to_raw_record(entity_type, record)

            if len(records) < _PAGE_SIZE:
                break
            offset += len(records)

    def _to_raw_record(self, entity_type: str, record: dict[str, Any]) -> RawRecord:
        source_id = str(record.get("sys_id", ""))
        # ServiceNow returns reference fields as {"value": "...", "display_value": "..."} dicts
        email_raw = record.get("email", "")
        email = email_raw if isinstance(email_raw, str) else email_raw.get("value", "")
        first = record.get("first_name", "")
        last = record.get("last_name", "")
        name = (
            f"{first} {last}".strip()
            or _extract_display(record.get("requested_for"))
            or _extract_display(record.get("caller_id"))
            or record.get("short_description")
            or record.get("number")
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


def _extract_display(field: Any) -> str | None:
    """Extract display_value from a ServiceNow reference field dict."""
    if isinstance(field, dict):
        return field.get("display_value") or field.get("value") or None
    return None
