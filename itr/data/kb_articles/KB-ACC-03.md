---
kb_id: KB-ACC-03
title: Password reset email never arrives
problem_class: ACC-03
category: ACC
last_updated: 2026-08-12
---
## Symptom
The customer requests a password reset, sometimes more than once, and the
email never shows up — not in the inbox, not in spam or junk. Login remains
blocked because there's no link to click.

## Cause
Three causes account for nearly all cases: the receiving mail server
silently suppressed or filtered the message, the account's email address on
file has a typo or is an old alias no longer monitored, or the organisation
has a corporate mail filter blocking automated sender domains outright.

## Resolution
1. Confirm the exact email address on the account and read it back to the
   customer — a surprising number of these are a stale or misspelled alias.
2. Ask them to check spam/junk and also any organisation-level quarantine
   (a mail admin portal), not just the personal inbox.
3. Check the delivery log for that message — if it shows a hard bounce or a
   suppression-list entry, that confirms the mail server rejected it, not
   that it was lost.
4. If the address is correct and delivery genuinely failed, manually
   trigger a fresh reset and, if the tooling allows, send from an alternate
   sending domain to route around a suppression entry.
5. As a last resort, verify identity through an alternate channel and reset
   the password directly rather than relying on email delivery at all.

## If this doesn't work
If the domain is on a suppression list because of a prior bounce storm, ask
the customer's mail admin to allowlist the sending domain — this is outside
what a manual resend can fix.
