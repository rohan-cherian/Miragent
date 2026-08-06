"""
tests/db/test_clickhouse.py

Unit tests for the ClickHouse event log client (mock implementation).

These tests run with NO external dependencies — no Docker, no ClickHouse.
They verify that:
  - Events can be written and read back
  - Cycle time queries return correct statistics
  - Stage distributions aggregate correctly
  - SLA breach counting works
  - Synthetic seed data provides realistic distributions
  - The factory function returns the correct implementation
  - Workers produce enhanced findings when ch_client is provided

Run with: poetry run pytest tests/db/test_clickhouse.py
"""

from datetime import datetime, timedelta, timezone

import pytest

from scout.db.clickhouse import (
    BusinessEvent,
    ClickHouseClientBase,
    CycleTimeResult,
    MockClickHouseClient,
    get_clickhouse_client,
)

TENANT = "test-tenant-ch"
NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> MockClickHouseClient:
    """Fresh mock client with no seed data."""
    return MockClickHouseClient()


@pytest.fixture
def ch_seeded() -> MockClickHouseClient:
    """Mock client pre-seeded with synthetic events."""
    return MockClickHouseClient(tenant_id=TENANT)


def make_event(
    entity_type: str,
    entity_id: str,
    event_type: str,
    days_ago: float = 0,
    tenant: str = TENANT,
) -> BusinessEvent:
    return BusinessEvent(
        tenant_id=tenant,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        occurred_at=NOW - timedelta(days=days_ago),
        source_connector="test",
        payload={"test": True},
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTERFACE COMPLIANCE
# ─────────────────────────────────────────────────────────────────────────────

class TestInterfaceCompliance:

    def test_mock_implements_base(self, client):
        """MockClickHouseClient must implement the abstract base."""
        assert isinstance(client, ClickHouseClientBase)

    def test_cycle_time_result_fields(self):
        r = CycleTimeResult(
            process="test", count=10, median_days=5.0,
            p75_days=8.0, p95_days=12.0, min_days=1.0, max_days=15.0,
        )
        assert r.process == "test"
        assert r.median_days == 5.0
        assert r.count == 10

    def test_health_check_mock(self, client):
        assert client.health_check() is True

    def test_factory_returns_mock_in_test_env(self):
        """Factory must return mock when USE_MOCK_CONNECTORS=true."""
        c = get_clickhouse_client(tenant_id=TENANT)
        assert isinstance(c, MockClickHouseClient)


# ─────────────────────────────────────────────────────────────────────────────
# WRITE & COUNT
# ─────────────────────────────────────────────────────────────────────────────

class TestEventWrite:

    def test_write_single_event(self, client):
        ev = make_event("opportunity", "opp-001", "created", days_ago=30)
        written = client.write_events([ev])
        assert written == 1

    def test_write_multiple_events(self, client):
        events = [
            make_event("opportunity", "opp-001", "created", days_ago=50),
            make_event("opportunity", "opp-001", "proposal", days_ago=30),
            make_event("opportunity", "opp-001", "closed_won", days_ago=5),
        ]
        written = client.write_events(events)
        assert written == 3

    def test_write_returns_count(self, client):
        events = [make_event("invoice", f"inv-{i}", "created") for i in range(10)]
        assert client.write_events(events) == 10

    def test_event_count_total(self, client):
        client.write_events([
            make_event("opportunity", "opp-1", "created"),
            make_event("person", "p-1", "hired"),
        ])
        assert client.event_count(TENANT) == 2

    def test_event_count_by_entity_type(self, client):
        client.write_events([
            make_event("opportunity", "opp-1", "created"),
            make_event("opportunity", "opp-2", "created"),
            make_event("person", "p-1", "hired"),
        ])
        assert client.event_count(TENANT, "opportunity") == 2
        assert client.event_count(TENANT, "person") == 1

    def test_event_count_tenant_isolation(self, client):
        client.write_events([
            make_event("opportunity", "opp-1", "created", tenant="tenant-a"),
            make_event("opportunity", "opp-2", "created", tenant="tenant-b"),
        ])
        assert client.event_count("tenant-a") == 1
        assert client.event_count("tenant-b") == 1

    def test_write_empty_list(self, client):
        assert client.write_events([]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# CYCLE TIME QUERIES
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleTimeQueries:

    def test_cycle_time_basic(self, client):
        """Write paired start/end events and verify cycle time computation."""
        # 3 opportunities: 10-day, 20-day, 30-day cycles
        for i, days in enumerate([10, 20, 30]):
            client.write_events([
                make_event("opportunity", f"opp-{i}", "created", days_ago=days + 1),
                make_event("opportunity", f"opp-{i}", "closed_won", days_ago=1),
            ])

        result = client.query_cycle_times(TENANT, "opportunity", "created", "closed_won")
        assert result.count == 3
        assert result.min_days <= result.median_days <= result.max_days
        # Median should be around 20 days (±2 days tolerance for approximation)
        assert 17 <= result.median_days <= 23

    def test_cycle_time_returns_correct_process_name(self, client):
        r = client.query_cycle_times(TENANT, "invoice", "created", "paid")
        assert "invoice" in r.process
        assert "created" in r.process
        assert "paid" in r.process

    def test_cycle_time_ignores_other_tenants(self, client):
        # Write events for two tenants
        client.write_events([
            make_event("opportunity", "opp-a", "created", days_ago=30, tenant="tenant-a"),
            make_event("opportunity", "opp-a", "closed_won", days_ago=1, tenant="tenant-a"),
            make_event("opportunity", "opp-b", "created", days_ago=100, tenant="tenant-b"),
            make_event("opportunity", "opp-b", "closed_won", days_ago=1, tenant="tenant-b"),
        ])
        result_a = client.query_cycle_times("tenant-a", "opportunity", "created", "closed_won")
        result_b = client.query_cycle_times("tenant-b", "opportunity", "created", "closed_won")
        assert result_a.count == 1
        assert result_b.count == 1

    def test_cycle_time_falls_back_to_synthetic(self, client):
        """With no real events, synthetic data must still return a result."""
        result = client.query_cycle_times(TENANT, "opportunity", "created", "closed_won")
        assert result.count > 0
        assert result.median_days > 0

    def test_cycle_time_min_lte_median_lte_max(self, ch_seeded):
        result = ch_seeded.query_cycle_times(TENANT, "opportunity", "created", "closed_won")
        assert result.min_days <= result.median_days
        assert result.median_days <= result.max_days

    def test_cycle_time_p75_between_median_and_p95(self, ch_seeded):
        result = ch_seeded.query_cycle_times(TENANT, "opportunity", "created", "closed_won")
        if result.count > 3:
            assert result.median_days <= result.p75_days <= result.p95_days


# ─────────────────────────────────────────────────────────────────────────────
# STAGE DISTRIBUTION
# ─────────────────────────────────────────────────────────────────────────────

class TestStageDistribution:

    def test_stage_distribution_from_events(self, client):
        client.write_events([
            make_event("opportunity", "o1", "prospecting"),
            make_event("opportunity", "o2", "prospecting"),
            make_event("opportunity", "o3", "proposal"),
            make_event("opportunity", "o4", "closed_won"),
        ])
        dist = client.query_stage_distribution(TENANT, "opportunity")
        assert dist.get("prospecting", 0) == 2
        assert dist.get("proposal", 0) == 1
        assert dist.get("closed_won", 0) == 1

    def test_stage_distribution_falls_back_to_synthetic(self, client):
        dist = client.query_stage_distribution(TENANT, "opportunity")
        assert len(dist) > 0
        assert all(isinstance(v, int) for v in dist.values())

    def test_stage_distribution_seeded(self, ch_seeded):
        dist = ch_seeded.query_stage_distribution(TENANT, "opportunity")
        assert "closed_won" in dist
        assert "closed_lost" in dist


# ─────────────────────────────────────────────────────────────────────────────
# SLA BREACHES
# ─────────────────────────────────────────────────────────────────────────────

class TestSlaBreaches:

    def test_sla_breach_count_is_non_negative(self, ch_seeded):
        breaches = ch_seeded.query_sla_breaches(
            TENANT, "ticket", "resolved", sla_hours=4.0
        )
        assert breaches >= 0

    def test_tight_sla_produces_more_breaches(self, ch_seeded):
        """Tighter SLA should produce more or equal breaches."""
        tight = ch_seeded.query_sla_breaches(TENANT, "ticket", "resolved", sla_hours=1.0)
        loose = ch_seeded.query_sla_breaches(TENANT, "ticket", "resolved", sla_hours=72.0)
        assert tight >= loose


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC SEED DATA
# ─────────────────────────────────────────────────────────────────────────────

class TestSyntheticData:

    def test_seeded_client_has_opportunity_events(self, ch_seeded):
        assert ch_seeded.event_count(TENANT, "opportunity") > 50

    def test_seeded_client_has_person_events(self, ch_seeded):
        assert ch_seeded.event_count(TENANT, "person") > 10

    def test_seeded_client_has_invoice_events(self, ch_seeded):
        assert ch_seeded.event_count(TENANT, "invoice") > 50

    def test_seeded_client_has_ticket_events(self, ch_seeded):
        assert ch_seeded.event_count(TENANT, "ticket") > 100

    def test_same_seed_produces_same_results(self):
        """Deterministic seeding: same tenant_id → same results."""
        c1 = MockClickHouseClient(tenant_id="stable-tenant")
        c2 = MockClickHouseClient(tenant_id="stable-tenant")
        r1 = c1.query_cycle_times("stable-tenant", "opportunity", "created", "closed_won")
        r2 = c2.query_cycle_times("stable-tenant", "opportunity", "created", "closed_won")
        assert r1.median_days == r2.median_days
        assert r1.count == r2.count


# ─────────────────────────────────────────────────────────────────────────────
# WORKER INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkerIntegration:
    """
    Verify that workers produce ClickHouse-powered findings
    when a ch_client is injected.
    """

    @pytest.fixture
    def neo4j_driver(self):
        """Mock Neo4j driver that returns empty results."""
        from unittest.mock import MagicMock
        driver = MagicMock()
        session = MagicMock()
        session.run.return_value = []
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        driver.session.return_value = session
        return driver

    def test_process_bottleneck_worker_with_ch(self, neo4j_driver, ch_seeded):
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        worker = ProcessBottleneckWorker(neo4j_driver)
        result = worker.run(TENANT, ch_client=ch_seeded)
        # Should have ClickHouse-powered findings
        ch_findings = [f for f in result.findings if f.data.get("source") == "clickhouse_event_log"]
        assert len(ch_findings) >= 1

    def test_lead_to_cash_worker_with_ch(self, neo4j_driver, ch_seeded):
        from scout.workers.lead_to_cash import LeadToCashWorker
        worker = LeadToCashWorker(neo4j_driver)
        result = worker.run(TENANT, ch_client=ch_seeded)
        # ClickHouse summary stats should be set
        assert result.summary_stats.get("clickhouse_event_log") is True

    def test_hire_to_retire_worker_with_ch(self, neo4j_driver, ch_seeded):
        from scout.workers.hire_to_retire import HireToRetireWorker
        worker = HireToRetireWorker(neo4j_driver)
        result = worker.run(TENANT, ch_client=ch_seeded)
        assert result.summary_stats.get("clickhouse_event_log") is True

    def test_issue_to_resolution_worker_with_ch(self, neo4j_driver, ch_seeded):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker
        worker = IssueToResolutionWorker(neo4j_driver)
        result = worker.run(TENANT, ch_client=ch_seeded)
        assert result.summary_stats.get("clickhouse_event_log") is True

    def test_workers_still_work_without_ch(self, neo4j_driver):
        """Backward compatibility: no ch_client → no crash."""
        from scout.workers.process_bottleneck import ProcessBottleneckWorker
        worker = ProcessBottleneckWorker(neo4j_driver)
        result = worker.run(TENANT)  # no ch_client
        # Should not error, should return INFO finding about ClickHouse
        info_findings = [f for f in result.findings if "clickhouse" in f.title.lower() or "ClickHouse" in f.detail]
        assert len(info_findings) >= 1
