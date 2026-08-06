"""
tests/test_user_management.py — Sprint 15 multi-tenant user & API key management tests.

Covers:
  - Tenant creation
  - User registration
  - Login returns JWT
  - GET /users/me with valid JWT
  - GET /users/me without JWT → 401
  - Create API key → returns raw key
  - List API keys (no raw key in list)
  - Delete (deactivate) API key
  - Deleted key no longer works for auth
  - Backward compat: settings.scout_api_key still works
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scout.api.app import create_app
from scout.config import settings
from scout.db.database import Base, get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def client(tmp_path):
    """
    Isolated TestClient for each test.

    Uses a fresh in-memory SQLite database so tests are fully independent.
    Auth is enabled (settings.auth_enabled=True) so we exercise real auth flows.
    """
    db_url = f"sqlite:///{tmp_path}/test_users.db"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Create all tables in the test DB.
    from scout.db import models  # noqa: F401 — side-effect: registers models with Base
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Patch the middleware's SessionLocal too, so API-key DB lookups use the test DB.
    import scout.db.database as _db_module
    original_session_local = _db_module.SessionLocal
    _db_module.SessionLocal = TestingSessionLocal

    original_auth = settings.auth_enabled
    settings.auth_enabled = True

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    # Teardown
    app.dependency_overrides.clear()
    _db_module.SessionLocal = original_session_local
    settings.auth_enabled = original_auth
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

_TENANT = {"name": "Acme Corp", "slug": "acme"}
_USER = {"email": "alice@acme.com", "password": "s3cr3t!", "tenant_slug": "acme", "role": "admin"}


def _create_tenant(client: TestClient, payload: dict | None = None) -> dict:
    resp = client.post("/users/tenants", json=payload or _TENANT)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_user(client: TestClient, payload: dict | None = None) -> dict:
    resp = client.post("/users/register", json=payload or _USER)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client: TestClient, email: str = _USER["email"], password: str = _USER["password"]) -> str:
    resp = client.post("/users/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tenant tests
# ---------------------------------------------------------------------------


class TestTenantCreation:

    def test_create_tenant_returns_201(self, client):
        resp = client.post("/users/tenants", json=_TENANT)
        assert resp.status_code == 201

    def test_create_tenant_response_shape(self, client):
        data = _create_tenant(client)
        assert "id" in data
        assert data["name"] == _TENANT["name"]
        assert data["slug"] == _TENANT["slug"]
        assert data["is_active"] is True

    def test_duplicate_tenant_slug_returns_409(self, client):
        _create_tenant(client)
        resp = client.post("/users/tenants", json=_TENANT)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# User registration tests
# ---------------------------------------------------------------------------


class TestUserRegistration:

    def test_register_user_returns_201(self, client):
        _create_tenant(client)
        resp = client.post("/users/register", json=_USER)
        assert resp.status_code == 201

    def test_register_user_response_shape(self, client):
        _create_tenant(client)
        data = _register_user(client)
        assert "id" in data
        assert data["email"] == _USER["email"]
        assert data["role"] == "admin"
        assert data["is_active"] is True
        assert "hashed_password" not in data

    def test_register_unknown_tenant_returns_404(self, client):
        resp = client.post(
            "/users/register",
            json={**_USER, "tenant_slug": "nonexistent"},
        )
        assert resp.status_code == 404

    def test_duplicate_email_returns_409(self, client):
        _create_tenant(client)
        _register_user(client)
        resp = client.post("/users/register", json=_USER)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


class TestLogin:

    def test_login_returns_token(self, client):
        _create_tenant(client)
        _register_user(client)
        resp = client.post("/users/login", json={"email": _USER["email"], "password": _USER["password"]})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["email"] == _USER["email"]

    def test_login_wrong_password_returns_401(self, client):
        _create_tenant(client)
        _register_user(client)
        resp = client.post("/users/login", json={"email": _USER["email"], "password": "wrong"})
        assert resp.status_code == 401

    def test_login_unknown_email_returns_401(self, client):
        _create_tenant(client)
        resp = client.post("/users/login", json={"email": "nobody@acme.com", "password": "x"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /users/me tests
# ---------------------------------------------------------------------------


class TestCurrentUser:

    def test_get_me_with_valid_jwt(self, client):
        _create_tenant(client)
        _register_user(client)
        token = _login(client)
        resp = client.get("/users/me", headers=_auth_headers(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == _USER["email"]

    def test_get_me_without_jwt_returns_401(self, client):
        resp = client.get("/users/me")
        assert resp.status_code == 401

    def test_get_me_with_invalid_jwt_returns_401(self, client):
        resp = client.get("/users/me", headers={"Authorization": "Bearer totally-invalid"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# API key tests
# ---------------------------------------------------------------------------


class TestApiKeys:

    def _setup(self, client):
        """Create tenant, register user, login — return JWT token."""
        _create_tenant(client)
        _register_user(client)
        return _login(client)

    def test_create_api_key_returns_raw_key(self, client):
        token = self._setup(client)
        resp = client.post(
            "/users/me/api-keys",
            json={"label": "CI runner"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "raw_key" in body
        assert body["raw_key"].startswith("sk-")

    def test_create_api_key_response_shape(self, client):
        token = self._setup(client)
        resp = client.post(
            "/users/me/api-keys",
            json={"label": "My key"},
            headers=_auth_headers(token),
        )
        body = resp.json()
        assert "id" in body
        assert "key_prefix" in body
        assert "label" in body
        assert body["is_active"] is True
        assert body["label"] == "My key"

    def test_list_api_keys_no_raw_key(self, client):
        token = self._setup(client)
        client.post("/users/me/api-keys", json={"label": "k1"}, headers=_auth_headers(token))
        resp = client.get("/users/me/api-keys", headers=_auth_headers(token))
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) >= 1
        for k in keys:
            assert "raw_key" not in k

    def test_delete_api_key_deactivates_it(self, client):
        token = self._setup(client)
        create_resp = client.post(
            "/users/me/api-keys",
            json={"label": "to-delete"},
            headers=_auth_headers(token),
        )
        key_id = create_resp.json()["id"]

        del_resp = client.delete(f"/users/me/api-keys/{key_id}", headers=_auth_headers(token))
        assert del_resp.status_code == 204

        # Key should no longer appear in list
        list_resp = client.get("/users/me/api-keys", headers=_auth_headers(token))
        ids = [k["id"] for k in list_resp.json()]
        assert key_id not in ids

    def test_delete_nonexistent_key_returns_404(self, client):
        token = self._setup(client)
        resp = client.delete(
            "/users/me/api-keys/00000000-0000-0000-0000-000000000000",
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404

    def test_deleted_key_no_longer_authenticates(self, client):
        """A deactivated DB key must be rejected by require_api_key."""
        token = self._setup(client)
        create_resp = client.post(
            "/users/me/api-keys",
            json={"label": "ephemeral"},
            headers=_auth_headers(token),
        )
        body = create_resp.json()
        raw_key = body["raw_key"]
        key_id = body["id"]

        # Verify the raw key works first.
        validate_resp = client.get("/auth/validate", headers={"X-API-Key": raw_key})
        assert validate_resp.status_code == 200

        # Deactivate the key.
        client.delete(f"/users/me/api-keys/{key_id}", headers=_auth_headers(token))

        # Now it must be rejected.
        validate_after = client.get("/auth/validate", headers={"X-API-Key": raw_key})
        assert validate_after.status_code == 401


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:

    def test_settings_scout_api_key_still_works(self, client):
        """The hardcoded settings.scout_api_key must still pass require_api_key."""
        original_key = settings.scout_api_key
        try:
            settings.scout_api_key = "compat-test-key"
            resp = client.get("/auth/validate", headers={"X-API-Key": "compat-test-key"})
            assert resp.status_code == 200
        finally:
            settings.scout_api_key = original_key

    def test_wrong_key_returns_401(self, client):
        resp = client.get("/auth/validate", headers={"X-API-Key": "not-a-valid-key"})
        assert resp.status_code == 401
