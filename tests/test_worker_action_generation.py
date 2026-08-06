"""
tests/test_worker_action_generation.py — Sprint 26: Worker → ActionFactory Integration

Validates that:
  1. ActionFactory persists ActionSpecs as RemediationAction rows with full
     execution_payload populated.
  2. HireToRetireWorker emits deprovision_access actions for inactive persons.
  3. IssueToResolutionWorker emits log_activity actions for stalled deals.
  4. VendorBenchmarkWorker emits flag_vendor_invoice actions for overpaying vendors.
  5. Idempotency: re-running the same worker does not create duplicate actions.
  6. execution_runner._build_payload() uses action.execution_payload first.
  7. Pre-built spec helpers produce correctly structured ActionSpecs.

Test isolation: uses SQLite in-memory + module-scoped fixture to stay fast.
All Neo4j calls are mocked so tests run without Docker.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ── DB bootstrap ──────────────────────────────────────────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-sprint26")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from scout.db.models import Base, RemediationAction  # noqa: E402

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

TENANT = "acme-sprint26"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db():
    session = TestingSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── ActionFactory unit tests ──────────────────────────────────────────────────

class TestActionFactory:
    """Direct tests of ActionFactory.emit() / flush() / idempotency."""

    def test_emit_and_flush_creates_row(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec

        factory = ActionFactory(db, TENANT)
        factory.emit(ActionSpec(
            action_type="log_activity",
            title="Test log activity",
            description="A test action",
            evidence_source="sfdc",
            evidence_query_type="meeting_logged",
            evidence_target_ids=["opp-001"],
            execution_payload={"subject": "Test follow-up", "type": "Task"},
            finding_hash="h-test-log-001",
            worker_name="TestWorker",
            timeframe="IMMEDIATE",
            arr_impact=50_000.0,
        ))
        ids = factory.flush()
        assert len(ids) == 1

        action = db.query(RemediationAction).filter_by(id=ids[0]).one()
        assert action.action_type == "log_activity"
        assert action.tenant_id == TENANT
        assert action.status == "OPEN"
        assert action.execution_payload["subject"] == "Test follow-up"
        assert action.arr_impact == 50_000.0
        assert action.evidence_target_ids == ["opp-001"]

    def test_idempotency_skips_duplicate(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec

        spec = ActionSpec(
            action_type="deprovision_access",
            title="Deprovision Alice",
            description="Alice left",
            evidence_source="workday",
            evidence_query_type="termination_processed",
            evidence_target_ids=["wd-alice"],
            execution_payload={"worker_id": "wd-alice"},
            finding_hash="h-depr-alice-idempotency",
            worker_name="HireToRetireWorker",
        )

        factory1 = ActionFactory(db, TENANT)
        factory1.emit(spec)
        ids1 = factory1.flush()
        assert len(ids1) == 1

        factory2 = ActionFactory(db, TENANT)
        factory2.emit(spec)
        ids2 = factory2.flush()
        # Duplicate — should be skipped
        assert ids2 == []

    def test_flush_clears_pending(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec

        factory = ActionFactory(db, TENANT)
        factory.emit(ActionSpec(
            action_type="log_activity",
            title="Once",
            description="only once",
            evidence_source="sfdc",
            evidence_query_type="meeting_logged",
            evidence_target_ids=["opp-flush-test"],
            finding_hash="h-flush-test-unique",
            worker_name="TestWorker",
        ))
        factory.flush()
        # Second flush — pending is cleared, no rows emitted
        ids2 = factory.flush()
        assert ids2 == []

    def test_multiple_specs_one_flush(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec

        factory = ActionFactory(db, TENANT)
        for i in range(3):
            factory.emit(ActionSpec(
                action_type="log_activity",
                title=f"Activity {i}",
                description=f"Deal {i} stalled",
                evidence_source="sfdc",
                evidence_query_type="meeting_logged",
                evidence_target_ids=[f"opp-multi-{i}"],
                finding_hash=f"h-multi-{i}-unique",
                worker_name="TestWorker",
            ))
        ids = factory.flush()
        assert len(ids) == 3

    def test_timeframe_sets_due_date(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec
        from datetime import datetime, timezone, timedelta

        factory = ActionFactory(db, TENANT)
        factory.emit(ActionSpec(
            action_type="log_activity",
            title="IMMEDIATE action",
            description="Urgent",
            evidence_source="sfdc",
            evidence_query_type="meeting_logged",
            evidence_target_ids=["opp-tz"],
            finding_hash="h-timeframe-immediate",
            worker_name="TestWorker",
            timeframe="IMMEDIATE",
        ))
        ids = factory.flush()
        action = db.query(RemediationAction).filter_by(id=ids[0]).one()
        expected = datetime.now(timezone.utc) + timedelta(days=1)
        # SQLite stores datetimes without timezone — strip tzinfo for comparison
        due = action.due_date.replace(tzinfo=None) if action.due_date.tzinfo else action.due_date
        exp_naive = expected.replace(tzinfo=None)
        diff = abs((due - exp_naive).total_seconds())
        assert diff < 5


# ── Pre-built spec helpers ─────────────────────────────────────────────────────

class TestPreBuiltSpecs:
    """Tests for the five pre-built ActionSpec factory functions."""

    def test_departed_rep_reassignment_spec(self):
        from scout.actions.factory import departed_rep_reassignment

        spec = departed_rep_reassignment(
            finding_hash="h-rep-sarah",
            worker_name="HireToRetireWorker",
            rep_name="Sarah Chen",
            rep_sfdc_id="005AB",
            account_ids=["001A", "001B", "001C"],
            new_owner_sfdc_id="005XY",
            arr_at_risk=340_000.0,
            assigned_to_email="vpsales@acme.com",
        )
        assert spec.action_type == "reassign_accounts"
        assert spec.evidence_source == "sfdc"
        assert spec.timeframe == "IMMEDIATE"
        assert spec.arr_impact == 340_000.0
        assert "3 account" in spec.title
        assert spec.execution_payload["new_owner_id"] == "005XY"
        assert spec.execution_payload["departed_rep_id"] == "005AB"
        assert spec.execution_payload["notify_owner"] is True
        assert spec.evidence_target_ids == ["001A", "001B", "001C"]

    def test_departed_rep_reassignment_singular(self):
        from scout.actions.factory import departed_rep_reassignment

        spec = departed_rep_reassignment(
            finding_hash="h-rep-bob",
            worker_name="HireToRetireWorker",
            rep_name="Bob",
            rep_sfdc_id="005B",
            account_ids=["001X"],
            new_owner_sfdc_id=None,
            arr_at_risk=10_000.0,
        )
        assert "1 account" in spec.title
        assert "accounts" not in spec.title

    def test_deprovision_departed_employee_spec(self):
        from scout.actions.factory import deprovision_departed_employee

        spec = deprovision_departed_employee(
            finding_hash="h-deprov-alice",
            worker_name="HireToRetireWorker",
            employee_name="Alice Smith",
            workday_id="wd-alice-001",
        )
        assert spec.action_type == "deprovision_access"
        assert spec.evidence_source == "workday"
        assert spec.timeframe == "IMMEDIATE"
        assert spec.execution_payload["worker_id"] == "wd-alice-001"
        assert spec.evidence_target_ids == ["wd-alice-001"]

    def test_stalled_deal_followup_spec(self):
        from scout.actions.factory import stalled_deal_followup

        spec = stalled_deal_followup(
            finding_hash="h-stall-deal-1",
            worker_name="IssueToResolutionWorker",
            opportunity_name="Acme Corp Enterprise",
            opportunity_id="opp-001",
            account_id="acct-001",
            days_stalled=72,
            owner_email="ae@acme.com",
            arr_at_risk=120_000.0,
        )
        assert spec.action_type == "log_activity"
        assert spec.evidence_source == "sfdc"
        assert "72 days" in spec.description
        assert spec.execution_payload["type"] == "Task"
        assert "Acme Corp Enterprise" in spec.execution_payload["subject"]
        assert spec.evidence_target_ids == ["opp-001", "acct-001"]
        assert spec.arr_impact == 120_000.0

    def test_overpaying_vendor_flag_spec(self):
        from scout.actions.factory import overpaying_vendor_flag

        spec = overpaying_vendor_flag(
            finding_hash="h-vendor-salesforce",
            worker_name="VendorBenchmarkWorker",
            vendor_name="Salesforce",
            invoice_ids=["ns-inv-001", "ns-inv-002"],
            overpay_pct=65.0,
            annual_spend=200_000.0,
        )
        assert spec.action_type == "flag_vendor_invoice"
        assert spec.evidence_source == "netsuite"
        assert "65%" in spec.title
        assert spec.arr_impact == pytest.approx(200_000.0 * 0.65)
        assert spec.evidence_target_ids == ["ns-inv-001", "ns-inv-002"]

    def test_comp_review_needed_spec(self):
        from scout.actions.factory import comp_review_needed

        spec = comp_review_needed(
            finding_hash="h-comp-bob",
            worker_name="HireToRetireWorker",
            employee_name="Bob Jones",
            workday_id="wd-bob",
            reason="Promotion",
            effective_date="2026-07-01",
        )
        assert spec.action_type == "initiate_comp_review"
        assert spec.evidence_source == "workday"
        assert spec.execution_payload["reason"] == "Promotion"
        assert spec.execution_payload["effective_date"] == "2026-07-01"


# ── HireToRetireWorker action emission ────────────────────────────────────────

class TestHireToRetireActionEmission:
    """Tests that HireToRetireWorker emits actions when db is provided."""

    def _make_mock_driver(self, persons: list[dict], manager_spans: list[dict] = None):
        """Build a mock Neo4j driver that returns the given person list."""
        driver = MagicMock()
        session_ctx = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_ctx)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        def run_side_effect(query, **kwargs):
            result_mock = MagicMock()
            if "MANAGES" in query:
                data = manager_spans or []
                result_mock.__iter__ = MagicMock(return_value=iter(data))
                result_mock.data.return_value = data
            else:
                result_mock.__iter__ = MagicMock(return_value=iter(persons))
                result_mock.data.return_value = persons
            result_mock.single.return_value = None
            return result_mock

        session_ctx.run.side_effect = run_side_effect
        return driver

    def test_emits_deprovision_for_inactive_person(self, db):
        from scout.workers.hire_to_retire import HireToRetireWorker

        inactive = [
            {"canonical_id": "p-001", "full_name": "Alice Smith",
             "department": "Sales", "title": "AE", "is_active": False}
        ]
        active = [
            {"canonical_id": "p-002", "full_name": "Bob Jones",
             "department": "Sales", "title": "Manager", "is_active": True}
        ]
        persons = active + inactive

        worker = HireToRetireWorker.__new__(HireToRetireWorker)
        worker.driver = self._make_mock_driver(persons)

        tenant = "acme-h2r-deprov-test"
        result = worker.run(tenant_id=tenant, config=None, db=db)
        assert result.error is None
        assert result.summary_stats.get("actions_emitted", 0) >= 1

        actions = db.query(RemediationAction).filter_by(
            tenant_id=tenant,
            action_type="deprovision_access",
        ).all()
        assert len(actions) >= 1
        action = actions[0]
        assert action.execution_payload["worker_id"] == "p-001"
        assert action.status == "OPEN"

    def test_no_actions_when_all_active(self, db):
        from scout.workers.hire_to_retire import HireToRetireWorker

        persons = [
            {"canonical_id": f"p-{i}", "full_name": f"Person {i}",
             "department": "Eng", "title": "SWE", "is_active": True}
            for i in range(5)
        ]

        worker = HireToRetireWorker.__new__(HireToRetireWorker)
        worker.driver = self._make_mock_driver(persons)

        result = worker.run(
            tenant_id="acme-all-active", config=None, db=db
        )
        assert result.summary_stats.get("actions_emitted", 0) == 0

    def test_no_actions_without_db(self):
        from scout.workers.hire_to_retire import HireToRetireWorker

        persons = [
            {"canonical_id": "p-nodb", "full_name": "Ghost User",
             "department": "IT", "title": "Admin", "is_active": False}
        ]

        worker = HireToRetireWorker.__new__(HireToRetireWorker)
        worker.driver = self._make_mock_driver(persons)

        result = worker.run(tenant_id="acme-nodb", config=None, db=None)
        # No crash, no actions_emitted key set by the emission path
        assert result.error is None
        assert "action_ids_created" not in result.summary_stats

    def test_idempotent_on_rerun(self, db):
        """Running the same worker twice should not create duplicate actions."""
        from scout.workers.hire_to_retire import HireToRetireWorker

        persons = [
            {"canonical_id": "p-idem-001", "full_name": "Idem Person",
             "department": "Ops", "title": "COO", "is_active": False}
        ]

        worker = HireToRetireWorker.__new__(HireToRetireWorker)
        worker.driver = self._make_mock_driver(persons)

        tenant = "acme-h2r-idem"
        worker.run(tenant_id=tenant, config=None, db=db)
        db.commit()

        # Reset mock to return same data
        worker.driver = self._make_mock_driver(persons)
        worker.run(tenant_id=tenant, config=None, db=db)
        db.commit()

        actions = db.query(RemediationAction).filter_by(
            tenant_id=tenant,
            action_type="deprovision_access",
        ).all()
        assert len(actions) == 1  # Not 2


# ── IssueToResolutionWorker action emission ───────────────────────────────────

class TestIssueToResolutionActionEmission:
    """Tests that IssueToResolutionWorker emits stalled-deal actions."""

    def _make_mock_driver(
        self,
        open_opps: list[dict],
        opp_summary: dict | None = None,
        orphaned: list[dict] | None = None,
    ):
        driver = MagicMock()
        session_ctx = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_ctx)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        summary = opp_summary or {"total": len(open_opps), "closed": 5, "won": 3}

        def run_side_effect(query, **kwargs):
            result_mock = MagicMock()
            if "is_closed: false" in query:
                result_mock.__iter__ = MagicMock(return_value=iter(open_opps))
                result_mock.single.return_value = None
            elif "orphaned" in query.lower() or "Customer" in query:
                data = orphaned or []
                result_mock.__iter__ = MagicMock(return_value=iter(data))
                result_mock.single.return_value = None
            else:
                # Summary query
                row = MagicMock()
                row.__getitem__ = lambda self, k: summary.get(k, 0)
                row.keys = lambda: summary.keys()

                class RowAdapter:
                    def __init__(self, d):
                        self._d = d
                    def __getitem__(self, k):
                        return self._d[k]
                    def keys(self):
                        return self._d.keys()

                result_mock.single.return_value = RowAdapter(summary)
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            return result_mock

        session_ctx.run.side_effect = run_side_effect
        return driver

    def test_emits_log_activity_for_stalled_deal(self, db):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker

        stalled = [
            {
                "canonical_id": "opp-stall-001",
                "name": "Big Enterprise Deal",
                "stage": "Proposal",
                "amount": 150_000.0,
                "days_in_pipeline": 95,
                "is_closed": False,
                "account_name": "Acme Corp",
                "account_canonical_id": "acct-001",
                "owner_email": "ae@acme.com",
            }
        ]

        worker = IssueToResolutionWorker.__new__(IssueToResolutionWorker)
        worker.driver = self._make_mock_driver(stalled)

        tenant = "acme-i2r-stall-test"
        result = worker.run(tenant_id=tenant, config=None, db=db)
        assert result.error is None
        assert result.summary_stats.get("actions_emitted", 0) >= 1

        actions = db.query(RemediationAction).filter_by(
            tenant_id=tenant,
            action_type="log_activity",
        ).all()
        assert len(actions) >= 1
        action = actions[0]
        assert action.execution_payload["type"] == "Task"
        assert "Big Enterprise Deal" in action.execution_payload["subject"]

    def test_no_actions_for_fresh_pipeline(self, db):
        """Deals under the threshold should produce no actions."""
        from scout.workers.issue_to_resolution import IssueToResolutionWorker

        fresh = [
            {
                "canonical_id": "opp-fresh-001",
                "name": "New Deal",
                "stage": "Qualification",
                "amount": 50_000.0,
                "days_in_pipeline": 10,  # well under threshold
                "is_closed": False,
                "account_name": "Beta Corp",
            }
        ]

        worker = IssueToResolutionWorker.__new__(IssueToResolutionWorker)
        worker.driver = self._make_mock_driver(fresh)

        result = worker.run(tenant_id="acme-fresh-pipe", config=None, db=db)
        assert result.summary_stats.get("actions_emitted", 0) == 0

    def test_stalled_deal_payload_fields(self, db):
        from scout.workers.issue_to_resolution import IssueToResolutionWorker

        stalled = [
            {
                "canonical_id": "opp-payload-check",
                "name": "Payload Check Deal",
                "stage": "Negotiation",
                "amount": 200_000.0,
                "days_in_pipeline": 100,
                "is_closed": False,
                "account_name": "Gamma Inc",
                "account_canonical_id": "acct-gamma",
                "owner_email": "rep@gamma.com",
            }
        ]

        worker = IssueToResolutionWorker.__new__(IssueToResolutionWorker)
        worker.driver = self._make_mock_driver(stalled)

        tenant = "acme-payload-check"
        worker.run(tenant_id=tenant, config=None, db=db)
        db.commit()

        action = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="log_activity"
        ).one()
        payload = action.execution_payload
        assert payload["type"] == "Task"
        assert "100 days" in payload["description"]
        assert action.arr_impact == 200_000.0
        assert action.assigned_to_email == "rep@gamma.com"


# ── VendorBenchmarkWorker action emission ─────────────────────────────────────

class TestVendorBenchmarkActionEmission:
    """Tests that VendorBenchmarkWorker emits flag_vendor_invoice actions."""

    def _make_mock_driver(self, vendors: list[dict]):
        driver = MagicMock()
        session_ctx = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_ctx)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        run_result = MagicMock()
        run_result.data.return_value = vendors
        session_ctx.run.return_value = run_result
        return driver

    def test_emits_flag_invoice_for_overpaying_vendor(self, db):
        from scout.workers.vendor_benchmark import VendorBenchmarkWorker

        # Salesforce is in the vendor catalog
        vendors = [
            {"name": "Salesforce", "annual_spend": 300_000.0,
             "category": "CRM", "contract_renewal": "2027-01-01",
             "payment_terms": "Net30", "is_active": True}
        ]

        worker = VendorBenchmarkWorker.__new__(VendorBenchmarkWorker)
        worker.driver = self._make_mock_driver(vendors)

        # Patch lookup_vendor to return a catalog with mid_market benchmark
        fake_catalog = {
            "typical_contract_size": {"mid_market": 100_000},
            "typical_discount_pct": 20,
            "red_flags": [],
            "alternatives": [],
            "negotiation_leverage": [],
        }

        with patch(
            "scout.workers.vendor_benchmark.lookup_vendor",
            return_value=fake_catalog,
        ):
            tenant = "acme-vendor-flag"
            result = worker.run(tenant_id=tenant, config=None, db=db)
            db.commit()

        assert result.error is None
        # 300k / 100k - 1 = 200% overpay > 50% critical threshold
        assert result.summary_stats.get("actions_emitted", 0) >= 1

        actions = db.query(RemediationAction).filter_by(
            tenant_id=tenant, action_type="flag_vendor_invoice"
        ).all()
        assert len(actions) == 1
        assert actions[0].evidence_source == "netsuite"

    def test_no_action_for_vendor_not_in_catalog(self, db):
        from scout.workers.vendor_benchmark import VendorBenchmarkWorker

        vendors = [
            {"name": "ObscureTool", "annual_spend": 500_000.0,
             "category": "Other", "contract_renewal": None,
             "payment_terms": None, "is_active": True}
        ]

        worker = VendorBenchmarkWorker.__new__(VendorBenchmarkWorker)
        worker.driver = self._make_mock_driver(vendors)

        with patch("scout.workers.vendor_benchmark.lookup_vendor", return_value=None):
            result = worker.run(
                tenant_id="acme-no-catalog", config=None, db=db
            )

        # No catalog → no action
        assert result.summary_stats.get("actions_emitted", 0) == 0

    def test_no_action_when_db_is_none(self):
        from scout.workers.vendor_benchmark import VendorBenchmarkWorker

        vendors = [
            {"name": "Salesforce", "annual_spend": 500_000.0,
             "category": "CRM", "contract_renewal": None,
             "payment_terms": None, "is_active": True}
        ]

        worker = VendorBenchmarkWorker.__new__(VendorBenchmarkWorker)
        worker.driver = self._make_mock_driver(vendors)

        fake_catalog = {
            "typical_contract_size": {"mid_market": 100_000},
            "typical_discount_pct": 20,
            "red_flags": [],
            "alternatives": [],
            "negotiation_leverage": [],
        }

        with patch("scout.workers.vendor_benchmark.lookup_vendor", return_value=fake_catalog):
            result = worker.run(
                tenant_id="acme-vendor-nodb", config=None, db=None
            )

        # db=None → no action emission path runs
        assert "action_ids_created" not in result.summary_stats
        assert result.error is None


# ── execution_runner._build_payload fix ───────────────────────────────────────

class TestBuildPayload:
    """execution_runner._build_payload uses execution_payload when set."""

    def test_uses_execution_payload_when_set(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec
        from scout.actions.execution_runner import _build_payload

        factory = ActionFactory(db, TENANT)
        factory.emit(ActionSpec(
            action_type="reassign_accounts",
            title="Reassign test",
            description="test",
            evidence_source="sfdc",
            evidence_query_type="account_owner_changed",
            evidence_target_ids=["acct-001"],
            execution_payload={
                "new_owner_id": "005XY",
                "departed_rep_id": "005AB",
                "notify_owner": True,
            },
            finding_hash="h-build-payload-test",
            worker_name="TestWorker",
        ))
        ids = factory.flush()
        action = db.query(RemediationAction).filter_by(id=ids[0]).one()

        payload = _build_payload(action)
        assert payload["new_owner_id"] == "005XY"
        assert payload["departed_rep_id"] == "005AB"
        assert payload["notify_owner"] is True

    def test_falls_back_to_generic_when_no_payload(self, db):
        from scout.actions.factory import ActionFactory, ActionSpec
        from scout.actions.execution_runner import _build_payload

        # Create action with empty execution_payload
        factory = ActionFactory(db, TENANT)
        factory.emit(ActionSpec(
            action_type="log_activity",
            title="Legacy action",
            description="pre-Sprint26",
            evidence_source="sfdc",
            evidence_query_type="meeting_logged",
            evidence_target_ids=["opp-legacy"],
            execution_payload={},  # empty — triggers fallback
            finding_hash="h-legacy-payload",
            worker_name="LegacyWorker",
            assigned_to_email="owner@acme.com",
        ))
        ids = factory.flush()
        action = db.query(RemediationAction).filter_by(id=ids[0]).one()
        action.execution_payload = None  # simulate pre-Sprint26 action
        db.flush()

        payload = _build_payload(action)
        # Falls back to generic fields
        assert payload["action_type"] == "log_activity"
        assert payload["assigned_to_email"] == "owner@acme.com"
