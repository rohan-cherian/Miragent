"""tests/observability — W1-PLT-06 structured logging + tracing + propagation."""

from __future__ import annotations

import json
import logging
import os

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Traces stay local unless the process opts into OTLP (see tests/conftest.py).
os.environ.setdefault("OTEL_TRACES_ENABLED", "false")

from scout.observability.context import get_context, with_context  # noqa: E402
from scout.observability.logging import JsonFormatter, configure_json_logging  # noqa: E402
from scout.observability import tracing as tracing_mod  # noqa: E402


@pytest.fixture()
def memory_exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Attach an in-memory exporter (no Jaeger needed)."""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing_mod, "_INIT", True)
    return exporter


class TestJsonLogging:
    def test_json_line_includes_context_ids(self, capsys: pytest.CaptureFixture[str]):
        configure_json_logging(level=logging.INFO)
        logger = logging.getLogger("test.observability.json")

        with with_context(run_id="run-abc", ticket_id="42", trace_id="trace-xyz"):
            logger.info("hello journey")

        # Root handler writes to stdout; also format a record directly for certainty
        record = logging.LogRecord(
            name="test.observability.json",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="direct",
            args=(),
            exc_info=None,
        )
        with with_context(run_id="run-abc", ticket_id="42", trace_id="trace-xyz"):
            line = JsonFormatter().format(record)

        payload = json.loads(line)
        assert payload["run_id"] == "run-abc"
        assert payload["ticket_id"] == "42"
        assert payload["trace_id"] == "trace-xyz"
        assert payload["message"] == "direct"
        assert payload["level"] == "INFO"


class TestContext:
    def test_with_context_binds_and_clears(self):
        assert get_context() is None
        with with_context(run_id="r1", ticket_id="9"):
            ctx = get_context()
            assert ctx is not None
            assert ctx.run_id == "r1"
            assert ctx.ticket_id == "9"
        assert get_context() is None


class TestTracingSpans:
    def test_nested_spans_share_trace_id(self, memory_exporter: InMemorySpanExporter):
        from scout.observability.tracing import get_current_trace_id, start_span

        with start_span("ticket.journey", attributes={"ticket.id": "1"}):
            root_tid = get_current_trace_id()
            assert root_tid is not None
            with start_span("ticket.ingest"):
                assert get_current_trace_id() == root_tid
            with start_span("agent.context"):
                assert get_current_trace_id() == root_tid

        spans = memory_exporter.get_finished_spans()
        names = {s.name for s in spans}
        assert "ticket.journey" in names
        assert "ticket.ingest" in names
        assert "agent.context" in names
        trace_ids = {format(s.context.trace_id, "032x") for s in spans}
        assert len(trace_ids) == 1
        assert root_tid in trace_ids


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
def journey_client(memory_exporter: InMemorySpanExporter) -> TestClient:
    url = _postgres_url()
    if not _postgres_reachable(url):
        pytest.skip("Postgres with src_zendesk not reachable")

    from scout.service.app import create_app
    from scout.service.config import ServiceSettings

    settings = ServiceSettings(database_url=url)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


class TestTicketJourneyE2E:
    def test_journey_returns_same_run_and_trace(
        self,
        journey_client: TestClient,
        memory_exporter: InMemorySpanExporter,
    ):
        # Pick any live ticket id
        import psycopg

        url = _postgres_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM src_zendesk.tickets LIMIT 1")
                ticket_id = str(cur.fetchone()[0])

        memory_exporter.clear()
        res = journey_client.get(
            f"/tickets/{ticket_id}/journey",
            headers={"X-Run-Id": "demo-run-001", "X-Ticket-Id": ticket_id},
        )
        assert res.status_code == 200, res.text
        body = res.json()

        assert body["run_id"] == "demo-run-001"
        assert body["ticket_id"] == ticket_id
        assert body["trace_id"]
        assert len(body["trace_id"]) == 32
        assert body["agents"][0]["name"] == "context"
        assert body["agents"][1]["name"] == "recommend"
        assert body["console"]["screen"] == "ticket-360"

        # Headers echo the same IDs for the console / trace viewer hand-off
        assert res.headers.get("x-run-id") == "demo-run-001"
        assert res.headers.get("x-trace-id") == body["trace_id"]
        assert res.headers.get("x-ticket-id") == ticket_id

        spans = memory_exporter.get_finished_spans()
        names = {s.name for s in spans}
        # Nested journey spans must be present
        assert "ticket.journey" in names
        assert "ticket.ingest" in names
        assert "agent.context" in names
        assert "agent.recommend" in names
        assert "console.response" in names

        journey_spans = [s for s in spans if s.name.startswith(("ticket.", "agent.", "console."))]
        assert journey_spans
        trace_ids = {format(s.context.trace_id, "032x") for s in journey_spans}
        assert len(trace_ids) == 1
        assert body["trace_id"] in trace_ids

    def test_missing_ticket_404(self, journey_client: TestClient):
        res = journey_client.get("/tickets/999999999/journey")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "ticket_not_found"
