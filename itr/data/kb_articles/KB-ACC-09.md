---
kb_id: KB-ACC-09
title: Requests blocked after an office IP or proxy change
problem_class: ACC-09
category: ACC
last_updated: 2026-08-11
---
## Symptom
API or console requests that worked yesterday are now rejected outright —
often with a generic "forbidden" or connection-refused response rather than
an authentication error. The customer usually reports it started right
after a network change: a new office, a new VPN provider, or a switch to a
corporate proxy.

## Cause
The account has an IP allowlist or a zero-trust network policy configured.
Outbound traffic now egresses from a different public IP than the one on
file, so every request is dropped before it reaches authentication — which
is why it doesn't look like a login problem even though it feels like one.

## Resolution
1. Ask the customer for their current outbound IP (or CIDR block) — a
   quick way is to have them hit an "what's my IP" endpoint from the same
   network making the failing calls.
2. Compare it against the account's configured allowlist in the security
   settings panel.
3. If it has genuinely changed, add the new IP/CIDR and remove the stale
   entry once the customer confirms the old office is fully decommissioned.
4. If they're behind a proxy or VPN provider that rotates exit IPs, ask for
   the provider's published egress range instead of a single address, or
   recommend a static-IP add-on if one exists.
5. Have the customer retry immediately — allowlist changes take effect
   within a minute in most environments.

## If this doesn't work
If the IP is confirmed correct and requests still fail, check whether a
zero-trust or SSO conditional-access policy is also in play — those can
block on device posture even with a correct source IP, and need the
identity team, not this allowlist, to resolve.
