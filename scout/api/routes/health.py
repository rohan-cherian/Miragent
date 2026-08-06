"""
scout/api/routes/health.py — GET /health

The health endpoint is the API's heartbeat. It probes every backing
service and returns a structured report of what's up and what's not.

Why does this matter in production?
  Kubernetes uses liveness and readiness probes. The readiness probe
  calls GET /health before sending any traffic to a new pod. If Neo4j
  isn't reachable, the pod stays out of rotation until it recovers.
  You get zero-downtime deployments and automatic recovery for free.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from neo4j import GraphDatabase

from scout.api.models import HealthResponse, ServiceHealth
from scout.config import settings

router = APIRouter()


def _check_neo4j() -> ServiceHealth:
    """Ping Neo4j with a minimal Cypher query and measure latency."""
    start = time.perf_counter()
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        with driver.session() as session:
            session.run("RETURN 1").consume()
        driver.close()
        latency = (time.perf_counter() - start) * 1000
        return ServiceHealth(name="neo4j", healthy=True, latency_ms=round(latency, 1))
    except Exception as exc:
        return ServiceHealth(name="neo4j", healthy=False, error=str(exc))


def _check_redis() -> ServiceHealth:
    """Ping Redis and measure latency. Redis is optional — absence does not degrade status."""
    start = time.perf_counter()
    try:
        import redis

        client = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        latency = (time.perf_counter() - start) * 1000
        return ServiceHealth(name="redis", healthy=True, latency_ms=round(latency, 1))
    except Exception as exc:
        # Redis is optional — used for async job queuing but not required for core API
        return ServiceHealth(name="redis", healthy=False, error="not configured (optional)")


# Required services — their health determines overall status
REQUIRED_SERVICES = {"neo4j"}


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Probes all backing services (Neo4j, Redis) and returns their "
        "health status. Used by Kubernetes liveness/readiness probes. "
        "Redis is optional — its absence does not degrade overall status."
    ),
    tags=["Operations"],
)
def health_check() -> HealthResponse:
    services = [_check_neo4j(), _check_redis()]
    required_healthy = all(s.healthy for s in services if s.name in REQUIRED_SERVICES)

    return HealthResponse(
        status="healthy" if required_healthy else "degraded",
        environment=settings.environment,
        services=services,
        timestamp=datetime.now(timezone.utc),
    )
