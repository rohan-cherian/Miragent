# ITR — clickable console (POC)

Motiveminds ITR, built to `ITR_UI_MasterSpec_v2_DeveloperReady.md`. Fourteen
product screens plus the demo swim lane, running entirely on synthetic fixtures.
No backend.

```bash
npm install
npm run dev      # http://localhost:5173
```

Pick a role at `/login`. The role changes what you can see and do:

| Role | Lands on | Can |
|---|---|---|
| **Manager** (Marcus Adeyemi) | `/overview` | Read everything, drill every number, record assignment feedback. Cannot decide resolutions — those controls are disabled with a reason, not hidden. |
| **Analyst** (Priya Nair) | `/queue` | Approve / edit / reject drafts, confirm merges, decide KB drafts. |
| **Admin** (Sutej Rao) | `/connections` | Resolve identities, re-run reconciliation, export audit. |
| **Demo** (presenter) | `/demo/connect/1` | The fenced connector journey and the presenter controls. |

## Where to start, as an Operations Manager

1. **`/intelligence`** — Monday's briefing. Read the paragraph, then click any
   number in it. The SSO recurrence, its root cause, the deflection estimate and
   the coaching signal all resolve to the cases behind them.
2. **`/overview`** — corpus health. Click the enterprise-tier bar; the case list
   opens over the chart and Esc returns you to it.
3. **`/audit?type=rejected`** — read the reject reasons to see where drafts fail.
   Then `A-99231`: an approval whose external write failed, with the approval
   intact and three retries on the record.
4. **`/queue`** — the work being judged, read-only at this role.

## Structure

```
src/
  contracts/   frozen: state enums · route registry · RBAC matrix · formatters · config
  fixtures/    the one synthetic corpus — 6,000 cases, 240 analysts, 900 articles
  mock/api.js  every §14A operation, with scripted latency and failure
  ui/          the §8 component library (see /kitchen-sink)
  shell/       S-01 shell, session, shared hooks
  screens/     S-02 … S-14, the panels, and the demo lane
```

Every dashboard figure is computed from the same case list the ticket list
queries, so the counts reconcile [NFR-31] and every drill lands on real rows.

## Scripted states (append to any URL)

The honesty behaviours are simulated with real timing, so they are demonstrable
rather than described:

| Hook | Effect |
|---|---|
| `?fail=429` | The next write rate-limits, retries, then succeeds |
| `?fail=write` | The next write exhausts its retries and lands in `failed` |
| `?conflict=1` | The next decision returns "already decided by R. Bose" |
| `?slow=3000` | Reads take 3s, so the honest-delay notice fires |
| `?empty=1` | Lists return empty |
| `?error=1` | Reads fail, so error states render |

Try `/queue?item=HFG-2214&fail=write` as the Analyst role: approve it, watch the
write queue → execute → retry ×2 → fail, and note that the approval survives and
only the execution can be re-fired.

## Other routes

- `/kitchen-sink` — every component in every state, for design review.
- `npm run smoke` — drives all routes in headless Chromium and writes
  screenshots to `./shots` (needs `npx playwright install chromium`).

## Reading the build

`LANE_NOTES.md` records every assumption made and every spec ambiguity found,
including one — the §7.2 chart palette's colourblind separation — that needs a
designer's decision rather than a developer's.
