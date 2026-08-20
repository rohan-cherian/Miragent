---
kb_id: KB-PAY-01
title: Diagnosing a declined payment authorisation
problem_class: PAY-01
category: PAY
last_updated: 2026-08-03
---
## Symptom
A charge is declined at authorisation time and the customer (or their
customer, if this is a platform charging on their behalf) wants to know
why, and what to do about it.

## Cause
Declines fall into a small set of categories reported back by the card
network or issuer: insufficient funds, a card-not-present risk flag,
expired or invalid card details, an issuer-side fraud hold, or a
platform-side risk rule (velocity limit, blocklist) rejecting the charge
before it even reaches the network.

## Resolution
1. Pull the decline reason code from the transaction record — do not guess
   from the generic customer-facing message, the underlying code is
   specific.
2. If it's an issuer decline (insufficient funds, fraud hold, expired
   card), the fix is on the cardholder's side — advise contacting their
   bank or updating the card, this platform cannot override an issuer
   decline.
3. If it's a platform-side risk rule, review what triggered it (velocity,
   blocklist match, mismatched billing details) and determine if it's a
   false positive worth a manual override.
4. For a false positive, clear the flag per the risk-override procedure and
   ask the customer to retry.
5. Document the decline reason on the case either way — repeated declines
   with the same reason code from the same customer are a pattern worth
   flagging even if each individual case is resolved.

## If this doesn't work
If the decline reason code itself is ambiguous or unlisted, escalate to the
Payments/Risk team with the transaction ID — do not attempt to force a
retry against a fraud hold without their review.
