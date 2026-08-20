---
kb_id: KB-CFG-09
title: Reactivating licence keys after a renewal
problem_class: CFG-09
category: CFG
last_updated: 2026-08-10
---
## Symptom
The customer renewed their subscription or upgraded to a plan that includes
a new capability, but the feature stays greyed out or the client returns
`INVALID_LICENSE_KEY` on activation. The purchase is confirmed on the
account, but the tenant behaves as if nothing changed.

## Cause
Renewals and upgrades regenerate the licence key server-side, but the
entitlement flag that turns a feature "on" for the tenant is a separate
record from the key itself. When the two updates race, the new key can
propagate before the entitlement flag flips, or the flag flips but the
client is still caching the old key.

## Resolution
1. Confirm in the billing console that the renewal or upgrade order shows
   status `active`, not `pending`.
2. Open the account's entitlements panel and check the specific feature
   flag is `enabled` — if it still shows the old plan's flags, force a
   re-sync from the billing record.
3. Regenerate the licence key from the licensing console even if it looks
   current; this forces both records to reconcile.
4. Ask the customer to sign out, clear the cached licence file, and sign
   back in (or restart the client) so it pulls the new key.
5. Confirm the feature is now visible before closing the case.

## If this doesn't work
If the entitlement flag is enabled and the key is current but the feature
is still hidden, escalate to Account Governance — this is likely a stale
feature-flag cache on the tenant's shard, not a licensing problem.
