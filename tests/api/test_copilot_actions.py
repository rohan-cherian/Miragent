"""
tests/api/test_copilot_actions.py — Sprint 82: Copilot → Action loop tests.

Covers:
  TestSuggestActions (6 tests)   — unit-test _suggest_actions directly
  TestCreateAction  (8 tests)    — POST /copilot/create-action behaviour
  TestAskWithActions (4 tests)   — POST /copilot/ask includes suggested_actions
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Env bootstrap (must come before scout imports) ────────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-copilot-actions-secret")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from scout.db.models import ApprovalRequest, Base, RemediationAction, User  # noqa: E402
from scout.api.routes.copilot import _suggest_actions  # noqa: E402

# ── In-memory SQLite ──────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

TENANT_ID = "copilot-test-tenant"
ADMIN_EMAIL = "copilot-admin@test.com"
ADMIN_ID = "copilot-admin-001"


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def db_session():
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture(scope="module", autouse=True)
def seed_users(setup_db, db_session):
    admin = User(
        id=ADMIN_ID,
        email=ADMIN_EMAIL,
        hashed_password="x",
        tenant_id=TENANT_ID,
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    yield


# ── Client helpers ─────────────────────────────────────────────────────────────

def _admin_user() -> User:
    return User(
        id=ADMIN_ID,
        email=ADMIN_EMAIL,
        hashed_password="x",
        tenant_id=TENANT_ID,
        role="admin",
        is_active=True,
    )


def _make_client(db_sess, current_user: User | None) -> TestClient:
    from scout.api.app import create_app
    from scout.db.database import get_db
    from scout.db.auth_utils import get_current_user
    from fastapi import HTTPException

    def override_db():
        yield db_sess

    app = create_app()
    app.dependency_overrides[get_db] = override_db

    if current_user is not None:
        def override_user():
            return current_user
        app.dependency_overrides[get_current_user] = override_user
    else:
        # Simulate unauthenticated: raise 401
        def override_user():
            raise HTTPException(status_code=401, detail="Not authenticated")
        app.dependency_overrides[get_current_user] = override_user

    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# TestSuggestActions (6 tests) — unit-test _suggest_actions directly
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestActions:

    def test_pipeline_with_stalled_deals_returns_reassign_accounts(self):
        data = {
            "stalled_deals": 5,
            "stalled_value": 250000,
            "win_rate_pct": 45.0,
        }
        actions = _suggest_actions("pipeline", data, TENANT_ID)
        assert len(actions) >= 1
        first = actions[0]
        assert first["action_type"] == "reassign_accounts"
        assert first["risk_tier"] == "MEDIUM"
        assert first["arr_impact"] == 250000

    def test_pipeline_with_no_stalled_deals_no_reassign(self):
        data = {
            "stalled_deals": 0,
            "stalled_value": 0,
            "win_rate_pct": 55.0,
        }
        actions = _suggest_actions("pipeline", data, TENANT_ID)
        types = [a["action_type"] for a in actions]
        assert "reassign_accounts" not in types

    def test_churn_with_at_risk_accounts_returns_high_risk_schedule_meeting(self):
        data = {
            "at_risk_count": 3,
            "at_risk_accounts": [
                {"name": "BigCo", "arr": 150000, "score": 40},
                {"name": "MedCo", "arr": 80000, "score": 50},
            ],
            "renewal_deals": 2,
            "renewal_value": 200000,
        }
        actions = _suggest_actions("churn", data, TENANT_ID)
        assert len(actions) >= 1
        first = actions[0]
        assert first["action_type"] == "schedule_meeting"
        # total ARR = 150000 + 80000 = 230000 > 100000 → HIGH
        assert first["risk_tier"] == "HIGH"
        assert first["arr_impact"] == 230000.0

    def test_vendors_with_underutilised_spend_returns_cancel_subscription(self):
        data = {
            "vendor_count": 10,
            "total_annual_spend": 500000,
            "underutilised_spend": 75000,
        }
        actions = _suggest_actions("vendors", data, TENANT_ID)
        assert len(actions) >= 1
        first = actions[0]
        assert first["action_type"] == "cancel_subscription"
        assert first["risk_tier"] == "MEDIUM"
        assert first["arr_impact"] == 75000

    def test_revenue_with_expansion_potential_returns_low_risk_schedule_meeting(self):
        data = {
            "total_arr": 1000000,
            "expansion_accounts": 5,
            "expansion_potential": 120000,
        }
        actions = _suggest_actions("revenue", data, TENANT_ID)
        assert len(actions) >= 1
        first = actions[0]
        assert first["action_type"] == "schedule_meeting"
        assert first["risk_tier"] == "LOW"
        assert first["arr_impact"] == 120000

    def test_snapshot_with_top_findings_returns_flag_for_review(self):
        data = {
            "narrative": "Company is performing below benchmarks.",
            "top_findings": [
                {"title": "High churn risk in Q4", "severity": "CRITICAL"},
                {"title": "Vendor overspend detected", "severity": "HIGH"},
            ],
            "critical": 1,
            "high": 2,
            "total_findings": 10,
        }
        actions = _suggest_actions("snapshot", data, TENANT_ID)
        assert len(actions) >= 1
        first = actions[0]
        assert first["action_type"] == "flag_for_review"
        assert first["risk_tier"] == "MEDIUM"
        assert "High churn risk in Q4" in first["title"] or "High churn risk in Q4" in first["description"]


# ─────────────────────────────────────────────────────────────────────────────
# TestCreateAction (8 tests) — POST /copilot/create-action
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateAction:

    def _payload(self, risk_tier: str = "LOW", **overrides) -> dict:
        base = {
            "tenant_id": TENANT_ID,
            "title": f"Test action {risk_tier}",
            "description": "A test remediation action.",
            "action_type": "flag_for_review",
            "risk_tier": risk_tier,
            "arr_impact": None,
            "worker_name": "copilot",
        }
        base.update(overrides)
        return base

    def test_creates_action_returns_action_id(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/copilot/create-action", json=self._payload("LOW"))
        assert resp.status_code == 200
        data = resp.json()
        assert "action_id" in data
        assert isinstance(data["action_id"], str) and len(data["action_id"]) > 0

    def test_low_risk_no_approval_id_not_routed(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/copilot/create-action", json=self._payload("LOW"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_id"] is None
        assert data["routed_to_approvals"] is False
        assert data["risk_tier"] == "LOW"

    def test_medium_risk_no_approval_id_not_routed(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/copilot/create-action", json=self._payload("MEDIUM"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_id"] is None
        assert data["routed_to_approvals"] is False

    def test_high_risk_creates_approval_and_routed(self, db_session):
        client = _make_client(db_session, _admin_user())
        payload = self._payload("HIGH", title="High risk action", arr_impact=200000.0)
        resp = client.post("/copilot/create-action", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_id"] is not None
        assert data["routed_to_approvals"] is True

        # Verify the ApprovalRequest was created in DB
        approval = db_session.query(ApprovalRequest).filter_by(id=data["approval_id"]).first()
        assert approval is not None
        assert approval.status == "PENDING"
        assert approval.action_id == data["action_id"]

    def test_unauthenticated_returns_401(self, db_session):
        client = _make_client(db_session, None)
        resp = client.post("/copilot/create-action", json=self._payload("LOW"))
        assert resp.status_code in (401, 403)

    def test_finding_hash_auto_generated_when_not_provided(self, db_session):
        client = _make_client(db_session, _admin_user())
        payload = self._payload("LOW", title="Auto hash action")
        # No finding_hash in payload
        assert "finding_hash" not in payload
        resp = client.post("/copilot/create-action", json=payload)
        assert resp.status_code == 200
        action_id = resp.json()["action_id"]

        # Verify the action exists in DB with a non-empty finding_hash
        action = db_session.query(RemediationAction).filter_by(id=action_id).first()
        assert action is not None
        assert action.finding_hash is not None and len(action.finding_hash) > 0

    def test_created_by_set_to_current_user_email(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/copilot/create-action", json=self._payload("LOW", title="created_by test"))
        assert resp.status_code == 200
        action_id = resp.json()["action_id"]

        action = db_session.query(RemediationAction).filter_by(id=action_id).first()
        assert action is not None
        assert action.created_by == ADMIN_EMAIL

    def test_action_appears_in_db_with_status_open(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/copilot/create-action", json=self._payload("MEDIUM", title="status open test"))
        assert resp.status_code == 200
        action_id = resp.json()["action_id"]

        action = db_session.query(RemediationAction).filter_by(id=action_id).first()
        assert action is not None
        assert action.status == "OPEN"
        assert action.tenant_id == TENANT_ID


# ─────────────────────────────────────────────────────────────────────────────
# TestAskWithActions (4 tests) — POST /copilot/ask returns suggested_actions
# ─────────────────────────────────────────────────────────────────────────────

def _mock_neo4j_driver():
    """Return a mock Neo4j driver that returns empty results."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = None
    mock_result.data.return_value = []
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_driver.close = MagicMock()
    return mock_driver


