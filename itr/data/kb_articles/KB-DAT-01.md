---
kb_id: KB-DAT-01
title: Recovering transactions missing from reporting
problem_class: DAT-01
category: DAT
last_updated: 2026-08-05
---
## Symptom
The customer knows a transaction exists upstream (in their ERP, e-commerce
platform, or payment processor) but it never shows up in this platform's
reports — no error, it's just silently absent.

## Cause
Missing records almost always mean a sync failure that didn't surface
loudly: a connector job that errored partway through a batch, a record that
failed validation and was silently dropped rather than queued for retry, or
a filter/date-range on the connector that excludes it by design (e.g. it
predates the connector's initial sync window).

## Resolution
1. Get the exact record identifier and its timestamp from the source
   system, and check the connector's sync logs around that time for
   errors or skipped-record entries.
2. If the connector log shows a validation failure, look at what field
   failed — a malformed value there is often the actual reason it never
   synced, not a platform bug.
3. If the record simply predates the connector's configured sync start
   date, explain that and offer a manual backfill for that specific range
   if the customer needs historical completeness.
4. If the log shows no error at all for that record, check for silent job
   failures — a batch that errored on record N can sometimes fail to log
   records N+1 onward as skipped even though they never landed.
5. Once the cause is identified, trigger a targeted re-sync or manual
   import for the missing record(s) rather than a full historical re-sync,
   which can create duplicates elsewhere (see DAT-02).

## If this doesn't work
If sync logs show the record was processed successfully but it's still not
appearing in reports, this is a reporting-layer issue, not an ingestion
one — escalate to Data Accuracy with the record id and expected report.
