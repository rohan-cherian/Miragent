"""
W1-SRC-06 — Workday Report-as-a-Service emulator.

Serves RaaS-style extract endpoints with **two deliberate column-name variants**
for the same underlying workers/orgs so normalisation can be exercised.
"""

from scout.emulators.workday.app import create_workday_app
from scout.emulators.workday.store import WorkdayStore

__all__ = ["WorkdayStore", "create_workday_app"]
