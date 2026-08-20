---
kb_id: KB-PAY-02
title: Assembling chargeback evidence before the deadline
problem_class: PAY-02
category: PAY
last_updated: 2026-08-03
---
## Symptom
A dispute (chargeback) has been raised against a transaction, and evidence
needs to be assembled and submitted before the network's response deadline
— usually a tight window, often 7-14 days depending on the card network.

## Cause
This is a time-critical evidence-gathering task, not a technical fault. The
main risk is missing the deadline entirely, which forfeits the case by
default regardless of how strong the underlying evidence is.

## Resolution
1. Confirm the response deadline immediately and treat it as the hard
   constraint driving everything else — flag it as urgent on the case.
2. Identify the dispute reason code (fraud, product not received, not as
   described, duplicate, etc.) — the required evidence differs by reason.
3. Gather the relevant evidence bundle: proof of delivery/fulfilment,
   customer communication showing agreement to the charge, IP/device data
   at time of purchase, and the refund policy shown at checkout, matched to
   what the specific reason code requires.
4. Submit the evidence bundle through the payment processor's dispute tool
   well ahead of the deadline, not at the last hour — submission systems
   can have their own delays.
5. Log the outcome once the network responds (won, lost, or further
   information requested) so the pattern is tracked over time.

## If this doesn't work
If the deadline is at serious risk of being missed or the reason code is
unclear, escalate immediately to the Payments/Risk team rather than
continuing to gather evidence on your own timeline.
