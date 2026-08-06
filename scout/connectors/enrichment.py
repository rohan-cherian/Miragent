"""
Clearbit and ZoomInfo enrichment connectors.

Clearbit enrichment connector: Enriches Account nodes with firmographic data
(industry, employee count, annual revenue, tech stack). Uses the Clearbit
Enrichment API v2. In Sprint 12, this connector is called after CRM extraction
to fill data gaps identified by LeadEnrichmentWorker.

ZoomInfo connector for B2B contact and company intelligence. Provides deeper
TAM data than Clearbit: technographics, intent data, org charts, and
contact-level data. Used by TamPenetrationWorker to score prospects against
verified ZoomInfo firmographics.

Enrichment connectors differ from CRM/HRIS connectors in two key ways:
  1. They are point-lookup (by domain or email), not bulk-extraction oriented.
  2. extract_full() is a no-op — callers use enrich_company() / enrich_person()
     directly as part of the ingestion pipeline enrichment phase.

Both connectors inherit from ConnectorBase so they integrate with Scout's
connector registry, health monitoring, and credential management.
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


# ═══════════════════════════════════════════════════════════
# CLEARBIT ENRICHMENT CONNECTOR
# ═══════════════════════════════════════════════════════════

class ClearbitConnector(ConnectorBase):
    """
    Clearbit enrichment connector.

    Enriches company (by domain) and person (by email) records using the
    Clearbit Enrichment API v2. Returns firmographic, technographic, and
    demographic data to fill gaps in CRM data.

    Authentication: HTTP Basic Auth with api_key as username, empty password.

    Credentials (auth_data keys):
        api_key — Clearbit API secret key (begins with "sk_")

    Usage pattern (called by LeadEnrichmentWorker):
        connector = ClearbitConnector(credentials)
        connector.authenticate()
        result = connector.enrich_company("stripe.com")
        result = connector.enrich_person("user@company.com")
    """

    CONNECTOR_ID = "clearbit"
    DISPLAY_NAME = "Clearbit Enrichment"
    CATEGORY = ConnectorCategory.CRM  # Closest available; ENRICHMENT not in enum
    CALLS_PER_SECOND = 2.0  # Clearbit: ~100 req/min = 1.67/sec; use 2

    _COMPANY_URL = "https://company.clearbit.com/v2/companies/find"
    _PERSON_URL = "https://person.clearbit.com/v2/people/find"

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._api_key: str = credentials.auth_data.get("api_key", "")

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Verify the API key by enriching a well-known domain (stripe.com).

        Clearbit returns 200 for a successful lookup, 422 if the domain
        doesn't have sufficient data (still means the key is valid), and
        401/403 for invalid credentials.

        Returns:
            True if the API key is accepted (200 or 422).
            False on authentication errors (401, 403) or network failures.
        """
        if not self._api_key:
            logger.error(
                "ClearbitConnector.authenticate: api_key not found in auth_data"
            )
            return False

        try:
            response = self._http_client.get(
                self._COMPANY_URL,
                params={"domain": "stripe.com"},
                auth=httpx.BasicAuth(self._api_key, ""),
            )
            # 200 = found, 422 = not enough data — both mean auth succeeded
            if response.status_code in (200, 422):
                logger.info(
                    "ClearbitConnector authenticated successfully for tenant=%s",
                    self.tenant_id,
                )
                return True
            response.raise_for_status()
            return True  # Any other 2xx
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ClearbitConnector.authenticate failed (HTTP %d): %s",
                exc.response.status_code,
                exc,
            )
            return False
        except Exception as exc:
            logger.exception(
                "ClearbitConnector.authenticate unexpected error: %s", exc
            )
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        """Return entity types this connector can enrich."""
        return [
            EntitySchema(
                entity_type="company_enrichment",
                display_name="Clearbit Company Enrichment",
                supports_incremental=False,  # Point-lookup, not bulk
                fields=[
                    "name", "domain", "industry", "employees",
                    "metrics.annualRevenue", "tech", "description",
                    "location", "foundedYear", "linkedin", "twitter",
                ],
            ),
            EntitySchema(
                entity_type="person_enrichment",
                display_name="Clearbit Person Enrichment",
                supports_incremental=False,
                fields=[
                    "name.fullName", "email", "location", "employment.title",
                    "employment.company", "linkedin.handle",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # BULK EXTRACTION (not applicable)
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Not applicable for enrichment connectors.

        Clearbit is a point-lookup API (by domain/email), not a bulk
        data source. Use enrich_company() or enrich_person() instead.
        LeadEnrichmentWorker calls these directly during the enrichment phase.
        """
        logger.warning(
            "ClearbitConnector.extract_full called for entity_type='%s' — "
            "Clearbit is a point-lookup enrichment API, not a bulk source. "
            "Use enrich_company() or enrich_person() directly.",
            entity_type,
        )
        return
        yield  # Make this a generator that immediately returns

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Not applicable for enrichment connectors.

        Returns an empty iterator and a refreshed cursor. Callers should
        use enrich_company() / enrich_person() for point-lookups.
        """
        logger.warning(
            "ClearbitConnector.extract_incremental called — not applicable "
            "for point-lookup enrichment connectors."
        )

        def _empty() -> Iterator[RawRecord]:
            return
            yield

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
        )
        return _empty(), updated_cursor

    # ─────────────────────────────────────────────────────
    # ENRICHMENT METHODS
    # ─────────────────────────────────────────────────────

    def enrich_company(self, domain: str) -> dict | None:
        """
        Enrich a company by its web domain using Clearbit's Company API.

        Returns firmographic data including industry, headcount, revenue,
        and technology stack. Returns None if Clearbit has no data for
        the domain (404) or on other non-auth errors.

        Key response fields:
            name              — Company legal name
            domain            — Canonical domain
            industry          — Industry vertical (e.g. "Financial Services")
            employees         — Estimated headcount
            metrics.annualRevenue — Estimated ARR
            tech              — List of technology tool identifiers

        Args:
            domain: e.g. "stripe.com", "acmecorp.io"

        Returns:
            Full Clearbit company JSON dict, or None if not found.
        """
        try:
            response = self._http_client.get(
                self._COMPANY_URL,
                params={"domain": domain},
                auth=httpx.BasicAuth(self._api_key, ""),
            )
            if response.status_code == 404:
                logger.debug(
                    "ClearbitConnector: no company data for domain=%s", domain
                )
                return None
            response.raise_for_status()
            logger.debug(
                "ClearbitConnector: enriched company domain=%s", domain
            )
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "ClearbitConnector.enrich_company failed for domain=%s: %s",
                domain,
                exc,
            )
            return None
        except Exception as exc:
            logger.exception(
                "ClearbitConnector.enrich_company unexpected error for domain=%s: %s",
                domain,
                exc,
            )
            return None

    def enrich_person(self, email: str) -> dict | None:
        """
        Enrich a person record by email using Clearbit's Person API.

        Returns contact-level data including job title, company, social
        profiles, and demographic signals. Returns None on 404.

        Args:
            email: The contact's work email address.

        Returns:
            Full Clearbit person JSON dict, or None if not found.
        """
        try:
            response = self._http_client.get(
                self._PERSON_URL,
                params={"email": email},
                auth=httpx.BasicAuth(self._api_key, ""),
            )
            if response.status_code == 404:
                logger.debug(
                    "ClearbitConnector: no person data for email=%s", email
                )
                return None
            response.raise_for_status()
            logger.debug(
                "ClearbitConnector: enriched person email=%s", email
            )
            return response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "ClearbitConnector.enrich_person failed for email=%s: %s",
                email,
                exc,
            )
            return None
        except Exception as exc:
            logger.exception(
                "ClearbitConnector.enrich_person unexpected error for email=%s: %s",
                email,
                exc,
            )
            return None

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        """
        Verify the API key and network connectivity via a stripe.com lookup.

        200 or 422 both indicate a healthy, authenticated connection.
        """
        start = time.monotonic()
        try:
            response = self._http_client.get(
                self._COMPANY_URL,
                params={"domain": "stripe.com"},
                auth=httpx.BasicAuth(self._api_key, ""),
            )
            is_healthy = response.status_code in (200, 422)
            latency_ms = (time.monotonic() - start) * 1000
            error_message = None
            if not is_healthy:
                error_message = f"HTTP {response.status_code}"
            logger.info(
                "ClearbitConnector health check: healthy=%s latency=%.1fms",
                is_healthy,
                latency_ms,
            )
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=is_healthy,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning("ClearbitConnector health check failed: %s", exc)
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=False,
                latency_ms=latency_ms,
                error_message=str(exc),
            )


