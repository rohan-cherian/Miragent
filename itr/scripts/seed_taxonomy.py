"""
Task 11 (Task 0 revision) — seed the problem taxonomy into itr360.problem_taxonomy.

Primary source: data/taxonomy.json, produced by scripts/extract_taxonomy.py
from the real workbook (ITR_SyntheticData_GenerationClasses_v1_30July2026.xlsx)
— the real 10-category / 100-problem-class taxonomy. If that file isn't
present, falls back to a small hardcoded 17-class set — a loud warning is
printed, this is never a silent substitution — covering just enough
categories to unblock the E1-E9 test email corpus.

THE ONE GOVERNING DECISION: the real taxonomy REPLACES the fallback
vocabulary, it does not coexist with it. A mixed label space would let the
classifier legally answer either "CFG-09" or "activation_failure" for the
same email, which makes its output unmeasurable. So whenever the real
taxonomy.json source is used, this script also retires the old fallback
classes still sitting in the table from earlier runs (see _retire_fallback).

problem_taxonomy has 6 columns and taxonomy.json carries more than that:
  - category       = the 3-letter workbook code ("ACC") — stable, FK-friendly.
  - problem_class   = the class_id ("ACC-01") — stable key.
  - description     = "{name} — {description}", so the human-readable name
                      still renders in triage prompts even though the model
                      has no separate name column.
  - example_phrases = from data/example_phrases.json via taxonomy.json.
  - default_priority = mapped through _PRIORITY_MAP (see below).
  entry_tier / disposition / kb_article_exists / csat_risk / complexity stay
  JSON-only — nothing downstream reads them from Postgres today. In
  particular the Y/N KB-article-eligibility flag lives ONLY in
  data/taxonomy.json, not in this table.

Priority mapping
-----------------
The workbook's Default priority values are low | normal | high | urgent.
triage.compute_priority()'s ladder (scout/agents/triage.py PRIORITY_LADDER)
is low | medium | high | critical. An off-ladder value silently degrades to
"medium" in that function, which would flatten every "urgent" class down to
"medium" — so the mapping happens here, once, explicitly:
  low -> low, normal -> medium, high -> high, urgent -> critical

The taxonomy must be seeded, not invented at runtime: a classifier
whose label space changes between runs cannot be evaluated.

Idempotent — safe to re-run. Upserts on (category, problem_class).
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scout.canonical.models import KBArticle, ProblemTaxonomy
from scout.config import settings

TAXONOMY_JSON_PATH = ROOT / "data" / "taxonomy.json"
EXTRACT_SCRIPT_NAME = "scripts/extract_taxonomy.py"

# workbook default_priority -> triage.compute_priority()'s PRIORITY_LADDER.
# See module docstring "Priority mapping" for why this exists.
_PRIORITY_MAP = {
    "low": "low",
    "normal": "medium",
    "high": "high",
    "urgent": "critical",
}

# The old fallback's category namespace. Any problem_taxonomy row still
# carrying one of these once the real taxonomy has loaded is retired —
# see _retire_fallback().
OLD_FALLBACK_CATEGORIES = {
    "licensing/activation",
    "network/vpn",
    "access/authentication",
    "billing/invoice",
    "hr/policy",
    "security/alerts",
}

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
    # ── security/alerts ───────────────────────────────────────────────────
    # USER-REPORTED security concerns: a person writing in because they saw
    # an alert, noticed odd activity, or received a suspicious email and
    # want it looked at. These are genuine support tickets.
    #
    # This category is NOT a classification target for E9 (the automated
    # Google "new device sign-in" security notification in the test corpus).
    # E9 is a system notification, not a support request, and must be
    # DROPPED upstream by Task 8's filters.py (Rohan) and logged in
    # raw_ingest.runs.errors — that is exit criterion 12, and nothing here
    # closes it. Letting E9 reach triage and land in this category would be
    # the exact failure the Task 8 rationale warns about ("every Google
    # security alert becomes a case").
    (
        "security/alerts",
        "new_device_signin",
        "Security alert for sign-in from a new or unrecognized device/location",
        [
            "I just got a new device sign-in alert I don't recognize",
            "there's an alert about a sign-in from a location I've never been to",
            "got a notification that someone signed in from a new device, was that you",
        ],
        "high",
    ),
    (
        "security/alerts",
        "suspicious_account_activity",
        "Unusual or suspicious activity detected on the account",
        [
            "there's activity on my account I didn't do",
            "I'm seeing logins and changes I don't recognise",
            "I think someone else is using my account",
        ],
        "high",
    ),
    (
        "security/alerts",
        "phishing_email_report",
        "User reporting a suspected phishing or spoofed email",
        [
            "I got an email that looks like it's from you but the link is weird",
            "is this email from support real or phishing",
            "reporting a suspicious email pretending to be your billing team",
        ],
        "medium",
    ),
]


def _load_from_taxonomy_json(path: Path) -> list[tuple]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[tuple] = []
    for entry in data["classes"]:
        category = entry["category"]
        problem_class = entry["class_id"]
        name = (entry.get("name") or "").strip()
        raw_description = (entry.get("description") or "").strip()
        description = f"{name} — {raw_description}" if name else (raw_description or None)
        example_phrases = list(entry.get("example_phrases") or [])
        raw_priority = (entry.get("default_priority") or "").strip().lower()
        default_priority = _PRIORITY_MAP.get(raw_priority)
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


def _retire_fallback(session: Session) -> int:
    """Delete any problem_taxonomy row still in the old fallback's category
    namespace. FK order matters: itr360.kb_article references
    (category, problem_class), so kb_article rows for a retired class are
    deleted first, along with their Qdrant points, then the taxonomy row.

    Returns the number of problem_taxonomy rows deleted.
    """
    stale_taxonomy = session.execute(
        select(ProblemTaxonomy).where(ProblemTaxonomy.category.in_(OLD_FALLBACK_CATEGORIES))
    ).scalars().all()
    if not stale_taxonomy:
        return 0

    stale_articles = session.execute(
        select(KBArticle).where(KBArticle.category.in_(OLD_FALLBACK_CATEGORIES))
    ).scalars().all()

    if stale_articles:
        _delete_kb_qdrant_points([article.id for article in stale_articles])
        for article in stale_articles:
            session.delete(article)
        session.flush()
        print(
            f"Deleted {len(stale_articles)} fallback kb_article row(s) "
            f"(and their Qdrant points) ahead of taxonomy retirement."
        )

    for row in stale_taxonomy:
        print(f"  retiring fallback class: {row.category} / {row.problem_class}")
        session.delete(row)

    return len(stale_taxonomy)


def _delete_kb_qdrant_points(article_ids: list[uuid.UUID]) -> None:
    """Best-effort cleanup of the Qdrant points for retired kb_article rows.

    kb_index point ids are deterministic uuid5(article_id, offsets) — there
    is no reverse index from article id to point id without recomputing
    chunk offsets, so this deletes by payload filter
    (source_system=kb_article AND kb_article_id in <ids>) instead. If Qdrant
    is unreachable this is NOT fatal: stale points simply expire on the next
    full scripts/seed_kb.py / index_all_kb_articles() re-index (upsert is
    idempotent on point id, but an orphaned point for a deleted article is
    never overwritten by a re-index — this filtered delete is what actually
    removes it. A failure here is reported and skipped, not raised.
    """
    if not article_ids:
        return
    try:
        from qdrant_client import QdrantClient, models

        client = QdrantClient(url=settings.qdrant_url)
        if not client.collection_exists(settings.qdrant_collection_name):
            return
        client.delete(
            collection_name=settings.qdrant_collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_system", match=models.MatchValue(value="kb_article")
                        ),
                        models.FieldCondition(
                            key="kb_article_id",
                            match=models.MatchAny(any=[str(a) for a in article_ids]),
                        ),
                    ]
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; Postgres cleanup still proceeds
        print(
            f"  WARNING: could not delete Qdrant points for retired KB articles "
            f"({type(exc).__name__}: {exc}) — they will be orphaned until the "
            f"collection is fully re-indexed."
        )


def main() -> int:
    used_fallback = not TAXONOMY_JSON_PATH.exists()

    if not used_fallback:
        print(f"Loading taxonomy from {TAXONOMY_JSON_PATH}")
        rows = _load_from_taxonomy_json(TAXONOMY_JSON_PATH)
    else:
        rows = FALLBACK_TAXONOMY

    engine = create_engine(settings.database_url, future=True)
    inserted = 0
    updated = 0
    retired = 0

    with Session(engine) as session:
        for category, problem_class, description, example_phrases, default_priority in rows:
            if _upsert(session, category, problem_class, description, example_phrases, default_priority):
                inserted += 1
            else:
                updated += 1

        if not used_fallback:
            retired = _retire_fallback(session)

        session.commit()

    categories = sorted({row[0] for row in rows})
    print()
    print(
        f"Upserted {len(rows)} problem classes across {len(categories)} categories "
        f"({inserted} inserted, {updated} updated)."
    )
    if not used_fallback:
        print(f"Retired {retired} fallback problem_taxonomy row(s).")

    if used_fallback:
        banner = "=" * 78
        print()
        print(banner)
        print(f"WARNING: {TAXONOMY_JSON_PATH.relative_to(ROOT)} not found in this workspace.")
        print(
            f"Loaded a PARTIAL FALLBACK taxonomy only ({len(rows)} problem classes, "
            f"{len(categories)} categories) -"
        )
        print("NOT the full 10-category / 100-problem-class taxonomy. This is enough")
        print("to unblock the E1-E8 test email corpus and nothing more (E9, the Google")
        print("security alert, is dropped upstream by Task 8 and never triaged).")
        print(f"Run `poetry run python {EXTRACT_SCRIPT_NAME}` first (it reads the real")
        print("workbook, data/ITR_SyntheticData_GenerationClasses_v1_30July2026.xlsx,")
        print(f"and writes {TAXONOMY_JSON_PATH.relative_to(ROOT)}), then re-run this script.")
        print(banner)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
