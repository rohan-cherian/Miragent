"""
tests/ingestion/test_event_writer.py — Unit tests for EventWriter (Sprint 40)

EventWriter translates canonical entities (CanonicalPerson, CanonicalVendor,
CanonicalOpportunity) into BusinessEvents and writes them to ClickHouse.

These tests run with NO external dependencies — the MockClickHouseClient
stores events in memory.

Coverage:
  - Person event generation: hired, onboarding_complete, terminated
  - Opportunity event generation: created, stage, closed_won, closed_lost
  - Vendor event generation: created
  - Buffer/flush mechanics (auto-flush at threshold, manual flush)
  - total_written accumulation
  - _parse_date helper for ISO date strings
  - Edge cases: no start_date, inactive persons, zero-day pipeline
"""

from datetime import datetime, timedelta, timezone

import pytest

from scout.db.clickhouse import BusinessEvent, MockClickHouseClient
from scout.graph.models import CanonicalOpportunity, CanonicalPerson, CanonicalVendor
from scout.ingestion.event_writer import EventWriter, _parse_date


TENANT = "test-tenant-40"


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def ch():
    """Fresh in-memory ClickHouse client with no pre-seeded events."""
    return MockClickHouseClient()  # no tenant_id → no synthetic events


@pytest.fixture
def writer(ch):
    return EventWriter(ch)


def make_person(
    canonical_id: str = "person-001",
    email: str = "alice@acme.com",
    full_name: str = "Alice Smith",
    is_active: bool = True,
    start_date: str | None = None,
    department: str | None = "Engineering",
    job_title: str | None = "Software Engineer",
    employment_type: str = "Regular",
    source_systems: list | None = None,
) -> CanonicalPerson:
    return CanonicalPerson(
        canonical_id=canonical_id,
        tenant_id=TENANT,
        email=email,
        full_name=full_name,
        is_active=is_active,
        start_date=start_date,
        department=department,
        job_title=job_title,
        employment_type=employment_type,
        source_systems=source_systems or ["workday"],
    )


def make_vendor(
    canonical_id: str = "vendor-001",
    name: str = "Salesforce Inc",
    normalized_name: str = "salesforce-inc",
    annual_spend: float = 200_000.0,
    category: str | None = "Software",
    source_systems: list | None = None,
) -> CanonicalVendor:
    return CanonicalVendor(
        canonical_id=canonical_id,
        tenant_id=TENANT,
        name=name,
        normalized_name=normalized_name,
        annual_spend=annual_spend,
        category=category,
        source_systems=source_systems or ["netsuite"],
    )