# ═══════════════════════════════════════════════════════════
# ZOOMINFO INTELLIGENCE CONNECTOR
# ═══════════════════════════════════════════════════════════

class ZoomInfoConnector(ConnectorBase):
    """
    ZoomInfo connector for B2B contact and company intelligence.

    Provides deeper TAM data than Clearbit: technographics, intent data,
    org charts, and contact-level data. Used by TamPenetrationWorker to
    score prospects against verified ZoomInfo firmographics.

    Authentication: Username/password → JWT token via POST /authenticate.
    JWT tokens are short-lived; re-authentication is triggered automatically
    when a 401 is received mid-session.

    Credentials (auth_data keys):
        username — ZoomInfo account username (email)
        password — ZoomInfo account password
    """

    CONNECTOR_ID = "zoominfo"
    DISPLAY_NAME = "ZoomInfo Intelligence"
    CATEGORY = ConnectorCategory.CRM  # Closest available; ENRICHMENT not in enum
    CALLS_PER_SECOND = 5.0

    _BASE_URL = "https://api.zoominfo.com"

    def __init__(self, credentials: ConnectorCredentials) -> None:
        super().__init__(credentials)
        self._token: str = ""
        self._username: str = credentials.auth_data.get("username", "")
        self._password: str = credentials.auth_data.get("password", "")

    # ─────────────────────────────────────────────────────
    # AUTHENTICATION
    # ─────────────────────────────────────────────────────

    def authenticate(self) -> bool:
        """
        Obtain a JWT token by POST-ing credentials to /authenticate.

        ZoomInfo's authentication endpoint accepts JSON with username
        and password. On success, the response contains a JWT in the
        `jwt` field which must be sent as a Bearer token on all
        subsequent requests.

        Returns:
            True if authentication succeeded and a JWT was stored.
            False on any failure.
        """
        if not self._username or not self._password:
            logger.error(
                "ZoomInfoConnector.authenticate: username or password missing in auth_data"
            )
            return False

        try:
            response = self._http_client.post(
                f"{self._BASE_URL}/authenticate",
                json={"username": self._username, "password": self._password},
            )
            response.raise_for_status()
            data = response.json()
            jwt = data.get("jwt", "")
            if not jwt:
                logger.error(
                    "ZoomInfoConnector.authenticate: no jwt in response body"
                )
                return False
            self._token = jwt
            logger.info(
                "ZoomInfoConnector authenticated successfully for tenant=%s",
                self.tenant_id,
            )
            return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ZoomInfoConnector.authenticate failed (HTTP %d): %s",
                exc.response.status_code,
                exc,
            )
            return False
        except Exception as exc:
            logger.exception(
                "ZoomInfoConnector.authenticate unexpected error: %s", exc
            )
            return False

    # ─────────────────────────────────────────────────────
    # SCHEMA DISCOVERY
    # ─────────────────────────────────────────────────────

    def discover_schema(self) -> list[EntitySchema]:
        """Return entity types this connector can query."""
        return [
            EntitySchema(
                entity_type="company_intelligence",
                display_name="ZoomInfo Company Intelligence",
                supports_incremental=False,
                fields=[
                    "id", "companyName", "website", "industry", "subIndustry",
                    "employeeCount", "revenue", "techAttributes", "intendedTopics",
                    "naics", "sic", "description", "country", "state", "city",
                ],
            ),
            EntitySchema(
                entity_type="contact_intelligence",
                display_name="ZoomInfo Contact Intelligence",
                supports_incremental=False,
                fields=[
                    "id", "firstName", "lastName", "email", "jobTitle",
                    "jobFunction", "managementLevel", "companyName",
                    "directPhone", "mobilePhone", "linkedin",
                ],
            ),
        ]

    # ─────────────────────────────────────────────────────
    # BULK EXTRACTION (not applicable)
    # ─────────────────────────────────────────────────────

    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Not applicable for ZoomInfo.

        ZoomInfo is a search/lookup API, not a bulk data source. Use
        search_companies() or search_contacts() directly.
        TamPenetrationWorker invokes these during prospect scoring.
        """
        logger.warning(
            "ZoomInfoConnector.extract_full called for entity_type='%s' — "
            "ZoomInfo is a search API, not a bulk source. "
            "Use search_companies() or search_contacts() directly.",
            entity_type,
        )
        return
        yield  # Make this a generator that immediately returns

    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Not applicable for ZoomInfo.

        Returns an empty iterator and a refreshed cursor.
        """
        logger.warning(
            "ZoomInfoConnector.extract_incremental called — not applicable "
            "for ZoomInfo search-based connector."
        )

        def _empty() -> Iterator[RawRecord]:
            return
            yield

        updated_cursor = ExtractionCursor(
            connector_id=self.CONNECTOR_ID,
            entity_type=entity_type,
            last_extracted_at=datetime.now(tz=timezone.utc),
        )
        return _empty(), updated_cursor

    # ─────────────────────────────────────────────────────
    # SEARCH METHODS
    # ─────────────────────────────────────────────────────

    def search_companies(self, filters: dict[str, Any]) -> list[dict]:
        """
        Search ZoomInfo's company database using structured filters.

        Useful for TAM analysis: find all companies in a target industry,
        employee size range, and geography that are not yet in the CRM.

        Example filters:
            {
                "industry": ["Financial Services", "Insurance"],
                "employeeCount": {"min": 500, "max": 5000},
                "country": "United States",
            }

        Args:
            filters: ZoomInfo search filters dict. See ZoomInfo API docs
                     for the full filter schema and supported operators.

        Returns:
            List of company dicts from the ZoomInfo response data array.
            Empty list on error or no results.
        """
        self._ensure_authenticated()
        try:
            response = self._http_client.post(
                f"{self._BASE_URL}/search/company",
                json=filters,
                headers=self._headers(),
            )
            if response.status_code == 401:
                logger.info(
                    "ZoomInfoConnector: token expired, re-authenticating"
                )
                if self.authenticate():
                    response = self._http_client.post(
                        f"{self._BASE_URL}/search/company",
                        json=filters,
                        headers=self._headers(),
                    )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ZoomInfoConnector.search_companies failed (HTTP %d): %s",
                exc.response.status_code,
                exc,
            )
            return []
        except Exception as exc:
            logger.exception(
                "ZoomInfoConnector.search_companies unexpected error: %s", exc
            )
            return []

    def search_contacts(
        self,
        company_name: str,
        titles: list[str],
    ) -> list[dict]:
        """
        Search for contacts at a specific company with given job titles.

        Used by TamPenetrationWorker and OutreachSequenceWorker to find
        decision-makers and influencers at target accounts.

        Args:
            company_name: Exact or partial company name to filter on.
            titles:       List of job title keywords (e.g. ["CFO", "VP Finance"]).

        Returns:
            List of contact dicts from the ZoomInfo response data array.
            Empty list on error or no results.
        """
        self._ensure_authenticated()
        payload = {
            "companyName": company_name,
            "jobTitle": titles,
        }
        try:
            response = self._http_client.post(
                f"{self._BASE_URL}/search/contact",
                json=payload,
                headers=self._headers(),
            )
            if response.status_code == 401:
                logger.info(
                    "ZoomInfoConnector: token expired, re-authenticating"
                )
                if self.authenticate():
                    response = self._http_client.post(
                        f"{self._BASE_URL}/search/contact",
                        json=payload,
                        headers=self._headers(),
                    )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ZoomInfoConnector.search_contacts failed (HTTP %d): %s",
                exc.response.status_code,
                exc,
            )
            return []
        except Exception as exc:
            logger.exception(
                "ZoomInfoConnector.search_contacts unexpected error: %s", exc
            )
            return []

    # ─────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────

    def health_check(self) -> ConnectorHealth:
        """
        Verify the connector is working by attempting (re-)authentication.

        ZoomInfo does not provide a dedicated health endpoint. We re-use
        the /authenticate call as a connectivity check, which also refreshes
        the JWT for subsequent requests.
        """
        start = time.monotonic()
        try:
            ok = self.authenticate()
            latency_ms = (time.monotonic() - start) * 1000
            logger.info(
                "ZoomInfoConnector health check: healthy=%s latency=%.1fms",
                ok,
                latency_ms,
            )
            return ConnectorHealth(
                connector_id=self.CONNECTOR_ID,
                is_healthy=ok,
                latency_ms=latency_ms,
                error_message=None if ok else "Re-authentication failed",
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            logger.warning("ZoomInfoConnector health check failed: %s", exc)
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
        """Return HTTP headers with the current JWT Bearer token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _ensure_authenticated(self) -> None:
        """
        Raise RuntimeError if authenticate() has not been called yet.

        Does not perform token refresh (that happens lazily on 401).
        """
        if not self._token:
            raise RuntimeError(
                "ZoomInfoConnector.authenticate() must be called before searching."
            )
