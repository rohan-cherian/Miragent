"""
OpenTelemetry tracing setup (OTLP → Jaeger or any OTLP collector).

Environment:
  OTEL_EXPORTER_OTLP_ENDPOINT  default http://127.0.0.1:4318
  OTEL_SERVICE_NAME            default miragent-console-api
  OTEL_TRACES_ENABLED          default true (set false in unit tests)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode, use_span

_INIT = False


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def init_tracing(
    *,
    service_name: str | None = None,
    otlp_endpoint: str | None = None,
) -> TracerProvider | None:
    """
    Initialise a global TracerProvider once.

    When OTEL_TRACES_ENABLED=false, installs a no-export provider still capable
    of generating trace IDs (useful in tests).
    """
    global _INIT
    if _INIT:
        provider = trace.get_tracer_provider()
        return provider if isinstance(provider, TracerProvider) else None

    name = service_name or os.getenv("OTEL_SERVICE_NAME", "miragent-console-api")
    resource = Resource.create(
        {
            "service.name": name,
            "service.namespace": "miragent",
        }
    )
    provider = TracerProvider(resource=resource)

    if _env_bool("OTEL_TRACES_ENABLED", True):
        endpoint = (
            otlp_endpoint
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            or "http://127.0.0.1:4318"
        )
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except Exception:
            # Fall back to console exporter so local runs still show spans
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _INIT = True
    return provider


def instrument_fastapi(app: Any, *, service_name: str | None = None) -> None:
    """Attach OpenTelemetry FastAPI instrumentation (ASGI + excluded health)."""
    init_tracing(service_name=service_name)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health,ready",
        )
    except Exception:
        # Instrumentation is best-effort; journey spans still work via start_span
        pass


def get_tracer(name: str = "miragent") -> trace.Tracer:
    init_tracing()
    return trace.get_tracer(name)


def get_current_trace_id() -> str | None:
    """Return the active span's trace id as 32-char hex, or None."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is None or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Start a child span; records exceptions onto the span."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def attach_span(span: Span):
    """Context manager to make an existing span current (rare)."""
    return use_span(span, end_on_exit=False)
