# ITR — Master UI Agent Distribution Plan
**Document:** `ITR_UI_AgentDistribution_v1.md` · **Date:** 10 Aug 2026 · **Author:** Rohan Cherian
**Purpose:** split the build of the clickable ITR console across parallel AI coding agents (Claude Code / separate sessions) so the whole UI lands fast without agents colliding. Source of truth for *what* to build: `ITR_UI_MasterSpec_v2_DeveloperReady.md` (the Spec). Scope contract: `ITR_POC_FeatureList_v2_3Aug2026.xlsx`. This document decides *who builds what, in what order, against which frozen contracts*.

---

## 1. Operating model — how the tandem works

**The one rule that makes parallelism safe: agents share contracts, never files.** Every agent owns an exclusive set of directories (§7 ownership matrix). The only things agents consume from each other are the five frozen contracts in §4. An agent that needs something outside its lane files a request in `CONTRACTS/CHANGELOG.md` — it never edits another lane.

**Waves.** Wave 0 builds the foundation two agents wide. Wave 1 runs six screen agents in parallel. Wave 2 is one integration/QA agent. Nothing in Wave 1 starts before Wave 0's contracts are tagged `v1-frozen`; that half-day of discipline is what prevents six agents rebuilding six different button components.

**Every agent session gets the same preamble** (§8.1), its own scope block (§8.2), and only the Spec sections it needs. Do not paste the whole Spec into every session — context is budget.