def _pipeline_neo4j_driver(stalled_deals: int = 3, stalled_value: float = 150000.0):
    """Return a mock Neo4j driver with pipeline data containing stalled deals."""
    mock_session = MagicMock()

    # open deals result
    open_result = MagicMock()
    open_result.single.return_value = {
        "open_deals": 10,
        "open_pipeline_value": 500000.0,
        "stalled_deals": stalled_deals,
        "stalled_value": stalled_value,
        "avg_days_in_stage": 18.5,
    }

    # won result
    won_result = MagicMock()
    won_result.single.return_value = {"won_count": 5, "won_value": 250000.0}

    # lost result
    lost_result = MagicMock()
    lost_result.single.return_value = {"lost_count": 2}

    call_count = [0]

    def run_side_effect(query, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return open_result
        elif call_count[0] == 2:
            return won_result
        else:
            return lost_result

    mock_session.run.side_effect = run_side_effect
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_driver.close = MagicMock()
    return mock_driver


def _churn_neo4j_driver():
    """Return a mock Neo4j driver with churn data containing at-risk accounts."""
    mock_session = MagicMock()

    at_risk_result = MagicMock()
    at_risk_result.data.return_value = [
        {"name": "BigCo", "score": 35, "arr": 200000},
        {"name": "MedCo", "score": 50, "arr": 75000},
    ]

    renewal_result = MagicMock()
    renewal_result.single.return_value = {"renewal_count": 3, "renewal_value": 150000.0}

    call_count = [0]

    def run_side_effect(query, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return at_risk_result
        else:
            return renewal_result

    mock_session.run.side_effect = run_side_effect
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    mock_driver.close = MagicMock()
    return mock_driver


class TestAskWithActions:

    def _ask(self, db_session, question: str, mock_driver) -> dict:
        client = _make_client(db_session, _admin_user())
        with patch("scout.api.routes.copilot.GraphDatabase") as mock_gdb, \
             patch("scout.api.routes.copilot._analyst") as mock_analyst:
            mock_gdb.driver.return_value = mock_driver
            mock_analyst._provider.complete.return_value = "Here is the answer."
            mock_analyst._provider.name = "mock"
            mock_analyst._provider.is_available = True

            resp = client.post("/copilot/ask", json={
                "tenant_id": TENANT_ID,
                "question": question,
            })

        assert resp.status_code == 200
        return resp.json()

    def test_pipeline_intent_with_stalled_data_includes_suggested_actions(self, db_session):
        driver = _pipeline_neo4j_driver(stalled_deals=3, stalled_value=150000.0)
        data = self._ask(db_session, "How many stalled deals do we have?", driver)
        assert "suggested_actions" in data
        assert isinstance(data["suggested_actions"], list)
        assert len(data["suggested_actions"]) >= 1
        types = [a["action_type"] for a in data["suggested_actions"]]
        assert "reassign_accounts" in types

    def test_churn_intent_with_at_risk_accounts_includes_suggested_actions(self, db_session):
        driver = _churn_neo4j_driver()
        data = self._ask(db_session, "Which customers are at risk of churning?", driver)
        assert "suggested_actions" in data
        assert isinstance(data["suggested_actions"], list)
        assert len(data["suggested_actions"]) >= 1
        types = [a["action_type"] for a in data["suggested_actions"]]
        assert "schedule_meeting" in types

    def test_snapshot_intent_suggested_actions_is_list(self, db_session):
        driver = _mock_neo4j_driver()
        data = self._ask(db_session, "Give me a general overview of the company.", driver)
        assert "suggested_actions" in data
        # May be empty or have items — but must be a list
        assert isinstance(data["suggested_actions"], list)

    def test_suggested_actions_never_none_always_list(self, db_session):
        """suggested_actions must always be a list, never None, for any question."""
        driver = _mock_neo4j_driver()
        for question in [
            "What is our pipeline?",
            "Tell me about vendors",
            "How is our revenue?",
        ]:
            data = self._ask(db_session, question, driver)
            assert "suggested_actions" in data, f"Missing for: {question}"
            assert data["suggested_actions"] is not None, f"None for: {question}"
            assert isinstance(data["suggested_actions"], list), f"Not a list for: {question}"
