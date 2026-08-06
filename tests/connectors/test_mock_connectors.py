"""
tests/connectors/test_mock_connectors.py

Unit tests for all three mock connectors.

These tests run with NO external dependencies — no Docker, no databases.
They verify that our connector implementations correctly fulfil
the ConnectorBase interface contract.

Run with:  poetry run pytest
"""

import pytest
from datetime import datetime

from scout.connectors.models import ConnectorCredentials, ExtractionCursor, RawRecord
from scout.connectors.mock.salesforce import SalesforceMockConnector
from scout.connectors.mock.workday import WorkdayMockConnector
from scout.connectors.mock.netsuite import NetsuiteMockConnector
from scout.connectors.registry import get_connector, list_connectors


# ── Shared fixture — create credentials for each connector ───────────────────

def make_creds(connector_id: str) -> ConnectorCredentials:
    """Create test credentials for any connector."""
    return ConnectorCredentials(
        connector_id=connector_id,
        tenant_id="test-tenant",
        auth_data={"token": "test-token-123"},
    )


# ─────────────────────────────────────────────────────────
# SALESFORCE TESTS
# ─────────────────────────────────────────────────────────

class TestSalesforceMock:

    def setup_method(self):
        """Create a fresh connector before each test."""
        self.connector = SalesforceMockConnector(make_creds("salesforce"))

    def test_connector_metadata(self):
        """Connector must declare its ID, name, and category."""
        assert self.connector.CONNECTOR_ID == "salesforce"
        assert "Salesforce" in self.connector.DISPLAY_NAME
        assert self.connector.CALLS_PER_SECOND > 0

    def test_authenticate_succeeds(self):
        """Mock auth should always succeed."""
        assert self.connector.authenticate() is True

    def test_discover_schema_returns_entities(self):
        """Schema discovery should return at least 2 entity types."""
        schema = self.connector.discover_schema()
        assert len(schema) >= 2
        entity_types = [s.entity_type for s in schema]
        assert "user" in entity_types
        assert "opportunity" in entity_types

    def test_extract_full_users_returns_raw_records(self):
        """extract_full should yield RawRecord objects."""
        records = list(self.connector.extract_full("user"))
        assert len(records) > 0
        for record in records:
            assert isinstance(record, RawRecord)
            assert record.connector_id == "salesforce"
            assert record.entity_type == "user"
            assert record.tenant_id == "test-tenant"
            assert record.source_id != ""
            assert isinstance(record.payload, dict)

    def test_extract_full_users_have_email_hints(self):
        """User records should have email hints for entity resolution."""
        records = list(self.connector.extract_full("user"))
        records_with_email = [r for r in records if r.email_hint]
        # Most users should have email hints (inactive users may not)
        assert len(records_with_email) >= len(records) * 0.7

    def test_extract_full_opportunities(self):
        """Should extract opportunity records."""
        records = list(self.connector.extract_full("opportunity"))
        assert len(records) > 0
        # Every opportunity must have an amount in its payload
        for record in records:
            assert "Amount" in record.payload

    def test_extract_full_unknown_entity_raises(self):
        """Unknown entity types should raise ValueError, not silently return empty."""
        with pytest.raises(ValueError, match="does not support entity type"):
            list(self.connector.extract_full("invoice"))  # that's a NetSuite entity

    def test_extract_incremental_returns_tuple(self):
        """Incremental extract must return (generator, cursor) tuple."""
        cursor = ExtractionCursor(
            connector_id="salesforce",
            entity_type="user",
            last_extracted_at=datetime(2024, 1, 1),
        )
        result = self.connector.extract_incremental("user", cursor)
        assert isinstance(result, tuple)
        assert len(result) == 2

        records_gen, new_cursor = result
        records = list(records_gen)

        # Cursor must be updated
        assert new_cursor.last_extracted_at > cursor.last_extracted_at
        # All returned records must be valid RawRecords
        for record in records:
            assert isinstance(record, RawRecord)

    def test_health_check_returns_healthy(self):
        """Health check should return healthy status with latency."""
        health = self.connector.health_check()
        assert health.is_healthy is True
        assert health.connector_id == "salesforce"
        assert health.latency_ms is not None
        assert health.latency_ms > 0


# ─────────────────────────────────────────────────────────
# WORKDAY TESTS
# ─────────────────────────────────────────────────────────

