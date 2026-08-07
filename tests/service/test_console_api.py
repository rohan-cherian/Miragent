"""tests/service/test_console_api.py — W1-API-01 FastAPI service skeleton."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from scout.service.app import create_app
from scout.service.config import ServiceSettings


DEFAULT_DSN = "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"


def _postgres_url() -> str:
    return os.getenv("API_DATABASE_URL") or os.getenv("ZENDESK_DATABASE_URL") or DEFAULT_DSN


def _postgres_reachable(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'src_zendesk' AND table_name = 'tickets'"
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture
def pg_url() -> str:
    url = _postgres_url()
    if not _postgres_reachable(url):
        pytest.skip("Postgres with src_zendesk not reachable")
    return url


@pytest.fixture
def client(pg_url: str) -> TestClient:
    settings = ServiceSettings(database_url=pg_url)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


class TestHealthReady:
    def test_health_ok(self, client: TestClient):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

    def test_ready_ok(self, client: TestClient):
        res = client.get("/ready")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ready"
        assert body["database"] == "ok"


class TestCorpusStats:
    def test_stats_are_live_from_postgres(self, client: TestClient, pg_url: str):
        import psycopg

        res = client.get("/corpus/stats")
        assert res.status_code == 200
        body = res.json()

        with psycopg.connect(pg_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM src_zendesk.tickets")
                tickets = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM src_zendesk.organizations")
                accounts = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM src_zendesk.users "
                    "WHERE role IN ('agent', 'admin')"
                )
                analysts = cur.fetchone()[0]

        assert body["tickets"] == tickets
        assert body["accounts"] == accounts
        assert body["analysts"] == analysts
        assert body["channels"] >= 1
        assert body["date_range"]["start"]
        assert body["date_range"]["end"]
        assert body["tickets"] > 0
        assert body["accounts"] > 0


class TestErrorEnvelope:
    def test_unknown_route_uses_envelope(self, client: TestClient):
        res = client.get("/does-not-exist")
        assert res.status_code == 404
        body = res.json()
        assert body["error"]["code"] == "not_found"
        assert "message" in body["error"]

    def test_missing_db_returns_envelope(self):
        settings = ServiceSettings(database_url="unused")
        app = create_app(settings=settings)

        # Simulate misconfig: clear db after startup
        with TestClient(app) as c:
            c.app.state.db = None
            res = c.get("/corpus/stats")
            assert res.status_code == 503
            assert res.json()["error"]["code"] == "misconfigured"
            assert "error" in res.json()
            assert "details" in res.json()["error"]
