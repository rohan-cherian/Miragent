"""Postgres store reading live ``src_workday`` dump data."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

_WORKERS_SQL = """
SELECT
    w.worker_wid,
    w.employee_id_display,
    w.legal_first_name,
    w.legal_last_name,
    w.work_email,
    w.original_hire_date,
    w.is_active,
    wpd.business_title,
    wpd.employment_status,
    so.sup_org_name,
    loc.location_name,
    mgr.employee_id_display AS manager_employee_id
FROM src_workday.worker w
LEFT JOIN src_workday.worker_position_data wpd
    ON wpd.worker_wid = w.worker_wid AND wpd.is_current
LEFT JOIN src_workday.supervisory_organization so
    ON so.sup_org_wid = wpd.sup_org_wid
LEFT JOIN src_workday.location loc
    ON loc.location_wid = wpd.location_wid
LEFT JOIN src_workday.worker mgr
    ON mgr.worker_wid = wpd.manager_worker_wid
ORDER BY w.employee_id_display
LIMIT %s OFFSET %s
"""

_WORKERS_COUNT_SQL = "SELECT COUNT(*) AS n FROM src_workday.worker"

_ORGS_SQL = """
SELECT
    org_wid,
    org_code,
    org_name,
    superior_org_wid,
    cost_center_code,
    is_active
FROM src_workday.organization
ORDER BY org_code
LIMIT %s OFFSET %s
"""

_ORGS_COUNT_SQL = "SELECT COUNT(*) AS n FROM src_workday.organization"

_SCHEMA_CHECK_SQL = """
SELECT 1 AS ok
FROM information_schema.tables
WHERE table_schema = 'src_workday' AND table_name = 'worker'
"""


class PostgresWorkdayStore:
    """Read-only store over ``src_workday`` (Sutej dump)."""

    backend_name = "postgres"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()
        self._assert_schema()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def _assert_schema(self) -> None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA_CHECK_SQL)
                    if cur.fetchone() is None:
                        raise RuntimeError(
                            "src_workday.worker missing — load "
                            "schema/dump-ITR_PORTAL-202608071347.sql first "
                            "(poetry run python scripts/load_workday_postgres.py)"
                        )
        except psycopg.Error as exc:
            raise RuntimeError(
                f"Cannot connect to Workday Postgres: {exc}"
            ) from exc

    def list_workers(self, *, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_WORKERS_COUNT_SQL)
                total = int(cur.fetchone()["n"])
                cur.execute(_WORKERS_SQL, (limit, offset))
                rows = [dict(r) for r in cur.fetchall()]
        return rows, total

    def list_organizations(
        self, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_ORGS_COUNT_SQL)
                total = int(cur.fetchone()["n"])
                cur.execute(_ORGS_SQL, (limit, offset))
                rows = [dict(r) for r in cur.fetchall()]
        return rows, total
