"""
tests/api/test_connectors.py — Connector management endpoint tests (Sprint 83).

Covers:
  TestConnectorsList (4 tests):       GET /connectors
  TestSalesforceAuthStart (4 tests):  GET /connectors/salesforce/auth-start
  TestSalesforceCallback (5 tests):   GET /connectors/salesforce/callback
  TestSalesforceDisconnect (3 tests): POST /connectors/salesforce/disconnect
  TestSalesforceTest (4 tests):       POST /connectors/salesforce/test
"""

from __future__ import annotations

import base64
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
os.environ.setdefault("SECRET_KEY", "test-connectors-secret")
os.environ.setdefault("CLICKHOUSE_HOST", "localhost")
os.environ.setdefault("SF_CLIENT_ID", "test-sf-client-id")
os.environ.setdefault("SF_CLIENT_SECRET", "test-sf-client-secret")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")

from scout.db.models import Base, ConnectorCredentialStore, User  # noqa: E402

# ── In-memory SQLite ──────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False)

# Stable IDs
ADMIN_ID = "conn-admin-001"
VIEWER_ID = "conn-viewer-001"
HOME_TENANT = "conn-home-tenant"


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
        email="conn-admin@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="admin",
        is_active=True,
    )
    viewer = User(
        id=VIEWER_ID,
        email="conn-viewer@fund.com",
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


def _make_anon_client(db_sess) -> TestClient:
    """Client without auth override (for callback endpoint which has no auth)."""
    from scout.api.app import create_app
    from scout.db.database import get_db

    def override_db():
        yield db_sess

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    return TestClient(app, raise_server_exceptions=False)


def _admin() -> User:
    return User(
        id=ADMIN_ID,
        email="conn-admin@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="admin",
        is_active=True,
    )


def _viewer() -> User:
    return User(
        id=VIEWER_ID,
        email="conn-viewer@fund.com",
        hashed_password="x",
        tenant_id=HOME_TENANT,
        role="viewer",
        is_active=True,
    )


def _encode_state(tenant_id: str, user_id: str) -> str:
    raw = f"{tenant_id}:{user_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


# ─────────────────────────────────────────────────────────────────────────────
# TestConnectorsList (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorsList:

    def test_admin_gets_list_200(self, db_session):
        client = _make_client(db_session, _admin())
        resp = client.get("/connectors")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_non_admin_gets_403(self, db_session):
        client = _make_client(db_session, _viewer())
        resp = client.get("/connectors")
        assert resp.status_code == 403

    def test_list_has_salesforce_entry(self, db_session):
        client = _make_client(db_session, _admin())
        resp = client.get("/connectors")
        assert resp.status_code == 200
        connector_ids = [c["connector_id"] for c in resp.json()]
        assert "salesforce" in connector_ids

    def test_is_connected_false_when_no_creds(self, db_session):
        # Ensure no active cred row for this tenant
        db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).update({"is_active": False})
        db_session.commit()

        client = _make_client(db_session, _admin())
        resp = client.get("/connectors")
        assert resp.status_code == 200
        sf = next((c for c in resp.json() if c["connector_id"] == "salesforce"), None)
        assert sf is not None
        assert sf["is_connected"] is False


# ─────────────────────────────────────────────────────────────────────────────
# TestSalesforceAuthStart (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSalesforceAuthStart:

    def test_admin_gets_auth_url(self, db_session):
        client = _make_client(db_session, _admin())
        with patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-client-id"
            mock_settings.sf_client_secret = "fake-secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            mock_settings.use_mock_connectors = True
            resp = client.get("/connectors/salesforce/auth-start?return_url=true")
        assert resp.status_code == 200
        assert "auth_url" in resp.json()

    def test_non_admin_gets_403(self, db_session):
        client = _make_client(db_session, _viewer())
        resp = client.get("/connectors/salesforce/auth-start?return_url=true")
        assert resp.status_code == 403

    def test_auth_url_contains_client_id(self, db_session):
        client = _make_client(db_session, _admin())
        with patch("scout.api.routes.connectors.settings") as mock_settings:
            mock_settings.sf_client_id = "MY_CLIENT_ID_XYZ"
            mock_settings.sf_client_secret = "secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            mock_settings.use_mock_connectors = True
            resp = client.get("/connectors/salesforce/auth-start?return_url=true")
        assert resp.status_code == 200
        assert "MY_CLIENT_ID_XYZ" in resp.json()["auth_url"]

    def test_auth_url_contains_redirect_uri(self, db_session):
        client = _make_client(db_session, _admin())
        with patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-client-id"
            mock_settings.sf_client_secret = "secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            mock_settings.use_mock_connectors = True
            resp = client.get("/connectors/salesforce/auth-start?return_url=true")
        assert resp.status_code == 200
        assert "callback" in resp.json()["auth_url"]


