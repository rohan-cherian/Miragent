---
kb_id: KB-DAT-02
title: Resolving duplicate transaction records inflating totals
problem_class: DAT-02
category: DAT
last_updated: 2026-08-05
---
## Symptom
The customer notices totals in a report are higher than expected and, on
investigation, finds the same transaction appearing more than once.

## Cause
Duplicates are typically caused by one of: a connector re-processing a
batch after a failed run without correctly skipping already-synced
records, a webhook firing more than once for the same event and each firing
being treated as new, or a manual re-import that wasn't scoped to exclude
already-present records.

## Resolution
1. Identify the duplicated record's external ID and confirm it's a true
   duplicate (same external ID, same amount) rather than two genuinely
   separate transactions that happen to look similar.
2. Check the connector's sync history for that record — a retry after a
   partial failure is the most common cause and will usually show two sync
   events for the same external ID.
3. If it's a retry-related duplicate, de-duplicate on the external ID going
   forward is expected behaviour — confirm the connector's dedup key is
   configured correctly; if it isn't, that's the actual fix, not a one-off
   cleanup.
4. Remove the duplicate record(s), keeping the earliest complete one, and
   recalculate any affected totals.
5. If a webhook double-fire is the cause, confirm idempotency handling is
   enabled on that webhook's endpoint before closing.

## If this doesn't work
If duplicates keep appearing after the dedup key is confirmed correct, this
is likely a connector defect rather than a one-off — escalate to Data
Accuracy with the pattern (how often, which connector) attached.
