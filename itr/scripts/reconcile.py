"""
Task 16 — CLI wrapper for scout.canonical.reconcile.reconcile().

Usage:
  poetry run python scripts/reconcile.py --source gmail

Exits non-zero if the reconciliation did not pass — anything less
than 100% completeness (or a checksum mismatch) is a FAILURE, not a
warning.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scout.canonical.reconcile import Reconciliation, reconcile


def _print_report(result: Reconciliation) -> None:
    header = f"{'OBJECT':<15}{'SOURCE':>12}{'CANONICAL':>12}{'DELTA':>10}{'CHECKSUM':>12}"
    print(header)
    print("-" * len(header))

    for obj in result.objects:
        checksum_label = "OK" if obj.checksum_ok else "MISMATCH"
        print(
            f"{obj.object_name:<15}{obj.source_count:>12}{obj.canonical_count:>12}"
            f"{obj.delta:>10}{checksum_label:>12}"
        )

    print()
    print(f"COMPLETENESS: {result.completeness_pct:.1f}%")
    print(f"RESULT: {'PASS' if result.passed else 'FAIL'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Source system to reconcile, e.g. gmail")
    args = parser.parse_args()

    result = reconcile(args.source)
    _print_report(result)

    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
