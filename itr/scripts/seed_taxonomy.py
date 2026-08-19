"""
Task 11 — seed the problem taxonomy into itr360.problem_taxonomy.

Primary source: ITR_POC_FeatureList_v2_3Aug2026.xlsx, searched at a
few likely locations under the repo root. If it isn't in this
workspace, falls back to a small hardcoded set — a loud warning is
printed, this is never a silent substitution — covering just enough
categories to unblock the E1-E9 test email corpus (license key
issues, VPN timeout, holiday-schedule query, invoice query).

The taxonomy must be seeded, not invented at runtime: a classifier
whose label space changes between runs cannot be evaluated.

Idempotent — safe to re-run. Upserts on (category, problem_class).
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.canonical.models import ProblemTaxonomy
from scout.config import settings

WORKBOOK_NAME = "ITR_POC_FeatureList_v2_3Aug2026.xlsx"

SEARCH_LOCATIONS = [
    ROOT,
    ROOT / "docs",
    ROOT / "data",
    ROOT.parent,
    ROOT.parent / "docs",
]

# (category, problem_class, description, example_phrases, default_priority)
FALLBACK_TAXONOMY = [
    (
        "licensing/activation",
        "license_key_invalid",
        "Customer's license key is rejected or shows invalid",
        ["my license key isn't working", "license key rejected", "invalid license key error"],
        "high",
    ),
    (
        "licensing/activation",
        "license_expired",
        "License has expired and needs renewal",
        ["license expired", "need to renew my license", "license ran out"],
        "medium",
    ),
    (
        "licensing/activation",
        "activation_failure",
        "Product activation fails after a valid key is entered",
        ["activation failed", "can't activate the product", "activation keeps failing"],
        "high",
    ),
    (
        "network/vpn",
        "vpn_connection_timeout",
        "VPN client times out during connection attempt",
        ["VPN keeps timing out", "can't connect to VPN", "VPN connection times out"],
        "high",
    ),
    (
        "network/vpn",
        "vpn_slow_performance",
        "VPN connects but throughput is degraded",
        ["VPN is really slow", "VPN connection is sluggish", "slow speeds over VPN"],
        "medium",
    ),
    (
        "network/vpn",
        "network_dns_failure",
        "DNS resolution failing over the VPN tunnel",
        ["can't resolve hostnames on VPN", "DNS not working over VPN", "sites won't load on VPN"],
        "medium",
    ),
    (
        "access/authentication",
        "password_reset",
        "User needs a password reset",
        ["forgot my password", "need a password reset", "can't remember my password"],
        "medium",
    ),
    (
        "access/authentication",
        "account_locked",
        "Account locked out after failed login attempts",
        ["my account is locked", "locked out after too many tries", "account lockout"],
        "high",
    ),
    (
        "access/authentication",
        "mfa_issue",
        "Multi-factor authentication code not accepted",
        ["MFA code not working", "two-factor code rejected", "can't get past MFA"],
        "high",
    ),
    (
        "billing/invoice",
        "invoice_inquiry",
        "Customer requesting a copy or explanation of an invoice",
        ["can I get a copy of my invoice", "question about my invoice", "need invoice details"],
        "low",
    ),
    (
        "billing/invoice",
        "payment_not_reflected",
        "Payment made but not reflected in the account",
        ["I paid but it's not showing", "payment not reflected", "balance still shows unpaid"],
        "medium",
    ),
    (
        "billing/invoice",
        "billing_discrepancy",
        "Charged amount does not match the expected amount",
        ["I was charged the wrong amount", "billing discrepancy", "invoice total looks wrong"],
        "medium",
    ),
    (
        "hr/policy",
        "holiday_schedule_inquiry",
        "Customer asking about the company holiday schedule or support availability",
        ["what are your holiday hours", "are you open on the holiday", "holiday schedule question"],
        "low",
    ),
    (
        "hr/policy",
        "general_policy_question",
        "General question about support policies or SLAs",
        ["what's your SLA", "what's your support policy", "how does support work"],
        "low",
    ),
]


def _find_workbook() -> Path | None:
    for location in SEARCH_LOCATIONS:
        candidate = location / WORKBOOK_NAME
        if candidate.exists():
            return candidate
    return None


def _load_from_workbook(path: Path) -> list[tuple]:
    import openpyxl

    rows: list[tuple] = []
    workbook = openpyxl.load_workbook(path, data_only=True)

    for sheet in workbook.worksheets:
        header: list[str] | None = None
        for raw_row in sheet.iter_rows(values_only=True):
            if header is None:
                header = [str(cell).strip().lower() if cell is not None else "" for cell in raw_row]
                continue
            if not any(raw_row):
                continue

            record = dict(zip(header, raw_row))
            category = str(record.get("category") or "").strip()
            problem_class = str(record.get("problem_class") or "").strip()
            if not category or not problem_class:
                continue

            description = str(record.get("description") or "").strip() or None
            raw_phrases = str(record.get("example_phrases") or "")
            example_phrases = [p.strip() for p in re.split(r"[;,|]", raw_phrases) if p.strip()]
            default_priority = str(record.get("default_priority") or "").strip() or None

            rows.append((category, problem_class, description, example_phrases, default_priority))

    return rows


def _upsert(
    session: Session,
    category: str,
    problem_class: str,
    description: str | None,
    example_phrases: list[str],
    default_priority: str | None,
) -> bool:
    """Upsert one row; returns True if inserted, False if an existing row was updated."""
    row = session.execute(
        select(ProblemTaxonomy).where(
            ProblemTaxonomy.category == category,
            ProblemTaxonomy.problem_class == problem_class,
        )
    ).scalar_one_or_none()

    if row is None:
        row = ProblemTaxonomy(
            id=uuid.uuid4(),
            category=category,
            problem_class=problem_class,
            description=description,
            example_phrases=example_phrases or None,
            default_priority=default_priority,
        )
        session.add(row)
        return True

    row.description = description
    row.example_phrases = example_phrases or None
    row.default_priority = default_priority
    return False


def main() -> int:
    workbook_path = _find_workbook()

    if workbook_path is not None:
        print(f"Loading taxonomy from {workbook_path}")
        rows = _load_from_workbook(workbook_path)
        used_fallback = False
    else:
        rows = FALLBACK_TAXONOMY
        used_fallback = True

    engine = create_engine(settings.database_url, future=True)
    inserted = 0
    updated = 0

    with Session(engine) as session:
        for category, problem_class, description, example_phrases, default_priority in rows:
            if _upsert(session, category, problem_class, description, example_phrases, default_priority):
                inserted += 1
            else:
                updated += 1
        session.commit()

    categories = sorted({row[0] for row in rows})
    print()
    print(
        f"Upserted {len(rows)} problem classes across {len(categories)} categories "
        f"({inserted} inserted, {updated} updated)."
    )

    if used_fallback:
        banner = "=" * 78
        print()
        print(banner)
        print(f"WARNING: {WORKBOOK_NAME} not found in this workspace.")
        print(
            f"Loaded a PARTIAL FALLBACK taxonomy only ({len(rows)} problem classes, "
            f"{len(categories)} categories) -"
        )
        print("NOT the full 10-category / 100-problem-class taxonomy. This is enough")
        print("to unblock the E1-E9 test email corpus and nothing more. Load the real")
        print(f"workbook ({WORKBOOK_NAME}) and re-run this script once it's available.")
        print(banner)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
