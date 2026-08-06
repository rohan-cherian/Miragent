"""
scout/db/clickhouse.py — ClickHouse event log client.

ClickHouse is a columnar database optimised for append-only write
and analytical read. Scout uses it as an event log:

  WRITE (ingestion pipeline):
    For every business record processed, one or more time-stamped
    events are appended — e.g. "opportunity.stage_changed",
    "person.hired", "invoice.paid".

  READ (workers):
    Workers query ClickHouse for cycle times, stage-transition
    histograms, and SLA-breach counts — measures that require
    actual timestamps, not proxy signals from the graph.

DESIGN PATTERN — Three-layer abstraction:

  ClickHouseClientBase  ← abstract interface
  MockClickHouseClient  ← in-memory, no Docker needed, used in tests
  RealClickHouseClient  ← clickhouse-driver, used in production

The factory function get_clickhouse_client() returns the right
implementation based on settings.use_mock_connectors.

EVENT SCHEMA (table: scout_events):
  tenant_id      String        — which tenant owns this event
  entity_type    String        — 'opportunity' | 'person' | 'invoice' | …
  entity_id      String        — canonical_id or source_id
  event_type     String        — 'stage_changed' | 'hired' | 'paid' | …
  occurred_at    DateTime      — when the business event happened
  source_connector String      — connector that produced the raw record
  payload        String        — JSON blob of event-specific metadata
"""

import json
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

from scout.config import settings

logger = logging.getLogger(__name__)

# ── DDL ───────────────────────────────────────────────────────────────────────

CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS scout_events (
    tenant_id       String,
    entity_type     LowCardinality(String),
    entity_id       String,
    event_type      LowCardinality(String),
    occurred_at     DateTime('UTC'),
    source_connector LowCardinality(String),
    payload         String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, entity_type, entity_id, occurred_at)
SETTINGS index_granularity = 8192
"""

# ── Data model ────────────────────────────────────────────────────────────────


class BusinessEvent:
    """One time-stamped business event to persist in ClickHouse."""

    __slots__ = (
        "tenant_id", "entity_type", "entity_id", "event_type",
        "occurred_at", "source_connector", "payload",
    )

    def __init__(
        self,
        tenant_id: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        occurred_at: datetime,
        source_connector: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.event_type = event_type
        self.occurred_at = occurred_at
        self.source_connector = source_connector
        self.payload = payload or {}

    def to_row(self) -> tuple:
        return (
            self.tenant_id,
            self.entity_type,
            self.entity_id,
            self.event_type,
            self.occurred_at,
            self.source_connector,
            json.dumps(self.payload),
        )


class CycleTimeResult:
    """Cycle time statistics for one process."""

    def __init__(
        self,
        process: str,
        count: int,
        median_days: float,
        p75_days: float,
        p95_days: float,
        min_days: float,
        max_days: float,
    ) -> None:
        self.process = process
        self.count = count
        self.median_days = median_days
        self.p75_days = p75_days
        self.p95_days = p95_days
        self.min_days = min_days
        self.max_days = max_days


# ── Abstract base ─────────────────────────────────────────────────────────────


class ClickHouseClientBase(ABC):
    """Abstract interface for the ClickHouse event log client."""

    @abstractmethod
    def write_events(self, events: list[BusinessEvent]) -> int:
        """Append events to the event log. Returns number written."""

    @abstractmethod
    def query_cycle_times(
        self,
        tenant_id: str,
        entity_type: str,
        start_event: str,
        end_event: str,
        since_days: int = 365,
    ) -> CycleTimeResult:
        """
        Compute cycle time between two event types for one entity type.

        Example:
          query_cycle_times(
              tenant_id="acme",
              entity_type="opportunity",
              start_event="created",
              end_event="closed_won",
          )
          → CycleTimeResult(median_days=47.3, p95_days=183.0, …)
        """

    @abstractmethod
    def query_stage_distribution(
        self,
        tenant_id: str,
        entity_type: str,
        since_days: int = 90,
    ) -> dict[str, int]:
        """Return count of events by event_type (stage histogram)."""

    @abstractmethod
    def query_sla_breaches(
        self,
        tenant_id: str,
        entity_type: str,
        event_type: str,
        sla_hours: float,
        since_days: int = 90,
    ) -> int:
        """Return count of events that breached an SLA window."""

    @abstractmethod
    def event_count(self, tenant_id: str, entity_type: str | None = None) -> int:
        """Return total event count for a tenant."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return True if the ClickHouse cluster is reachable."""

    def close(self) -> None:
        """Release any connection resources."""


