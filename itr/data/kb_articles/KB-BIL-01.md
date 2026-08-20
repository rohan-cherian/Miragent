---
kb_id: KB-BIL-01
title: Explaining an unexpected usage overage charge
problem_class: BIL-01
category: BIL
last_updated: 2026-08-09
---
## Symptom
The customer's invoice is higher than expected, and unlike a flat pricing
dispute, the extra amount traces to a usage-based line item — API calls,
records processed, or seats — that crossed a plan threshold during the
period.

## Cause
Usage-based plans bill overage once a metered quantity exceeds what the
base plan includes. Customers are frequently unaware of where their
threshold sits or don't have visibility into their own usage trend, so a
gradual increase in normal activity looks like a billing surprise rather
than a predictable crossing of a line.

## Resolution
1. Pull the usage report for the billing period and identify exactly which
   metric crossed its threshold and by how much.
2. Show the customer the day-by-day or week-by-week trend, not just the
   period total — this usually makes clear whether it was a gradual
   increase or a one-off spike (e.g. a bulk import).
3. Explain the overage rate applied and confirm the math on the invoice
   matches the usage report.
4. If the spike was a one-off and the customer wants to avoid this going
   forward, point them at usage alerts/thresholds if the product offers
   them, or flag a plan upgrade conversation to the account team.
5. Overage charges are correctly billed usage, not a defect — do not credit
   them without a specific reason (metering bug, duplicate count) backing
   it up.

## If this doesn't work
If the customer believes the usage count itself is wrong (not just the
charge), that's a metering-accuracy question — escalate to Billing Ops with
the specific records in dispute rather than adjusting the invoice directly.