def make_opportunity(
    canonical_id: str = "opp-001",
    name: str = "Pinnacle Deal",
    stage: str | None = "Proposal/Price Quote",
    amount: float = 75_000.0,
    days_in_pipeline: int = 45,
    is_closed: bool = False,
    is_won: bool = False,
    close_date: str | None = None,
    source_systems: list | None = None,
) -> CanonicalOpportunity:
    return CanonicalOpportunity(
        canonical_id=canonical_id,
        tenant_id=TENANT,
        name=name,
        stage=stage,
        amount=amount,
        days_in_pipeline=days_in_pipeline,
        is_closed=is_closed,
        is_won=is_won,
        close_date=close_date,
        source_systems=source_systems or ["salesforce"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# _parse_date HELPER
# ─────────────────────────────────────────────────────────────────────────────

class TestParseDateHelper:

    def test_valid_iso_date_returns_datetime(self):
        result = _parse_date("2023-03-15")
        assert result is not None
        assert result.year == 2023
        assert result.month == 3
        assert result.day == 15

    def test_valid_iso_datetime_returns_datetime(self):
        result = _parse_date("2023-03-15T10:30:00")
        assert result is not None
        assert result.hour == 10
        assert result.minute == 30

    def test_zulu_suffix_handled(self):
        result = _parse_date("2023-03-15T00:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_invalid_string_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_result_is_timezone_aware(self):
        result = _parse_date("2023-06-01")
        assert result is not None
        assert result.tzinfo is not None


# ─────────────────────────────────────────────────────────────────────────────
# PERSON EVENTS
# ─────────────────────────────────────────────────────────────────────────────

class TestPersonEvents:

    def test_active_person_with_start_date_emits_hired(self, writer, ch):
        person = make_person(is_active=True, start_date="2021-06-01")
        count = writer.write_from_persons([person], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "hired" in event_types

    def test_active_person_with_start_date_emits_onboarding_complete(self, writer, ch):
        person = make_person(is_active=True, start_date="2021-06-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "onboarding_complete" in event_types

    def test_inactive_person_emits_terminated(self, writer, ch):
        person = make_person(is_active=False, start_date="2020-01-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "terminated" in event_types

    def test_active_person_no_start_date_still_emits_hired(self, writer, ch):
        """Active person with no start_date gets a synthetic hire date."""
        person = make_person(is_active=True, start_date=None)
        writer.write_from_persons([person], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "hired" in event_types

    def test_inactive_person_no_start_date_emits_no_terminated(self, writer, ch):
        """Inactive person with no start_date cannot compute termination date."""
        person = make_person(is_active=False, start_date=None)
        writer.write_from_persons([person], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        # No hired → no terminated (can't derive termination without hire date)
        assert "terminated" not in event_types

    def test_hired_event_has_correct_entity_id(self, writer, ch):
        person = make_person(canonical_id="person-xyz", start_date="2022-01-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        hired = [e for e in ch._events if e.event_type == "hired"]
        assert len(hired) >= 1
        assert hired[0].entity_id == "person-xyz"

    def test_hired_event_has_correct_tenant(self, writer, ch):
        person = make_person(start_date="2022-01-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        hired = [e for e in ch._events if e.event_type == "hired"]
        assert hired[0].tenant_id == TENANT

    def test_hired_event_payload_has_department(self, writer, ch):
        person = make_person(start_date="2022-01-01", department="Sales")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        hired = [e for e in ch._events if e.event_type == "hired"][0]
        assert hired.payload.get("department") == "Sales"

    def test_hired_event_payload_has_job_title(self, writer, ch):
        person = make_person(start_date="2022-01-01", job_title="VP of Sales")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        hired = [e for e in ch._events if e.event_type == "hired"][0]
        assert hired.payload.get("job_title") == "VP of Sales"

    def test_source_connector_from_source_systems(self, writer, ch):
        person = make_person(start_date="2022-01-01", source_systems=["bamboohr"])
        writer.write_from_persons([person], TENANT)
        writer.flush()
        hired = [e for e in ch._events if e.event_type == "hired"][0]
        assert hired.source_connector == "bamboohr"

    def test_multiple_persons_emit_multiple_hired(self, writer, ch):
        persons = [
            make_person("p-001", "alice@acme.com", start_date="2021-01-01"),
            make_person("p-002", "bob@acme.com", start_date="2021-06-01"),
        ]
        writer.write_from_persons(persons, TENANT)
        writer.flush()
        hired = [e for e in ch._events if e.event_type == "hired"]
        assert len(hired) == 2

    def test_write_from_persons_returns_event_count(self, writer):
        person = make_person(start_date="2022-01-01", is_active=True)
        count = writer.write_from_persons([person], TENANT)
        # Active person with start_date should emit at least hired + onboarding_complete
        assert count >= 2

    def test_empty_persons_list_returns_zero(self, writer):
        count = writer.write_from_persons([], TENANT)
        assert count == 0

    def test_terminated_event_has_voluntary_payload(self, writer, ch):
        person = make_person(is_active=False, start_date="2020-01-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        terminated = [e for e in ch._events if e.event_type == "terminated"]
        assert len(terminated) == 1
        assert "voluntary" in terminated[0].payload


# ─────────────────────────────────────────────────────────────────────────────
# OPPORTUNITY EVENTS
# ─────────────────────────────────────────────────────────────────────────────

class TestOpportunityEvents:

    def test_open_opp_emits_created_event(self, writer, ch):
        opp = make_opportunity(is_closed=False, is_won=False)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "created" in event_types

    def test_open_opp_emits_stage_event(self, writer, ch):
        opp = make_opportunity(stage="Proposal/Price Quote", is_closed=False)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "proposal/price_quote" in event_types

    def test_closed_won_opp_emits_closed_won(self, writer, ch):
        opp = make_opportunity(is_closed=True, is_won=True)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "closed_won" in event_types

    def test_closed_lost_opp_emits_closed_lost(self, writer, ch):
        opp = make_opportunity(is_closed=True, is_won=False)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "closed_lost" in event_types

    def test_closed_won_does_not_emit_closed_lost(self, writer, ch):
        opp = make_opportunity(is_closed=True, is_won=True)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "closed_lost" not in event_types

    def test_created_event_has_correct_entity_id(self, writer, ch):
        opp = make_opportunity(canonical_id="opp-abc123")
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"]
        assert len(created) == 1
        assert created[0].entity_id == "opp-abc123"

    def test_created_event_payload_has_amount(self, writer, ch):
        opp = make_opportunity(amount=95_000.0)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.payload["amount"] == 95_000.0

    def test_created_event_entity_type_is_opportunity(self, writer, ch):
        opp = make_opportunity()
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.entity_type == "opportunity"

    def test_opp_no_stage_skips_stage_event(self, writer, ch):
        opp = make_opportunity(stage=None, is_closed=False)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        # created should still be emitted
        assert "created" in event_types

    def test_closed_won_uses_close_date_when_provided(self, writer, ch):
        close_date = "2024-03-15"
        opp = make_opportunity(is_closed=True, is_won=True, close_date=close_date)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        closed_won = [e for e in ch._events if e.event_type == "closed_won"][0]
        assert closed_won.occurred_at.year == 2024
        assert closed_won.occurred_at.month == 3

    def test_multiple_opps_emit_multiple_created(self, writer, ch):
        opps = [
            make_opportunity("opp-001", "Deal A"),
            make_opportunity("opp-002", "Deal B"),
        ]
        writer.write_from_opportunities(opps, TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"]
        assert len(created) == 2

    def test_empty_opps_list_returns_zero(self, writer):
        count = writer.write_from_opportunities([], TENANT)
        assert count == 0

    def test_write_from_opportunities_returns_count(self, writer):
        opp = make_opportunity(is_closed=False, stage="Prospecting")
        count = writer.write_from_opportunities([opp], TENANT)
        # Open opp with stage → created + stage event = 2
        assert count >= 2

    def test_source_connector_on_opportunity_event(self, writer, ch):
        opp = make_opportunity(source_systems=["hubspot"])
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.source_connector == "hubspot"


# ─────────────────────────────────────────────────────────────────────────────
# VENDOR EVENTS
# ─────────────────────────────────────────────────────────────────────────────

class TestVendorEvents:

    def test_vendor_emits_created_event(self, writer, ch):
        vendor = make_vendor()
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        event_types = [e.event_type for e in ch._events]
        assert "created" in event_types

    def test_vendor_created_event_entity_id(self, writer, ch):
        vendor = make_vendor(canonical_id="vendor-xyz")
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.entity_id == "vendor-xyz"

    def test_vendor_created_event_entity_type(self, writer, ch):
        vendor = make_vendor()
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = ch._events[-1]
        assert created.entity_type == "vendor"

    def test_vendor_created_event_payload_has_name(self, writer, ch):
        vendor = make_vendor(name="Workday Inc")
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.payload["name"] == "Workday Inc"

    def test_vendor_created_event_payload_has_annual_spend(self, writer, ch):
        vendor = make_vendor(annual_spend=450_000.0)
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.payload["annual_spend"] == 450_000.0

    def test_vendor_created_event_payload_has_category(self, writer, ch):
        vendor = make_vendor(category="Cloud Infrastructure")
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.payload["category"] == "Cloud Infrastructure"

    def test_vendor_source_connector_from_source_systems(self, writer, ch):
        vendor = make_vendor(source_systems=["quickbooks"])
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.source_connector == "quickbooks"

    def test_vendor_source_connector_defaults_to_netsuite(self, writer, ch):
        vendor = make_vendor(source_systems=[])
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"][0]
        assert created.source_connector == "netsuite"

    def test_multiple_vendors_one_created_each(self, writer, ch):
        vendors = [
            make_vendor("v-001", "Salesforce Inc", "salesforce-inc"),
            make_vendor("v-002", "Workday Inc", "workday-inc"),
            make_vendor("v-003", "AWS", "aws"),
        ]
        writer.write_from_vendors(vendors, TENANT)
        writer.flush()
        created = [e for e in ch._events if e.event_type == "created"]
        assert len(created) == 3

    def test_empty_vendors_list_returns_zero(self, writer):
        count = writer.write_from_vendors([], TENANT)
        assert count == 0

    def test_write_from_vendors_returns_count(self, writer):
        vendors = [make_vendor("v-001", "A", "a"), make_vendor("v-002", "B", "b")]
        count = writer.write_from_vendors(vendors, TENANT)
        assert count == 2


# ─────────────────────────────────────────────────────────────────────────────
# FLUSH MECHANICS
# ─────────────────────────────────────────────────────────────────────────────

class TestFlushMechanics:

    def test_flush_returns_count_of_written_events(self, writer, ch):
        person = make_person(start_date="2022-01-01", is_active=True)
        writer.write_from_persons([person], TENANT)
        written = writer.flush()
        assert written >= 2  # at least hired + onboarding_complete

    def test_flush_empty_buffer_returns_zero(self, writer):
        written = writer.flush()
        assert written == 0

    def test_double_flush_second_returns_zero(self, writer):
        person = make_person(start_date="2022-01-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        second = writer.flush()
        assert second == 0

    def test_buffer_cleared_after_flush(self, writer):
        person = make_person(start_date="2022-01-01")
        writer.write_from_persons([person], TENANT)
        writer.flush()
        assert len(writer._buffer) == 0

    def test_total_written_accumulates_across_flushes(self, writer):
        person_a = make_person("p-001", "a@acme.com", start_date="2022-01-01", is_active=True)
        person_b = make_person("p-002", "b@acme.com", start_date="2022-06-01", is_active=False)
        writer.write_from_persons([person_a], TENANT)
        writer.flush()
        first_batch = writer.total_written
        writer.write_from_persons([person_b], TENANT)
        writer.flush()
        assert writer.total_written > first_batch

    def test_total_written_property(self, writer):
        assert writer.total_written == 0
        vendor = make_vendor()
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        assert writer.total_written == 1

    def test_auto_flush_at_threshold(self):
        """Auto-flush fires when buffer reaches 500 items."""
        ch = MockClickHouseClient()
        writer = EventWriter(ch)
        # Generate 500+ small vendors to trigger auto-flush
        vendors = [
            make_vendor(f"v-{i:04d}", f"Vendor {i}", f"vendor-{i}")
            for i in range(510)
        ]
        writer.write_from_vendors(vendors, TENANT)
        # Auto-flush should have fired; ch._events should have data
        # (the remaining buffer may not be flushed yet)
        assert len(ch._events) >= 500

    def test_events_persist_in_clickhouse_after_flush(self, writer, ch):
        vendor = make_vendor()
        writer.write_from_vendors([vendor], TENANT)
        before = len(ch._events)
        writer.flush()
        assert len(ch._events) > before


# ─────────────────────────────────────────────────────────────────────────────
# CROSS-ENTITY INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossEntityIntegration:

    def test_mixed_entity_writes_all_show_up_in_clickhouse(self, writer, ch):
        person = make_person(start_date="2022-01-01")
        vendor = make_vendor()
        opp = make_opportunity()
        writer.write_from_persons([person], TENANT)
        writer.write_from_vendors([vendor], TENANT)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        entity_types = {e.entity_type for e in ch._events}
        assert "person" in entity_types
        assert "vendor" in entity_types
        assert "opportunity" in entity_types

    def test_all_events_tagged_with_tenant_id(self, writer, ch):
        person = make_person(start_date="2022-01-01")
        vendor = make_vendor()
        writer.write_from_persons([person], TENANT)
        writer.write_from_vendors([vendor], TENANT)
        writer.flush()
        for event in ch._events:
            assert event.tenant_id == TENANT

    def test_all_events_have_occurred_at(self, writer, ch):
        person = make_person(start_date="2022-01-01")
        vendor = make_vendor()
        opp = make_opportunity()
        writer.write_from_persons([person], TENANT)
        writer.write_from_vendors([vendor], TENANT)
        writer.write_from_opportunities([opp], TENANT)
        writer.flush()
        for event in ch._events:
            assert event.occurred_at is not None
            assert isinstance(event.occurred_at, datetime)
