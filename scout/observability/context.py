"""
Request / run context: run_id, trace_id, ticket_id.

Uses contextvars so every log line and span in the same async/thread
pipeline carries the same IDs without threading them through every call.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ObservabilityContext:
    run_id: str
    ticket_id: str | None = None
    trace_id: str | None = None


_ctx: ContextVar[ObservabilityContext | None] = ContextVar(
    "miragent_observability_ctx",
    default=None,
)


def new_run_id() -> str:
    """Generate a stable run identifier (UUID4 hex)."""
    return uuid.uuid4().hex


def get_context() -> ObservabilityContext | None:
    return _ctx.get()


def bind_context(
    *,
    run_id: str | None = None,
    ticket_id: str | None = None,
    trace_id: str | None = None,
) -> Token:
    """
    Bind (or merge into) the current observability context.

    Returns a reset token — prefer ``with_context`` / ``clear_context``.
    """
    current = _ctx.get()
    next_ctx = ObservabilityContext(
        run_id=run_id or (current.run_id if current else new_run_id()),
        ticket_id=ticket_id if ticket_id is not None else (current.ticket_id if current else None),
        trace_id=trace_id if trace_id is not None else (current.trace_id if current else None),
    )
    return _ctx.set(next_ctx)


def clear_context(token: Token | None = None) -> None:
    if token is not None:
        _ctx.reset(token)
    else:
        _ctx.set(None)


@contextmanager
def with_context(
    *,
    run_id: str | None = None,
    ticket_id: str | None = None,
    trace_id: str | None = None,
) -> Iterator[ObservabilityContext]:
    token = bind_context(run_id=run_id, ticket_id=ticket_id, trace_id=trace_id)
    try:
        ctx = get_context()
        assert ctx is not None
        yield ctx
    finally:
        clear_context(token)
