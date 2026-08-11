"""
tests/conftest.py — Session-level fixtures and skip logic for the full test suite.

Any test that uses `seeded_driver` or `seeded_client` requires a live Neo4j
instance. When Neo4j is not reachable (e.g. running tests without Docker),
those tests are automatically skipped with a clear message rather than failing.
"""

from __future__ import annotations

import os

import pytest

# Avoid OTLP export noise / retries when Jaeger is not running during unit tests.
# Journey tests attach an InMemorySpanExporter to the same TracerProvider.
os.environ.setdefault("OTEL_TRACES_ENABLED", "false")


def _neo4j_reachable() -> bool:
    """Return True if Neo4j is accepting connections at the configured URI."""
    try:
        from neo4j import GraphDatabase
        from scout.config import settings

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
            connection_timeout=2.0,
        )
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


# Checked once per session; shared across all conftest levels
_NEO4J_AVAILABLE: bool | None = None


def _get_neo4j_available() -> bool:
    global _NEO4J_AVAILABLE
    if _NEO4J_AVAILABLE is None:
        _NEO4J_AVAILABLE = _neo4j_reachable()
    return _NEO4J_AVAILABLE


# Fixtures that indicate the test needs a live Neo4j graph
_NEO4J_FIXTURES = {"seeded_driver", "seeded_client"}

_SKIP_MARKER = pytest.mark.skip(
    reason=(
        "Neo4j not reachable (localhost:7687) — "
        "start Neo4j to run graph/worker integration tests"
    )
)


def pytest_collection_modifyitems(config, items):
    """
    After collection: auto-skip any test whose fixture chain includes a
    fixture that requires a live Neo4j connection.
    """
    if _get_neo4j_available():
        return  # Neo4j is up — run all tests normally

    for item in items:
        fixturenames = getattr(item, "fixturenames", [])
        if any(f in _NEO4J_FIXTURES for f in fixturenames):
            item.add_marker(_SKIP_MARKER)
