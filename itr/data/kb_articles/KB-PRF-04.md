---
kb_id: KB-PRF-04
title: Diagnosing a backed-up batch job or processing queue
problem_class: PRF-04
category: PRF
last_updated: 2026-08-15
---
## Symptom
Asynchronous processing — a bulk import, a scheduled export, a background
recalculation — is taking noticeably longer than usual, and results the
customer expects are late or not yet available.

## Cause
Queue backlogs build up for a small number of reasons: a spike in overall
platform volume affecting the shared queue, one customer's unusually large
job consuming a disproportionate share of workers, or a stuck job at the
front of the queue blocking everything behind it.

## Resolution
1. Check the queue's current depth and processing rate against its normal
   baseline to confirm there actually is a backlog, not just a naturally
   large job still in progress.
2. Identify whether the backlog is platform-wide (check the operations
   dashboard) or specific to this account's job.
3. If platform-wide, this is a capacity/reliability issue — route to
   on-call with the customer's job as an example, don't troubleshoot it as
   an isolated case.
4. If specific to this account, check for a stuck or failed job at the
   front of that account's queue that needs to be manually retried or
   cleared.
5. Give the customer a realistic estimate based on current queue depth
   rather than the job's normal processing time, since that's what will
   actually match their experience.

## If this doesn't work
If a job appears stuck (no progress over an extended period, not just slow)
rather than merely queued, escalate to engineering — a stuck job usually
needs to be killed and restarted, not waited out.
