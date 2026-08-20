---
kb_id: KB-PRF-02
title: Investigating partial degradation and elevated latency
problem_class: PRF-02
category: PRF
last_updated: 2026-08-15
---
## Symptom
The customer reports things are "slow" or "flaky" rather than fully down —
requests intermittently time out, pages take longer than usual to load, or
some actions succeed while others fail with no obvious pattern.

## Cause
Partial degradation is harder to pin down than a full outage because it can
originate almost anywhere: elevated load on a shared component, a slow
downstream dependency, a specific endpoint or feature under strain rather
than the whole platform, or — less often — something specific to the
customer's own network path.

## Resolution
1. Check the status page and internal monitoring for any elevated
   error-rate or latency signal already being tracked before assuming this
   is unique to the customer.
2. Ask the customer for specifics: which action, roughly when, how
   frequently — "everything is slow" versus "this one report is slow" point
   to very different causes.
3. If monitoring shows elevated latency broadly, this is likely a platform
   condition — route to the on-call/reliability team with the customer's
   report as a data point, don't try to resolve it as an individual case.
4. If monitoring is clean and it's isolated to this customer, check for
   network-path issues on their side (traceroute, regional CDN edge) before
   assuming a platform cause.
5. Keep the customer informed with what's known even if the root cause
   isn't yet identified — a degradation case can run longer than a full
   outage before resolving.

## If this doesn't work
If the pattern can't be reproduced and monitoring shows nothing unusual,
escalate to reliability engineering with as much specific detail (times,
endpoints, request IDs) as the customer can provide, rather than closing it
as unreproducible.
