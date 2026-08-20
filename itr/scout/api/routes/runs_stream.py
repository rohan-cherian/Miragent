"""
Task 24 — GET /runs/{id}/stream (Server-Sent Events).

Emits raw_ingest.run_stage_event rows as they are written, so the console's
progress bars animate from real data rather than a scripted timer.

Polling rather than LISTEN/NOTIFY: the writer (scout/raw/runs.py) inserts plain
rows and knows nothing about subscribers. Adding a trigger to make it notify
would couple ingestion to the console, and the seven stages of a run are not a
high-frequency feed — a short poll is honest and cheap.

The stream closes when the run reaches a terminal state, so the browser does
not hold a connection open forever on a finished run.

Layering (Task 4): imports nothing from scout.gmail, scout.connectors, or
googleapiclient.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from scout.api.deps import _get_engine as get_engine

router = APIRouter()

_POLL_SECONDS = 1.0
_MAX_SECONDS = 300  # a run that has not finished in 5 minutes is not animating
_TERMINAL = {"success", "failed", "partial"}

_EVENTS_SQL = text(
    """
    SELECT id, stage, progress_pct, log_line, duration_ms, created_at
    FROM raw_ingest.run_stage_event
    WHERE run_id = :run_id AND id > :after_id
    ORDER BY id
    """
)

_STATUS_SQL = text("SELECT status FROM raw_ingest.runs WHERE id = :run_id")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _event_stream(run_id: uuid.UUID) -> AsyncIterator[str]:
    engine = get_engine()
    after_id = 0
    waited = 0.0

    while waited < _MAX_SECONDS:
        with engine.connect() as conn:
            rows = conn.execute(
                _EVENTS_SQL, {"run_id": str(run_id), "after_id": after_id}
            ).mappings().all()
            status = conn.execute(_STATUS_SQL, {"run_id": str(run_id)}).scalar()

        for row in rows:
            after_id = max(after_id, int(row["id"]))
            yield _sse(
                "stage",
                {
                    "stage": row["stage"],
                    "progress_pct": row["progress_pct"],
                    "log_line": row["log_line"],
                    "duration_ms": row["duration_ms"],
                    "created_at": row["created_at"],
                },
            )

        if status is None:
            yield _sse("error", {"detail": f"no run {run_id}"})
            return

        # Terminal only after draining: the last stage event and the status
        # change are written in that order, so exiting on status alone would
        # drop the final row.
        if status in _TERMINAL and not rows:
            yield _sse("done", {"status": status})
            return

        await asyncio.sleep(_POLL_SECONDS)
        waited += _POLL_SECONDS

    yield _sse("done", {"status": "timeout"})


@router.get("/runs/{id}/stream")
async def stream_run(id: uuid.UUID) -> StreamingResponse:  # noqa: A002 - contract names it `id`
    return StreamingResponse(
        _event_stream(id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this an nginx in front of the API buffers the whole
            # stream and the bars jump from 0 to 100 at the end.
            "X-Accel-Buffering": "no",
        },
    )
