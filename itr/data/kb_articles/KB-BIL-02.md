---
kb_id: KB-BIL-02
title: Handling an invoice dispute over line items or amount
problem_class: BIL-02
category: BIL
last_updated: 2026-08-09
---
## Symptom
The customer contacts support saying an invoice total doesn't match what
they expected — a quantity looks wrong, a line item is unrecognised, or the
billing period doesn't line up with a mid-cycle cancellation or upgrade.

## Cause
Most disputes trace back to one of three things: a plan or seat-count
change that took effect mid-cycle and produced a prorated line, a usage
metric (API calls, records processed) crossing a threshold the customer
wasn't tracking, or a genuine billing-system error where a charge posted
twice or against the wrong subscription.

## Resolution
1. Pull the invoice and the underlying billing events for the period in
   question — don't just re-read the invoice PDF, check the source ledger.
2. Identify which line item is disputed and classify it: proration, usage
   overage, duplicate charge, or plan mismatch.
3. If it's proration or usage, prepare a short breakdown showing the dates,
   the metric, and the rate — this resolves the majority of disputes
   without a credit.
4. If it's a duplicate charge or a genuine system error, issue a credit or
   refund per policy and note the root cause on the case.
5. Reply with the breakdown or the credit confirmation, and reference the
   dispute reason explicitly so the customer sees it was actually checked,
   not just waved through.

## If this doesn't work
If the customer disputes the underlying rate or plan terms themselves
(not just the invoice math), escalate to Billing Ops — a rate dispute is a
contract question, not a billing-accuracy one, and needs sign-off before
any adjustment is made.