class TestWorkdayMock:

    def setup_method(self):
        self.connector = WorkdayMockConnector(make_creds("workday"))

    def test_connector_id(self):
        assert self.connector.CONNECTOR_ID == "workday"

    def test_extract_workers_includes_manager_relationships(self):
        """
        Workers must include managerId — this is what builds the
        org hierarchy in the Neo4j graph (MANAGES relationships).
        """
        records = list(self.connector.extract_full("worker"))
        workers_with_managers = [
            r for r in records if r.payload.get("managerId")
        ]
        # Most workers (except CEO) should have a manager
        assert len(workers_with_managers) >= len(records) - 2

    def test_extract_workers_have_employment_type(self):
        """Employment type is critical for cost analysis (FTE vs contractor)."""
        records = list(self.connector.extract_full("worker"))
        for record in records:
            assert "employmentType" in record.payload
            assert record.payload["employmentType"] in ("Regular", "Contractor", "Intern", "Part-time")

    def test_extract_departments(self):
        """Should extract department hierarchy records."""
        records = list(self.connector.extract_full("department"))
        assert len(records) > 0
        for record in records:
            assert "departmentId" in record.payload
            assert "name" in record.payload

    def test_workday_rate_limit_is_conservative(self):
        """Workday's rate limit should be lower than Salesforce's."""
        sfdc = SalesforceMockConnector(make_creds("salesforce"))
        assert self.connector.CALLS_PER_SECOND < sfdc.CALLS_PER_SECOND


# ─────────────────────────────────────────────────────────
# NETSUITE TESTS
# ─────────────────────────────────────────────────────────

class TestNetsuiteMock:

    def setup_method(self):
        self.connector = NetsuiteMockConnector(make_creds("netsuite"))

    def test_connector_id(self):
        assert self.connector.CONNECTOR_ID == "netsuite"

    def test_extract_vendors_have_spend_data(self):
        """
        Vendors must have annual spend — this powers the Vendor
        Intelligence Worker's consolidation analysis.
        """
        records = list(self.connector.extract_full("vendor"))
        assert len(records) > 0
        for record in records:
            assert "annualSpend" in record.payload
            assert isinstance(record.payload["annualSpend"], (int, float))

    def test_extract_vendors_have_renewal_dates(self):
        """Contract renewal dates power the negotiation timing engine."""
        records = list(self.connector.extract_full("vendor"))
        vendors_with_renewals = [
            r for r in records if r.payload.get("contractRenewal")
        ]
        # Most software vendors should have renewal dates
        software_vendors = [
            r for r in records if r.payload.get("category") == "Software"
        ]
        assert len(vendors_with_renewals) >= len(software_vendors) * 0.8

    def test_extract_invoices(self):
        """Should extract AP invoice records."""
        records = list(self.connector.extract_full("invoice"))
        assert len(records) > 0
        for record in records:
            assert "amount" in record.payload
            assert "status" in record.payload
            assert record.payload["status"] in ("Open", "Paid", "Overdue")

    def test_overdue_invoices_exist_in_fixture(self):
        """
        Fixture must include overdue invoices — these are the ones
        the Working Capital Worker flags for immediate action.
        """
        records = list(self.connector.extract_full("invoice"))
        overdue = [r for r in records if r.payload["status"] == "Overdue"]
        assert len(overdue) >= 1  # must have at least one to test the worker


# ─────────────────────────────────────────────────────────
# REGISTRY TESTS
# ─────────────────────────────────────────────────────────

class TestConnectorRegistry:

    def test_get_connector_salesforce(self):
        """Registry should return a working Salesforce connector."""
        creds = make_creds("salesforce")
        connector = get_connector("salesforce", creds)
        assert connector.CONNECTOR_ID == "salesforce"
        assert connector.authenticate() is True

    def test_get_connector_unknown_raises(self):
        """Unknown connector IDs should raise a clear ValueError."""
        creds = make_creds("nonexistent_system")
        with pytest.raises(ValueError, match="Unknown connector"):
            get_connector("nonexistent_system", creds)

    def test_list_connectors_returns_all(self):
        """list_connectors should return all registered connectors."""
        connectors = list_connectors()
        ids = [c["connector_id"] for c in connectors]
        assert "salesforce" in ids
        assert "workday" in ids
        assert "netsuite" in ids

    def test_all_connectors_pass_health_check(self):
        """Every registered connector should be healthy in mock mode."""
        for connector_id in ["salesforce", "workday", "netsuite"]:
            creds = make_creds(connector_id)
            connector = get_connector(connector_id, creds)
            health = connector.health_check()
            assert health.is_healthy, f"{connector_id} failed health check"
