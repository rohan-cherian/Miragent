"""
scout/connectors/base.py — The ConnectorBase abstract class.

This is the most important file in Scout.

Every data source — Salesforce, Workday, NetSuite, Okta, Slack,
and every mock version of each — must inherit from this class
and implement its five abstract methods.

WHY ABSTRACT BASE CLASSES?
Normally Python is "duck typed" — if an object has a .quack() method,
it's close enough to a duck. ABCs add a stricter guarantee: Python will
raise an error at *import time* if a subclass is missing any required method.
This catches integration bugs the moment a developer forgets a method —
not hours later when a scan fails in production.

WHY IS THIS THE MOST IMPORTANT FILE?
The orchestrator only ever calls ConnectorBase methods.
It doesn't know whether it's talking to a real Salesforce connector
or a mock. This means:
- You can test the entire ingestion pipeline on your laptop with mocks
- You can swap a mock for a real connector by changing one line in the registry
- You can add a new connector (ServiceNow, Okta) without touching the orchestrator
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from functools import wraps
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from scout.connectors.models import (
    ConnectorCredentials,
    ConnectorHealth,
    EntitySchema,
    ExtractionCursor,
    RawRecord,
    ConnectorCategory,
)


# ─────────────────────────────────────────────────────────
# RATE LIMITING DECORATOR
#
# Enterprise APIs (Workday, SFDC) enforce strict limits on
# how many requests you can make per second. Exceed them
# and you get a temporary ban ("429 Too Many Requests").
#
# This decorator sits in front of every API call and
# enforces the connector's own declared limit automatically.
# ─────────────────────────────────────────────────────────

def rate_limited(func: Any) -> Any:
    """
    Decorator that enforces CALLS_PER_SECOND on any method.

    How it works:
    1. Before the call, check how long since the last call
    2. If less than 1/CALLS_PER_SECOND has elapsed, sleep the difference
    3. Record the call time, then proceed

    Example: CALLS_PER_SECOND = 5.0 means minimum 0.2s between calls.
    If the last call was 0.1s ago, we sleep 0.1s before proceeding.
    """
    @wraps(func)
    def wrapper(self: "ConnectorBase", *args: Any, **kwargs: Any) -> Any:
        min_interval = 1.0 / self.CALLS_PER_SECOND
        elapsed = time.time() - self._last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time = time.time()
        return func(self, *args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────────────────
# CONNECTOR BASE CLASS
# ─────────────────────────────────────────────────────────

class ConnectorBase(ABC):
    """
    Abstract base class that every Scout connector must implement.

    Class attributes (set by each subclass):
        CONNECTOR_ID    — unique identifier, e.g. "salesforce"
        DISPLAY_NAME    — human readable, e.g. "Salesforce CRM"
        CATEGORY        — which domain, e.g. ConnectorCategory.CRM
        CALLS_PER_SECOND — rate limit to respect

    Abstract methods (must be implemented by every connector):
        authenticate()         — establish connection, verify credentials
        discover_schema()      — what entity types can this connector return?
        extract_full()         — pull all records of a given entity type
        extract_incremental()  — pull only records changed since last run
        health_check()         — is this connector working right now?
    """

    # ── Subclasses must set these ──────────────────────────
    CONNECTOR_ID: str = NotImplemented
    DISPLAY_NAME: str = NotImplemented
    CATEGORY: ConnectorCategory = NotImplemented
    CALLS_PER_SECOND: float = 5.0  # safe default; override in each connector

    def __init__(self, credentials: ConnectorCredentials) -> None:
        self.credentials = credentials
        self.tenant_id = credentials.tenant_id
        self._last_call_time: float = 0.0
        self._http_client = httpx.Client(timeout=30.0)

    # ─────────────────────────────────────────────────────
    # ABSTRACT METHODS — every connector must implement these
    # ─────────────────────────────────────────────────────

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Establish connection to the source system and verify credentials work.

        Returns:
            True if authentication succeeded.

        Raises:
            ConnectorAuthError if credentials are wrong or expired.

        This is called once at the start of every scan. If it returns False,
        the connector is skipped and an alert is raised.
        """
        ...

    @abstractmethod
    def discover_schema(self) -> list[EntitySchema]:
        """
        Return a list of entity types this connector can produce.

        Example for Salesforce:
            [
                EntitySchema(entity_type="user", display_name="Salesforce Users", ...),
                EntitySchema(entity_type="account", display_name="Salesforce Accounts", ...),
                EntitySchema(entity_type="opportunity", display_name="Opportunities", ...),
            ]

        This is called during onboarding so Scout knows what to extract.
        It's also used to validate extraction requests.
        """
        ...

    @abstractmethod
    def extract_full(self, entity_type: str) -> Iterator[RawRecord]:
        """
        Extract ALL records of a given entity type from the source system.

        This is used:
        - During the initial 60-day scan (first time we've ever connected)
        - When a connector is reset (e.g., after a schema change)

        Returns a generator (Iterator) rather than a list — this is important.
        Enterprise systems can have millions of records. Loading them all into
        memory at once would crash your laptop. A generator yields one record
        at a time, so memory usage stays constant regardless of dataset size.

        Example usage:
            for record in connector.extract_full("user"):
                pipeline.process(record)  # process one at a time
        """
        ...

    @abstractmethod
    def extract_incremental(
        self,
        entity_type: str,
        cursor: ExtractionCursor,
    ) -> tuple[Iterator[RawRecord], ExtractionCursor]:
        """
        Extract only records that changed since the last extraction run.

        Takes a cursor (where we left off) and returns:
        - A generator of new/changed records
        - An updated cursor to save for the next run

        This is the normal ongoing operation after the initial full scan.
        Most enterprise APIs support this via a "modified since" parameter
        or a change log endpoint.

        Why not always do a full extract?
        Full extract for Workday (50,000 workers) takes ~20 minutes.
        Incremental extract (changed since yesterday) takes ~30 seconds.
        """
        ...

    @abstractmethod
    def health_check(self) -> ConnectorHealth:
        """
        Verify the connector is working right now.

        Called before every scan and periodically by monitoring.
        Should be fast (< 2 seconds) — just a lightweight ping.

        Returns a ConnectorHealth object with is_healthy and latency_ms.
        """
        ...

    # ─────────────────────────────────────────────────────
    # SHARED HTTP HELPERS
    # Real connectors use these. Mock connectors don't need them
    # (they return fixture data directly).
    #
    # tenacity's @retry decorator automatically retries on
    # network errors with exponential backoff.
    # ─────────────────────────────────────────────────────

    @rate_limited
    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        """
        Make a rate-limited, auto-retrying GET request.

        The @rate_limited decorator ensures we don't exceed CALLS_PER_SECOND.
        The @retry decorator retries on network errors with exponential backoff:
          attempt 1: immediate
          attempt 2: wait 1s
          attempt 3: wait 2s
          attempt 4: wait 4s
          attempt 5: wait 8s
        After 5 failures, the exception is re-raised.
        """
        response = self._http_client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    @rate_limited
    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _post(self, url: str, data: dict | None = None, headers: dict | None = None) -> dict:
        """Make a rate-limited, auto-retrying POST request."""
        response = self._http_client.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()

    def _paginate(
        self,
        first_url: str,
        next_url_key: str = "nextRecordsUrl",
        records_key: str = "records",
        headers: dict | None = None,
    ) -> Iterator[dict]:
        """
        Generic cursor-based pagination helper.

        Many enterprise APIs return results in pages:
        Page 1: records 1-200 + a URL for page 2
        Page 2: records 201-400 + a URL for page 3
        ...
        Last page: remaining records + no next URL

        This method follows those pages automatically, yielding
        one record at a time across all pages.

        Args:
            first_url: the initial API endpoint
            next_url_key: the JSON key that contains the next page URL
            records_key: the JSON key that contains the records array
        """
        url: str | None = first_url
        while url:
            page = self._get(url, headers=headers)
            for record in page.get(records_key, []):
                yield record
            url = page.get(next_url_key)  # None on the last page → loop ends

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} tenant={self.tenant_id}>"
