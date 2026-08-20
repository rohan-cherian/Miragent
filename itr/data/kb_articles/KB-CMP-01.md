---
kb_id: KB-CMP-01
title: Investigating a tax rate that doesn't match customer expectation
problem_class: CMP-01
category: CMP
last_updated: 2026-08-06
---
## Symptom
The customer reports the calculated tax rate on a transaction is wrong —
too high, too low, or a rate applied in a jurisdiction they didn't expect
to owe tax in at all.

## Cause
Tax calculation depends on several inputs together: the ship-to/ship-from
addresses, the product's tax category, any exemption certificate on file,
and the jurisdiction's current rate table. A mismatch in any one of these —
a stale exemption, a miscategorised product, or an address that resolves to
the wrong jurisdiction — produces a rate that looks wrong even though the
engine calculated correctly against its inputs.

## Resolution
1. Pull the transaction's tax calculation detail (not just the final rate)
   to see which jurisdiction and product category were actually used.
2. Verify the ship-to address resolved correctly — jurisdiction boundaries
   near city/county lines are the most common source of "wrong" rates that
   are actually correct for the resolved address.
3. Check the product's tax category mapping — a generically-mapped product
   can inherit the wrong taxability rules.
4. Check for an exemption certificate on the account; if one exists but
   wasn't applied, confirm it's valid and correctly associated with this
   transaction type.
5. If all inputs check out and the rate still looks wrong, compare against
   the jurisdiction's published current rate — rate tables do change, and a
   recent change may not yet be reflected in the discussion the customer is
   having internally.

## If this doesn't work
If the calculation detail shows correct inputs and a rate the customer
still disputes, escalate to the Compliance/Tax team — do not adjust a tax
amount manually without their sign-off, as it has audit implications.
