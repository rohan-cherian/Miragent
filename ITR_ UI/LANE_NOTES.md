# LANE_NOTES — ITR clickable console

Assumptions made while building, and every spec ambiguity found. Per the
distribution plan §6, these roll up to Spec §15 rather than being resolved
silently in code.

---

## 1. Build framing

**Built through the Operations Manager's eyes.** The brief was to think like an
Operations Manager while building. Persona B (Marcus Adeyemi, support director)
is the primary reader of S-03, S-11, S-13 and S-09, so those four screens carry
the most depth: prose-first briefing, drill-through on every figure, anonymised
capability signals, and reject-reason review as a first-class manager task. The
analyst and admin surfaces (S-04, S-05..S-08, S-02, S-10, §12) are built to their
full §10 contract but optimised for *legibility to a manager reviewing the work*
as much as for seconds-per-decision.

Concretely, the manager lens changed four decisions:

1. **Nothing is a dead end.** Every number on a manager surface is a `<Drill>`
   that opens the backing cases as an overlay on the origin screen — the chart
   stays visible behind it, so "where did that come from" never costs the reader
   their place.
2. **Read-only is stated, not implied.** On S-04 the Manager role sees every
   decision control *disabled with a reason*, not hidden. A director should be
   able to inspect the work being judged without being able to judge it, and
   should be able to see that this is by design.
3. **Absence is explained.** Where a rule removes something from view — a signal
   below its sample floor, a pattern below significance, a person's name in the
   development-areas section — the screen says so in a sentence rather than
   leaving a silent gap.
4. **The digest is written, not dashboarded.** S-11 leads with a paragraph a
   director could forward, with the figures embedded as drillable links.

**Stack.** React 18 + Vite + plain CSS custom properties, per [D-01]. No CSS
framework: token fidelity (§7.2 hex is truth) mattered more than utility speed.
All data comes from local fixtures behind `src/mock/api.js`. No backend.

**Single-agent build.** The distribution plan splits this across nine agents with
a file-ownership matrix. Built as one codebase, the matrix collapses to a folder
convention — `contracts/`, `ui/`, `shell/`, `screens/`, `fixtures/`, `mock/`.
The five frozen contracts still exist as real modules and no screen redeclares
one; if the work is later split across sessions, `src/contracts/**` is the
freeze boundary.

---

## 2. Assumptions made (beyond those already in Spec §15)

