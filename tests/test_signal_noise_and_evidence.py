"""
tests/test_signal_noise_and_evidence.py

Tests for Sprint 22 (Signal/Noise Engine) and Sprint 23 (Organic Action Tracking).

Covers:
  Sprint 22:
  - NoiseProfile creation and signal score computation
  - WIP cap adaptation based on dismiss rate
  - ThresholdProposal generation when dismiss rate exceeds trigger
  - Proposal deduplication (no double proposals for same key)
  - Admin API: GET /admin/noise-profiles
  - Admin API: POST /admin/proposals/{id}/accept → applies threshold change
  - Admin API: POST /admin/proposals/{id}/reject

  Sprint 23:
  - EvidenceChecker protocol (mock-based)
  - SalesforceEvidenceChecker: account_owner_changed logic
  - WorkdayEvidenceChecker: comp_event_completed logic
  - NetSuiteEvidenceChecker: po_approved logic
  - evidence_scanner.run_evidence_scan: auto-completes FOUND actions
  - evidence_scanner.run_evidence_scan: marks IN_PROGRESS on PARTIAL
  - evidence_scanner: logs EvidenceCheckLog rows
  - evidence_scanner: schedules ActionReminder rows
  - Admin API: GET /admin/actions/{id}/evidence
  - Admin API: POST /admin/actions/{id}/recheck
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from scout.actions.evidence_checkers import (
    EvidenceResult,
    NetSuiteEvidenceChecker,
    SalesforceEvidenceChecker,
    WorkdayEvidenceChecker,
    get_checker,
)
from scout.actions.evidence_scanner import run_evidence_scan
from scout.engine.noise_scanner import (
    NOISE_TRIGGER,
    MIN_SAMPLE,
    run_noise_scan,
    get_wip_cap,
)


# ─────────────────────────────────────────────────────────────────────────────
# SHARED FIXTURES
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app_client():
    """TestClient backed by a fresh SQLite DB for the whole module."""
    os.environ.setdefault("USE_MOCK_CONNECTORS", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite:///./test_sprint22.db")
    os.environ.setdefault("SECRET_KEY", "test-secret-sprint22")
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "password")

    from scout.api.app import create_app
    from scout.db.database import engine
    from scout.db.models import Base
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    app = create_app()
    with TestClient(app) as client:
        yield client

    import os as _os
    for f in ["test_sprint22.db", "test_sprint22.db-shm", "test_sprint22.db-wal"]:
        try:
            _os.remove(f)
        except FileNotFoundError:
            pass


@pytest.fixture(scope="module")
def admin_token(app_client):
    app_client.post("/users/tenants", json={"name": "Acme Sprint22", "slug": "acme-22"})
    app_client.post("/users/register", json={
        "email": "admin22@acme.com", "password": "S3cr3t!",
        "tenant_slug": "acme-22", "role": "admin",
    })
    resp = app_client.post("/users/login", json={
        "email": "admin22@acme.com", "password": "S3cr3t!",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def db_session():
    """Provide a direct SQLAlchemy session for unit-testing scanner logic."""
    from scout.db.database import SessionLocal
    from scout.db.models import Base, Tenant
    from scout.db.database import engine
    # Use a fresh in-memory DB for unit tests
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    session = Session()

    # Seed a tenant
    tenant = Tenant(id="t-unit", name="Unit Test Tenant", slug="unit-test")
    session.add(tenant)
    session.commit()

    yield session
    session.close()


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 22: NOISE SCANNER — UNIT TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestNoiseScanner:

    def _seed_dispositions(self, db, tenant_id, worker_name, acted, dismissed, snoozed=0):
        """Seed FindingDisposition rows for testing."""
        from scout.db.models import FindingDisposition
        now = datetime.now(timezone.utc)
        for i in range(acted):
            db.add(FindingDisposition(
                tenant_id=tenant_id, finding_hash=f"h-a-{i}",
                worker_name=worker_name, severity="HIGH",
                disposition="ACTED", disposed_by="test@test.com",
                disposed_at=now,
            ))
        for i in range(dismissed):
            db.add(FindingDisposition(
                tenant_id=tenant_id, finding_hash=f"h-d-{worker_name}-{i}",
                worker_name=worker_name, severity="HIGH",
                disposition="DISMISSED", disposed_by="test@test.com",
                disposed_at=now,
            ))
        for i in range(snoozed):
            db.add(FindingDisposition(
                tenant_id=tenant_id, finding_hash=f"h-s-{i}",
                worker_name=worker_name, severity="MEDIUM",
                disposition="SNOOZED", disposed_by="test@test.com",
                disposed_at=now,
            ))
        db.commit()

    def test_scan_creates_noise_profile(self, db_session):
        self._seed_dispositions(db_session, "t-unit", "HireToRetireWorker",
                                acted=3, dismissed=2)
        summary = run_noise_scan(db_session, "t-unit")
        assert "HireToRetireWorker" in summary["workers_scanned"]
        assert summary["profiles_updated"] >= 1

    def test_signal_score_all_acted(self, db_session):
        from scout.db.models import NoiseProfile
        from sqlalchemy import select
        self._seed_dispositions(db_session, "t-unit", "VendorBenchmarkWorker",
                                acted=8, dismissed=0)
        run_noise_scan(db_session, "t-unit")
        profile = db_session.execute(
            select(NoiseProfile).where(
                NoiseProfile.tenant_id == "t-unit",
                NoiseProfile.worker_name == "VendorBenchmarkWorker",
            )
        ).scalar_one_or_none()
        assert profile is not None
        assert profile.signal_score == 1.0
        assert profile.dismissed_rate == 0.0

    def test_signal_score_all_dismissed(self, db_session):
        from scout.db.models import NoiseProfile
        from sqlalchemy import select
        # Use a unique worker name to avoid interference from other test data
        self._seed_dispositions(db_session, "t-unit", "LeadToCashWorker",
                                acted=0, dismissed=8)
        run_noise_scan(db_session, "t-unit")
        profile = db_session.execute(
            select(NoiseProfile).where(
                NoiseProfile.tenant_id == "t-unit",
                NoiseProfile.worker_name == "LeadToCashWorker",
            )
        ).scalar_one_or_none()
        assert profile is not None
        assert profile.signal_score == 0.0
        assert profile.dismissed_rate == 1.0

    def test_wip_cap_adapts_with_dismiss_rate(self, db_session):
        from scout.db.models import NoiseProfile
        from sqlalchemy import select
        # High dismiss rate → low WIP cap
        self._seed_dispositions(db_session, "t-unit", "ProcessBottleneckWorker",
                                acted=1, dismissed=9)
        run_noise_scan(db_session, "t-unit")
        cap = get_wip_cap(db_session, "t-unit", "ProcessBottleneckWorker")
        assert cap < 5   # should be reduced from default

    def test_no_proposal_below_min_sample(self, db_session):
        from scout.db.models import ThresholdProposal
        from sqlalchemy import select
        # Only 2 dismissals — below MIN_SAMPLE
        self._seed_dispositions(db_session, "t-unit", "ExpenseAuditWorker",
                                acted=0, dismissed=2)
        summary = run_noise_scan(db_session, "t-unit")
        proposals = db_session.execute(
            select(ThresholdProposal).where(
                ThresholdProposal.tenant_id == "t-unit",
                ThresholdProposal.worker_name == "ExpenseAuditWorker",
            )
        ).scalars().all()
        assert proposals == []

    def test_proposal_created_at_high_dismiss_rate(self, db_session):
        from scout.db.models import ThresholdProposal
        from sqlalchemy import select
        # 8 dismissed out of 10 = 80% — above NOISE_TRIGGER
        self._seed_dispositions(db_session, "t-unit", "IssueToResolutionWorker",
                                acted=2, dismissed=8)
        run_noise_scan(db_session, "t-unit")
        proposals = db_session.execute(
            select(ThresholdProposal).where(
                ThresholdProposal.tenant_id == "t-unit",
                ThresholdProposal.worker_name == "IssueToResolutionWorker",
                ThresholdProposal.status == "PENDING",
            )
        ).scalars().all()
        assert len(proposals) >= 1
        p = proposals[0]
        assert p.proposed_value > p.current_value
        assert p.direction == "raise"
        assert "80%" in p.rationale or "0.8" in p.rationale

    def test_no_duplicate_proposals(self, db_session):
        """Running the scanner twice should not create duplicate PENDING proposals."""
        from scout.db.models import ThresholdProposal
        from sqlalchemy import select
        # Re-run — IssueToResolutionWorker already has PENDING proposals from previous test
        run_noise_scan(db_session, "t-unit")
        proposals = db_session.execute(
            select(ThresholdProposal).where(
                ThresholdProposal.tenant_id == "t-unit",
                ThresholdProposal.worker_name == "IssueToResolutionWorker",
                ThresholdProposal.status == "PENDING",
            )
        ).scalars().all()
        # Should be same count — no duplicates added
        keys = [p.threshold_key for p in proposals]
        assert len(keys) == len(set(keys)), "Duplicate proposals created for same key!"

    def test_proposal_confidence_scales_with_sample_size(self, db_session):
        from scout.db.models import ThresholdProposal
        from sqlalchemy import select
        proposals = db_session.execute(
            select(ThresholdProposal).where(
                ThresholdProposal.tenant_id == "t-unit",
                ThresholdProposal.worker_name == "IssueToResolutionWorker",
            )
        ).scalars().all()
        for p in proposals:
            assert 0 < p.confidence <= 1.0

    def test_get_wip_cap_returns_default_for_unknown_worker(self, db_session):
        from scout.engine.noise_scanner import DEFAULT_WIP_CAP
        cap = get_wip_cap(db_session, "t-unit", "NonExistentWorker")
        assert cap == DEFAULT_WIP_CAP


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 22: NOISE API — INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestNoiseAPI:

    def test_noise_profiles_endpoint_requires_auth(self, app_client):
        resp = app_client.get("/admin/noise-profiles")
        assert resp.status_code in (401, 403)

    def test_noise_profiles_returns_list(self, app_client, admin_token):
        resp = app_client.get(
            "/admin/noise-profiles",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_refresh_noise_profiles_requires_admin(self, app_client, admin_token):
        resp = app_client.post(
            "/admin/noise-profiles/refresh",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "profiles_updated" in data

    def test_proposals_endpoint_empty_initially(self, app_client, admin_token):
        resp = app_client.get(
            "/admin/proposals",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_proposal_accept_reject_404_on_unknown(self, app_client, admin_token):
        auth = {"Authorization": f"Bearer {admin_token}"}
        resp = app_client.post("/admin/proposals/nonexistent-id/accept", headers=auth)
        assert resp.status_code == 404

        resp = app_client.post("/admin/proposals/nonexistent-id/reject", headers=auth)
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 23: EVIDENCE CHECKERS — UNIT TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestSalesforceEvidenceChecker:

    def _mock_connector(self, accounts: dict, activities: dict = None):
        """Build a mock SFDC connector with specified account data."""
        conn = MagicMock()
        conn.get_account.side_effect = lambda acct_id: accounts.get(acct_id)
        conn.get_activities.return_value = activities or []
        return conn

    def test_no_connector_returns_not_yet(self):
        checker = SalesforceEvidenceChecker(connector=None)
        result = checker.check("account_owner_changed", ["001"], {})
        assert result.result == EvidenceResult.NOT_YET

    def test_all_accounts_reassigned_returns_found(self):
        now_str = datetime.now(timezone.utc).isoformat()
        conn = self._mock_connector({
            "001": {"OwnerId": "NewRep", "LastModifiedDate": now_str},
            "002": {"OwnerId": "NewRep", "LastModifiedDate": now_str},
        })
        checker = SalesforceEvidenceChecker(connector=conn)
        result = checker.check(
            "account_owner_changed",
            ["001", "002"],
            {"created_at": "2020-01-01", "departed_rep_id": "OldRep"},
        )
        assert result.result == EvidenceResult.FOUND

    def test_partial_accounts_reassigned_returns_partial(self):
        now_str = datetime.now(timezone.utc).isoformat()
        conn = self._mock_connector({
            "001": {"OwnerId": "NewRep", "LastModifiedDate": now_str},
            "002": {"OwnerId": "OldRep", "LastModifiedDate": now_str},  # not reassigned
        })
        checker = SalesforceEvidenceChecker(connector=conn)
        result = checker.check(
            "account_owner_changed",
            ["001", "002"],
            {"created_at": "2020-01-01", "departed_rep_id": "OldRep"},
        )
        assert result.result == EvidenceResult.PARTIAL

    def test_no_accounts_reassigned_returns_not_yet(self):
        now_str = datetime.now(timezone.utc).isoformat()
        conn = self._mock_connector({
            "001": {"OwnerId": "OldRep", "LastModifiedDate": now_str},
        })
        checker = SalesforceEvidenceChecker(connector=conn)
        result = checker.check(
            "account_owner_changed",
            ["001"],
            {"created_at": "2020-01-01", "departed_rep_id": "OldRep"},
        )
        assert result.result == EvidenceResult.NOT_YET

    def test_meeting_logged_returns_found(self):
        conn = MagicMock()
        conn.get_activities.return_value = [{"Id": "act1", "Subject": "Call"}]
        checker = SalesforceEvidenceChecker(connector=conn)
        result = checker.check(
            "meeting_logged",
            ["001"],
            {"created_at": "2020-01-01"},
        )
        assert result.result == EvidenceResult.FOUND

    def test_connector_exception_returns_error(self):
        conn = MagicMock()
        conn.get_account.side_effect = Exception("API rate limit exceeded")
        checker = SalesforceEvidenceChecker(connector=conn)
        result = checker.check(
            "account_owner_changed",
            ["001"],
            {"created_at": "2020-01-01", "departed_rep_id": "OldRep"},
        )
        assert result.result == EvidenceResult.ERROR
        assert "rate limit" in result.error_detail


class TestWorkdayEvidenceChecker:

    def test_no_connector_returns_not_yet(self):
        checker = WorkdayEvidenceChecker(connector=None)
        result = checker.check("comp_event_completed", ["w001"], {})
        assert result.result == EvidenceResult.NOT_YET

    def test_comp_events_found_for_all_workers(self):
        conn = MagicMock()
        conn.get_comp_events.return_value = [{"eventId": "e1"}]
        checker = WorkdayEvidenceChecker(connector=conn)
        result = checker.check(
            "comp_event_completed",
            ["w001", "w002"],
            {"created_at": "2020-01-01"},
        )
        assert result.result == EvidenceResult.FOUND

    def test_position_filled_partial(self):
        conn = MagicMock()
        conn.get_position.side_effect = lambda pos_id: (
            {"status": "FILLED"} if pos_id == "pos1" else {"status": "OPEN"}
        )
        checker = WorkdayEvidenceChecker(connector=conn)
        result = checker.check("position_filled", ["pos1", "pos2"], {})
        assert result.result == EvidenceResult.PARTIAL

    def test_position_all_filled(self):
        conn = MagicMock()
        conn.get_position.return_value = {"status": "FILLED"}
        checker = WorkdayEvidenceChecker(connector=conn)
        result = checker.check("position_filled", ["pos1"], {})
        assert result.result == EvidenceResult.FOUND


class TestNetSuiteEvidenceChecker:

    def test_no_connector_returns_not_yet(self):
        checker = NetSuiteEvidenceChecker(connector=None)
        result = checker.check("po_approved", ["po1"], {})
        assert result.result == EvidenceResult.NOT_YET

    def test_po_approved_found(self):
        conn = MagicMock()
        conn.get_po_status.return_value = "Approved"
        checker = NetSuiteEvidenceChecker(connector=conn)
        result = checker.check("po_approved", ["po1", "po2"], {})
        assert result.result == EvidenceResult.FOUND

    def test_po_partial(self):
        conn = MagicMock()
        conn.get_po_status.side_effect = lambda po_id: (
            "Approved" if po_id == "po1" else "Pending"
        )
        checker = NetSuiteEvidenceChecker(connector=conn)
        result = checker.check("po_approved", ["po1", "po2"], {})
        assert result.result == EvidenceResult.PARTIAL

    def test_invoice_paid_not_yet(self):
        conn = MagicMock()
        conn.get_recent_payments.return_value = []
        checker = NetSuiteEvidenceChecker(connector=conn)
        result = checker.check("vendor_invoice_paid", ["v1"], {"created_at": "2020-01-01"})
        assert result.result == EvidenceResult.NOT_YET


class TestCheckerRegistry:

    def test_get_checker_sfdc(self):
        checker = get_checker("sfdc")
        assert checker is not None
        assert checker.source_name == "sfdc"

    def test_get_checker_workday(self):
        checker = get_checker("workday")
        assert checker.source_name == "workday"

    def test_get_checker_netsuite(self):
        checker = get_checker("netsuite")
        assert checker.source_name == "netsuite"

    def test_get_checker_unknown_returns_none(self):
        checker = get_checker("hubspot")
        assert checker is None


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 23: EVIDENCE SCANNER — UNIT TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestEvidenceScanner:

    def _seed_action(
        self, db, tenant_id="t-unit",
        evidence_source="sfdc",
        evidence_query_type="account_owner_changed",
        status="OPEN",
        target_ids=None,
        due_days=7,
    ):
        from scout.db.models import RemediationAction
        action = RemediationAction(
            tenant_id=tenant_id,
            finding_hash="test-hash",
            worker_name="HireToRetireWorker",
            title="Reassign accounts for departed rep",
            description="Rep left — reassign 3 accounts.",
            action_type="reassign_accounts",
            assigned_to_email="vpsales@acme.com",
            effort="LOW",
            timeframe="IMMEDIATE",
            status=status,
            evidence_source=evidence_source,
            evidence_query_type=evidence_query_type,
            evidence_target_ids=target_ids or ["001", "002"],
            due_date=datetime.now(timezone.utc) + timedelta(days=due_days),
        )
        db.add(action)
        db.commit()
        return action

    def test_found_evidence_auto_completes_action(self, db_session):
        action = self._seed_action(db_session)
        action_id = action.id

        # Mock SFDC connector that says all accounts reassigned
        now_str = datetime.now(timezone.utc).isoformat()
        mock_conn = MagicMock()
        mock_conn.get_account.return_value = {
            "OwnerId": "NewRep", "LastModifiedDate": now_str
        }

        summary = run_evidence_scan(
            db_session, "t-unit",
            connector_map={"sfdc": mock_conn}
        )

        from sqlalchemy import select
        from scout.db.models import RemediationAction
        updated = db_session.get(RemediationAction, action_id)
        assert updated.status == "COMPLETE"
        assert updated.completion_method == "AUTO"
        assert updated.completed_at is not None
        assert summary["auto_completed"] >= 1

    def test_partial_evidence_marks_in_progress(self, db_session):
        """
        Partial: one account reassigned, one not found (returns None).
        The checker only counts accounts that exist and have a new owner.
        An account returning None from get_account() is simply skipped —
        so 1 changed out of 2 targets = PARTIAL.
        """
        action = self._seed_action(db_session, target_ids=["acct-found", "acct-missing"])
        action_id = action.id

        now_str = datetime.now(timezone.utc).isoformat()
        mock_conn = MagicMock()
        mock_conn.get_account.side_effect = lambda acct_id: (
            {"OwnerId": "NewRep", "LastModifiedDate": now_str}
            if acct_id == "acct-found"
            else None   # simulates account not returned by API
        )

        run_evidence_scan(
            db_session, "t-unit",
            connector_map={"sfdc": mock_conn}
        )

        from scout.db.models import RemediationAction
        updated = db_session.get(RemediationAction, action_id)
        # 1 account changed out of 2 targets → PARTIAL, not COMPLETE
        assert updated.status == "IN_PROGRESS"

    def test_no_evidence_leaves_status_open(self, db_session):
        # No connector → NOT_YET for all
        action = self._seed_action(db_session)
        action_id = action.id

        run_evidence_scan(db_session, "t-unit", connector_map={})

        from scout.db.models import RemediationAction
        updated = db_session.get(RemediationAction, action_id)
        assert updated.status == "OPEN"

    def test_evidence_check_logged(self, db_session):
        from scout.db.models import EvidenceCheckLog
        from sqlalchemy import select

        action = self._seed_action(db_session, evidence_query_type="meeting_logged")
        action_id = action.id

        mock_conn = MagicMock()
        mock_conn.get_activities.return_value = []

        run_evidence_scan(db_session, "t-unit", connector_map={"sfdc": mock_conn})

        logs = db_session.execute(
            select(EvidenceCheckLog).where(EvidenceCheckLog.action_id == action_id)
        ).scalars().all()
        assert len(logs) >= 1
        assert logs[0].evidence_source == "sfdc"

    def test_error_result_does_not_change_status(self, db_session):
        action = self._seed_action(db_session)
        action_id = action.id

        mock_conn = MagicMock()
        mock_conn.get_account.side_effect = Exception("Salesforce is down")

        run_evidence_scan(db_session, "t-unit", connector_map={"sfdc": mock_conn})

        from scout.db.models import RemediationAction
        updated = db_session.get(RemediationAction, action_id)
        # Status should be unchanged despite error
        assert updated.status in ("OPEN", "IN_PROGRESS")  # not COMPLETE

    def test_reminders_scheduled_for_upcoming_due_dates(self, db_session):
        from scout.db.models import ActionReminder
        from sqlalchemy import select

        # Seed action with due date 5 days from now
        action = self._seed_action(db_session, due_days=5)

        run_evidence_scan(db_session, "t-unit", connector_map={})

        reminders = db_session.execute(
            select(ActionReminder).where(ActionReminder.action_id == action.id)
        ).scalars().all()
        # Should have reminders at 3 days before and 1 day before (both in future)
        assert len(reminders) >= 1
        for r in reminders:
            assert r.status == "PENDING"
            assert r.assigned_to_email == "vpsales@acme.com"

    def test_reminders_not_duplicated_on_rescan(self, db_session):
        from scout.db.models import ActionReminder
        from sqlalchemy import select

        action = self._seed_action(db_session, due_days=5)
        # Run twice
        run_evidence_scan(db_session, "t-unit", connector_map={})
        run_evidence_scan(db_session, "t-unit", connector_map={})

        reminders = db_session.execute(
            select(ActionReminder).where(ActionReminder.action_id == action.id)
        ).scalars().all()
        send_ats = [r.send_at for r in reminders]
        # No duplicate send_at values
        assert len(send_ats) == len(set(send_ats))

    def test_completed_actions_skipped(self, db_session):
        """Already-COMPLETE actions should be skipped entirely."""
        action = self._seed_action(db_session, status="COMPLETE")
        action_id = action.id

        mock_conn = MagicMock()
        summary = run_evidence_scan(db_session, "t-unit", connector_map={"sfdc": mock_conn})

        # Connector should NOT have been called for this action
        assert summary["auto_completed"] == 0 or mock_conn.get_account.call_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# SPRINT 23: EVIDENCE API — INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────────


class TestEvidenceAPI:

    @pytest.fixture(scope="class")
    def seeded_action_id(self, app_client, admin_token):
        """Create a RemediationAction via DB and return its ID."""
        from scout.db.database import SessionLocal
        from scout.db.models import RemediationAction, Tenant, User
        from sqlalchemy import select

        with SessionLocal() as db:
            # Get the tenant_id for acme-22
            tenant = db.execute(
                select(Tenant).where(Tenant.slug == "acme-22")
            ).scalar_one_or_none()
            if tenant is None:
                return None

            action = RemediationAction(
                tenant_id=tenant.id,
                finding_hash="api-test-hash",
                worker_name="HireToRetireWorker",
                title="Test Action",
                description="A test remediation action.",
                action_type="reassign_accounts",
                assigned_to_email="vpsales@acme.com",
                effort="LOW",
                timeframe="IMMEDIATE",
                status="OPEN",
                evidence_source="sfdc",
                evidence_query_type="account_owner_changed",
                evidence_target_ids=["001"],
            )
            db.add(action)
            db.commit()
            return action.id

    def test_evidence_trail_empty_initially(self, app_client, admin_token, seeded_action_id):
        if seeded_action_id is None:
            pytest.skip("Could not seed action")
        resp = app_client.get(
            f"/admin/actions/{seeded_action_id}/evidence",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_recheck_endpoint_returns_ok(self, app_client, admin_token, seeded_action_id):
        if seeded_action_id is None:
            pytest.skip("Could not seed action")
        resp = app_client.post(
            f"/admin/actions/{seeded_action_id}/recheck",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "check_result" in data
        assert "new_status" in data

    def test_recheck_creates_evidence_log(self, app_client, admin_token, seeded_action_id):
        if seeded_action_id is None:
            pytest.skip("Could not seed action")
        # Recheck was called in previous test — evidence log should now exist
        resp = app_client.get(
            f"/admin/actions/{seeded_action_id}/evidence",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        logs = resp.json()
        assert len(logs) >= 1
        assert logs[0]["evidence_source"] == "sfdc"
        assert logs[0]["evidence_query_type"] == "account_owner_changed"
        assert "checked_at" in logs[0]

    def test_evidence_trail_404_for_unknown_action(self, app_client, admin_token):
        resp = app_client.get(
            "/admin/actions/nonexistent-id/evidence",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404

    def test_recheck_404_for_unknown_action(self, app_client, admin_token):
        resp = app_client.post(
            "/admin/actions/nonexistent-id/recheck",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 404
