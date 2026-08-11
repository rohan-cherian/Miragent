"""
W1-PLT-06 — Observability baseline.

Structured JSON logging + OpenTelemetry tracing with run_id / trace_id
propagated end-to-end (ingest → agents → console response).
"""

from scout.observability.context import (
    ObservabilityContext,
    bind_context,
    clear_context,
    get_context,
    new_run_id,
    with_context,
)
from scout.observability.logging import configure_json_logging, get_logger
from scout.observability.tracing import (
    get_current_trace_id,
    init_tracing,
    instrument_fastapi,
    start_span,
)

__all__ = [
    "ObservabilityContext",
    "bind_context",
    "clear_context",
    "configure_json_logging",
    "get_context",
    "get_current_trace_id",
    "get_logger",
    "init_tracing",
    "instrument_fastapi",
    "new_run_id",
    "start_span",
    "with_context",
]
