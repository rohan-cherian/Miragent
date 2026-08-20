---
kb_id: KB-DAT-04
title: Records landing in the wrong period due to timezone handling
problem_class: DAT-04
category: DAT
last_updated: 2026-08-05
---
## Symptom
A transaction the customer expects to see in one reporting period (e.g. the
last day of a month) instead shows up in the next period.

## Cause
Usually the source system records the timestamp in local time while this
platform posts in UTC, so anything near a period boundary can shift by a
day depending on the customer's timezone offset.

## Resolution
1. Confirm the account's configured reporting timezone against the source
   system's timezone.
2. Check the raw timestamp on the affected record in both systems to see
   whether the shift matches the timezone offset.
3. If it does, this is expected behaviour, not an error — explain the
   posting-date rule clearly.

## If this doesn't work
If the shift doesn't match the expected offset, escalate to Data Accuracy —
that points to a timezone-handling bug rather than expected rounding.
