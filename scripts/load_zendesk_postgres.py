"""
Load schema/001_src_zendesk_schema.sql into Postgres for the Zendesk emulator.

Strips pg_dump \\restrict / \\unrestrict lines (PG17+) so the dump loads on PG16.
Requires ``psql`` on PATH, or falls back to chunked execution via psycopg.

Usage:
  poetry run python scripts/load_zendesk_postgres.py
  poetry run python scripts/load_zendesk_postgres.py --dsn postgresql://...
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
DEFAULT_DUMP = ROOT / "schema" / "001_src_zendesk_schema.sql"
DEFAULT_DSN = (
    os.getenv("ZENDESK_DATABASE_URL")
    or "postgresql://zendesk_admin:zendesk_dev@localhost:5433/zendesk_agent"
)


def _sanitize_dump(src: Path) -> str:
    text = src.read_text(encoding="utf-8", errors="replace")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("\\restrict") or stripped.startswith("\\unrestrict"):
            continue
        # Dump was taken as role "postgres"; our compose user is zendesk_admin.
        if "OWNER TO postgres" in line:
            line = line.replace("OWNER TO postgres", "OWNER TO CURRENT_USER")
        lines.append(line)
    return "\n".join(lines) + "\n"


def _load_with_psql(dsn: str, sql_path: Path) -> None:
    cmd = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)]
    print("Loading via psql…")
    subprocess.run(cmd, check=True)


def _load_with_psycopg(dsn: str, sql_text: str) -> None:
    import psycopg

    print("psql not found — loading via psycopg (may take a few minutes)…")
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=DEFAULT_DSN, help="Postgres connection URL")
    parser.add_argument(
        "--dump",
        type=Path,
        default=DEFAULT_DUMP,
        help="Path to src_zendesk SQL dump",
    )
    args = parser.parse_args()

    if not args.dump.is_file():
        print(f"Dump not found: {args.dump}", file=sys.stderr)
        return 1

    print(f"Dump: {args.dump} ({args.dump.stat().st_size / 1e6:.1f} MB)")
    print(f"DSN:  {args.dsn}")
    sanitized = _sanitize_dump(args.dump)

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sql",
        delete=False,
    ) as tmp:
        tmp.write(sanitized)
        tmp_path = Path(tmp.name)

    try:
        if shutil.which("psql"):
            _load_with_psql(args.dsn, tmp_path)
        else:
            _load_with_psycopg(args.dsn, sanitized)
    except Exception as exc:
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        tmp_path.unlink(missing_ok=True)

    # Verify
    import psycopg

    with psycopg.connect(args.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM src_zendesk.tickets")
            tickets = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM src_zendesk.users")
            users = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM src_zendesk.organizations")
            orgs = cur.fetchone()[0]

    print(f"Loaded OK — tickets={tickets}, users={users}, organizations={orgs}")
    print("Set ZENDESK_DATABASE_URL and start the emulator to serve this data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
