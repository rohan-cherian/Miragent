---
kb_id: KB-CFG-01
title: Unblocking a stalled onboarding / implementation go-live
problem_class: CFG-01
category: CFG
last_updated: 2026-08-07
---
## Symptom
A new customer's go-live date is approaching or has passed, and the
customer or their implementation partner reports they're stuck on a
configuration step — a mapping, a hierarchy setup, an entitlement — that
they cannot complete themselves.

## Cause
Onboarding stalls almost always trace to a dependency that isn't visible
from the customer's side: a required upstream configuration (org hierarchy,
data mapping, a permission grant) that only an internal team can complete,
or a step the implementation checklist assumes was done but wasn't.

## Resolution
1. Pull the onboarding checklist for this account and identify the exact
   step the customer is blocked on — ask for a screenshot or the specific
   error if it's not obvious from the ticket.
2. Check whether the blocking step depends on an internal action (e.g. a
   tenant provisioning flag, a data import) that hasn't completed yet.
3. If it's an internal dependency, complete it or route it to the owning
   team with the go-live date attached so it's prioritised correctly.
4. If it's a customer-side configuration step, walk them through it
   directly rather than pointing at documentation — onboarding urgency
   warrants hands-on help.
5. Confirm the customer can proceed past the blocked step before closing,
   and flag the case to the CSM/onboarding owner so the go-live date stays
   accurate.

## If this doesn't work
If the blocker is a genuine product gap (a configuration the customer needs
doesn't exist yet), escalate to Account Governance rather than looking for
a workaround that will need to be undone later.
