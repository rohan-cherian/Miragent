"""
itr/scout/connectors/base.py — the four connector protocols (Task 21).

Every source adapter implements the same four capabilities, so adding a system
in Slice 2 means writing one adapter folder rather than touching the pipeline.

The load-bearing detail is ``ActionExecutor.execute``: it takes an
``ApprovedAction``, not an ``Action``. The approval lives *in the type*, so the
argument cannot be constructed without an approval record. That makes
"recommendation only" structural rather than procedural — you cannot forget to
check, because there is nothing to pass if nobody approved it.

These are ``typing.Protocol`` classes, so adapters satisfy them structurally
with no inheritance and no import from this module at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "MetadataInventory",
    "ApprovedAction",
    "ActionResult",
    "SendResult",
    "MetadataReader",
    "DataReader",
    "EventListener",
    "ActionExecutor",
]


# ── data carried across the boundary ─────────────────────────────────────────


@dataclass(frozen=True)
class MetadataInventory:
    """What a source says it contains, before any extraction.

    Feeds the console's Source Catalogue: object counts per entity, which
    objects are standard vs custom, and the adapter's declared rate limit.
    """

    source_system: str
    objects: list[dict[str, Any]] = field(default_factory=list)
    threads: int | None = None
    messages: int | None = None
    attachments: int | None = None
    is_emulated: bool = False
    rate_limit: dict[str, Any] = field(default_factory=dict)
    scanned_at: datetime | None = None


@dataclass(frozen=True)
class ApprovedAction:
    """An action a human has approved, and the evidence that they did.

    Deliberately not constructible from an unapproved action: every field
    below is required, and ``payload_hash`` must match the text that was
    actually approved. ``ActionExecutor.execute`` takes this type and nothing
    else, so an unapproved send has no way to reach the wire.

    ``payload_hash`` is checked again inside the executor rather than trusted.
    A hash that travelled with the object proves only that someone built the
    object; re-reading the approval row proves the approval still exists and
    still covers this exact text.
    """

    approval_id: str
    case_id: str
    action_type: str
    payload_hash: str
    approved_by: str | None = None
    approved_at: datetime | None = None


@dataclass(frozen=True)
class ActionResult:
    """Outcome of executing an approved action."""

    ok: bool
    external_id: str | None = None
    thread_external_id: str | None = None
    executed_at: datetime | None = None
    detail: str | None = None


@dataclass(frozen=True)
class SendResult:
    """What Gmail returned for a sent reply."""

    message_id: str
    thread_id: str
    sent_at: datetime

    def as_action_result(self) -> ActionResult:
        return ActionResult(
            ok=True,
            external_id=self.message_id,
            thread_external_id=self.thread_id,
            executed_at=self.sent_at,
        )


# ── the four protocols ───────────────────────────────────────────────────────


@runtime_checkable
class MetadataReader(Protocol):
    """Describe the source without extracting from it."""

    def scan(self) -> MetadataInventory: ...


@runtime_checkable
class DataReader(Protocol):
    """Pull records out of the source."""

    def backfill(self, cursor: str | None = None) -> Any: ...

    def fetch(self, entity: str, external_id: str) -> Any: ...


@runtime_checkable
class EventListener(Protocol):
    """Receive pushed events, when the source supports them."""

    def verify(self, headers: dict[str, str], body: bytes) -> bool: ...

    def to_events(self, body: bytes) -> list[dict[str, Any]]: ...


@runtime_checkable
class ActionExecutor(Protocol):
    """Write back to the source. Approval is required by the signature."""

    def execute(self, action: ApprovedAction) -> ActionResult: ...
