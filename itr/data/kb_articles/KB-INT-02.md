---
kb_id: KB-INT-02
title: E-commerce connector orders stop flowing or arrive incomplete
problem_class: INT-02
category: INT
last_updated: 2026-08-04
---
## Symptom
Orders from Shopify, Magento, or BigCommerce either stop appearing
entirely, or continue to sync but with missing fields — a missing customer
address, a missing line-item detail, or a blank tax/shipping value.

## Cause
A full stoppage is usually a broken webhook subscription or an expired API
credential on the storefront side. Partial/incomplete records are a
different problem: the storefront's data model changed (a custom field
added, an app modifying the checkout payload) in a way the connector's
field mapping doesn't account for.

## Resolution
1. First determine which failure mode this is — nothing syncing at all, or
   orders syncing with specific fields missing — since the fix differs.
2. For a full stoppage: check the storefront's webhook/app connection
   status; a disconnected or reinstalled app on the storefront side
   silently breaks the subscription without notifying this platform.
3. For incomplete records: compare the raw payload from a recent order
   against the connector's field mapping to find which field is unmapped or
   renamed.
4. Reconnect the storefront app or webhook if disconnected, and confirm
   with a test order that new orders sync in full.
5. For historical orders affected by the gap, run a scoped backfill for the
   affected date range once the underlying issue is fixed.

## If this doesn't work
If the storefront connection is healthy and mappings look correct but
fields are still missing, escalate to Integrations engineering with a
sample raw payload — this may require a mapping update on the connector
itself.
