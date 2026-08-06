"""
tests/api/test_access.py — Multi-tenant access control endpoint tests (Sprint 80).

Covers:
  GET  /access/my-tenants       — home tenant always returned; granted extras included
  GET  /access/users/{user_id}  — admin-only; returns tenants for specified user
  POST /access/grant            — creates access row; idempotent second call
  DELETE /access/revoke         — removes access; 400 for home tenant; 403 for non-admin

Uses in-memory SQLite + dependency overrides (same pattern as test_portfolio.py).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Env bootstrap (must come before any scout imports) ────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")
os.environ.setdefault("SECRET_KEY", "test-access-secret")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from scout.db.models import Base, InsightSnapshot, User, UserTenantAccess  # noqa: E402

# ── In-memory SQLite ──────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

# Stable IDs for use across tests
ADMIN_USER_ID = "admin-user-001"
VIEWER_USER_ID = "viewer-user-001"
HOME_TENANT = "home-tenant-001"
EXTRA_TENANT_A = "extra-tenant-a"
EXTRA_TENANT_B = "extra-tenant-b"


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


# ── Seed base users ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def seed_users(setup_db, db_session):
    """Seed admin and viewer users into the DB (needed for FK constraints)."""
    admin = User(
        id=ADMIN_USER_ID,
        email="admin@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="admin",
        is_active=True,
    )
    viewer = User(
        id=VIEWER_USER_ID,
        email="viewer@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="viewer",
        is_active=True,
    )
    db_session.add(admin)
    db_session.add(viewer)
    db_session.commit()
    yield


# ── Client helpers ────────────────────────────────────────────────────────────

def _make_client(db_sess, current_user: User) -> TestClient:
    """Return a TestClient with DB and auth dependency overrides applied."""
    from scout.api.app import create_app
    from scout.db.database import get_db
    from scout.db.auth_utils import get_current_user

    def override_db():
        yield db_sess

    def override_user():
        return current_user

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    return TestClient(app, raise_server_exceptions=True)


def _admin_user() -> User:
    return User(
        id=ADMIN_USER_ID,
        email="admin@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="admin",
        is_active=True,
    )


def _viewer_user() -> User:
    return User(
        id=VIEWER_USER_ID,
        email="viewer@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="viewer",
        is_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /access/my-tenants
# ─────────────────────────────────────────────────────────────────────────────

class TestMyTenants:

    def test_returns_200(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.get("/access/my-tenants")
        assert resp.status_code == 200

    def test_home_tenant_always_included(self, db_session):
        """Even with no granted rows, home tenant must appear."""
        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        tenant_ids = [t["tenant_id"] for t in data["tenants"]]
        assert HOME_TENANT in tenant_ids

    def test_home_tenant_is_home_true(self, db_session):
        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        home_entries = [t for t in data["tenants"] if t["tenant_id"] == HOME_TENANT]
        assert len(home_entries) == 1
        assert home_entries[0]["is_home"] is True

    def test_granted_tenant_included(self, db_session):
        """After granting access, the extra tenant must appear."""
        # Grant access row directly
        row = UserTenantAccess(
            user_id=ADMIN_USER_ID,
            tenant_id=EXTRA_TENANT_A,
            granted_by=ADMIN_USER_ID,
        )
        db_session.add(row)
        db_session.commit()

        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        tenant_ids = [t["tenant_id"] for t in data["tenants"]]
        assert EXTRA_TENANT_A in tenant_ids
        assert HOME_TENANT in tenant_ids

    def test_granted_tenant_is_home_false(self, db_session):
        """Granted extra tenant must have is_home=False."""
        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        extra = [t for t in data["tenants"] if t["tenant_id"] == EXTRA_TENANT_A]
        assert extra[0]["is_home"] is False

    def test_response_shape(self, db_session):
        """Each entry must have the required keys."""
        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        for entry in data["tenants"]:
            assert "tenant_id" in entry
            assert "is_home" in entry
            assert "last_insights_run" in entry
            assert "has_full_intelligence" in entry

    def test_no_snapshot_has_full_intelligence_false(self, db_session):
        """Tenant with no InsightSnapshot must report has_full_intelligence=False."""
        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        home = next(t for t in data["tenants"] if t["tenant_id"] == HOME_TENANT)
        # HOME_TENANT has no snapshot seeded → False
        assert home["has_full_intelligence"] is False
        assert home["last_insights_run"] is None

    def test_with_snapshot_has_full_intelligence_true(self, db_session):
        """Tenant with an InsightSnapshot must report has_full_intelligence=True."""
        snap = InsightSnapshot(
            tenant_id=EXTRA_TENANT_A,
            critical=0,
            high=1,
            medium=0,
            low=0,
            total_findings=1,
            workers_run=3,
            run_at=datetime(2026, 5, 19, 9, 0, 0),
        )
        db_session.add(snap)
        db_session.commit()

        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        extra = next(t for t in data["tenants"] if t["tenant_id"] == EXTRA_TENANT_A)
        assert extra["has_full_intelligence"] is True
        assert extra["last_insights_run"] is not None

    def test_no_duplicate_home_tenant(self, db_session):
        """If home tenant is also in granted rows, it must not appear twice."""
        # Add a row that duplicates the home tenant
        existing = (
            db_session.query(UserTenantAccess)
            .filter_by(user_id=ADMIN_USER_ID, tenant_id=HOME_TENANT)
            .first()
        )
        if not existing:
            row = UserTenantAccess(
                user_id=ADMIN_USER_ID,
                tenant_id=HOME_TENANT,
                granted_by=ADMIN_USER_ID,
            )
            db_session.add(row)
            db_session.commit()

        client = _make_client(db_session, _admin_user())
        data = client.get("/access/my-tenants").json()
        home_entries = [t for t in data["tenants"] if t["tenant_id"] == HOME_TENANT]
        assert len(home_entries) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Tests: POST /access/grant
# ─────────────────────────────────────────────────────────────────────────────

class TestGrantAccess:

    def test_grant_creates_access_row(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/access/grant", json={
            "user_id": VIEWER_USER_ID,
            "tenant_id": EXTRA_TENANT_B,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["user_id"] == VIEWER_USER_ID
        assert data["tenant_id"] == EXTRA_TENANT_B
        assert data["created"] is True

    def test_grant_row_persisted_in_db(self, db_session):
        row = (
            db_session.query(UserTenantAccess)
            .filter_by(user_id=VIEWER_USER_ID, tenant_id=EXTRA_TENANT_B)
            .first()
        )
        assert row is not None

    def test_grant_idempotent_second_call(self, db_session):
        """Second grant for the same pair must return ok=True, created=False."""
        client = _make_client(db_session, _admin_user())
        resp = client.post("/access/grant", json={
            "user_id": VIEWER_USER_ID,
            "tenant_id": EXTRA_TENANT_B,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["created"] is False

    def test_grant_with_note(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.post("/access/grant", json={
            "user_id": VIEWER_USER_ID,
            "tenant_id": "extra-with-note",
            "note": "PE partner needs board-level access",
        })
        assert resp.status_code == 200
        assert resp.json()["created"] is True

    def test_grant_non_admin_returns_403(self, db_session):
        """Non-admin attempting to grant must receive 403."""
        client = _make_client(db_session, _viewer_user())
        resp = client.post("/access/grant", json={
            "user_id": ADMIN_USER_ID,
            "tenant_id": EXTRA_TENANT_A,
        })
        assert resp.status_code == 403

    def test_grant_by_admin_succeeds(self, db_session):
        """Admin granting access to any user must succeed."""
        client = _make_client(db_session, _admin_user())
        resp = client.post("/access/grant", json={
            "user_id": VIEWER_USER_ID,
            "tenant_id": "yet-another-tenant",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Tests: DELETE /access/revoke
# ─────────────────────────────────────────────────────────────────────────────

class TestRevokeAccess:

    def test_revoke_removes_access(self, db_session):
        # Ensure EXTRA_TENANT_B row exists for VIEWER (seeded in TestGrantAccess)
        existing = (
            db_session.query(UserTenantAccess)
            .filter_by(user_id=VIEWER_USER_ID, tenant_id=EXTRA_TENANT_B)
            .first()
        )
        if not existing:
            db_session.add(UserTenantAccess(
                user_id=VIEWER_USER_ID,
                tenant_id=EXTRA_TENANT_B,
                granted_by=ADMIN_USER_ID,
            ))
            db_session.commit()

        client = _make_client(db_session, _admin_user())
        resp = client.delete(f"/access/revoke/{VIEWER_USER_ID}/{EXTRA_TENANT_B}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Row must be gone
        row = (
            db_session.query(UserTenantAccess)
            .filter_by(user_id=VIEWER_USER_ID, tenant_id=EXTRA_TENANT_B)
            .first()
        )
        assert row is None

    def test_revoke_home_tenant_returns_400(self, db_session):
        """Revoking the user's home tenant must return 400."""
        client = _make_client(db_session, _admin_user())
        resp = client.delete(f"/access/revoke/{VIEWER_USER_ID}/{HOME_TENANT}")
        assert resp.status_code == 400

    def test_revoke_nonexistent_row_still_returns_ok(self, db_session):
        """Revoking a row that doesn't exist must not crash — idempotent."""
        client = _make_client(db_session, _admin_user())
        resp = client.delete(f"/access/revoke/{VIEWER_USER_ID}/nonexistent-tenant")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_revoke_non_admin_returns_403(self, db_session):
        client = _make_client(db_session, _viewer_user())
        resp = client.delete(f"/access/revoke/{ADMIN_USER_ID}/{EXTRA_TENANT_A}")
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GET /access/users/{user_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestUserTenants:

    def test_admin_can_view_user_tenants(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.get(f"/access/users/{VIEWER_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert "tenants" in data

    def test_home_tenant_included_for_target_user(self, db_session):
        client = _make_client(db_session, _admin_user())
        data = client.get(f"/access/users/{VIEWER_USER_ID}").json()
        tenant_ids = [t["tenant_id"] for t in data["tenants"]]
        assert HOME_TENANT in tenant_ids

    def test_non_admin_gets_403(self, db_session):
        client = _make_client(db_session, _viewer_user())
        resp = client.get(f"/access/users/{ADMIN_USER_ID}")
        assert resp.status_code == 403

    def test_unknown_user_gets_404(self, db_session):
        client = _make_client(db_session, _admin_user())
        resp = client.get("/access/users/nonexistent-user-xyz")
        assert resp.status_code == 404

    def test_granted_tenants_shown_for_user(self, db_session):
        """After granting VIEWER access to EXTRA_TENANT_A, admin should see it."""
        # Ensure grant exists
        existing = (
            db_session.query(UserTenantAccess)
            .filter_by(user_id=VIEWER_USER_ID, tenant_id=EXTRA_TENANT_A)
            .first()
        )
        if not existing:
            db_session.add(UserTenantAccess(
                user_id=VIEWER_USER_ID,
                tenant_id=EXTRA_TENANT_A,
                granted_by=ADMIN_USER_ID,
            ))
            db_session.commit()

        client = _make_client(db_session, _admin_user())
        data = client.get(f"/access/users/{VIEWER_USER_ID}").json()
        tenant_ids = [t["tenant_id"] for t in data["tenants"]]
        assert EXTRA_TENANT_A in tenant_ids