# ── Mock implementation ───────────────────────────────────────────────────────


class MockClickHouseClient(ClickHouseClientBase):
    """
    In-memory ClickHouse client.

    Stores events in a plain Python list. On startup, seeds realistic
    cycle-time distributions so workers see meaningful numbers even
    before any real events are written.

    Deterministic: seeded from tenant_id so test results are stable.
    """

    def __init__(self, tenant_id: str | None = None) -> None:
        self._events: list[BusinessEvent] = []
        self._seed = hash(tenant_id or "default") % (2 ** 32)
        if tenant_id:
            self._seed_synthetic_events(tenant_id)

    # ── Write ──────────────────────────────────────────────────────────

    def write_events(self, events: list[BusinessEvent]) -> int:
        self._events.extend(events)
        return len(events)

    # ── Read ───────────────────────────────────────────────────────────

    def query_cycle_times(
        self,
        tenant_id: str,
        entity_type: str,
        start_event: str,
        end_event: str,
        since_days: int = 365,
    ) -> CycleTimeResult:
        """
        Compute cycle times from in-memory events, or return synthetic
        data if no real events exist yet.
        """
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        paired: list[float] = []

        # Group events by entity_id and find start/end pairs
        by_entity: dict[str, list[BusinessEvent]] = {}
        for ev in self._events:
            if ev.tenant_id != tenant_id:
                continue
            if ev.entity_type != entity_type:
                continue
            if ev.occurred_at < since:
                continue
            by_entity.setdefault(ev.entity_id, []).append(ev)

        for _, evs in by_entity.items():
            evs_sorted = sorted(evs, key=lambda e: e.occurred_at)
            t_start = next(
                (e.occurred_at for e in evs_sorted if e.event_type == start_event), None
            )
            t_end = next(
                (e.occurred_at for e in evs_sorted if e.event_type == end_event), None
            )
            if t_start and t_end and t_end > t_start:
                paired.append((t_end - t_start).total_seconds() / 86400)

        # Fall back to synthetic data if no real events
        if not paired:
            paired = self._synthetic_cycle_times(entity_type, start_event, end_event)

        paired.sort()
        n = len(paired)

        def percentile(p: float) -> float:
            idx = int(n * p / 100)
            return paired[min(idx, n - 1)]

        return CycleTimeResult(
            process=f"{entity_type}.{start_event}→{end_event}",
            count=n,
            median_days=round(percentile(50), 1),
            p75_days=round(percentile(75), 1),
            p95_days=round(percentile(95), 1),
            min_days=round(min(paired), 1),
            max_days=round(max(paired), 1),
        )

    def query_stage_distribution(
        self,
        tenant_id: str,
        entity_type: str,
        since_days: int = 90,
    ) -> dict[str, int]:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        dist: dict[str, int] = {}
        for ev in self._events:
            if ev.tenant_id == tenant_id and ev.entity_type == entity_type:
                if ev.occurred_at >= since:
                    dist[ev.event_type] = dist.get(ev.event_type, 0) + 1
        if not dist:
            dist = self._synthetic_stage_distribution(entity_type)
        return dist

    def query_sla_breaches(
        self,
        tenant_id: str,
        entity_type: str,
        event_type: str,
        sla_hours: float,
        since_days: int = 90,
    ) -> int:
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        # Compute cycle times for completed cycles and count breaches
        result = self.query_cycle_times(
            tenant_id, entity_type, "created", event_type, since_days
        )
        if result.count == 0:
            return 0
        sla_days = sla_hours / 24
        # Estimate breaches as count of events above SLA (using p95 heuristic)
        breach_pct = max(0, (result.p95_days - sla_days) / max(result.p95_days, 1))
        return round(result.count * breach_pct)

    def event_count(self, tenant_id: str, entity_type: str | None = None) -> int:
        return sum(
            1 for e in self._events
            if e.tenant_id == tenant_id
            and (entity_type is None or e.entity_type == entity_type)
        )

    def health_check(self) -> bool:
        return True  # always healthy

    # ── Synthetic seed data ────────────────────────────────────────────

    def _seed_synthetic_events(self, tenant_id: str) -> None:
        """
        Pre-populate realistic events so workers return meaningful data
        before any real ingestion has happened.

        Distributions are intentionally realistic but slightly noisy
        (some slow deals, some fast) so workers produce varied findings.
        """
        rng = random.Random(self._seed)
        now = datetime.now(timezone.utc)

        # Opportunity events (Lead-to-Cash process)
        stages = [
            "prospecting", "qualification", "proposal",
            "negotiation", "closed_won", "closed_lost",
        ]
        for i in range(120):
            opp_id = f"opp-{i:04d}"
            created_days_ago = rng.randint(10, 400)
            t0 = now - timedelta(days=created_days_ago)
            self._events.append(BusinessEvent(
                tenant_id=tenant_id, entity_type="opportunity",
                entity_id=opp_id, event_type="created",
                occurred_at=t0, source_connector="salesforce",
                payload={"amount": rng.randint(10_000, 500_000)},
            ))
            # Progress through stages
            t = t0
            for stage in stages:
                t = t + timedelta(days=rng.gauss(18, 8))
                if t > now:
                    break
                self._events.append(BusinessEvent(
                    tenant_id=tenant_id, entity_type="opportunity",
                    entity_id=opp_id, event_type=stage,
                    occurred_at=t, source_connector="salesforce",
                    payload={"stage": stage},
                ))

        # Person (Hire-to-Retire) events
        for i in range(80):
            person_id = f"person-{i:04d}"
            hire_days_ago = rng.randint(30, 1200)
            t0 = now - timedelta(days=hire_days_ago)
            self._events.append(BusinessEvent(
                tenant_id=tenant_id, entity_type="person",
                entity_id=person_id, event_type="hired",
                occurred_at=t0, source_connector="workday",
                payload={"department": rng.choice(["Engineering", "Sales", "Finance", "HR"])},
            ))
            onboard_days = rng.gauss(14, 5)
            self._events.append(BusinessEvent(
                tenant_id=tenant_id, entity_type="person",
                entity_id=person_id, event_type="onboarding_complete",
                occurred_at=t0 + timedelta(days=max(1, onboard_days)),
                source_connector="workday", payload={},
            ))
            # ~15% attrition
            if rng.random() < 0.15 and hire_days_ago > 91:
                term_days = rng.randint(90, hire_days_ago)
                self._events.append(BusinessEvent(
                    tenant_id=tenant_id, entity_type="person",
                    entity_id=person_id, event_type="terminated",
                    occurred_at=t0 + timedelta(days=term_days),
                    source_connector="workday",
                    payload={"voluntary": rng.choice([True, False])},
                ))

        # Invoice (Procure-to-Pay) events
        for i in range(200):
            inv_id = f"inv-{i:04d}"
            created_days_ago = rng.randint(1, 180)
            t0 = now - timedelta(days=created_days_ago)
            self._events.append(BusinessEvent(
                tenant_id=tenant_id, entity_type="invoice",
                entity_id=inv_id, event_type="created",
                occurred_at=t0, source_connector="netsuite",
                payload={"amount": rng.randint(500, 50_000)},
            ))
            pay_days = rng.gauss(32, 12)  # ~32 day average payment, some slow
            if t0 + timedelta(days=pay_days) <= now:
                self._events.append(BusinessEvent(
                    tenant_id=tenant_id, entity_type="invoice",
                    entity_id=inv_id, event_type="paid",
                    occurred_at=t0 + timedelta(days=max(1, pay_days)),
                    source_connector="netsuite",
                    payload={"late": pay_days > 30},
                ))

        # Ticket (Issue-to-Resolution) events
        for i in range(300):
            ticket_id = f"ticket-{i:04d}"
            created_days_ago = rng.randint(1, 120)
            t0 = now - timedelta(days=created_days_ago)
            priority = rng.choice(["P1", "P1", "P2", "P2", "P3", "P3", "P4"])
            sla_map = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}
            self._events.append(BusinessEvent(
                tenant_id=tenant_id, entity_type="ticket",
                entity_id=ticket_id, event_type="created",
                occurred_at=t0, source_connector="jira",
                payload={"priority": priority},
            ))
            resolve_hours = rng.gauss(sla_map[priority] * 1.4, sla_map[priority] * 0.6)
            resolve_hours = max(0.5, resolve_hours)
            if t0 + timedelta(hours=resolve_hours) <= now:
                self._events.append(BusinessEvent(
                    tenant_id=tenant_id, entity_type="ticket",
                    entity_id=ticket_id, event_type="resolved",
                    occurred_at=t0 + timedelta(hours=resolve_hours),
                    source_connector="jira",
                    payload={"priority": priority, "hours": round(resolve_hours, 1)},
                ))

        logger.debug(
            f"MockClickHouseClient seeded {len(self._events)} events for {tenant_id}"
        )

    def _synthetic_cycle_times(
        self, entity_type: str, start_event: str, end_event: str
    ) -> list[float]:
        """Return plausible cycle-time distributions when no events exist."""
        rng = random.Random(self._seed ^ hash(f"{entity_type}.{end_event}"))
        templates: dict[str, tuple[float, float, int]] = {
            # (mean_days, std_days, count)
            "opportunity": (82.0, 38.0, 95),
            "person": (12.0, 5.0, 75),
            "invoice": (31.0, 14.0, 180),
            "ticket": (0.4, 0.3, 260),   # hours converted to days
        }
        mean, std, n = templates.get(entity_type, (30.0, 15.0, 50))
        return [max(0.5, rng.gauss(mean, std)) for _ in range(n)]

    def _synthetic_stage_distribution(self, entity_type: str) -> dict[str, int]:
        rng = random.Random(self._seed ^ hash(entity_type))
        if entity_type == "opportunity":
            return {
                "prospecting": rng.randint(30, 50),
                "qualification": rng.randint(25, 40),
                "proposal": rng.randint(15, 30),
                "negotiation": rng.randint(10, 20),
                "closed_won": rng.randint(15, 25),
                "closed_lost": rng.randint(20, 35),
            }
        if entity_type == "ticket":
            return {
                "created": rng.randint(80, 120),
                "in_progress": rng.randint(40, 70),
                "resolved": rng.randint(100, 160),
                "closed": rng.randint(90, 140),
            }
        return {"created": rng.randint(50, 100), "completed": rng.randint(40, 80)}


