"""
tests/test_dashboard_api.py — Sprint 28: Dashboard API Tests

Validates:
  1. GET /dashboard/summary — headline KPIs are correctly aggregated
  2. GET /dashboard/signal-scores — returns NoiseProfile data per worker
  3. GET /dashboard/actions — paginated, filtered action list
  4. GET /dashboard/actions/{id} — action detail with execution log
  5. GET /dashboard/approvals — pending approval inbox
  6. GET /dashboard/approvals/{id} — approval detail with proposed_payload
  7. GET /dashboard/webhook-activity — webhook event summary
  8. Auth: all endpoints require a valid JWT
  9. Tenant isolation: users cannot see other tenants' data
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── DB bootstrap ──────────────────────────────────────────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-sprint28")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from scout.db.models import (  # noqa: E402
    ApprovalRequest,
    Base,
    ExecutionLog,
    NoiseProfile,
    RemediationAction,
    Tenant,
    User,
    WebhookEvent,
)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

TENANT = "acme-sprint28"
OTHER_TENANT = "other-co-sprint28"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def db_session():
    """Module-scoped session for seeding data."""
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture(scope="module")
def seeded_data(db_session):
    """Seed the DB with test data for all dashboard tests."""
    now = datetime.now(timezone.utc)

    # ── Tenant + user ──────────────────────────────────────────────────────
    tenant = Tenant(
        id=TENANT,
        name="Acme Sprint 28",
        slug="acme-sprint28",
        is_active=True,
    )
    db_session.add(tenant)

    other_tenant = Tenant(
        id=OTHER_TENANT,
        name="Other Co",
        slug="other-co-sprint28",
        is_active=True,
    )
    db_session.add(other_tenant)

    user = User(
        id="user-dash-001",
        email="admin@acme.com",
        hashed_password="hashed",
        tenant_id=TENANT,
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    # ── RemediationActions ─────────────────────────────────────────────────
    actions = [
        RemediationAction(
            tenant_id=TENANT,
            action_type="log_activity",
            title="Follow up on Deal A",
            description="Deal A is stalled",
            status="OPEN",
            effort="LOW",
            timeframe="IMMEDIATE",
            arr_impact=100_000.0,
            evidence_source="sfdc",
            evidence_query_type="meeting_logged",
            evidence_target_ids=["opp-001", "acct-001"],
            execution_payload={"type": "Task", "subject": "Follow-up"},
            worker_name="IssueToResolutionWorker",
            finding_hash="h-deal-a",
            assigned_to_email="ae@acme.com",
            due_date=now + timedelta(days=1),
        ),
        RemediationAction(
            tenant_id=TENANT,
            action_type="deprovision_access",
            title="Deprovision Alice Smith",
            description="Alice left",
            status="IN_PROGRESS",
            effort="LOW",
            timeframe="IMMEDIATE",
            arr_impact=None,
            evidence_source="workday",
            evidence_query_type="termination_processed",
            evidence_target_ids=["wd-alice"],
            execution_payload={"worker_id": "wd-alice"},
            worker_name="HireToRetireWorker",
            finding_hash="h-alice-deprov",
        ),
        RemediationAction(
            tenant_id=TENANT,
            action_type="reassign_accounts",
            title="Reassign 5 accounts from Bob",
            description="Bob departed",
            status="COMPLETE",
            effort="LOW",
            timeframe="IMMEDIATE",
            arr_impact=250_000.0,
            evidence_source="sfdc",
            evidence_query_type="account_owner_changed",
            evidence_target_ids=["acct-001", "acct-002", "acct-003", "acct-004", "acct-005"],
            execution_payload={"new_owner_id": "005XY", "departed_rep_id": "005BOB"},
            worker_name="HireToRetireWorker",
            finding_hash="h-bob-reassign",
            completion_method="AUTO",
            completed_at=now - timedelta(days=5),
        ),
        # Other-tenant action (should NOT appear in acme queries)
        RemediationAction(
            tenant_id=OTHER_TENANT,
            action_type="log_activity",
            title="Other tenant action",
            description="Should not be visible to acme",
            status="OPEN",
            evidence_source="sfdc",
            evidence_query_type="meeting_logged",
            evidence_target_ids=["opp-other"],
            execution_payload={},
            worker_name="IssueToResolutionWorker",
            finding_hash="h-other-tenant",
        ),
    ]
    for a in actions:
        db_session.add(a)
    db_session.flush()

    action_ids = [a.id for a in actions[:3]]  # exclude other-tenant

    # ── ExecutionLog ───────────────────────────────────────────────────────
    log = ExecutionLog(
        tenant_id=TENANT,
        action_id=action_ids[2],  # reassign action
        action_type="reassign_accounts",
        source_system="sfdc",
        target_ids=["acct-001", "acct-002"],
        payload={"new_owner_id": "005XY"},
        result="SUCCESS",
        result_detail="5 accounts reassigned successfully",
        executed_by="system",
    )
    db_session.add(log)

    # ── NoiseProfile ───────────────────────────────────────────────────────
    profiles = [
        NoiseProfile(
            tenant_id=TENANT,
            worker_name="HireToRetireWorker",
            signal_score=0.82,
            acted_rate=0.75,
            dismissed_rate=0.15,
            active_action_cap=8,
            total_surfaced=40,
        ),
        NoiseProfile(
            tenant_id=TENANT,
            worker_name="IssueToResolutionWorker",
            signal_score=0.65,
            acted_rate=0.60,
            dismissed_rate=0.30,
            active_action_cap=5,
            total_surfaced=25,
        ),
    ]
    for p in profiles:
        db_session.add(p)

    # ── ApprovalRequest ────────────────────────────────────────────────────
    approval = ApprovalRequest(
        tenant_id=TENANT,
        action_id=action_ids[0],
        action_type="log_activity",
        risk_tier="MEDIUM",
        proposed_payload={"type": "Task", "subject": "Miragent: Follow-up on Deal A"},
        rationale="Agent wants to log a follow-up task for stalled deal Deal A.",
        status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db_session.add(approval)

    # ── WebhookEvent ───────────────────────────────────────────────────────
    events = [
        WebhookEvent(
            tenant_id=TENANT,
            source="sfdc",
            event_type="opportunity.updated",
            payload={"Id": "opp-001"},
            status="DONE",
            actions_triggered=["action-1"],
        ),
        WebhookEvent(
            tenant_id=TENANT,
            source="workday",
            event_type="worker.terminated",
            payload={"worker_id": "wd-alice"},
            status="DONE",
            actions_triggered=[],
        ),
        WebhookEvent(
            tenant_id=TENANT,
            source="netsuite",
            event_type="unknown.event",
            payload={},
            status="IGNORED",
            actions_triggered=[],
        ),
        WebhookEvent(
            tenant_id=TENANT,
            source="sfdc",
            event_type="contact.terminated",
            payload={"Id": "003FAIL"},
            status="FAILED",
            error_detail="Connection timeout",
            actions_triggered=[],
        ),
    ]
    for e in events:
        db_session.add(e)

    db_session.commit()

    return {
        "user": user,
        "action_ids": action_ids,
        "approval_id": approval.id,
    }


# ── App client ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_client(seeded_data):
    from scout.api.app import create_app
    from scout.db.database import get_db

    def override_db():
        session = TestingSession()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_headers(seeded_data):
    """Return Authorization header for the test user."""
    import jwt
    from scout.config import settings

    token = jwt.encode(
        {
            "sub": seeded_data["user"].id,
            "tenant_id": TENANT,
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


# ── Dashboard summary tests ───────────────────────────────────────────────────

class TestDashboardSummary:
    def test_summary_returns_correct_counts(self, app_client, auth_headers, seeded_data):
        resp = app_client.get("/dashboard/summary", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["tenant_id"] == TENANT
        assert data["open_actions"] == 1        # "log_activity" OPEN
        assert data["in_progress_actions"] == 1  # "deprovision_access" IN_PROGRESS
        assert data["completed_actions_30d"] >= 1  # "reassign_accounts" COMPLETE
        assert data["total_arr_at_risk"] == pytest.approx(100_000.0)
        assert "generated_at" in data

    def test_summary_arr_excludes_complete_actions(self, app_client, auth_headers):
        """ARR at risk should exclude COMPLETE actions."""
        resp = app_client.get("/dashboard/summary", headers=auth_headers)
        data = resp.json()
        # Only the OPEN log_activity has arr_impact=100k; the COMPLETE reassign (250k) is excluded
        assert data["total_arr_at_risk"] < 200_000

    def test_summary_pending_approvals_count(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/summary", headers=auth_headers)
        data = resp.json()
        assert data["pending_approvals"] >= 1

    def test_summary_requires_auth(self, app_client):
        resp = app_client.get("/dashboard/summary")
        assert resp.status_code == 401


# ── Signal scores tests ───────────────────────────────────────────────────────

class TestSignalScores:
    def test_signal_scores_returns_profiles(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/signal-scores", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

        # Ordered by signal_score desc: H2R (0.82) before I2R (0.65)
        assert data[0]["worker_name"] == "HireToRetireWorker"
        assert data[0]["signal_score"] == pytest.approx(0.82, abs=0.001)
        assert data[1]["worker_name"] == "IssueToResolutionWorker"

    def test_signal_scores_fields_present(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/signal-scores", headers=auth_headers)
        score = resp.json()[0]
        assert "signal_score" in score
        assert "acted_rate" in score
        assert "dismissed_rate" in score
        assert "active_action_cap" in score
        assert "total_surfaced" in score

    def test_signal_scores_requires_auth(self, app_client):
        resp = app_client.get("/dashboard/signal-scores")
        assert resp.status_code == 401


# ── Actions list tests ────────────────────────────────────────────────────────

class TestActionsList:
    def test_actions_default_returns_open_and_in_progress(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/actions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        statuses = {item["status"] for item in data["items"]}
        assert "COMPLETE" not in statuses
        assert "OPEN" in statuses or "IN_PROGRESS" in statuses

    def test_actions_filter_by_status_complete(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/actions?status=COMPLETE", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["status"] == "COMPLETE" for item in data["items"])
        assert data["total"] >= 1

    def test_actions_filter_by_action_type(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/actions?status=OPEN&action_type=log_activity", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["action_type"] == "log_activity" for item in data["items"])

    def test_actions_filter_by_worker(self, app_client, auth_headers):
        resp = app_client.get(
            "/dashboard/actions?status=IN_PROGRESS&worker_name=HireToRetireWorker",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(item["worker_name"] == "HireToRetireWorker" for item in data["items"])

    def test_actions_pagination_fields(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/actions?limit=10&offset=0", headers=auth_headers)
        data = resp.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "items" in data
        assert data["limit"] == 10
        assert data["offset"] == 0

    def test_actions_excludes_other_tenant(self, app_client, auth_headers):
        """Actions from other tenants must not appear in the list."""
        resp = app_client.get("/dashboard/actions?status=OPEN", headers=auth_headers)
        data = resp.json()
        titles = [item["title"] for item in data["items"]]
        assert "Other tenant action" not in titles

    def test_actions_requires_auth(self, app_client):
        resp = app_client.get("/dashboard/actions")
        assert resp.status_code == 401


# ── Action detail tests ───────────────────────────────────────────────────────

class TestActionDetail:
    def test_action_detail_returns_full_data(self, app_client, auth_headers, seeded_data):
        action_id = seeded_data["action_ids"][0]  # log_activity OPEN action
        resp = app_client.get(f"/dashboard/actions/{action_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["id"] == action_id
        assert data["action_type"] == "log_activity"
        assert data["status"] == "OPEN"
        assert data["arr_impact"] == 100_000.0
        assert data["evidence_target_ids"] == ["opp-001", "acct-001"]
        assert data["execution_payload"]["type"] == "Task"
        assert "execution_logs" in data

    def test_action_detail_includes_execution_logs(self, app_client, auth_headers, seeded_data):
        action_id = seeded_data["action_ids"][2]  # COMPLETE reassign action with log
        resp = app_client.get(f"/dashboard/actions/{action_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["execution_logs"]) >= 1
        log = data["execution_logs"][0]
        assert log["result"] == "SUCCESS"
        assert "executed_at" in log

    def test_action_detail_404_for_unknown(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/actions/nonexistent-id", headers=auth_headers)
        assert resp.status_code == 404

    def test_action_detail_404_for_other_tenant(self, app_client, auth_headers):
        # Get the other-tenant action (4th action seeded)
        session = TestingSession()
        other_action = session.query(RemediationAction).filter_by(
            tenant_id=OTHER_TENANT
        ).first()
        session.close()

        if other_action:
            resp = app_client.get(f"/dashboard/actions/{other_action.id}", headers=auth_headers)
            assert resp.status_code == 404  # tenant isolation

    def test_action_detail_requires_auth(self, app_client, seeded_data):
        action_id = seeded_data["action_ids"][0]
        resp = app_client.get(f"/dashboard/actions/{action_id}")
        assert resp.status_code == 401


# ── Approvals inbox tests ─────────────────────────────────────────────────────

class TestApprovalsInbox:
    def test_approvals_returns_pending(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/approvals", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert all(item["status"] == "PENDING" for item in data)

    def test_approvals_fields_present(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/approvals", headers=auth_headers)
        approval = resp.json()[0]
        required_fields = ["id", "action_id", "action_type", "risk_tier",
                           "rationale", "status", "expires_at"]
        for field in required_fields:
            assert field in approval

    def test_approval_detail_includes_payload(self, app_client, auth_headers, seeded_data):
        approval_id = seeded_data["approval_id"]
        resp = app_client.get(f"/dashboard/approvals/{approval_id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "proposed_payload" in data
        assert data["proposed_payload"]["type"] == "Task"
        assert data["risk_tier"] == "MEDIUM"
        assert data["rationale"] is not None

    def test_approval_detail_404_for_unknown(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/approvals/no-such-id", headers=auth_headers)
        assert resp.status_code == 404

    def test_approvals_requires_auth(self, app_client):
        resp = app_client.get("/dashboard/approvals")
        assert resp.status_code == 401


# ── Webhook activity tests ────────────────────────────────────────────────────

class TestWebhookActivity:
    def test_webhook_activity_summary(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/webhook-activity", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_events"] >= 4
        assert data["done_events"] >= 2
        assert data["failed_events"] >= 1
        assert data["ignored_events"] >= 1

    def test_webhook_activity_by_source(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/webhook-activity", headers=auth_headers)
        data = resp.json()
        assert "sfdc" in data["by_source"]
        assert "workday" in data["by_source"]
        assert "netsuite" in data["by_source"]

    def test_webhook_activity_by_status(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/webhook-activity", headers=auth_headers)
        data = resp.json()
        assert "DONE" in data["by_status"]
        assert "FAILED" in data["by_status"]
        assert "IGNORED" in data["by_status"]

    def test_webhook_activity_custom_window(self, app_client, auth_headers):
        resp = app_client.get("/dashboard/webhook-activity?days=1", headers=auth_headers)
        assert resp.status_code == 200

    def test_webhook_activity_requires_auth(self, app_client):
        resp = app_client.get("/dashboard/webhook-activity")
        assert resp.status_code == 401
