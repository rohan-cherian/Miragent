"""
Task 16 — reconciliation: reconcile(source_system) -> Reconciliation.

Proves the translation layer isn't quietly dropping records — the
failure mode nobody notices until someone asks why a message is
missing. Compares row counts (and a sampled checksum) between a
src_<source_system> table and itr360.message rows tagged with that
source_system. Anything less than 100% completeness is a FAILURE, not
a warning — no tolerance threshold here, by design.

ASSUMPTION: src_gmail (Rohan's side, Tasks 5-9) may not exist yet in
this workspace. reconcile("gmail") will raise a natural "relation does
not exist" error at the source-count/checksum step if so — expected,
not something this module papers over. No src_gmail.attachment-style
table exists anywhere in this codebase yet, so 'attachment' is a TODO,
not reconciled here.

Must never import scout.gmail, scout.connectors, or googleapiclient
(tests/test_layering.py, Task 4).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from scout.canonical.models import Message
from scout.config import settings
from scout.governance.audit import write as audit_write

TENANT_ID = uuid.UUID(str(settings.tenant_id))

# Object types reconciled per source_system.
# TODO: add 'attachment' once a src_gmail.attachment-style table
# exists anywhere in this codebase to reconcile against — none does
# yet.
_OBJECTS_BY_SOURCE: dict[str, list[str]] = {
    "gmail": ["message"],
}

_SAMPLE_FRACTION = 0.10

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, future=True)
    return _engine


@dataclass
class ObjectDelta:
    object_name: str
    source_count: int
    canonical_count: int
    delta: int
    checksum_ok: bool


@dataclass
class Reconciliation:
    source_system: str
    objects: list[ObjectDelta] = field(default_factory=list)
    completeness_pct: float = 100.0
    passed: bool = True


def _sample_size(total: int) -> int:
    if total <= 0:
        return 0
    return max(1, round(total * _SAMPLE_FRACTION))


def _checksum(pairs: list[tuple]) -> str:
    """Stable checksum over an (id, timestamp) pair set, order-independent."""
    normalized = sorted(f"{a}:{b}" for a, b in pairs)
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()


def _reconcile_message(session: Session, source_system: str) -> ObjectDelta:
    source_table = f"src_{source_system}.message"

    source_count = session.execute(text(f"SELECT count(*) FROM {source_table}")).scalar_one()

    canonical_count = session.execute(
        select(func.count()).select_from(Message).where(Message.source_system == source_system)
    ).scalar_one()

    delta = source_count - canonical_count

    sample_n = _sample_size(source_count)
    checksum_ok = True

    if sample_n > 0:
        source_sample = session.execute(
            text(f"SELECT message_id, internal_date_ms FROM {source_table} ORDER BY random() LIMIT :n"),
            {"n": sample_n},
        ).all()
        source_checksum = _checksum([(row[0], row[1]) for row in source_sample])

        sampled_ids = [str(row[0]) for row in source_sample]
        canonical_rows = session.execute(
            select(Message.src_message_id, Message.sent_at).where(
                Message.source_system == source_system,
                Message.external_id.in_(sampled_ids),
            )
        ).all()
        # sent_at is a tz-aware datetime; normalize to epoch ms to compare
        # against the source side's internal_date_ms on equal footing.
        canonical_checksum = _checksum(
            [(row.src_message_id, int(row.sent_at.timestamp() * 1000)) for row in canonical_rows]
        )

        checksum_ok = source_checksum == canonical_checksum

    return ObjectDelta(
        object_name="message",
        source_count=source_count,
        canonical_count=canonical_count,
        delta=delta,
        checksum_ok=checksum_ok,
    )


_RECONCILERS = {
    "message": _reconcile_message,
}


def reconcile(source_system: str) -> Reconciliation:
    """Compare source vs. canonical row counts (and a sampled checksum)
    for every object type configured for source_system. Persists the
    result via scout.governance.audit.write() (category="scan",
    action="reconciliation") rather than a dedicated table — Task 10's
    schema has none, and adding one is out of this task's scope.
    """
    object_names = _OBJECTS_BY_SOURCE.get(source_system, [])
    engine = _get_engine()

    deltas: list[ObjectDelta] = []
    with Session(engine) as session:
        for object_name in object_names:
            reconciler = _RECONCILERS[object_name]
            deltas.append(reconciler(session, source_system))

    total_source = sum(d.source_count for d in deltas)
    total_canonical = sum(d.canonical_count for d in deltas)

    completeness_pct = 100.0 if total_source == 0 else (total_canonical / total_source) * 100
    passed = completeness_pct == 100.0 and all(d.checksum_ok for d in deltas)

    result = Reconciliation(
        source_system=source_system,
        objects=deltas,
        completeness_pct=completeness_pct,
        passed=passed,
    )

    audit_write(
        actor="system",
        action="reconciliation",
        category="scan",
        outputs={
            "source_system": result.source_system,
            "objects": [
                {
                    "object_name": d.object_name,
                    "source_count": d.source_count,
                    "canonical_count": d.canonical_count,
                    "delta": d.delta,
                    "checksum_ok": d.checksum_ok,
                }
                for d in result.objects
            ],
            "completeness_pct": result.completeness_pct,
            "passed": result.passed,
        },
    )

    return result
