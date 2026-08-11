"""
Load schema/dump-ITR_PORTAL-202608071347.sql into Postgres for the Workday emulator.

Strips pg_dump \\restrict / \\unrestrict lines and remaps OWNER TO postgres.
Requires ``psql`` on PATH for the ~230 MB dump (psycopg fallback is unsupported
for this size).

Usage:
  poetry run python scripts/load_workday_postgres.py
  poetry run python scripts/load_workday_postgres.py --dsn postgresql://...
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DUMP = ROOT / "schema" / "dump-ITR_PORTAL-202608071347.sql"
DEFAULT_DSN = (
    os.getenv("WORKDAY_DATABASE_URL")
    or os.getenv("ZENDESK_DATABASE_URL")
    or "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
)


def _sanitize_to_file(src: Path, dest: Path) -> None:
    """Stream-sanitize so we do not hold ~230 MB twice in RAM."""
    with src.open("r", encoding="utf-8", errors="replace") as inn, dest.open(
        "w", encoding="utf-8", newline="\n"
    ) as out:
        for line in inn:
            stripped = line.strip()
            if stripped.startswith("\\restrict") or stripped.startswith("\\unrestrict"):
                continue
            if "OWNER TO postgres" in line:
                line = line.replace("OWNER TO postgres", "OWNER TO CURRENT_USER")
            out.write(line)


def _load_with_psql(dsn: str, sql_path: Path) -> None:
    cmd = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)]
    print("Loading via psql (this can take several minutes)…")
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="Postgres connection URL")
    parser.add_argument(
        "--dump",
        type=Path,
        default=DEFAULT_DUMP,
        help="Path to src_workday SQL dump",
    )
    args = parser.parse_args()

    if not args.dump.is_file():
        print(f"Dump not found: {args.dump}", file=sys.stderr)
        return 1

    if not shutil.which("psql"):
        print(
            "psql is required to load the Workday dump (~230 MB). "
            "Install PostgreSQL client tools and retry.",
            file=sys.stderr,
        )
        return 1

    print(f"Dump: {args.dump} ({args.dump.stat().st_size / 1e6:.1f} MB)")
    print(f"DSN:  {args.dsn}")

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sql",
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        print("Sanitizing dump…")
        _sanitize_to_file(args.dump, tmp_path)
        _load_with_psql(args.dsn, tmp_path)
    except Exception as exc:
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        tmp_path.unlink(missing_ok=True)

    import psycopg

    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM src_workday.worker")
            workers = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM src_workday.organization")
            orgs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM src_workday.job_requisition")
            reqs = cur.fetchone()[0]

    print(f"Loaded OK — workers={workers}, organizations={orgs}, job_requisitions={reqs}")
    print("Set WORKDAY_DATABASE_URL (or ZENDESK_DATABASE_URL) and start the emulator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
