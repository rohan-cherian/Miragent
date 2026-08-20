---
kb_id: KB-API-02
title: Handling 429 rate-limit errors and requesting a higher limit
problem_class: API-02
category: API
last_updated: 2026-08-13
---
## Symptom
A client starts receiving `429 Too Many Requests`, either steadily under
normal load or in bursts during a specific job (a nightly sync, a bulk
import). The developer wants to know why, and often asks for the limit to
simply be raised.

## Cause
Rate limits are enforced per API key against either a request-count window
or a concurrency ceiling. The two most common triggers are a client that
doesn't implement backoff and retries aggressively (multiplying the
problem), or a genuine change in usage pattern — new integration, larger
batch job — that has outgrown the plan's default limit.

## Resolution
1. Check the account's current plan limit and the actual request volume
   around the failure window to see whether this is a burst or a sustained
   ceiling breach.
2. Confirm the client honours the `Retry-After` header and backs off — if
   it's retrying in a tight loop, that alone can turn a brief 429 into a
   prolonged outage for that client.
3. If the pattern is a legitimate new workload (batch import, higher
   traffic), recommend restructuring the calls into fewer, larger batched
   requests where the API supports it.
4. If usage still exceeds the plan's rate limit after batching, escalate a
   limit-increase request with the observed peak rate attached.
5. Confirm with the developer once the new limit (or the corrected client
   behaviour) is in place that the 429s have stopped.

## If this doesn't work
If 429s persist even under the documented limit, this may be a rate-limiter
bug rather than a usage problem — escalate to Developer Support with
timestamps and request IDs from the failing window.