# ─────────────────────────────────────────────────────────────────────────────
# TestSalesforceCallback (5 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSalesforceCallback:

    def _mock_token_response(self) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ACCESS_TOKEN_123",
            "refresh_token": "REFRESH_TOKEN_456",
            "instance_url": "https://acme.salesforce.com",
            "token_type": "Bearer",
        }
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_valid_code_stores_credentials(self, db_session):
        # Clean up any existing rows for this tenant
        db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).delete()
        db_session.commit()

        state = _encode_state(HOME_TENANT, ADMIN_ID)
        client = _make_anon_client(db_session)

        with patch("httpx.post", return_value=self._mock_token_response()), \
             patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-id"
            mock_settings.sf_client_secret = "fake-secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            resp = client.get(
                f"/connectors/salesforce/callback?code=AUTHCODE&state={state}",
                follow_redirects=False,
            )

        # Should redirect to success page
        assert resp.status_code in (302, 307, 200)

        row = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).first()
        assert row is not None

    def test_invalid_code_returns_400(self, db_session):
        state = _encode_state(HOME_TENANT, ADMIN_ID)
        client = _make_anon_client(db_session)

        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.text = "invalid_grant"
        error_resp.raise_for_status.side_effect = Exception("400 Bad Request")

        with patch("httpx.post", side_effect=Exception("bad_code")), \
             patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-id"
            mock_settings.sf_client_secret = "fake-secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            resp = client.get(
                f"/connectors/salesforce/callback?code=BADCODE&state={state}",
                follow_redirects=False,
            )

        assert resp.status_code == 400

    def test_state_decoded_correctly(self, db_session):
        """The callback should extract tenant_id from state and store it."""
        db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).delete()
        db_session.commit()

        state = _encode_state(HOME_TENANT, ADMIN_ID)
        client = _make_anon_client(db_session)

        with patch("httpx.post", return_value=self._mock_token_response()), \
             patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-id"
            mock_settings.sf_client_secret = "fake-secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            client.get(
                f"/connectors/salesforce/callback?code=CODE&state={state}",
                follow_redirects=False,
            )

        row = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).first()
        assert row is not None
        assert row.tenant_id == HOME_TENANT

    def test_stored_auth_data_has_access_token(self, db_session):
        db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).delete()
        db_session.commit()

        state = _encode_state(HOME_TENANT, ADMIN_ID)
        client = _make_anon_client(db_session)

        with patch("httpx.post", return_value=self._mock_token_response()), \
             patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-id"
            mock_settings.sf_client_secret = "fake-secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            client.get(
                f"/connectors/salesforce/callback?code=CODE&state={state}",
                follow_redirects=False,
            )

        row = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).first()
        assert row is not None
        assert "access_token" in row.auth_data
        assert row.auth_data["access_token"] == "ACCESS_TOKEN_123"

    def test_existing_row_updated_not_duplicated(self, db_session):
        """Calling callback twice should upsert, not insert a second row."""
        # Ensure exactly one row exists from previous tests
        existing_count = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).count()
        # Insert one if none exist
        if existing_count == 0:
            db_session.add(ConnectorCredentialStore(
                tenant_id=HOME_TENANT,
                connector_id="salesforce",
                auth_data={"refresh_token": "old_rt"},
                is_active=True,
            ))
            db_session.commit()

        state = _encode_state(HOME_TENANT, ADMIN_ID)
        client = _make_anon_client(db_session)

        with patch("httpx.post", return_value=self._mock_token_response()), \
             patch("scout.config.settings") as mock_settings:
            mock_settings.sf_client_id = "fake-id"
            mock_settings.sf_client_secret = "fake-secret"
            mock_settings.sf_instance_url = "https://login.salesforce.com"
            mock_settings.api_base_url = "http://localhost:8000"
            client.get(
                f"/connectors/salesforce/callback?code=CODE2&state={state}",
                follow_redirects=False,
            )

        count = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).count()
        assert count == 1


