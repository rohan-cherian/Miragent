"""
Manual smoke test for scout/governance/audit.py.

This is NOT the formal pytest suite (that's tests/test_audit_completeness.py,
a separate later task). This is a standalone script — run directly with
`poetry run python scripts/manual_test_audit.py` — that exercises
write(), list(), and timeline() and prints OK/FAIL lines instead of using
pytest assertions. It talks to whatever database
scout.config.settings.database_url points to.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.governance.audit import list as audit_list
from scout.governance.audit import timeline, write


def test_valid_write() -> None:
    try:
        row_id = write(actor="tausif", action="test_event", category="system")
        print(f"OK - inserted row id: {row_id}")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")


def test_invalid_category() -> None:
    try:
        write(actor="x", action="y", category="not_a_real_category")
        print("FAIL - no exception raised, this is a bug")
    except ValueError as exc:
        print(f"OK - correctly raised ValueError: {exc}")
    except Exception as exc:
        print(f"FAIL - wrong exception type: {type(exc).__name__}: {exc}")


def test_list_and_timeline() -> None:
    try:
        rows = audit_list(category="system")
        print(f"OK - list() returned {len(rows)} rows")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")

    try:
        rows = timeline(case_id=uuid.uuid4())
        print(f"OK - timeline() returned {len(rows)} rows")
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    print("--- Test 1: write() with a valid category ---")
    test_valid_write()

    print()
    print("--- Test 2: write() with an invalid category ---")
    test_invalid_category()

    print()
    print("--- Test 3: list() and timeline() ---")
    test_list_and_timeline()

    print()
    print("Done.")