**Model allocation (per Aamit's credit discipline):** planning/prompting on Fable high; **all build agents on Sonnet high; escalate a single stuck task to Opus mid, never a whole lane.** Generation-heavy repetition (fixtures) on Sonnet.

**Stack [ASSUMPTION D-01]:** React + Vite SPA, plain CSS custom properties from the token file (no Tailwind — token fidelity per Spec §7 matters more than utility speed), react-router, all data from local fixture JSON behind a mock API module. Aamit declared stack freedom ("React or plain HTML is fine"); if he opts for Go+HTMX after his article, only §3.A1's internals change — lanes and contracts survive.

---

## 2. Build target and honest fidelity

The deliverable is the **clickable wireframe console**: every S-01..S-14 screen and the §12 demo lane, every journey in Spec §13 traversable, running on fixtures — no backend. WriteExecution, retries and chaos states are **simulated by the mock API with scripted timing** so the honesty behaviours (approved ≠ written, 429-resume, honest-delay notices) are demonstrable, not decorative. Everything renders the Spec's states: this build's definition of "clickable" includes empty/loading/error/denied, not just the happy path.

---

## 3. Agent roster

### Wave 0 — Foundation (2 agents, parallel, ~half day)

**A0 · Design System & Component Library**
- **Builds:** `packages/ui/` — tokens as CSS custom properties (Spec §7.2–7.6, hex is truth), all 15 components of Spec §8 with every listed state (incl. mutation-in-progress), a `/kitchen-sink` route rendering every component in every state for review.
- **Spec input:** §7, §8, §11.2 (band behaviours), §11.8 (error copy patterns).
- **DoD:** kitchen-sink screenshot-reviewable; evidence card refuses to render without a source ref (structural P-2); confidence Low state suppresses primary action; zero pastel anywhere.
- **Must not:** build screens, routes, or fixtures.

**A1 · Shell, Routing, Auth Stub & Mock Data Plane**
- **Builds:** `apps/console/src/shell/` (S-01), S-14 login/role picker, router implementing the **route registry Spec §6.3 exactly**, RBAC guard from §11.6 matrix, breadcrumb/Esc/overlay-state machinery (§5.4), notification panel shell (CR-03 — behind a flag), **⌘K global search (CR-02 — behind the same flag mechanism)**, the `?` shortcut overlay, and the **demo header with the Replay toggle [F-088]** — demo-role/flag gated per §11.6 so no product persona can see it (the cache itself is a mock-plane switch: `?replay=1` serves recorded responses); `packages/mock-api/` + `packages/fixtures/` — the Halcyon corpus slice (name from `config.demo_tenant_name` **only**), mock endpoints for every §14A operation with scripted latency/failure hooks, and the state-machine enums of §5.3 exported as the **single shared source** (`packages/contracts/state.ts`).
- **Spec input:** §5.3, §5.4, §6, §10.1, §10.14, §10.15, §11.6, §11.9, §14A, §14C.
- **DoD:** role pick → role-default route; denied deep-link shows §11.6 state; `submitDecision` mock demonstrates approved→queued→retrying→succeeded/failed on demand; fixtures cover every state each Wave-1 agent must render (checklist per lane below).
- **Must not:** style beyond structural layout (consumes A0 as it lands), build feature screens.

**Wave-0 exit gate:** `CONTRACTS/` tagged `v1-frozen` — tokens, component exports, fixture schema, mock-API signatures, state enums, route table. Wave 1 launches only after this tag.

### Wave 1 — Screen lanes (6 agents, fully parallel)

Every lane: consumes contracts, owns its directories, implements its screens to the **full per-screen contract in Spec §10 including Scope Class banners, all states, keyboard maps and a11y**, and self-verifies against its §14B acceptance rows before handoff.

**A2 · Decision lane — S-04 Approval queue** *(the workhorse; most senior lane)*
Spec §10.4 + §5.3.2a/b + §11.7. Exact keyboard map; draft pane with citation anchors and withheld-sentence placeholders; approve/edit(diff)/reject(reason ≥10ch); merge-confirm modal; escalation card variant; decision-vs-write states visible incl. write-failed refire; "already decided by X" conflict path against the mock. **Fixture needs from A1:** items in every band, a merge proposal pair, an escalation, a scripted write-failure, a version-conflict item.

**A3 · Ticket lane — S-05 Ticket 360 + S-12 Call player**
Spec §10.5, §10.12. Identity card fresh/partial/conflict (+deep-link to identity queue), cross-channel timeline with virtualisation, read-context link panels (F-119, no write controls), audio player with synced transcript, per-word confidence marks, signed-URL refresh simulation, full keyboard transport. **Fixtures:** the HFG-2214 voice/email/slack trio, a partial-match actor, a conflict actor, one call artefact with word timings (can be generated tone + fabricated timing JSON — label it).

**A4 · Evidence lane — S-06 Citations panel + S-07 Explainers**
Spec §10.6, §10.7, §11.2. Evidence cards incl. redacted/stale/learned/`evidence unavailable`; filtered-count footer; low-context banner + re-enrich; anchor↔card keyboard linkage; classification block with prior-agreement note; dedup compare view feeding A2's modal (via contract, not import from A2's lane — the compare view lives in §10.7's panel, the modal in S-04); SLA chip expansion (deterministic vs "explanation" prose); trigger-conflict hold. **Fixtures:** a pack with 4-system attribution + one restricted + one redacted + one `learned` citation, a low-context case with cause, a dedup pair at 0.93 and one at 0.71, a held trigger-conflict.

**A5 · Assignment & Ops lane — S-08 Analyst panel + S-02 Connections (+Identity tab)**
Spec §10.8, §10.2, §5.3.4, §5.3.6. Shadow chip + feedback-only semantics; component score bars all drillable to case lists (routes to S-13 panel mode — via route, not import); stretch labelling; no-eligible → escalation suggestion; six system cards with chaos states; reconciliation tables; the identity resolution queue with candidate evidence and resolve/mark/dismiss (audit toast). **Anti-ranking guardrail check is part of this lane's DoD** (no leaderboard artefact anywhere, employment type absent). **Fixtures:** a 3-analyst shortlist with component evidence + one stretch + one below-floor class, an ambiguous actor with two scored candidates, per-system chaos scripts (429-resume, checksum delta), a pre-first-sync system.

**A6 · Insight lane — S-03 Dashboard + S-13 Tickets list + S-11 Digest**
Spec §10.3, §10.13, §10.11. Dark-series charts with "view as table" toggles, every segment → S-13 panel mode with filter chips; S-13 dual mode (page/panel) with URL state; digest as prose-first briefing, every number drillable, capability map + anonymised development areas, below-significance absence. **Fixtures:** aggregates matching S-02's counts [NFR-31], a 14-case cluster with week-over-week movement, a thin-coverage class, an empty-filter result.

**A7 · Governance & Demo lane — S-09 Audit + S-10 KB review + §12 D-1..D-4 + storyboard frames**
Spec §10.9, §10.10, §12. Immutable timeline with diff view and retry entries; completeness header; QA-flag chips; KB two-pane with dedupe warning and update-diff, draft=true verbs, structurally no publish-live; demo lane: concept-locked tiles, discovery tables, staged-estimate plan with hover basis + [ASSUMPTION] tags, two-phase board, fast-forward stepping, the **two distinct controls** (Run incremental sync now = pull job; Simulate incoming event = webhook injection reaching A2's queue through the mock plane); parity storyboard as three static frames clearly labelled non-product. **Fixtures:** a full decision_audit chain incl. a retry sequence and a QA-flagged run, a KB draft + near-duplicate article pair + an update-diff case, connector-run scripts per §5.3.7 state incl. `failed(resumable)`.

### Wave 2 — Integration (1 agent)

**A8 · Integration, Journeys & QA**
- **Owns:** `apps/console/src/journeys-qa/` + the right to file (not fix) cross-lane defects.
- **Does:** wires the eight demo-scene journeys and three critical tasks (Spec §13) end-to-end through the real routes; runs the full §14B acceptance matrix; keyboard-only full pass; WCAG 2.2 AA sweep (focus, live regions, contrast); Scope-Class banner audit; the two negative tests (no publish-live control exists; no ungated write path exists); demo-script binding (which screen state each scene opens on, seeded via fixture bookmarks).
- **Defect protocol:** files issues tagged to the owning lane; only trivial (<5-line) fixes in place, logged.

**Load-balancing note:** A7 is the heaviest lane (2 product screens + 4 demo screens + storyboard). If a seventh Wave-1 session is available, split it: **A7a** Governance (S-09, S-10) · **A7b** Demo lane (§12 + storyboard) — the ownership matrix already separates their paths (`screens/governance/**` vs `demo/**`), so the split is free.

---

## 4. The five frozen contracts (Wave-0 outputs, versioned in `CONTRACTS/`)

1. **Design tokens** — `packages/ui/tokens.css` (Spec §7.2 hex values verbatim; Pantone refs live in the design appendix, not in code).
2. **Component API** — exported props/states of the 15 Spec-§8 components; kitchen-sink is the living reference. A lane needing a new state requests it from A0 via changelog; it never forks a local copy.
3. **State enums & machines** — `packages/contracts/state.ts`: every §5.3 enum (Case [OD-1 config-held], RecommendationDecision, WriteExecution, dedup, assignment-shadow, KB draft, identity, connector). Screens import; nobody redeclares.
4. **Mock-API signatures + fixture schema** — every §14A operation with its Citation DTO, scripted-failure hooks (`?fail=429`, `?conflict=1`, `?slow=3000`), and the fixture manifest listing which records exercise which states. Fixtures are the shared world: one corpus, no lane-local data.
5. **Route registry** — Spec §6.3 table as `routes.ts`; deep-link/overlay params exactly as specified. Cross-lane navigation happens by route, never by importing another lane's components.
6. **Shared utilities** — `packages/contracts/format.ts`: the §11.9 time/date formatter (tenant TZ, relative+absolute tooltip, SLA countdown hook) and the §11.11 event stub (`emit(event, trace_id)` → console/log sink) — one implementation, or six lanes format dates six ways and nobody's clicks are traceable.

**Change control:** contracts are append-only after `v1-frozen`; breaking changes need a changelog entry + the affected lanes' acknowledgement. This is the entire coordination overhead — kept deliberately small.

---

## 5. Dependency graph & schedule

```
Day 0 (first hour)  You: repo scaffold — monorepo skeleton, lane directories from §7, empty CONTRACTS/, lint+format config, branch-per-lane. (10 minutes of human setup that saves every agent inventing structure.)
Day 0 AM   A0 ─┬─ tokens+components ──► v1-frozen ─┐
           A1 ─┴─ shell+routes+mock+fixtures ──────┤ (gate)
Day 0 PM → Day 2   A2 · A3 · A4 · A5 · A6 · A7  (parallel, no cross-imports)
Day 2 PM   A8 integration + acceptance + a11y + demo binding
Day 3      defect burn-down by owning lanes · freeze · demo rehearsal
```
Real dependencies beyond the gate are **fixture dependencies**, all satisfied by A1's checklist (each lane's "fixture needs" above). A2↔A4 share the citation-anchor pattern — defined once in the component contract (A0), consumed by both. A7's simulate-event must land an item in A2's queue — through the mock plane, which A1 owns, so neither lane touches the other.

---

## 6. Per-lane Definition of Done (uniform)

A lane is done when: (1) every owned screen implements its full Spec-§10 contract — layout, all component states, data bound per §14C rules (null behaviours included), keyboard map, a11y notes, Scope-Class banner; (2) its §14B acceptance rows pass by self-check; (3) every number/metric it renders drills somewhere real (route exists); (4) no console errors, no contract forks, no files outside its lane; (5) `LANE_NOTES.md` records assumptions made and any spec ambiguity found (these roll up to the Spec's §15).

---

## 7. File-ownership matrix (merge-conflict prevention)

| Path | Owner |
|---|---|
| `packages/ui/**` | A0 |
| `packages/contracts/**`, `packages/mock-api/**`, `packages/fixtures/**`, `apps/console/src/shell/**`, `routes.ts` | A1 |
| `apps/console/src/screens/queue/**` | A2 |
| `apps/console/src/screens/ticket/**` (360 + call) | A3 |
| `apps/console/src/screens/evidence/**` (citations + explainers) | A4 |
| `apps/console/src/screens/assignment/**`, `screens/connections/**` | A5 |
| `apps/console/src/screens/insight/**` (dashboard, tickets-list, digest) | A6 |
| `apps/console/src/screens/governance/**` (audit, kb), `apps/console/src/demo/**` | A7 |
| `apps/console/src/journeys-qa/**`, `/ISSUES/**` | A8 |
| `CONTRACTS/CHANGELOG.md` | append-only, all |

One branch per lane (`lane/a2-queue` …), merged to `main` only at wave boundaries by whoever runs the sessions (you), in ownership order — with this matrix, merges are mechanically conflict-free.

---

## 8. Session prompts

### 8.1 Common preamble (paste first in every session)
> You are one of several agents building the ITR clickable console in parallel. You own ONLY the paths listed in your scope block; you must not create or edit files outside them. You consume the frozen contracts in `CONTRACTS/` (tokens, component API, state enums, mock-API signatures, route registry) and never redefine them — if something is missing, append a request to `CONTRACTS/CHANGELOG.md` and continue with a clearly-marked local TODO. Build to the attached Spec sections exactly: every listed component state (default/loading/empty/error/stale/partial/low-confidence/permission-denied/mutation-in-progress), the exact keyboard map, the Scope-Class banner, and the null behaviours in the ViewModel rules. Decision and write are separate states everywhere; success never renders on approval alone. No pastel chart colours; no colour-only meaning; WCAG 2.2 AA. Record every assumption in `LANE_NOTES.md`. Do not invent features: anything not in your Spec sections is out of your scope.

### 8.2 Scope block template
> **You are Agent A_n — ⟨lane name⟩.** Own: ⟨paths⟩. Build: ⟨screens⟩ to Spec sections ⟨…⟩ (attached). Fixtures available: ⟨manifest entries⟩. Your acceptance rows: ⟨§14B lines⟩. Forbidden: ⟨adjacent lanes' surfaces⟩. Definition of done: §6 of the distribution plan. Start by restating your scope and listing the states you must render per screen; then build screen-by-screen, states-first, happy-path last.

*(Concrete blocks for A0–A8 are exactly the roster entries in §3 — paste the entry + preamble + the named Spec sections, nothing more.)*

---

## 9. Risks this plan is explicitly designed against

**Component drift** (six agents, six button styles) → killed by Wave-0 gate + kitchen-sink + no-fork rule. **Merge hell** → killed by the ownership matrix; lanes cannot conflict. **Context bloat / cost** → each session gets only its Spec sections; Sonnet default, Opus by exception. **Happy-path bias** → states-first build order in every scope block; A8's matrix is state-heavy. **Silent scope growth** → preamble forbids invention; LANE_NOTES roll ambiguities up to Spec §15 instead of resolving them in code. **The demo trap** — a beautiful queue that can't demo scene 7 → A8 binds fixtures to demo scenes as its first task, not its last.

---

## 10. Open items for you/Aamit before launch
1. Ratify stack [D-01] (React+Vite+CSS-vars) or call Go+HTMX — decides A1's internals only.
2. OD-1/OD-2/OD-3 from the Spec materially shape A2/A5/A6 (Case enum, shadow-only, CR-01/02/03) — the lanes build to the Spec's stated defaults if unanswered, flagged in LANE_NOTES.
3. Confirm `config.demo_tenant_name` before A1 generates fixtures (find-replace later is cheap but avoidable).
4. Who runs the sessions: one person (you) can drive Wave 1 six-wide; if Tausif/Manas take lanes, hand them this doc + their §3 entry only.

*End of ITR_UI_AgentDistribution_v1.md*
