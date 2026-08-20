---
kb_id: KB-ACC-01
title: SSO / SAML login failures after an IdP-side change
problem_class: ACC-01
category: ACC
last_updated: 2026-08-14
---
## Symptom
Users at a customer with SSO enabled suddenly cannot log in — they're
bounced back to the login page after authenticating with their identity
provider, or see a generic "authentication failed" error with no further
detail.

## Cause
The SAML handshake depends on three things staying in sync: the signing
certificate, the assertion URL/entity ID, and the attribute mapping (which
IdP attribute maps to email, name, and group). A change on either side —
a certificate rotation, an IdP reconfiguration, or an attribute rename —
breaks the handshake even though nothing changed in this product.

## Resolution
1. Pull the SAML response from a failed login attempt (browser dev tools or
   a SAML tracer extension) and check whether it's a signature failure, an
   assertion-expired error, or a missing-attribute error — each points
   somewhere different.
2. Signature failure: compare the certificate fingerprint on file against
   what the IdP is currently signing with; IdPs often rotate certs on a
   schedule the customer's IT team doesn't proactively announce.
3. Assertion/URL mismatch: confirm the entity ID and ACS URL configured on
   the IdP side exactly match what's on the account's SSO settings.
4. Missing attribute: check the attribute mapping — a common cause is the
   IdP renaming or restructuring a claims policy without updating the
   mapping here.
5. Update the stale side (usually the certificate) and have one user test
   before declaring it resolved organisation-wide.

## If this doesn't work
If the SAML response validates cleanly but users still can't reach the app,
the failure is downstream of authentication (session or provisioning) —
escalate to Identity & Access Management rather than continuing to treat it
as a SAML problem.
