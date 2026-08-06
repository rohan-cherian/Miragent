"""Tests for GET /health."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from scout.api.app import create_app


@pytest.fixture
def client():
    """Fresh TestClient for each test — no shared state."""
    app = create_app()
    return TestClient(app, raise_server_exceptions=True)


class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        """The health endpoint must always respond — even if services are down."""
        response = client.get("/health")
        # 200 means the API itself is up; 'status' field tells you about services
        assert response.status_code == 200

    def test_health_response_shape(self, client):
        """Validate the response schema matches HealthResponse."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "services" in data
        assert "timestamp" in data
        assert isinstance(data["services"], list)

    def test_health_status_is_string(self, client):
        """Status must be 'healthy' or 'degraded'."""
        response = client.get("/health")
        data = response.json()
        assert data["status"] in ("healthy", "degraded")

    def test_health_services_have_required_fields(self, client):
        """Each service entry must have name and healthy fields."""
        response = client.get("/health")
        data = response.json()
        for service in data["services"]:
            assert "name" in service
            assert "healthy" in service
            assert isinstance(service["healthy"], bool)

    def test_health_checks_neo4j(self, client):
        """Neo4j must appear in the services list."""
        response = client.get("/health")
        data = response.json()
        service_names = [s["name"] for s in data["services"]]
        assert "neo4j" in service_names

    def test_health_checks_redis(self, client):
        """Redis must appear in the services list."""
        response = client.get("/health")
        data = response.json()
        service_names = [s["name"] for s in data["services"]]
        assert "redis" in service_names

    def test_health_degraded_when_service_down(self, client):
        """If any service is unreachable, status should be 'degraded'."""
        # Patch the Neo4j driver to simulate a connection failure
        with patch("scout.api.routes.health.GraphDatabase") as mock_gdb:
            mock_gdb.driver.side_effect = Exception("Connection refused")
            response = client.get("/health")
            data = response.json()
            assert data["status"] == "degraded"
            # The neo4j entry should be marked unhealthy
            neo4j_entry = next(s for s in data["services"] if s["name"] == "neo4j")
            assert neo4j_entry["healthy"] is False
            assert neo4j_entry["error"] is not None