| # | Assumption | Where | Reversal cost |
|---|---|---|---|
| L-01 | **Chart series order re-sequenced.** §7.2 lists series 1–6 as purple · navy · green · amber · red · black. Adjacent slots 1↔2 (purple/navy) fail CVD separation — ΔE 4.6 deutan, 8.9 normal-vision, both below the safe floor. The six hex values are unchanged; the *order* is purple · green · amber · navy · red · black, which lifts the worst adjacent pair to ΔE 14.5 normal / 10.2 tritan. Every chart also ships a legend, direct value labels and a view-as-table toggle, which is what makes the remaining gap legal. **This needs a designer's ratification** — see §4 below. | `styles/tokens.css` | One line |
| L-02 | Charts are hand-rolled SVG/CSS rather than a charting library. Three forms are needed (horizontal bar, single-series line, three-slice donut) and a library would have imported its own colour and type opinions against §7.2. | `ui/charts.jsx` | Contained |
| L-03 | Status *washes* (`--success-bg` etc.) are derived tints not listed in §7.2. They are UI chrome only and never appear as a chart fill. | `styles/tokens.css` | Trivial |
| L-04 | Case age > 7 days is excluded from the approval queue. §10.4 does not bound the queue's contents; an approval queue holding year-old cases reads as a bug. Decided work lives in Audit. | `mock/api.js` `buildQueue()` | Trivial |
| L-05 | Default queue sort treats a **paused** SLA clock as carrying no live risk, so paused items sort below every running clock. §10.4 says "SLA risk desc, then age" without saying what a paused clock does. | `mock/api.js` | Trivial |
| L-06 | Connections completeness is measured over **reconciled** objects; an object still syncing is reported separately rather than counted as a shortfall. Counting an in-flight sync as a gap reports a false failure. | `fixtures/ops.js` | Trivial |
| L-07 | SLA amber threshold is **2 hours to deadline**. §7.6's example ("Breach 42m") implies a band but never states it. | `contracts/format.js` | One constant |
| L-08 | Capability "coverage depth" is defined as *the number of analysts needed to cover 80% of a class's resolved volume*; ≤2 with ≥30 resolved cases is flagged thin. §10.11 says "classes × coverage depth (thin classes flagged)" without defining either term. | `fixtures/aggregates.js` | One function |
| L-09 | The audio artefact is **simulated**: the player runs a clock over fabricated word timings rather than decoding a real file. Per-word confidence, the low-confidence marks, the transport, and the signed-URL refresh all behave as specified; the sound does not exist. Swapping in a real artefact touches only `CALLS` and the `<audio>` binding. | `fixtures/details.js`, `ui/audio.jsx` | Contained |
| ~~L-10~~ | **Closed.** KPI deltas are now computed against the immediately preceding window of the same length, driven by the `?period=` control. Where the corpus holds no comparable prior window the delta is absent rather than estimated. | `fixtures/aggregates.js` | — |
| L-16 | **Open is modelled as a stock, not a flow**, so it carries no period delta. Comparing "open cases created this window" against "open cases created last window" compares a young cohort with an aged one and always shows growth — it reports the shape of the corpus, not the health of the queue. | `fixtures/aggregates.js` | Trivial |
| L-17 | Cases carry a **`resolved_at`** and a **`draft_outcome`**, neither named in `05_Data_Entities`. Without the first, "solved this period" can only be a cohort measure; without the second, the usable-draft-rate target has no per-ticket denominator and the metric silently becomes approvals-over-drafts, which sits far above target for the wrong reason. | `fixtures/corpus.js` | Contained |
| L-18 | Case status **decays smoothly with age** rather than by month bucket. Bucketing left almost nothing older than 30 days open, which made month-over-month comparisons absurd. | `fixtures/corpus.js` | Contained |
| L-19 | Some figures drill to a **filtered case list**, others to the **surface holding their records** (Knowledge, Audit). Both satisfy P-4; what it forbids is a number resolving to nothing. The analyst-roster drill deliberately resolves to the cohort's *casework*, never to a list of people — an ordered list of analysts is the ranking artefact §1.4 forbids. | `fixtures/aggregates.js` | — |
| L-11 | CR-01 / CR-02 / CR-03 are **built behind flags in `config.flags`**, defaulting on. [OD-3] is unratified; a "drop" decision is one boolean each, and S-13 stays because §5.4's no-dead-end rule requires it. | `contracts/config.js` | One boolean each |
| L-12 | The corpus contains **class specialists**: each class has 3–11 handlers with a skewed weighting, so the top one or two carry most of it. Uniform random assignment produced a capability map with no thin classes at all, which would have made §10.11's central claim unreadable. Real support orgs are not uniformly staffed. | `fixtures/corpus.js` | Contained |
| L-13 | The first 26 generated cases are pinned to `auth-sso` inside the last 7 days, seeding the AUTH-341 recurrence the digest narrative depends on. Without it the top cluster was whichever class the RNG happened to favour. | `fixtures/corpus.js` | Contained |
| L-14 | Search results are computed with substring matching over case id / subject / requester. No index, no ranking. | `mock/api.js` | Contained |
| L-15 | Optimistic-locking version tokens are present in the mock's shape but stubbed to `v1`. The 409 path is exercised via the `?conflict=1` hook rather than by real version drift. | `mock/api.js` | Needs a backend |

---

## 3. Spec ambiguities found (proposed, not resolved)

- **OD-1 (Case enum) is honoured as config.** `CASE_TRANSITIONS` is declared next
  to the enum in `contracts/state.js`, but no screen currently offers a
  transition control, so nothing depends on the transition table yet. When
  status-change controls arrive, the guard is already there.
- **A gap in §11.9.** The refresh mechanism is marked [API CONTRACT NEEDED].
  Nothing in this build polls; surfaces render a "last refreshed" stamp and the
  60s stale rule is unimplemented because there is no second read to compare
  against. This is the largest single piece of §11 not built.
- **§10.15's sticky-failure rule vs. "mark all read".** Specified and
  implemented: mark-all-read skips sticky items. But the spec does not say what
  clears a sticky item other than the case leaving `write_failed`. In this build
  nothing clears it — deliberate, and worth confirming.
- **§10.7's class-override control [A-02].** Not built. The spec marks it as an
  assumption to remove if out of scope, and building a mutation on an unratified
  assumption is the wrong default. The classification block is read/expand only.
- **§12.2 storyboard frames.** Not built. [OD-4] proposes storyboard-only
  disposition; three static frames are presentation material, not console work,
  and building them would blur the fence §12 is meant to hold.
- **Audit export.** The Admin-only CSV export button exists and is correctly
  gated, but produces no file — [A-07] ratifies the permission, not the format.

---

