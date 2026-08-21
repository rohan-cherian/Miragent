"""
Seed the T15 "E4" near-duplicate so the dedup-link rule is demonstrated on
real pipeline code.

The live mailbox contains E1-E3 (one thread, three messages) but no E4: nobody
happened to open a second, separately-threaded ticket about the same problem
inside the dedup window. Correlation rule 4 and Case.related_case_ids are real
and unit-covered, but nothing in the corpus exercises them end to end, so the
acceptance check for "duplicates LINKED, never merged" had no evidence to read.

E4 is therefore seeded deliberately and flagged is_synthetic, rather than left
to be satisfied by whatever debris a failed test run happened to leave behind
(which is exactly what used to happen, and what made the check look green).

It is built to fall PAST the earlier rules, not into them:
  * a brand-new thread  -> rule 1 (thread match) cannot fire
  * no In-Reply-To/References -> rule 2 (reply match) cannot fire
  * sent inside DUP_WINDOW_HOURS of the source case -> rule 4 is reachable
  * subject reworded but >0.85 similar -> rule 4 actually matches

Idempotent: re-running replaces the previous seed rather than stacking copies.

Usage:  poetry run python scripts/seed_e4_duplicate.py
Then:   poetry run python scripts/ingest_canonical.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from scout.canonical import correlation  # noqa: E402
from scout.config import settings  # noqa: E402

# Mirrors the literal in correlation._find_dedup_candidate. Kept as a named
# constant here so a future change to the rule shows up as a seed failure
# rather than as a scenario that silently stops linking.
DUP_SUBJECT_THRESHOLD = 0.85

DSN = settings.database_url.replace("postgresql+psycopg://", "postgresql://").replace(
    "@localhost:", "@127.0.0.1:"
)

E4_EXTERNAL_ID = "e4-dedup-scenario"

# Candidate rewordings, most natural first. Each is a small EDIT of the anchor
# subject rather than a rephrasing: correlation scores with
# difflib.SequenceMatcher, which compares character sequences, so reordering
# the same words scores far lower than a human would guess (the obvious
# "Q2 reconciliation numbers still dont tie out" scores 0.382 against
# "Numbers dont tie out in the Q2 reconciliation" and does not match at all).
_REWORDINGS = (
    lambda s: s.replace(" dont ", " still dont ", 1) if " dont " in s else s + " again",
    lambda s: s + " - still open",
    lambda s: s + " (again)",
)


def _pick_subject(anchor_subject: str) -> str:
    """First rewording that clears the same threshold correlation uses.

    Verified here rather than assumed: the threshold is a similarity score on
    a subject chosen at runtime, so a hard-coded string that happens to work
    against today's anchor would silently stop matching against tomorrow's.
    """
    for reword in _REWORDINGS:
        candidate = reword(anchor_subject)
        if candidate == anchor_subject:
            continue
        # correlation's own scorer, not a reimplementation of it.
        score = correlation._similarity(anchor_subject, candidate)
        if score > DUP_SUBJECT_THRESHOLD:
            print(f"  subject similarity {score:.3f} (needs > {DUP_SUBJECT_THRESHOLD})")
            return candidate
    raise SystemExit(
        f"no rewording of {anchor_subject!r} clears the similarity threshold — "
        "add one to _REWORDINGS rather than lowering the rule"
    )


def main() -> int:
    with psycopg.connect(DSN, connect_timeout=5, row_factory=dict_row) as conn:
        cur = conn.cursor()

        # Anchor on a real case that already has a requester, so rule 4 has a
        # same-person candidate to find.
        cur.execute(
            """
            SELECT m.tenant_id, m.mailbox_id, m.from_address, m.from_display_name,
                   m.to_addresses, m.object_path, m.connector_run_id,
                   m.internal_date_ms, c.id AS case_id, c.subject AS case_subject
            FROM itr360.case_ c
            JOIN itr360.message cm ON cm.case_id = c.id
            JOIN src_gmail.message m ON m.external_id = cm.external_id
            WHERE c.requester_id IS NOT NULL
            ORDER BY c.opened_at DESC
            LIMIT 1
            """
        )
        src = cur.fetchone()
        if src is None:
            print("  no canonical case with a requester — run ingest_canonical first")
            return 1

        # Remove any previous seed so this is a replace, not an append.
        cur.execute(
            "DELETE FROM src_gmail.message WHERE external_id = %s", (E4_EXTERNAL_ID,)
        )
        cur.execute(
            "DELETE FROM src_gmail.thread WHERE external_id = %s", (E4_EXTERNAL_ID,)
        )

        subject = _pick_subject(src["case_subject"])
        thread_id = uuid.uuid4()
        # Two hours after the anchor: comfortably inside the 24h dedup window.
        sent_ms = int(src["internal_date_ms"]) + 2 * 60 * 60 * 1000

        cur.execute(
            """
            INSERT INTO src_gmail.thread
              (id, tenant_id, source_system, external_id, mailbox_id, message_count,
               first_internal_date_ms, last_internal_date_ms, is_synthetic,
               connector_run_id, observed_at, valid_from)
            VALUES (%s, %s, 'gmail', %s, %s, 1, %s, %s, true, %s, now(), now())
            """,
            (thread_id, src["tenant_id"], E4_EXTERNAL_ID, src["mailbox_id"],
             sent_ms, sent_ms, src["connector_run_id"]),
        )

        cur.execute(
            """
            INSERT INTO src_gmail.message
              (id, tenant_id, source_system, external_id, thread_id, mailbox_id,
               subject, from_address, from_display_name, to_addresses,
               body_text, body_html_present, quoted_stripped,
               object_path, checksum_sha256, internal_date_ms,
               is_synthetic, connector_run_id, observed_at, valid_from)
            VALUES (%s, %s, 'gmail', %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, false, false,
                    %s, %s, %s,
                    true, %s, now(), now())
            """,
            (
                uuid.uuid4(), src["tenant_id"], E4_EXTERNAL_ID, thread_id,
                src["mailbox_id"], subject, src["from_address"],
                src["from_display_name"], src["to_addresses"],
                "Following up separately because the earlier thread went quiet. "
                "The Q2 reconciliation totals still do not tie out against the "
                "ledger and we need this closed before the audit review.",
                src["object_path"], uuid.uuid4().hex, sent_ms,
                src["connector_run_id"],
            ),
        )
        conn.commit()

    print(f"  seeded E4 '{subject}'")
    print(f"  anchor case {str(src['case_id'])[:8]} — {src['case_subject'][:50]}")
    print(f"  sender {src['from_address']} · new thread · +2h inside the window")
    print("  next: poetry run python scripts/ingest_canonical.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