# ─────────────────────────────────────────────────────────────────────────────
# TestSalesforceDisconnect (3 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSalesforceDisconnect:

    def _ensure_active_cred(self, db_session):
        """Ensure an active credential row exists for the home tenant."""
        row = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).first()
        if row:
            row.is_active = True
        else:
            row = ConnectorCredentialStore(
                tenant_id=HOME_TENANT,
                connector_id="salesforce",
                auth_data={"refresh_token": "rt"},
                is_active=True,
            )
            db_session.add(row)
        db_session.commit()

    def test_disconnects_active_credential(self, db_session):
        self._ensure_active_cred(db_session)
        client = _make_client(db_session, _admin())
        resp = client.post("/connectors/salesforce/disconnect")
        assert resp.status_code == 200
        assert resp.json()["disconnected"] is True

        row = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).first()
        assert row is not None
        assert row.is_active is False

    def test_404_when_no_credential(self, db_session):
        # Deactivate all rows
        db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).update({"is_active": False})
        db_session.commit()

        client = _make_client(db_session, _admin())
        resp = client.post("/connectors/salesforce/disconnect")
        assert resp.status_code == 404

    def test_non_admin_gets_403(self, db_session):
        client = _make_client(db_session, _viewer())
        resp = client.post("/connectors/salesforce/disconnect")
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# TestSalesforceTest (4 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSalesforceTest:

    def _ensure_active_cred(self, db_session):
        row = db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).first()
        if row:
            row.is_active = True
            row.auth_data = {
                "refresh_token": "rt",
                "instance_url": "https://acme.salesforce.com",
                "client_id": "cid",
                "client_secret": "csec",
            }
        else:
            row = ConnectorCredentialStore(
                tenant_id=HOME_TENANT,
                connector_id="salesforce",
                auth_data={
                    "refresh_token": "rt",
                    "instance_url": "https://acme.salesforce.com",
                    "client_id": "cid",
                    "client_secret": "csec",
                },
                is_active=True,
            )
            db_session.add(row)
        db_session.commit()

    def test_returns_connected_false_when_no_creds(self, db_session):
        # Deactivate all
        db_session.query(ConnectorCredentialStore).filter_by(
            tenant_id=HOME_TENANT, connector_id="salesforce"
        ).update({"is_active": False})
        db_session.commit()

        client = _make_client(db_session, _admin())
        resp = client.post("/connectors/salesforce/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert "error" in data

    def test_returns_connected_true_when_creds_exist(self, db_session):
        self._ensure_active_cred(db_session)

        from scout.connectors.models import ConnectorHealth

        mock_health = ConnectorHealth(
            connector_id="salesforce",
            is_healthy=True,
            latency_ms=42.0,
        )

        with patch(
            "scout.connectors.salesforce.SalesforceConnector.health_check",
            return_value=mock_health,
        ):
            client = _make_client(db_session, _admin())
            resp = client.post("/connectors/salesforce/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True

    def test_health_check_error_returns_connected_false(self, db_session):
        self._ensure_active_cred(db_session)

        from scout.connectors.models import ConnectorHealth

        mock_health = ConnectorHealth(
            connector_id="salesforce",
            is_healthy=False,
            latency_ms=0.0,
            error_message="Connection refused",
        )

        with patch(
            "scout.connectors.salesforce.SalesforceConnector.health_check",
            return_value=mock_health,
        ):
            client = _make_client(db_session, _admin())
            resp = client.post("/connectors/salesforce/test")

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["error"] == "Connection refused"

    def test_non_admin_gets_403(self, db_session):
        client = _make_client(db_session, _viewer())
        resp = client.post("/connectors/salesforce/test")
        assert resp.status_code == 403
