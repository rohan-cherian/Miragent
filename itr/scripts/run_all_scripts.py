"""
Run the Gmail scripts folder smoke suite in one go.

Not every script can (or should) run unattended:
  - gmail_oauth_login.py     opens a browser — skip unless --include-login
  - gmail_sync_loop.py       never exits — skipped (use gmail_sync_once instead)
  - gmail_send_test.py       needs --to — skip unless --send-to EMAIL
  - gmail_watch_register.py  needs a Pub/Sub topic — skip unless --include-watch

Default order (safe / non-interactive):
  1. load_gmail_schema.py
  2. minio_smoke_test.py
  3. gmail_read_sample.py --max 3
  4. gmail_sync_once.py --max 20 --list
  5. export_fixtures.py --limit 20   (optional: --skip-export)

Usage:
  poetry run python scripts/run_all_scripts.py
  poetry run python scripts/run_all_scripts.py --send-to you@example.com
  poetry run python scripts/run_all_scripts.py --skip-export --max 5
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@dataclass
class StepResult:
    name: str
    status: str  # passed | failed | skipped
    elapsed_s: float = 0.0
    detail: str = ""
    output: str = ""


@dataclass
class SuiteReport:
    results: list[StepResult] = field(default_factory=list)

    def add(self, result: StepResult) -> None:
        self.results.append(result)

    def print_summary(self) -> int:
        print("\n" + "=" * 60)
        print("Gmail scripts smoke suite")
        print("=" * 60)
        for r in self.results:
            line = f"  [{r.status.upper():7}] {r.name}"
            if r.status != "skipped":
                line += f"  ({r.elapsed_s:.1f}s)"
            if r.detail:
                line += f"  — {r.detail}"
            print(line)
        failed = sum(1 for r in self.results if r.status == "failed")
        passed = sum(1 for r in self.results if r.status == "passed")
        skipped = sum(1 for r in self.results if r.status == "skipped")
        print("-" * 60)
        print(f"  passed={passed}  failed={failed}  skipped={skipped}")
        print("=" * 60)
        return 1 if failed else 0


def _run(name: str, args: list[str], *, timeout: int | None = 600) -> StepResult:
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    print(f"\n>>> {' '.join(cmd)}")
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        print(out)
        return StepResult(
            name=name,
            status="failed",
            elapsed_s=time.perf_counter() - started,
            detail=f"timed out after {timeout}s",
            output=out,
        )

    combined = ""
    if proc.stdout:
        combined += proc.stdout
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if proc.stderr:
        combined += proc.stderr
        print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", file=sys.stderr)

    elapsed = time.perf_counter() - started
    if proc.returncode == 0:
        return StepResult(name=name, status="passed", elapsed_s=elapsed, output=combined)
    return StepResult(
        name=name,
        status="failed",
        elapsed_s=elapsed,
        detail=f"exit {proc.returncode}",
        output=combined,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=20, help="Max messages for sync_once / read_sample")
    parser.add_argument("--skip-export", action="store_true", help="Skip export_fixtures.py")
    parser.add_argument("--skip-sync", action="store_true", help="Skip gmail_sync_once.py")
    parser.add_argument("--skip-read", action="store_true", help="Skip gmail_read_sample.py")
    parser.add_argument(
        "--send-to",
        default="",
        help="If set, also run gmail_send_test.py --to this address",
    )
    parser.add_argument(
        "--include-login",
        action="store_true",
        help="Also run gmail_oauth_login.py (opens browser; interactive)",
    )
    parser.add_argument(
        "--include-watch",
        action="store_true",
        help="Also run gmail_watch_register.py (needs GMAIL_PUBSUB_TOPIC)",
    )
    parser.add_argument(
        "--include-loop",
        action="store_true",
        help="Also run gmail_sync_loop.py for --loop-seconds (default 15) then stop",
    )
    parser.add_argument(
        "--loop-seconds",
        type=int,
        default=15,
        help="How long to leave the loop running when --include-loop is set",
    )
    args = parser.parse_args()

    report = SuiteReport()

    if not args.include_login:
        report.add(
            StepResult(
                name="gmail_oauth_login.py",
                status="skipped",
                detail="interactive browser login (use --include-login)",
            )
        )
    else:
        # No timeout — user may take a while in the browser.
        report.add(_run("gmail_oauth_login.py", [], timeout=None))

    report.add(_run("load_gmail_schema.py", []))
    report.add(_run("minio_smoke_test.py", []))

    if args.skip_read:
        report.add(StepResult("gmail_read_sample.py", "skipped", detail="--skip-read"))
    else:
        report.add(_run("gmail_read_sample.py", ["--max", str(min(args.max, 5))]))

    if args.send_to:
        report.add(
            _run(
                "gmail_send_test.py",
                ["--to", args.send_to, "--subject", "scripts smoke suite", "--body", "ok"],
            )
        )
    else:
        report.add(
            StepResult(
                name="gmail_send_test.py",
                status="skipped",
                detail="needs recipient (use --send-to EMAIL)",
            )
        )

    if args.skip_sync:
        report.add(StepResult("gmail_sync_once.py", "skipped", detail="--skip-sync"))
    else:
        report.add(
            _run(
                "gmail_sync_once.py",
                ["--max", str(args.max), "--list"],
                timeout=900,
            )
        )

    if args.skip_export:
        report.add(StepResult("export_fixtures.py", "skipped", detail="--skip-export"))
    else:
        report.add(
            _run(
                "export_fixtures.py",
                ["--limit", str(args.max)],
                timeout=600,
            )
        )

    if args.include_watch:
        report.add(_run("gmail_watch_register.py", [], timeout=120))
    else:
        report.add(
            StepResult(
                name="gmail_watch_register.py",
                status="skipped",
                detail="needs Pub/Sub topic (use --include-watch)",
            )
        )

    if args.include_loop:
        cmd = [
            sys.executable,
            str(SCRIPTS / "gmail_sync_loop.py"),
            "--interval",
            "10",
            "--max",
            str(args.max),
        ]
        print(f"\n>>> {' '.join(cmd)}  (kill after {args.loop_seconds}s)")
        started = time.perf_counter()
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            out, _ = proc.communicate(timeout=args.loop_seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                out, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        report.add(
            StepResult(
                name="gmail_sync_loop.py",
                status="passed",
                elapsed_s=time.perf_counter() - started,
                detail=f"ran ~{args.loop_seconds}s then stopped",
                output=out or "",
            )
        )
    else:
        report.add(
            StepResult(
                name="gmail_sync_loop.py",
                status="skipped",
                detail="infinite poller; covered by sync_once (use --include-loop)",
            )
        )

    return report.print_summary()


if __name__ == "__main__":
    raise SystemExit(main())
