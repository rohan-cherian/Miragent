# ADR-003: Case correlation rules

**Status:** Accepted
**Date:** 2026-08-18
**Task:** 15 — Thread reconstruction and case correlation

## Context

The product is Issue-to-Resolution, not email-to-vector: a case is the
unit of work, and it forms from a conversation, not a single message.
`scout.canonical.correlation.find_or_create_case()` decides, for every
incoming message, which `itr360.case_` row it belongs to — matching an
existing conversation where possible, and creating a new case
otherwise.

## Decision

Apply these five rules, in order, stopping at the first one that fires:

| # | Rule | Reason string | What happens |
|---|------|----------------|--------------|
| 1 | **same_thread** | `same_thread` | An `itr360.message` row already exists with this `thread_id` — use its case. |
| 2 | **in_reply_to** | `in_reply_to` | No thread match, but the message's `in_reply_to` header resolves to a known message (matched on `src_message_id`) — use its case. Fallback for clients that break threading. |
| 3a | **reopen** | `reopened` | The case matched by rule 1 or 2 is `closed`, and it closed within `REOPEN_WINDOW_DAYS` of this message's `sent_at` — reopen it (`status` back to `open`, `reopened_count` incremented). |
| 3b | **new_after_window** | `new_after_window` | The matched case is `closed`, but closed *outside* `REOPEN_WINDOW_DAYS` — create a new case, cross-linked to the old one via `related_case_ids` (both directions). |
| 4 | **dedup_link** | `dedup_link` | No thread match at all, but the same person opened another case within `DUP_WINDOW_HOURS` with a similar subject (`difflib.SequenceMatcher` ratio > 0.85) — create a new case, cross-linked via `related_case_ids`, and log an audit row proposing the dedup. |
| 5 | **new_case** | `new_case` | None of the above — create a brand new case. |

Both window constants are configured in `scout.config.settings`, never
hardcoded:

- `REOPEN_WINDOW_DAYS` — how recently a case can have closed and still
  reopen instead of forking.
- `DUP_WINDOW_HOURS` — how recently the same person can have opened a
  similar-subject case before a new one is proposed as a duplicate
  rather than treated as unrelated.

Every rule, including the plain `new_case` path, writes exactly one
`itr360.case_event` row and one `decision_audit` row
(`category="scan"`, `action="case_correlation"`), so the full
correlation history is reconstructable and auditable.

## Link, never merge

Rules 3b and 4 never merge two cases into one — they create a new case
and cross-link both via `related_case_ids`. Merging two cases is close
to unrecoverable in a real support system (history, attachments, and
audit trails split silently), and no confidence score in a Slice 1 POC
justifies that risk. A human-initiated merge is a future capability,
not something the correlation waterfall does automatically.

## Consequences

- Case correlation, like Task 14's identity waterfall, fails closed:
  when correlation is uncertain, it creates a new case and links it
  rather than guessing which existing case is "close enough."
- `case_.requester_id` is set on any case this module creates when
  `person_id` is known, so Task 14's identity-queue retro-link
  (`scout.canonical.identity.queue`, marked `TODO`) has a target to
  update once it's implemented.
