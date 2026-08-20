---
kb_id: KB-PRF-01
title: Responding to a full outage report
problem_class: PRF-01
category: PRF
last_updated: 2026-08-15
---
## Symptom
A customer reports the service, or a critical surface of it, is completely
unavailable — the console won't load, API calls all fail, or a core
workflow is entirely blocked for every user at the account, not just one
person.

## Cause
Full outages are treated as a status/incident question first and a
troubleshooting question second: the priority is establishing whether this
is a known, already-being-worked incident, versus something isolated to
this one account (a DNS issue, a network path problem, an account-level
lock).

## Resolution
1. Immediately check the internal status page / incident channel for a
   known active incident before doing any account-specific digging.
2. If there's a known incident, respond to the customer with the incident
   reference and current status rather than duplicating investigation
   already underway.
3. If there's no known incident, quickly confirm scope: is it just this
   customer, or can it be reproduced generally? Check the account for
   anything account-specific (a suspension, a billing hold) that could
   explain a total block.
4. If it reproduces and no incident exists yet, escalate immediately to the
   on-call team — a full outage not yet tracked as an incident is the
   highest-priority thing you can raise.
5. Keep the customer updated at short, regular intervals until resolved —
   silence during a full outage is worse than an "still investigating"
   update.

## If this doesn't work
This class always escalates — a support agent alone does not resolve a full
outage. If you cannot immediately confirm known-incident status, escalate
to on-call without waiting for further diagnosis.
