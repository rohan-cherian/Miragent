---
kb_id: KB-PRF-03
title: Speeding up a slow-loading report or dashboard view
problem_class: PRF-03
category: PRF
last_updated: 2025-11-02
---
## Symptom
A specific report or dashboard view takes a long time to render, or times
out, while the rest of the console feels normal.

## Cause
In the Legacy Reports module, slow renders are almost always a wide date
range combined with no filters applied — the report engine scans the full
range before aggregating. This article predates the newer Reports v2
engine; if the customer is on Reports v2 the same root cause (unfiltered
wide date range) still applies, but the workaround steps below reference
the old module's UI.

## Resolution
1. Ask which report/view is slow and over what date range — a range beyond
   90 days with no other filters is the most common trigger.
2. In Legacy Reports, apply an account or category filter alongside the
   date range; this was the standard workaround before pagination was
   improved.
3. Narrow the date range to the smallest window that still answers the
   customer's question, and suggest running it in smaller chunks if they
   need the full history.
4. If the customer is on the newer Reports v2 interface, the same
   narrow-the-range approach applies, though the exact filter controls have
   moved — check the current UI rather than following this article's
   screenshots literally.

## If this doesn't work
If a narrow, filtered range is still slow, this may no longer be a usage
pattern issue — escalate to Performance engineering, since this article has
not been re-verified against the current reporting engine.
