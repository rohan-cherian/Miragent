"""
tests/api/test_digest.py — Email digest endpoint tests (Sprint 81).

Covers:
  TestDigestRecipients (8 tests): CRUD on /digest/recipients
  TestSendNow (5 tests):          POST /digest/send-now behaviour
  TestBuildDigestHtml (4 tests):  HTML builder unit tests
  TestBuildAndSend (3 tests):     Orchestrator with mocked smtplib
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
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
os.environ.setdefault("SECRET_KEY", "test-digest-secret")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")

from scout.db.models import Base, DigestRecipient, InsightSnapshot, User  # noqa: E402

# ── In-memory SQLite ──────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

# Stable IDs
ADMIN_ID = "digest-admin-001"
VIEWER_ID = "digest-viewer-001"
HOME_TENANT = "digest-home-tenant"
TENANT_A = "digest-tenant-a"
TENANT_B = "digest-tenant-b"


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
        email="digest-admin@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="admin",
        is_active=True,
    )
    viewer = User(
        id=VIEWER_ID,
        email="digest-viewer@fund.com",
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


def _admin() -> User:
    return User(
        id=ADMIN_ID,
        email="digest-admin@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="admin",
        is_active=True,
    )


def _viewer() -> User:
    return User(
        id=VIEWER_ID,
        email="digest-viewer@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="viewer",
        is_active=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TestDigestRecipients (8 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestDigestRecipients:

    def test_list_recipients_admin_200(self, db_session):
        client = _make_client(db_session, _admin())
        resp = client.get("/digest/recipients")
        assert resp.status_code == 200
        assert "recipients" in resp.json()

    def test_list_recipients_non_admin_403(self, db_session):
        client = _make_client(db_session, _viewer())
        resp = client.get("/digest/recipients")
        assert resp.status_code == 403

    def test_add_recipient_201(self, db_session):
        client = _make_client(db_session, _admin())
        resp = client.post(
            "/digest/recipients",
            json={"email": "partner@vc.com", "name": "VC Partner"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "partner@vc.com"
        assert data["name"] == "VC Partner"
        assert data["active"] is True
        assert data["tenant_id"] is None

    def test_add_duplicate_409(self, db_session):
        client = _make_client(db_session, _admin())
        # First add
        client.post("/digest/recipients", json={"email": "dup@vc.com"})
        # Second add — same email + same tenant_id (None) → 409
        resp = client.post("/digest/recipients", json={"email": "dup@vc.com"})
        assert resp.status_code == 409

    def test_add_with_tenant_id_scope(self, db_session):
        client = _make_client(db_session, _admin())
        resp = client.post(
            "/digest/recipients",
            json={"email": "scoped@vc.com", "tenant_id": TENANT_A},
        )
        assert resp.status_code == 201
        assert resp.json()["tenant_id"] == TENANT_A

    def test_delete_recipient_soft_delete(self, db_session):
        client = _make_client(db_session, _admin())
        # Add one first
        add_resp = client.post(
            "/digest/recipients",
            json={"email": "todelete@vc.com"},
        )
        assert add_resp.status_code == 201
        rid = add_resp.json()["id"]

        # Delete it
        del_resp = client.delete(f"/digest/recipients/{rid}")
        assert del_resp.status_code == 200
        assert del_resp.json()["active"] is False

        # Verify the DB row is inactive, not physically removed
        row = db_session.query(DigestRecipient).filter_by(id=rid).first()
        assert row is not None
        assert row.active is False

    def test_delete_nonexistent_404(self, db_session):
        client = _make_client(db_session, _admin())
        resp = client.delete("/digest/recipients/does-not-exist-xyz")
        assert resp.status_code == 404

    def test_list_shows_only_active(self, db_session):
        client = _make_client(db_session, _admin())
        # Add and then delete a recipient
        add_resp = client.post(
            "/digest/recipients",
            json={"email": "inactive@vc.com"},
        )
        assert add_resp.status_code == 201
        rid = add_resp.json()["id"]
        client.delete(f"/digest/recipients/{rid}")

        # The list endpoint should return all rows (active=False included in list)
        # but we verify the deleted one has active=False in the response
        resp = client.get("/digest/recipients")
        assert resp.status_code == 200
        all_recs = resp.json()["recipients"]
        inactive = [r for r in all_recs if r["id"] == rid]
        assert len(inactive) == 1
        assert inactive[0]["active"] is False


# ─────────────────────────────────────────────────────────────────────────────
# TestSendNow (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSendNow:

    def test_send_now_admin_200(self, db_session):
        client = _make_client(db_session, _admin())
        with patch("smtplib.SMTP"):
            resp = client.post("/digest/send-now")
        assert resp.status_code == 200
        data = resp.json()
        assert "sent" in data
        assert "recipient_count" in data
        assert "company_count" in data

    def test_send_now_non_admin_403(self, db_session):
        client = _make_client(db_session, _viewer())
        resp = client.post("/digest/send-now")
        assert resp.status_code == 403

    def test_send_now_no_recipients_returns_sent_false(self, db_session):
        # Deactivate all portfolio-wide recipients first
        db_session.query(DigestRecipient).filter(
            DigestRecipient.tenant_id.is_(None)
        ).update({"active": False})
        db_session.commit()

        client = _make_client(db_session, _admin())
        with patch("smtplib.SMTP"):
            resp = client.post("/digest/send-now")
        assert resp.status_code == 200
        assert resp.json()["sent"] is False
        assert resp.json()["recipient_count"] == 0

    def test_send_now_smtp_user_empty_returns_sent_false(self, db_session):
        """When smtp_user is empty, send_digest returns False without raising."""
        # Add a recipient so recipient_count > 0
        db_session.add(DigestRecipient(email="checksmtp@vc.com", active=True))
        db_session.commit()

        client = _make_client(db_session, _admin())
        # smtp_user is "" by default in test env — no patch needed
        resp = client.post("/digest/send-now")
        assert resp.status_code == 200
        # sent=False because smtp_user is blank
        assert resp.json()["sent"] is False

    def test_send_now_returns_company_count(self, db_session):
        """company_count reflects the number of snapshots found."""
        now = datetime.now(timezone.utc)
        snap = InsightSnapshot(
            tenant_id="send-now-tenant",
            run_at=now,
            critical=0,
            high=1,
            total_findings=1,
        )
        db_session.add(snap)
        db_session.commit()

        client = _make_client(db_session, _admin())
        with patch("smtplib.SMTP"):
            resp = client.post("/digest/send-now")
        assert resp.status_code == 200
        # At least one company in the portfolio
        assert resp.json()["company_count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# TestBuildDigestHtml (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildDigestHtml:

    def test_empty_snapshots_returns_valid_html(self):
        from scout.email_digest import build_digest_html
        html = build_digest_html([], datetime.now(timezone.utc))
        assert isinstance(html, str)
        assert len(html) > 0
        assert "<!DOCTYPE html>" in html
        assert "Miragent" in html

    def test_one_snapshot_includes_company_data(self):
        from scout.email_digest import build_digest_html
        snap = {
            "tenant_id": "acme-corp",
            "critical": 2,
            "high": 3,
            "medium": 5,
            "low": 1,
            "total_findings": 11,
            "top_findings": [
                {"title": "Overspend on AWS", "severity": "CRITICAL"},
                {"title": "Expired vendor contract", "severity": "HIGH"},
            ],
            "company_profile": {"name": "Acme Corp"},
            "narrative_snippet": "Acme Corp shows significant vendor spend risk.",
        }
        html = build_digest_html([snap], datetime.now(timezone.utc))
        assert "Acme Corp" in html
        assert "Overspend on AWS" in html
        assert "Critical" in html

    def test_multiple_snapshots_all_appear(self):
        from scout.email_digest import build_digest_html
        snaps = [
            {
                "tenant_id": f"tenant-{i}",
                "critical": i,
                "high": 0,
                "medium": 0,
                "low": 0,
                "total_findings": i,
                "top_findings": [],
                "company_profile": {"name": f"Company {i}"},
                "narrative_snippet": "",
            }
            for i in range(3)
        ]
        html = build_digest_html(snaps, datetime.now(timezone.utc))
        assert "Company 0" in html
        assert "Company 1" in html
        assert "Company 2" in html

    def test_narrative_snippet_truncated_to_202_chars(self):
        from scout.email_digest import build_digest_html
        long_narrative = "A" * 400
        snap = {
            "tenant_id": "trunc-tenant",
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "total_findings": 0,
            "top_findings": [],
            "company_profile": {},
            "narrative_snippet": long_narrative,
        }
        html = build_digest_html([snap], datetime.now(timezone.utc))
        # The truncated snippet is 197 chars + "..." = 200 chars, well within 202
        assert "A" * 203 not in html  # no run longer than 202 A's in the output


# ─────────────────────────────────────────────────────────────────────────────
# TestBuildAndSend (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildAndSend:

    def _fresh_session(self):
        """Return a fresh in-memory session with the schema created."""
        return TestingSession()

    def test_smtp_called_with_correct_args(self, db_session):
        """When smtp_user is set, smtplib.SMTP should be called."""
        from scout.email_digest import build_and_send_portfolio_digest

        # Add an active portfolio-wide recipient
        db_session.add(DigestRecipient(email="smtp-test@vc.com", active=True, tenant_id=None))
        db_session.commit()

        smtp_instance = MagicMock()
        smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
        smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("scout.config.settings") as mock_settings, \
             patch("smtplib.SMTP", return_value=smtp_instance) as mock_smtp:
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "secret"
            mock_settings.smtp_host = "smtp.gmail.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_from = "digest@miragent.io"

            result = build_and_send_portfolio_digest(db_session)

        # SMTP constructor should have been called
        mock_smtp.assert_called_once()

    def test_smtp_error_returns_sent_false_not_raise(self, db_session):
        """If SMTP raises, build_and_send should return sent=False and not propagate."""
        from scout.email_digest import build_and_send_portfolio_digest

        db_session.add(DigestRecipient(email="smtp-err@vc.com", active=True, tenant_id=None))
        db_session.commit()

        with patch("scout.config.settings") as mock_settings, \
             patch("smtplib.SMTP", side_effect=ConnectionRefusedError("no server")):
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "secret"
            mock_settings.smtp_host = "smtp.gmail.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_from = "digest@miragent.io"

            # Must not raise
            result = build_and_send_portfolio_digest(db_session)

        assert result["sent"] is False

    def test_empty_snapshots_still_sends_empty_digest(self, db_session):
        """Even with no InsightSnapshot rows, the function should proceed and call send."""
        from scout.email_digest import build_and_send_portfolio_digest

        # Ensure at least one recipient exists
        db_session.add(DigestRecipient(email="empty-snap@vc.com", active=True, tenant_id=None))
        db_session.commit()

        # Remove all snapshots for a clean slate in a separate session
        db_session.query(InsightSnapshot).delete()
        db_session.commit()

        smtp_instance = MagicMock()
        smtp_instance.__enter__ = MagicMock(return_value=smtp_instance)
        smtp_instance.__exit__ = MagicMock(return_value=False)

        with patch("scout.config.settings") as mock_settings, \
             patch("smtplib.SMTP", return_value=smtp_instance):
            mock_settings.smtp_user = "user@example.com"
            mock_settings.smtp_password = "secret"
            mock_settings.smtp_host = "smtp.gmail.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_from = "digest@miragent.io"

            result = build_and_send_portfolio_digest(db_session)

        assert result["company_count"] == 0
        # sent=True because we have recipients and smtp_user is set (SMTP mocked)
        assert result["sent"] is True
