"""Workday store protocol — workers + orgs for RaaS extracts."""

from __future__ import annotations

from typing import Any, Protocol


class WorkdayDataStore(Protocol):
    """Backend that supplies rows for report extracts."""

    backend_name: str

    def list_workers(self, *, offset: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Return (page_rows, total_count). Rows use internal field names."""
        ...

    def list_organizations(
        self, *, offset: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (page_rows, total_count) for organizations."""
        ...