## 4. The one thing that needs a designer, not a developer

**The §7.2 chart palette is not colourblind-safe as ordered.** Ran through the
palette validator against the light surface:

```
[FAIL] Lightness band      all six sit in a narrow dark band
[FAIL] Chroma floor        navy, green, amber and black read as grey
[FAIL] CVD separation      worst adjacent purple↔navy ΔE 4.6 (deutan)
[FAIL] Normal-vision floor worst adjacent purple↔navy ΔE 8.9 — below 15
[PASS] Contrast vs surface all six ≥ 3:1
```

This is a direct consequence of "dark, saturated shades only; no pastels" (§7.1)
— that constraint caps the lightness spread a categorical palette needs. The
re-sequencing in L-01 plus mandatory legends, direct labels and table toggles
gets the built charts to a defensible place, and most charts here are
single-series anyway (which needs no categorical separation at all). But a
six-series chart on this palette would still be hard to read, and no amount of
implementation fixes that. **Recommendation:** either widen the ramp with two
lighter-but-still-saturated steps, or cap categorical charts at four series and
use small multiples beyond that. Raised here rather than decided in code.

---

## 4A. Manager-lane remediation (closed after the conformance audit)

A follow-up audit of the Operations Manager's surfaces against §10.3, §10.11,
§13.2 J-DL-B and §13.3 J-CT-2 found eight defects. All eight are now closed:

| # | Defect | Clause |
|---|---|---|
| 1 | Three of six KPI tiles had no drill target — Analysts, KB articles, KB coverage. A direct P-4 breach on the manager's landing screen. | §10.3, P-4 |
| 2 | `?period=` was declared in the route registry and consumed nowhere, so "what changed this month" had no mechanism. Now a real control with computed deltas. | §6.3, §10.3 |
| 3 | KB coverage donut segments did not drill. Gap and thin now open the ranked gap queue. | §10.3 mj2 |
| 4 | **The digest exemplar broke J-CT-2.** The cluster picked its exemplar by array position, landing on a generated case with no linked defect — so the manager's flagship journey stopped one hop before the root cause. Clusters now prefer a case carrying cross-system evidence. | §13.3 J-CT-2 |
| 5 | Digest summary and quality figures were not drillable. | §10.11, P-4 |
| 6 | Analyst roster bars did not drill. Now open the cohort's casework. | §10.3, §1.4 |
| 7 | Audit showed a reject *reason* but not the *draft* that was rejected. | §10.9 mj3 |
| 8 | The three Usefulness metrics from `08_Metrics_KPIs` — usable draft rate, assignment acceptance, KB draft acceptance — appeared nowhere. Added as an Adoption block in the digest, each derived from decision records and drillable. | §1.4, §10.11 |

Two corpus defects surfaced while verifying the above and were fixed rather than
worked around: status was bucketed by month (L-18) and there was no resolution
timestamp (L-17). Both were producing figures that described the generator
rather than the operation.

## 5. What was built, against the spec's own definition of done

| Screen | Route | State |
|---|---|---|
| S-01 shell | all | Built — nav, breadcrumbs, tenant chip, ⌘K, bell, `?` overlay, chords |
| S-02 connections + identity | `/connections`, `/connections/identity` | Built |
| S-03 dashboard | `/overview` | Built |
| S-04 approval queue | `/queue` | Built — full keyboard map, all decision/write states |
| S-05 ticket 360 | `/case/:id` | Built |
| S-06 citations | `/case/:id?tab=citations` | Built |
| S-07 explainers | `/case/:id?tab=explainers` | Built |
| S-08 analyst panel | `/case/:id?tab=assignment` | Built — shadow-only |
| S-09 audit | `/audit` | Built |
| S-10 KB review | `/knowledge` | Built |
| S-11 digest | `/intelligence` | Built |
| S-12 call player | inline in S-05 | Built — simulated audio (L-09) |
| S-13 tickets | `/tickets` + overlay drill | Built — both modes |
| S-14 login | `/login` | Built |
| §10.15 notifications | bell overlay | Built (CR-03 flag) |
| §12 demo lane D-1..D-4 | `/demo/connect/:step` | Built |
| §12.2 storyboard | — | Not built (OD-4) |
| Kitchen sink | `/kitchen-sink` | Built |

**Negative tests, both passing.** There is no "Publish live" control anywhere in
the codebase — `grep -ri "publish.*live"` returns only the comments explaining
its absence. There is no path from a control to an external write that does not
first record a decision: `submitDecision` is the only caller of `runWrite`, and
`refireExecution` refuses without an existing approval record.