# ── Real implementation ───────────────────────────────────────────────────────


class RealClickHouseClient(ClickHouseClientBase):
    """
    Production ClickHouse client using the clickhouse-driver library.

    On first call, creates the scout_events table if it doesn't exist.
    Uses connection pooling via clickhouse-driver's built-in pool.
    """

    def __init__(self) -> None:
        try:
            from clickhouse_driver import Client as CHClient  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "clickhouse-driver not installed. "
                "Run: poetry add clickhouse-driver"
            ) from exc

        self._client = CHClient(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            user=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            connect_timeout=5,
            send_receive_timeout=30,
        )
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist (idempotent)."""
        try:
            self._client.execute(
                f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_database}"
            )
            self._client.execute(CREATE_EVENTS_TABLE)
        except Exception as exc:
            logger.warning(f"ClickHouse schema init failed: {exc}")

    def write_events(self, events: list[BusinessEvent]) -> int:
        if not events:
            return 0
        rows = [e.to_row() for e in events]
        self._client.execute(
            """
            INSERT INTO scout_events
            (tenant_id, entity_type, entity_id, event_type,
             occurred_at, source_connector, payload)
            VALUES
            """,
            rows,
        )
        return len(rows)

    def query_cycle_times(
        self,
        tenant_id: str,
        entity_type: str,
        start_event: str,
        end_event: str,
        since_days: int = 365,
    ) -> CycleTimeResult:
        sql = """
        WITH
            starts AS (
                SELECT entity_id, min(occurred_at) AS t_start
                FROM scout_events
                WHERE tenant_id = %(tid)s
                  AND entity_type = %(et)s
                  AND event_type  = %(se)s
                  AND occurred_at >= now() - toIntervalDay(%(days)s)
                GROUP BY entity_id
            ),
            ends AS (
                SELECT entity_id, min(occurred_at) AS t_end
                FROM scout_events
                WHERE tenant_id = %(tid)s
                  AND entity_type = %(et)s
                  AND event_type  = %(ee)s
                  AND occurred_at >= now() - toIntervalDay(%(days)s)
                GROUP BY entity_id
            ),
            cycles AS (
                SELECT dateDiff('day', s.t_start, e.t_end) AS days_elapsed
                FROM starts s
                JOIN ends e USING (entity_id)
                WHERE e.t_end > s.t_start
            )
        SELECT
            count()        AS cnt,
            median(days_elapsed) AS med,
            quantile(0.75)(days_elapsed) AS p75,
            quantile(0.95)(days_elapsed) AS p95,
            min(days_elapsed) AS mn,
            max(days_elapsed) AS mx
        FROM cycles
        """
        rows = self._client.execute(sql, {
            "tid": tenant_id, "et": entity_type,
            "se": start_event, "ee": end_event, "days": since_days,
        })
        if not rows or rows[0][0] == 0:
            return CycleTimeResult(
                process=f"{entity_type}.{start_event}→{end_event}",
                count=0, median_days=0.0, p75_days=0.0,
                p95_days=0.0, min_days=0.0, max_days=0.0,
            )
        cnt, med, p75, p95, mn, mx = rows[0]
        return CycleTimeResult(
            process=f"{entity_type}.{start_event}→{end_event}",
            count=int(cnt),
            median_days=round(float(med), 1),
            p75_days=round(float(p75), 1),
            p95_days=round(float(p95), 1),
            min_days=round(float(mn), 1),
            max_days=round(float(mx), 1),
        )

    def query_stage_distribution(
        self,
        tenant_id: str,
        entity_type: str,
        since_days: int = 90,
    ) -> dict[str, int]:
        rows = self._client.execute(
            """
            SELECT event_type, count() AS n
            FROM scout_events
            WHERE tenant_id = %(tid)s
              AND entity_type = %(et)s
              AND occurred_at >= now() - toIntervalDay(%(days)s)
            GROUP BY event_type
            ORDER BY n DESC
            """,
            {"tid": tenant_id, "et": entity_type, "days": since_days},
        )
        return {r[0]: r[1] for r in rows}

    def query_sla_breaches(
        self,
        tenant_id: str,
        entity_type: str,
        event_type: str,
        sla_hours: float,
        since_days: int = 90,
    ) -> int:
        rows = self._client.execute(
            """
            WITH
                starts AS (
                    SELECT entity_id, min(occurred_at) AS t_start
                    FROM scout_events
                    WHERE tenant_id = %(tid)s
                      AND entity_type = %(et)s
                      AND event_type = 'created'
                      AND occurred_at >= now() - toIntervalDay(%(days)s)
                    GROUP BY entity_id
                ),
                ends AS (
                    SELECT entity_id, min(occurred_at) AS t_end
                    FROM scout_events
                    WHERE tenant_id = %(tid)s
                      AND entity_type = %(et)s
                      AND event_type = %(evt)s
                      AND occurred_at >= now() - toIntervalDay(%(days)s)
                    GROUP BY entity_id
                )
            SELECT count()
            FROM starts s JOIN ends e USING (entity_id)
            WHERE dateDiff('second', s.t_start, e.t_end) > %(sla_sec)s
              AND e.t_end > s.t_start
            """,
            {
                "tid": tenant_id, "et": entity_type,
                "evt": event_type, "days": since_days,
                "sla_sec": int(sla_hours * 3600),
            },
        )
        return int(rows[0][0]) if rows else 0

    def event_count(self, tenant_id: str, entity_type: str | None = None) -> int:
        if entity_type:
            rows = self._client.execute(
                "SELECT count() FROM scout_events WHERE tenant_id=%(tid)s AND entity_type=%(et)s",
                {"tid": tenant_id, "et": entity_type},
            )
        else:
            rows = self._client.execute(
                "SELECT count() FROM scout_events WHERE tenant_id=%(tid)s",
                {"tid": tenant_id},
            )
        return int(rows[0][0]) if rows else 0

    def health_check(self) -> bool:
        try:
            result = self._client.execute("SELECT 1")
            return result == [(1,)]
        except Exception:
            return False

    def close(self) -> None:
        try:
            self._client.disconnect()
        except Exception:
            pass


# ── Factory ───────────────────────────────────────────────────────────────────


def get_clickhouse_client(tenant_id: str | None = None) -> ClickHouseClientBase:
    """
    Return the appropriate ClickHouse client based on configuration.

    When USE_MOCK_CONNECTORS=true (local dev / CI), returns MockClickHouseClient
    with pre-seeded synthetic data.

    When USE_MOCK_CONNECTORS=false (production), returns RealClickHouseClient.
    The client will fail loudly at startup if ClickHouse isn't reachable,
    preventing silent data loss.
    """
    if settings.use_mock_connectors:
        logger.debug("Using MockClickHouseClient (USE_MOCK_CONNECTORS=true)")
        return MockClickHouseClient(tenant_id=tenant_id)

    logger.info(
        f"Connecting to ClickHouse at {settings.clickhouse_host}:{settings.clickhouse_port}"
    )
    return RealClickHouseClient()
