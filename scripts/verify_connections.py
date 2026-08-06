"""
scripts/verify_connections.py — Verify all database connections are healthy.

Run this after `docker compose up -d` to confirm every service
is reachable and responding correctly.

Usage:
    poetry run python scripts/verify_connections.py
"""

import sys
import time

def check(label: str, fn) -> bool:
    """Run a check and print a pass/fail result."""
    try:
        start = time.time()
        fn()
        ms = (time.time() - start) * 1000
        print(f"  ✅  {label} ({ms:.0f}ms)")
        return True
    except Exception as e:
        print(f"  ❌  {label} — {e}")
        return False


def verify_neo4j():
    from neo4j import GraphDatabase
    from scout.config import settings
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    with driver.session() as session:
        result = session.run("RETURN 'Scout connected to Neo4j' AS msg")
        msg = result.single()["msg"]
    driver.close()


def verify_clickhouse():
    from clickhouse_driver import Client
    from scout.config import settings
    client = Client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        user=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
    )
    result = client.execute("SELECT 'Scout connected to ClickHouse'")
    assert result[0][0] == "Scout connected to ClickHouse"


def verify_weaviate():
    import weaviate
    from scout.config import settings
    client = weaviate.connect_to_local(
        host="localhost",
        port=8080,
    )
    assert client.is_ready()
    client.close()


def verify_redis():
    import redis
    from scout.config import settings
    r = redis.from_url(settings.redis_url.replace("redis://", "redis://:miragent_dev@").replace(":6379", ":6379"))
    assert r.ping()


def verify_mock_connectors():
    """Verify all mock connectors are functional (no Docker needed)."""
    from scout.connectors.registry import get_connector
    from scout.connectors.models import ConnectorCredentials

    for connector_id in ["salesforce", "workday", "netsuite"]:
        creds = ConnectorCredentials(
            connector_id=connector_id,
            tenant_id="verify-script",
            auth_data={},
        )
        connector = get_connector(connector_id, creds)
        assert connector.authenticate()
        health = connector.health_check()
        assert health.is_healthy


def main():
    print()
    print("━" * 50)
    print("  Miragent Scout — Connection Verification")
    print("━" * 50)

    results = []

    print()
    print("  Mock Connectors (no Docker required):")
    results.append(check("Salesforce / Workday / NetSuite mocks", verify_mock_connectors))

    print()
    print("  Database Services (requires: docker compose up -d):")
    results.append(check("Neo4j  (graph database)", verify_neo4j))
    results.append(check("ClickHouse  (events store)", verify_clickhouse))
    results.append(check("Weaviate  (vector search)", verify_weaviate))
    results.append(check("Redis  (task queue)", verify_redis))

    print()
    passed = sum(results)
    total = len(results)
    print("━" * 50)
    if passed == total:
        print(f"  🚀  All {total} checks passed. Scout is ready.")
    else:
        print(f"  ⚠️   {passed}/{total} checks passed.")
        print("       If databases failed: run `docker compose up -d` first.")
    print("━" * 50)
    print()

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
