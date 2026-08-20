---
kb_id: KB-API-01
title: Diagnosing a sudden 401 or 403 on API calls
problem_class: API-01
category: API
last_updated: 2026-08-13
---
## Symptom
Calls that worked previously start returning `401 Unauthorized` or
`403 Forbidden`. The developer usually reports "nothing changed on our
side," and the error body from a well-behaved client is often the fastest
way to tell the two failure modes apart.

## Cause
`401` almost always means the credential itself is bad: an expired OAuth
token, a revoked or rotated API key, or a malformed signature. `403` means
the credential is valid but lacks permission: an insufficient OAuth scope,
a key restricted to a different resource, or an IP/allowlist rule (see
ACC-09 if the response looks network-level rather than credential-level).

## Resolution
1. Get the exact status code and, if available, the response body —
   `401` vs `403` immediately narrows the cause.
2. For `401`: check token/key expiry and rotation history. API keys and
   OAuth tokens that were rotated recently invalidate old cached
   credentials client-side even though the new one is valid.
3. For `403`: check the scopes granted to the token or key against what the
   endpoint requires, and confirm the key isn't scoped to a different
   environment (sandbox vs production is a common mismatch).
4. Ask the developer to regenerate the credential from the developer
   console and retry with the fresh value rather than a cached one.
5. If it's a signed-request integration, verify the signature is computed
   over the exact request body being sent — a mismatch there also surfaces
   as `401`.

## If this doesn't work
If credentials are current and scoped correctly but the error persists,
escalate to Developer Support with a request ID — this may be a
propagation delay on a recently rotated key rather than a client-side
issue.
