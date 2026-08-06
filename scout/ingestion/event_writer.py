"""
scout/ingestion/event_writer.py — Business event writer for the ClickHouse event log.

The EventWriter translates the Scout canonical entity model into time-stamped
business events and appends them to ClickHouse.

WHY EVENTS MATTER:
  Neo4j stores the *current state* of the digital twin — who works where,
  what vendors we use, what deals are open. But many intelligence questions
  need *history*:

    "How long does it take us to close a deal on average?"
    "What % of invoices are paid within our 30-day terms?"
    "How long does onboarding take for Sales hires vs. Engineering?"

  These require knowing *when* things happened, not just *what* they are now.
  That's what the event log provides.

EVENT TYPES (by entity):

  opportunity:
    created          — deal first entered CRM
    stage_changed    — moved from one stage to another
    closed_won       — final closed-won event
    closed_lost      — final closed-lost event

  person:
    hired            — start_date from HRIS
    onboarding_start — first day at company
    onboarding_complete — onboarding checklist finished
    terminated       — is_active flipped to False
    promoted         — job title changed to higher grade

  invoice:
    created          — AP invoice received
    approved         — approved for payment
    paid             — payment posted

  vendor:
    created          — first seen in any source system
    spend_updated    — annual_spend changed
    contract_renewed — contract_renewal date updated

USAGE:
  writer = EventWriter(ch_client)
  writer.write_from_persons(persons, tenant_id)
  writer.write_from_opportunities(opportunities, tenant_id)
  writer.flush()   # no-op for mock; for real CH commits the batch
"""

import logging
from datetime import datetime, timezone

from scout.db.clickhouse import BusinessEvent, ClickHouseClientBase
from scout.graph.models import CanonicalOpportunity, CanonicalPerson, CanonicalVendor

logger = logging.getLogger(__name__)

_NOW = datetime.now(timezone.utc)

# ── Helpers ───────────────────────────────────────────────


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse ISO date string to UTC datetime."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


