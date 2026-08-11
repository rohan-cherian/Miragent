"""One-shot: journey → flush → query Jaeger for the trace_id."""

from __future__ import annotations

import os
import time

import httpx
import psycopg
from fastapi.testclient import TestClient
from opentelemetry import trace

os.environ["OTEL_TRACES_ENABLED"] = "true"
os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:4318"
os.environ["OTEL_SERVICE_NAME"] = "miragent-console-api"

import scout.observability.tracing as tracing_mod

tracing_mod._INIT = False

from scout.service.app import create_app
from scout.service.config import ServiceSettings

dsn = os.environ.get(
    "ZENDESK_DATABASE_URL",
    "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent",
)
app = create_app(settings=ServiceSettings(database_url=dsn))

with TestClient(app) as client:
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM src_zendesk.tickets LIMIT 1")
            ticket_id = str(cur.fetchone()[0])

    res = client.get(
        f"/tickets/{ticket_id}/journey",
        headers={"X-Run-Id": "jaeger-demo-001"},
    )
    body = res.json()
    print("status", res.status_code)
    print("run_id", body.get("run_id"))
    print("trace_id", body.get("trace_id"))
    print("ticket_id", body.get("ticket_id"))
    print("x-trace-id", res.headers.get("x-trace-id"))
    trace_id = body.get("trace_id") or ""

provider = trace.get_tracer_provider()
if hasattr(provider, "force_flush"):
    provider.force_flush(timeout_millis=10000)
time.sleep(2)

r = httpx.get(f"http://127.0.0.1:16686/api/traces/{trace_id}", timeout=15)
print("jaeger_status", r.status_code)
if r.status_code == 200:
    data = r.json()
    traces = data.get("data") or []
    spans = traces[0].get("spans", []) if traces else []
    print("span_count", len(spans))
    print("span_ops", sorted({s.get("operationName") for s in spans}))
else:
    print("jaeger_body", r.text[:500])
    services = httpx.get("http://127.0.0.1:16686/api/services", timeout=10)
    print("services", services.text)
