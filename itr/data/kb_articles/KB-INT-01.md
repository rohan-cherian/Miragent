---
kb_id: KB-INT-01
title: ERP connector stops syncing after a credential change
problem_class: INT-01
category: INT
last_updated: 2026-08-04
---
## Symptom
A NetSuite, SAP, or Dynamics connector that was syncing normally suddenly
stops, usually with an authentication error in the connector's status
panel. The customer often reports an unrelated IT change around the same
time — a password rotation, an SSO migration, or an API user account
change on the ERP side.

## Cause
ERP connectors typically authenticate with a dedicated integration user or
an OAuth token issued specifically for the connector. When that account's
password is rotated, its permissions are changed, or the token expires
without a renewal step being run, the connector's stored credential goes
stale and every sync attempt fails at the authentication step.

## Resolution
1. Check the connector's status panel for the exact error — expired token,
   invalid credential, or a permissions/scope error each point differently.
2. Confirm with the customer's IT/ERP admin whether the integration
   account's credentials were recently changed and, if so, get the new
   credential or re-authorize the OAuth connection.
3. Re-enter the credential or re-run the OAuth authorization flow in the
   connector settings.
4. Trigger a manual sync and confirm records flow through before relying on
   the next scheduled run.
5. Check whether any records failed to sync during the outage window and
   whether the connector needs a manual backfill for that gap.

## If this doesn't work
If the credential is confirmed current and valid but authentication still
fails, escalate to the connector engineering team — this may be an
API-version or endpoint change on the ERP side that needs a connector
update.
