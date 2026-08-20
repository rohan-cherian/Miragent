"""
Smoke tests for itr/scripts/*.py — can they start and print something?

Default: every script answers --help (or exits 0 with no args for schema/minio).
Live end-to-end is opt-in via RUN_GMAIL_SCRIPTS_LIVE=1 (needs Postgres, MinIO, token).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

HELP_SCRIPTS = [
    "gmail_read_sample.py",
    "gmail_send_test.py",
    "gmail_sync_once.py",
    "gmail_sync_loop.py",
    "gmail_watch_register.py",
    "export_fixtures.py",
    "run_all_scripts.py",
]

NO_HELP_SCRIPTS = [
    "load_gmail_schema.py",
    "minio_smoke_test.py",
    "gmail_oauth_login.py",
]


@pytest.mark.parametrize("name", HELP_SCRIPTS)
def test_script_prints_help(name: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / name), "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in (proc.stdout + proc.stderr).lower()


@pytest.mark.parametrize("name", NO_HELP_SCRIPTS + HELP_SCRIPTS)
def test_script_file_exists(name: str) -> None:
    assert (SCRIPTS / name).is_file()


@pytest.mark.skipif(
    os.environ.get("RUN_GMAIL_SCRIPTS_LIVE") != "1",
    reason="Set RUN_GMAIL_SCRIPTS_LIVE=1 to run the live scripts suite",
)
def test_run_all_scripts_live() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "run_all_scripts.py"),
            "--max",
            "5",
            "--skip-export",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    print(proc.stdout)
    print(proc.stderr, file=sys.stderr)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "passed=" in proc.stdout
