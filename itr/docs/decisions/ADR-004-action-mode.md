# ADR-004: ACTION_MODE and the draft-only gate

**Status:** Accepted
**Date:** 2026-08-19
**Task:** 22 — Dispatch, write state machine, and the draft-only gate

## Context

`scout.canonical.execution.dispatch_write()` is the only code path in
this project capable of sending something external (a Gmail reply) on
the strength of a recorded human decision. `scout.config.settings.ACTION_MODE`
controls whether that ever actually happens.

## Decision

`ACTION_MODE` has exactly two values:

| Value | Meaning |
|---|---|
| `draft_only` | Nothing is ever actually sent or written externally. `dispatch_write()` inserts a suppressed `WriteExecution` (`state="not_started"`, `suppressed_reason="ACTION_MODE=draft_only (MVP Phase 1)"`) and returns immediately. |
| `gated_execute` | Only reachable after an approved human decision. `dispatch_write()` runs the full `not_started -> queued -> executing -> (retrying -> executing)* -> succeeded \| failed` state machine, with up to 3 attempts and exponential backoff with jitter between retries. |

**`draft_only` is the Phase 1 default**, and stays that way until Tasks
20–23 (human gate + audit) are all done. This isn't a stylistic
preference — the project's 4-week strategy lists "autonomous action of
any kind" as an explicit non-goal for this phase. Slice 1 proves the
identity waterfall, case correlation, redaction, and the approval
record work end to end; it does not yet prove anything about safely
sending mail on a human's behalf.

## The guarantee is structural, not conventional

In `draft_only` mode, the check happens **first**, before anything
else in `dispatch_write()` — before the state machine starts, before
`GmailAdapter` is even loaded. The adapter is only ever referenced
inside the branch that runs when `ACTION_MODE == "gated_execute"`, and
even there it's loaded dynamically (`importlib.import_module()`) at
the moment of an actual send attempt, not imported at module load
time.

This means `draft_only` isn't "a flag someone checks before calling
the send function" — it's the reason the send function's own code
never executes at all. There's no code path in `dispatch_write()`
that reaches the adapter while `ACTION_MODE=draft_only`. A developer
who accidentally deletes the `if` check would get a very different
kind of bug (a genuine attempt to run the untested gated_execute path)
rather than a config flag silently doing nothing — the failure mode of
removing the gate is loud, not quiet.

## Consequences

- A failed write never touches or invalidates the `RecommendationDecision`
  that authorised it — `recommendation_decision` and `write_execution`
  are Task 10's two deliberately separate state machines. `refire()`
  retries a failed send by reusing the existing `decision_id`, never by
  creating a second decision.
- Build the executor, test it (including the `gated_execute` state
  machine and its retry/backoff behavior via `GMAIL_FORCE_SEND_FAIL`),
  and ship it switched off. Flipping `ACTION_MODE` to `gated_execute`
  is a deliberate, separate decision for a later phase — not something
  this task does.