class EventWriter:
    """
    Translates canonical entities into ClickHouse business events.

    Designed to be called once per ingestion pipeline run, after
    entity resolution, so events reflect deduplicated canonical IDs.
    """

    def __init__(self, ch_client: ClickHouseClientBase) -> None:
        self._ch = ch_client
        self._buffer: list[BusinessEvent] = []
        self._written = 0

    # ── Public write methods ──────────────────────────────

    def write_from_persons(
        self, persons: list[CanonicalPerson], tenant_id: str
    ) -> int:
        """Generate and buffer person lifecycle events."""
        count = 0
        for person in persons:
            events = self._person_events(person, tenant_id)
            self._buffer.extend(events)
            count += len(events)
        self._flush_if_needed()
        return count

    def write_from_opportunities(
        self, opportunities: list[CanonicalOpportunity], tenant_id: str
    ) -> int:
        """Generate and buffer opportunity lifecycle events."""
        count = 0
        for opp in opportunities:
            events = self._opportunity_events(opp, tenant_id)
            self._buffer.extend(events)
            count += len(events)
        self._flush_if_needed()
        return count

    def write_from_vendors(
        self, vendors: list[CanonicalVendor], tenant_id: str
    ) -> int:
        """Generate and buffer vendor lifecycle events."""
        count = 0
        for vendor in vendors:
            events = self._vendor_events(vendor, tenant_id)
            self._buffer.extend(events)
            count += len(events)
        self._flush_if_needed()
        return count

    def flush(self) -> int:
        """Force-write any buffered events. Returns count written."""
        if not self._buffer:
            return 0
        written = self._ch.write_events(self._buffer)
        self._written += written
        self._buffer.clear()
        logger.debug(f"EventWriter: flushed {written} events")
        return written

    @property
    def total_written(self) -> int:
        return self._written

    # ── Internal event builders ───────────────────────────

    def _flush_if_needed(self, threshold: int = 500) -> None:
        """Auto-flush when buffer gets large."""
        if len(self._buffer) >= threshold:
            self.flush()

    def _person_events(
        self, person: CanonicalPerson, tenant_id: str
    ) -> list[BusinessEvent]:
        events: list[BusinessEvent] = []
        source = person.source_systems[0] if person.source_systems else "unknown"

        # hired event — use start_date if available, else approximate from is_active
        hired_at = _parse_date(person.start_date)
        if hired_at is None:
            # Synthetic approximation: active employees assumed hired ~1 year ago
            # for mock data; inactive employees flagged only if recently inactive
            if person.is_active:
                hired_at = _NOW.replace(
                    year=_NOW.year - 1,
                    month=1,
                    day=1,
                )

        if hired_at:
            events.append(BusinessEvent(
                tenant_id=tenant_id,
                entity_type="person",
                entity_id=person.canonical_id,
                event_type="hired",
                occurred_at=hired_at,
                source_connector=source,
                payload={
                    "department": person.department,
                    "job_title": person.job_title,
                    "employment_type": person.employment_type,
                },
            ))

            # Approximate onboarding_complete: 14 days after hire
            from datetime import timedelta
            onboard_at = hired_at + timedelta(days=14)
            if onboard_at <= _NOW:
                events.append(BusinessEvent(
                    tenant_id=tenant_id,
                    entity_type="person",
                    entity_id=person.canonical_id,
                    event_type="onboarding_complete",
                    occurred_at=onboard_at,
                    source_connector=source,
                    payload={},
                ))

        # terminated event — if person is inactive
        if not person.is_active and hired_at:
            from datetime import timedelta
            # Approximate: terminated 6 months after hire (mock heuristic)
            term_at = hired_at + timedelta(days=180)
            if term_at <= _NOW:
                events.append(BusinessEvent(
                    tenant_id=tenant_id,
                    entity_type="person",
                    entity_id=person.canonical_id,
                    event_type="terminated",
                    occurred_at=term_at,
                    source_connector=source,
                    payload={"voluntary": True},
                ))

        return events

    def _opportunity_events(
        self, opp: CanonicalOpportunity, tenant_id: str
    ) -> list[BusinessEvent]:
        events: list[BusinessEvent] = []
        source = opp.source_systems[0] if opp.source_systems else "salesforce"

        # created event — approximate from days_in_pipeline
        from datetime import timedelta
        created_at = _NOW - timedelta(days=max(0, opp.days_in_pipeline))
        events.append(BusinessEvent(
            tenant_id=tenant_id,
            entity_type="opportunity",
            entity_id=opp.canonical_id,
            event_type="created",
            occurred_at=created_at,
            source_connector=source,
            payload={"amount": opp.amount, "stage": opp.stage},
        ))

        # stage event — current stage
        if opp.stage:
            events.append(BusinessEvent(
                tenant_id=tenant_id,
                entity_type="opportunity",
                entity_id=opp.canonical_id,
                event_type=opp.stage.lower().replace(" ", "_"),
                occurred_at=created_at + timedelta(days=opp.days_in_pipeline // 2),
                source_connector=source,
                payload={"stage": opp.stage, "amount": opp.amount},
            ))

        # closed events
        if opp.is_won and opp.is_closed:
            close_at = _parse_date(opp.close_date) or (created_at + timedelta(days=opp.days_in_pipeline))
            events.append(BusinessEvent(
                tenant_id=tenant_id,
                entity_type="opportunity",
                entity_id=opp.canonical_id,
                event_type="closed_won",
                occurred_at=close_at,
                source_connector=source,
                payload={"amount": opp.amount},
            ))
        elif opp.is_closed and not opp.is_won:
            close_at = _parse_date(opp.close_date) or (created_at + timedelta(days=opp.days_in_pipeline))
            events.append(BusinessEvent(
                tenant_id=tenant_id,
                entity_type="opportunity",
                entity_id=opp.canonical_id,
                event_type="closed_lost",
                occurred_at=close_at,
                source_connector=source,
                payload={"amount": opp.amount},
            ))

        return events

    def _vendor_events(
        self, vendor: CanonicalVendor, tenant_id: str
    ) -> list[BusinessEvent]:
        source = vendor.source_systems[0] if vendor.source_systems else "netsuite"
        return [
            BusinessEvent(
                tenant_id=tenant_id,
                entity_type="vendor",
                entity_id=vendor.canonical_id,
                event_type="created",
                occurred_at=_NOW,
                source_connector=source,
                payload={
                    "name": vendor.name,
                    "category": vendor.category,
                    "annual_spend": vendor.annual_spend,
                },
            )
        ]
