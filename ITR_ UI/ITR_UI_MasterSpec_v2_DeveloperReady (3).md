# ITR — Master UI & Product Specification
**Document:** `ITR_UI_MasterSpec_v1.md` · **Version:** 2.0 (developer-ready — v3 prompt corrections + PM readiness review applied) · **Date:** 10 August 2026
**Scope authority:** `ITR_POC_FeatureList_v2_3Aug2026.xlsx` — 137 features · 16 epics · 12 agents · 6 emulated source systems · 8 demo scenes
**Vendor / product:** Motiveminds ITR · **Demo tenant:** Halcyon Foods Group **[ASSUMPTION A-01]**
**Tenant name is a single config value** (`config.demo_tenant_name`). Every occurrence of "Halcyon Foods Group" in this document and in the build resolves from that one value, so A-01's eventual answer is a one-line change. No screen, fixture or copy string may hard-code it.

---

## 1. Purpose, scope and how to read this document

### 1.1 Purpose
This document is the single specification from which the ITR user interface is designed, built and tested for the 4-week POC. It defines the product narrative, the personas, every flow, every user journey, the visual design system, the component library, and a complete specification for each of the fourteen product-console screens (S-01–S-14) and the shell's notification panel, plus the fenced Demo Swim Lane at the same depth. It is written so that a Product Manager, UX Designer, UI Designer, Frontend Engineer, Backend Engineer and QA Engineer can build without repeatedly asking basic clarification questions.

### 1.2 Scope
- **In scope:** every UI-bearing feature in `02_Feature_List` (137 features; §14 classifies all of them). This is a **4-week POC, not the 10–12-week sellable MVP** — the twelve core screens are **POC product-console surfaces**, not "the real product". Demo-grade means polished and honest, not fake: every count is a live query, every claim is cited, every write is gated.
- **Scope Class (mandatory, declared on every screen, flow and journey):** `POC functional` — must actually work in the POC · `POC demo-only` — exists to make the demo legible, no production promise · `Future/MVP` — context only, not designed here · `Out of scope` — must not appear in the console. Where workbook sheets conflict, the conflict is recorded in §15 as an Open Decision — never silently resolved.
- **Out of scope:** everything in `09_Out_of_Scope`, restated in §1.4. Nothing in this document designs an excluded capability into the product console.
- **Deployment context:** single-tenant, customer-hosted, desktop-first. No native mobile [09_Out_of_Scope]. React console with auth stub and design tokens [F-079].

### 1.3 How to read this document
1. Read §3 (Product narrative) first — it is the spine everything else hangs on.
2. §5 (Flows) defines the lifecycle, the agent-to-UI map, the state machines and the navigation graph. Every screen spec in §10 assumes these.
3. §9 (Feature catalogue) describes each UI-bearing feature in PM terms; §10 specifies the screens that realise them. Catalogue = *what and why*; screen spec = *where and how*.
4. §13 (User journeys) threads the screens back together, step by step, with failure branches.
5. §14 is the traceability matrix. If a screen element cannot be traced there, it does not ship.
- **Feature IDs** are cited inline as `[F-###]`. Non-functional constraints as `[NFR-#]` referencing `07_NonFunctional`. Assumptions as **[ASSUMPTION A-##]**, consolidated in §15.

### 1.4 Binding exclusions (from `09_Out_of_Scope`)
The console contains: **no** autonomous (non-HITL) execution — not even a disabled toggle, because a disabled path is a path; **no** workforce management — no shift planning, rostering, forecasting, absence, round-robin; **no** analyst ranking, appraisal or performance-management surface — capability signals route work and surface support needs, never rank people; **no** end-user chatbot in the product (the demo chat portal is fenced in §12); **no** predictive volume forecasting; **no** multi-tenant switching; **no** native mobile. Only numbers listed in `08_Metrics_KPIs` may appear on any screen.

---

## 2. Product principles and the recommendation-only stance

**P-1 · The system recommends. A human decides.** No external write occurs without an explicit, recorded, attributable human approval [F-093, NFR-18]. **Corrected scope of the stance:** every AI output is shown with its evidence and confidence, but only outputs whose feature or HITL gate requires action carry approve/edit/reject controls — purely informational or shadow-mode outputs do not get mutation controls. A human decision and its external write are **separate states**: approval recorded ≠ write succeeded, and the UI never shows success on the approval record alone (§5.3.2b). There is no "auto" mode anywhere, and no setting that could create one.

**P-2 · No claim without a citation.** An uncited claim is indistinguishable from a hallucination. The UI structurally refuses to render an uncited claim [NFR-16]: the evidence card component (§8.4) requires a source reference to render its body, and the draft renderer suppresses any sentence lacking a citation anchor, replacing it with a "withheld — no supporting evidence" placeholder [F-066, F-083].

**P-3 · Confidence is honest, calibrated, and consequential.** Confidence is shown as a labelled band — High / Medium / Low — with the numeric score on hover [F-077]. The Low band *changes behaviour*: it suppresses one-click approve, expands evidence by default, and routes to "needs human triage" rather than guessing [F-059, F-054].

**P-4 · Every number resolves to its evidence.** Any metric, score or count on screen is click-through to the records that produced it [F-126, NFR-42]. A number that cannot be drilled into is decoration and is not permitted.

**P-5 · Emulated is labelled, everywhere, always.** Every source is labelled *Emulated* on the connections screen, and the global tenant bar carries a persistent "Synthetic data" chip [F-121, NFR-44]. An unfamiliar viewer must correctly identify emulation without being told.

**P-6 · The audit trail is the product's memory.** Recommendation → evidence → confidence → model/version → human decision → action → outcome, as one immutable timeline per ticket [F-085, F-089]. Every approval or rejection the user performs is itself rendered back to them in the audit viewer — the UI closes its own loop.

**P-7 · Density with keyboard-first ergonomics for the analyst; overview-to-detail for the manager.** The analyst screens optimise seconds-per-decision; the manager screens optimise questions-per-glance, and every overview resolves into detail on click — never a dead-end dashboard.

## 2A. Terminology and glossary
**ITR** — the product (Motiveminds). **Digital twin** — the canonical model built from the six emulated sources. **Canonical entity** — a `05_Data_Entities` object every screen renders. **Context pack** — the cited, PII-filtered, token-budgeted evidence bundle compiled per case [F-051]. **Evidence card** — the UI unit rendering one pack item with provenance (§8.4). **Citation anchor** — the `[n]` marker linking a draft sentence to its card. **Recommendation** — any agent proposal shown to a human. **Decision** — the human's recorded approve/edit/reject (§5.3.2a). **Write / WriteExecution** — the external mutation performed by the Action Executor after approval (§5.3.2b); *decision ≠ write*. **HITL gate** — a point where the flow cannot proceed without a recorded human action. **Shadow mode** — assignment proposes and records feedback but performs no external routing write [F-064]. **ResolutionRecord** — the captured outcome that feeds retrieval [F-078]. **Emulated** — a high-fidelity replica source system; never a live tenant [F-121]. **Scope Class** — POC functional / POC demo-only / Future-MVP / Out of scope (§1.2). **CR** — change request, unratified addition (§16). **OD / A-nn** — Open Decision / assumption (§15). **Band** — calibrated High/Medium/Low confidence label (§11.2). **Stub user/role** — the auth-stub identity picked at S-14 that audit rows attribute to.

---

## 3. Product narrative — the life of a ticket and how the features connect

### 3.1 Product thesis
ITR is an agentic AI layer for enterprise support operations that sees what no single tool sees. It ingests six enterprise systems — Zendesk, Salesforce Service Cloud, Workday, Jira, Microsoft Entra, Slack/Teams — into one canonical model (the digital twin), runs a twelve-agent pipeline over every ticket, and returns *recommendations with evidence*: who this requester really is, what this issue really is, what we already know about it across every system, who is measurably best placed to handle it, and what a cited draft resolution looks like. It does this better than incumbent tooling for one structural reason: the incumbent sees one system; ITR's context pack spans at least three [NFR-33]. And it is trustable for one structural reason: a human approves every write, and every decision is audited [P-1, P-6].

### 3.2 The life of a ticket — end to end
One issue, followed from arrival to organisational learning. Each stage names the agent (from `04_Agent_Specs`), the canonical entities produced (from `05_Data_Entities`), and the screen where a human sees it.

**Scene 1 — Six systems, one twin.** Before any ticket: the six emulated sources are connected, backfilled and reconciled. *Agent 1 · Listener* (deterministic, no LLM in the hot path) ingests via the real adapter contract; the reconciliation job proves 100% completeness [F-120]. → Entities: every canonical table seeded; `connector_run_id` on every row [NFR-32]. → **Seen on:** Connections view (S-02), Corpus dashboard (S-03).

**Scene 2 — An issue arrives.** Daniel Okafor in Payroll Ops at Halcyon calls the support line: "SSO login fails since the password rotation." The call is a real audio artefact, transcribed by a real ASR engine with per-word confidence [F-133]; the transcript is normalised into a canonical `Comment` with `channel=voice`, `audio_uri`, `asr_confidence` [F-134]. The same issue also lands by email and a Slack thread. → Entities: `Case HFG-2214`, `Comment` ×3 (voice, email, slack), `call_recording`. → **Seen on:** Ticket 360 timeline (S-05), Call player (S-12).

**Scene 3 — Who is this.** *Agent 2 · Context Enricher* triggers identity resolution: Daniel is matched across Zendesk (requester), Workday (Worker, org unit, manager chain), Entra (groups, devices, sign-ins) and Salesforce (account contact) in under 2 seconds [E05, NFR-3]. → Entities: resolved `Actor`, cached 360 summary card [F-045]. → **Seen on:** Ticket 360 (S-05).

**Scene 4 — What is it.** *Agent 3 · Triage/Classifier* (Haiku-first, Sonnet on low confidence) classifies to the 100-class taxonomy with calibrated confidence, consuming Zendesk's own AI fields as a prior [F-059, F-061]. *Agent 4 · Dedup & Linker* finds the two sibling tickets from email and Slack and **proposes** a merge — never auto-merges [F-060]. *Agent 5 · Prioritisation* computes SLA breach risk deterministically; the LLM writes only the explanation [F-062]. A linked Jira defect (AUTH-341) surfaces via the Jira adapter. → Entities: `Category/Intent` set on Case, merge proposal, `SLAClock` risk, Jira issue link. → **Seen on:** Explainers panel (S-07).

**Scene 5 — What do we know.** The *Context Compiler* runs hybrid retrieval — vector + BM25 + graph expansion, reciprocal-rank fusion, cross-encoder rerank — applies the trust filter and PII redaction, and compresses into a token-budgeted, **cited** context pack spanning ≥3 systems [F-050, F-051, F-052, NFR-33], compiled in p95 < 2 s [NFR-1]. → Entity: context pack with per-source attribution. → **Seen on:** Context & citations panel (S-06).

**Scene 6 — Who should handle it.** The capability engine scores every eligible analyst on measured evidence — class experience 0.30 · outcome quality 0.25 · skill match 0.20 · efficiency 0.10 · load & availability 0.10 · level appropriateness 0.05; employment type never scored [F-127]. *Agent 6 · Assignment* applies trigger-conflict checks and proposes, in shadow mode first [F-063, F-064, F-065]. Priya Nair (L2) tops the shortlist on 41 handled `auth-sso` tickets, 94% CSAT. Every number is click-through to its tickets [F-126]. → Entities: `analyst_class_experience`, `analyst_capability_signal`, assignment proposal. → **Seen on:** Analyst recommendation panel (S-08).

**Scene 7 — What should we do.** *Agent 7 · Resolution* drafts a cited reply grounded strictly in retrieved evidence — ResolutionRecords, KB articles, the 20 authored runbooks [F-066, F-067], injection-resistant [F-068]. Priya reviews it in the approval queue beside its evidence, edits one step, approves. *Agent 9 · Action Executor* (deterministic) performs the gated write-back to Zendesk, records the `decision_audit` row and a new `ResolutionRecord` [F-070, F-089]. If confidence had been low or no match found, *Agent 8 · Escalation* guarantees a path — a draft or an escalation, never neither [F-069]. → **Seen on:** Approval queue (S-04), Audit viewer (S-09).

**Scene 8 — What did we learn.** *Agent 10 · KB Curator* drafts an article from the ResolutionRecord — draft only, publication gated [F-072]. *Agent 12 · Pattern Miner* finds the recurrence: fourteen SSO tickets since the rotation, a deflection candidate and a KB gap [F-073, F-074]. *Agent 11 · QA/Verifier* (Opus, sampled) scores the run for groundedness and calibration [F-076]. The weekly digest lands on the support director's desk [F-075]. → **Seen on:** KB draft review (S-10), Weekly digest (S-11), Audit viewer (S-09).

### 3.3 The compounding loop
Scene 8 is not the end of the flow; it is the input to the next one. Every approved, edited or rejected outcome is captured as a `ResolutionRecord` [F-078] whose `issue_signature` vector joins the retrieval corpus. The next SSO ticket retrieves Priya's approved fix as first-class evidence; the KB Curator's accepted article deflects the one after that; the Pattern Miner's cluster prompts the root-cause fix that prevents the rest. The product is measurably more valuable in week four than in week one, and the UI makes the loop visible: the audit viewer shows outcome → ResolutionRecord, and the citations panel shows prior resolutions being cited back.

### 3.4 The whiteboard map — features to stages to screens
```
STAGE A · UNDERSTAND        STAGE B · ROUTE            STAGE C · RESOLVE          STAGE D · LEARN
Agents 1-4                  Agents 5-6                 Agents 7-9                 Agents 10-12
Listener · Enricher ·       Prioritisation ·           Resolution · Escalation ·  KB Curator · QA/Verifier ·
Triage · Dedup              Assignment (shadow)        Action Executor            Pattern Miner
    |                           |                          |                          |
    v                           v                          v                          v
S-02 Connections            S-07 Explainers            S-04 Approval queue        S-10 KB draft review
S-03 Corpus dashboard       S-08 Analyst panel         S-06 Citations panel       S-11 Weekly digest
S-05 Ticket 360             (SLA badge on S-04/05/07)  S-09 Audit viewer          S-09 Audit viewer
S-12 Call player
                HUMAN GATES: identity resolve (F-044, S-02) · merge confirm (A4) · routing gate (A6) · EVERY write (A7/A9) · KB publish (A10)
```
Read left to right for the life of a ticket; read the bottom row for where a human decides. There is exactly one path to an external write, and it runs through an approval record.

---

## 4. Personas and their day-in-the-life journeys

### 4.1 Persona A — Support Analyst / Consultant (primary)
**Who:** Priya Nair, L2 analyst, identity & access class specialist, 41 `auth-sso` tickets handled, works the queue ~6.5 h/day. **Goal:** clear the approval queue accurately and fast. **Cares about:** how fast can I judge whether this draft is right; where is the evidence; what exactly am I approving; how do I get to the next one without touching the mouse. **Design consequences:** keyboard-first [F-081]; density over whitespace; evidence adjacent to draft, never behind a navigation; confidence must be glanceable; reject must demand a reason but cost ≤5 seconds.

**Day in the life** *(canonical narrative — §13.2 formalises it as entry/paths/failure/exit and does not repeat the steps; one source, no drift)*:
09:00 opens **Approval queue (S-04)** — 23 pending, sorted by SLA risk. 09:01 `J` to first item, draft left / evidence right; scans three evidence cards, `A` approves; toast confirms audit row. 09:04 next item is Low confidence — one-click approve suppressed; `X` expands the context pack, opens **Ticket 360 (S-05)** in the side panel to check the requester's device from Entra; edits the draft (`E`), approves the edit. 09:20 a merge proposal appears from Dedup — reviews the two linked tickets side by side, confirms merge. 10:45 a voice ticket: opens **Call player (S-12)** from the timeline, jumps to the low-confidence words, corrects her judgement of the customer's actual ask, rejects the draft with reason "transcript misread account ID". 12:30 checks her own decisions in **Audit viewer (S-09)** for a disputed ticket. Through the day she never leaves the queue for more than one screen's depth, and returns with `Esc`.

### 4.2 Persona B — Operations Manager / Support Director
**Who:** Marcus Adeyemi, support director, 240 analysts across 40 teams. Does not work individual tickets. **Goal:** keep the operation healthy and improving. **Cares about:** is the queue healthy; what is at SLA risk; where is team capability thin; what patterns recur; what did the system get right and wrong this week. **Design consequences:** overview → detail on click, never a dead end [P-7]; every number backed by tickets [P-4]; development areas anonymised by employment type [F-129]; no ranking surface exists [§1.4].

**Day in the life (J-DL-B):** Monday 08:30 opens **Weekly digest (S-11)**: three recurring clusters, one deflection candidate, two KB gaps, one SLA hotspot, team capability map. Clicks the SSO cluster → the fourteen tickets behind it → one exemplar in **Ticket 360**. 08:50 reviews the capability map: `payroll-integrations` is thin — two analysts carry 80% of volume; opens the development-areas list (anonymised by employment type) and notes a coaching action outside the system. 09:10 checks **Corpus dashboard (S-03)** for volume by channel and tier; clicks the enterprise-tier bar → filtered case list. 09:30 in **Audit viewer (S-09)** filters last week's rejections, reads reject reasons to see where drafts fail. He never sees a per-analyst ranking, and every claim he forwards to his own leadership is click-through evidenced.

### 4.3 Persona C — Platform Admin
**Who:** Sutej-role platform admin at Motiveminds. **Goal:** the pipeline is connected, complete, and auditable. **Cares about:** connection state of six systems; ingestion completeness; audit integrity; RBAC; whether anything is broken. **Design consequences:** reconciliation status is first-class [F-120]; emulated labelling unambiguous [F-121]; chaos-mode behaviour (429/500/slow/partial) surfaces as honest status, not silent failure.

**Day in the life (J-DL-C):** 08:00 opens **Connections view (S-02)**: six systems, last sync, object counts, completeness 100%; Zendesk shows a 429 backoff event from the overnight backfill — resolved by Temporal retry, zero loss [NFR-9]. 08:15 runs the demo-tenant onboarding rehearsal in the **Demo Swim Lane connector journey (§12.1)**. 08:40 verifies audit completeness [NFR-15] in **Audit viewer**, spot-checks that every demo-path write has an approval record. 09:00 reviews RBAC assignments; confirms the analyst role cannot see the audit export.

---

## 5. Flows — lifecycle, agent-to-UI map, state machines, navigation graph

### 5.1 End-to-end ticket lifecycle flow (all branches)
Trigger → agent → output → human gate → next state → screen. The spine is §3.2; the branches are binding UI behaviour.

1. **Intake.** Webhook/export event → *Listener* → canonical `Case`+`Comment`, idempotent on `external_id` [F-057]. No gate. → Case `status=new`. Voice branch: audio → TTS/ASR pipeline → transcript Comment with `asr_confidence` [F-133, F-134] → Call player available.
2. **Enrich.** Case → *Context Enricher* → identity resolution [F-042/043] + cited context pack. **Branch — sub-threshold identity:** match below threshold ⇒ never guessed; queued to the unresolved-identity queue (S-02 Identity tab) for human resolution [F-044]; the case proceeds with a partial-identity annotation. **Branch — low context:** retrieval below threshold ⇒ low-context flag raised, pipeline pauses for enrichment rather than answering [F-054]; S-06 shows the flag state; the approval queue shows the item as "awaiting context".
3. **Classify.** → *Triage* → intent/category/priority/sentiment/language + confidence [F-059]. **Branch — low confidence:** ⇒ "needs human triage" state, never a guess; queue badge "Triage needed"; Haiku escalates to Sonnet once before flagging.
4. **Dedup.** → *Dedup & Linker* → similarity + fingerprint [F-060]. **Branch — high score:** merge *proposal* → human confirm gate on S-04/S-07 → on confirm, cases merged and audit row written; on decline, cases linked only. **Branch — mid score:** link only, no proposal.
5. **Prioritise.** SLAClock events → *Prioritisation* → deterministic score + breach-risk flag; LLM writes prose only and can never change the number [F-062]. Recomputes on every SLAClock event; badge updates live on S-04/S-05/S-07.
6. **Assign.** Capability engine shortlist → *Assignment* → proposal + ranked alternatives + rationale [F-063]. **Shadow mode:** proposes without acting [F-064]; the routing gate is a human accept on S-08. **Branch — trigger conflict:** a customer automation would fire ⇒ proposal annotated with the conflicting trigger and held [F-065].
7. **Resolve.** Context pack + ResolutionRecords + runbooks → *Resolution* → cited draft + confidence [F-066]. **Branch — approve:** human approves on S-04 ⇒ *Action Executor* performs gated write, `decision_audit` + `ResolutionRecord` written [F-070]. **Branch — edit:** human edits then approves ⇒ edited text written; edit distance recorded. **Branch — reject:** mandatory reason ⇒ no write; case returns to queue with reject context; Resolution may re-draft once with the reason as added instruction. **Branch — low confidence / no match:** *Escalation* produces a structured summary + suggested owner [F-069] — every ticket gets a path: a draft or an escalation, never neither.
8. **Learn.** Close → ResolutionRecord [F-078] → *KB Curator* draft (publish-gated on S-10) [F-072] → *Pattern Miner* weekly batch (S-11) [F-074] → *QA/Verifier* samples runs incl. all low-confidence [F-076] → calibration updates thresholds [F-077].

**Failure/chaos branches (all stages):** emulator returns 429/500/slow/partial ⇒ Temporal resumes from checkpoint, zero loss [NFR-8, NFR-35]; the UI shows honest status ("rate-limited, retrying — no data loss") on S-02, never a silent spinner.

### 5.2 Agent-to-UI map — one row per agent
| # | Agent | Stage | Produces | Surfaced on | HITL gate | Human can |
|---|---|---|---|---|---|---|
| 1 | Listener | A | Canonical records, idempotent | S-02 sync status, S-03 counts | — | Observe completeness; trigger Sync now (demo) |
| 2 | Context Enricher | A | Cited, PII-filtered context pack | S-06 evidence cards; low-context flag | — | Expand/inspect citations; request re-enrich |
| 3 | Triage/Classifier | A | Intent, category, priority, sentiment, language, confidence | S-07 classification block; S-04 badges | — (low conf ⇒ human triage state) | Override class **[ASSUMPTION A-02: override is a proposal-correcting act recorded in audit]** |
| 4 | Dedup & Linker | A | Merge/link proposals + similarity | S-07 duplicates block; S-04 proposal card | **Merge confirm** | Confirm merge / keep link / dismiss |
| 5 | Prioritisation | B | Deterministic priority + breach risk + reason | SLA badge on S-04/S-05/S-07 | — | Read reason; number is not editable |
| 6 | Assignment | B | Proposal + ranked alternatives + rationale | S-08 panel | **Routing gate** | Accept proposal / pick alternative / decline (shadow) |
| 7 | Resolution | C | Cited draft actions + confidence | S-04 draft pane; citations in S-06 | **Every write** | Approve / edit / reject-with-reason |
| 8 | Escalation | C | Structured escalation summary + suggested owner | S-04 escalation card; S-05 timeline | — | Accept owner / reassign target |
| 9 | Action Executor | C | External write + audit + ResolutionRecord | S-09 timeline; toast on S-04 | **Post-approval only** | None — deterministic; user sees outcome |
| 10 | KB Curator | D | Draft article / update proposal | S-10 review | **Publish gate** | Approve-as-draft / edit / reject-with-reason |
| 11 | QA/Verifier | D | Quality score, flagged runs, calibration | S-09 flags; S-11 quality section | — | Review flagged runs |
| 12 | Pattern Miner | D | Weekly digest: patterns, deflection, gaps | S-11 | — | Drill into clusters; act outside system |

### 5.3 State machines
**5.3.1 Case lifecycle** — `Case.status_category`. **[OPEN DECISION OD-1]** `05_Data_Entities` names the field but does not define its values or legal transitions. Proposed enum (Zendesk-aligned, marked **[ASSUMPTION]** until the architect ratifies): `new → open → pending → hold → solved → closed`, plus `solved → open` (reopen). Proposed triggers: `new→open` first agent/human touch; `open→pending` awaiting requester; `open/pending→hold` awaiting third party (e.g. Jira defect); `→solved` only via an approved resolution write or human manual solve; `solved→closed` policy timer; `solved→open` requester reply (feeds reopen_rate). Per-state UI: status chip with colour+icon+label; `hold` shows the blocking link; `solved` shows the resolving ResolutionRecord; illegal transitions are not offered as controls. The build treats the enum as config so OD-1's answer is not a refactor.
**5.3.2a RecommendationDecision** (human decision — one machine): `draft_pending → in_review → approved | edited_approved | rejected`; `rejected → redrafted(once) → draft_pending`; `superseded` when a newer draft replaces an undecided one. Guards: `rejected` requires a non-empty reason [F-081]; decision rows record actor + time [F-089]; there is no bypass transition [NFR-13].
**5.3.2b WriteExecution** (external effect — a second, linked machine): `not_started → queued → executing → retrying(n) → succeeded | failed`. An approved decision with a pending write is a **visible intermediate state** ("approved · writing…"); `retrying` shows attempt count; `failed` is terminal-until-refired, keeps the approval, and flags the queue item "write failed — action required" [F-070]. UI copy exists for every state; success renders only on `succeeded`.
**5.3.3 Dedup proposal:** `link_proposed | merge_proposed → human_confirmed | declined`; `human_confirmed → write_pending → merged | write_failed`. Agent 4 never merges; **a merge is an external write command** and enters the same central HITL gate → ActionExecutor path as any write (§11.3) [F-060].
**5.3.4 Assignment proposal (shadow):** `proposed → conflict_held | feedback_accepted | feedback_overridden`. **POC default is shadow-only [F-064]:** accept/override records evaluation feedback and an audit row — it performs **no external assignment write**. A write-enabled mode exists only if the architect confirms it **[OPEN DECISION OD-2]**; until then no write-path states exist and the panel's `Shadow` chip says "recommendations only — no ticket is reassigned".
**5.3.5 KB draft:** `generated → under_review → edited → approved_for_draft_write → draft_created|draft_updated | write_failed`, or `rejected(reason)`. The approved verb is precisely **"Create/update Zendesk Guide draft (draft=true)"** — no state and no control can make content publicly live; a "Publish live" control is prohibited [F-072, F-086].
**5.3.6 Identity resolution [F-044]:** `matched | ambiguous → queued → human_resolved(candidate) | marked_new_actor | dismissed(reason)`. Resolution writes an audit row and retro-links the actor's cases; surfaced on S-02 Identity tab (§10.2) with S-05 deep-link.
**5.3.7 Connector run (demo lane, §12):** `configured → initializing → discovering → awaiting_confirmation → ingesting → reconciling → complete | failed(resumable)`. "Complete" means **an emulated ingestion run completed** — the word "live" is never used of an emulated source.
For every transition above: actor, trigger, preconditions, audit event, UI message and recovery path are as stated per screen in §10/§12.
### 5.4 Screen-to-screen navigation graph — no dead ends
```
Login (S-14) ──role──> Shell (S-01) ── left nav ──> S-02 Connections · S-03 Dashboard · S-04 Queue · S-13 Tickets · S-09 Audit · S-10 KB review · S-11 Digest
S-04 Queue ⇄ S-05 Ticket 360 (side panel or full) ⇄ S-06 Citations · S-07 Explainers · S-08 Analyst panel (panels within 360/queue detail)
S-05 timeline ──> S-12 Call player (inline expand) ──Esc──> S-05
S-03 any chart segment ──> S-13 (panel mode, filter applied) ──> S-05 · back via breadcrumb
S-11 any cluster/number ──> S-13 (panel mode) ──> S-05 · back via breadcrumb
S-08 any evidence number ──> S-13 (panel mode, case-id set) ──> S-05
Bell ──> Notification panel (overlay) ──deep-link──> exact screen state
S-02 Identity tab ⇄ S-05 conflict state (deep-link both ways)
S-09 any timeline entry ──> S-05 / S-06 evidence source · back via breadcrumb
Global: breadcrumb always present; Esc closes the topmost panel; ⌘K/CTRL-K search from anywhere → S-13 results mode (direct case-id hit skips to S-05).
```
Rule: every drill-down keeps its origin in the breadcrumb; every panel closes back to its parent; the queue position is preserved on return (the analyst never loses her place).

### 5.5 Cross-cutting interaction flows
- **Approve/edit/reject:** select item → review draft+evidence → `A` approve (confirm toast, audit row, Executor fires) · `E` edit (inline editor, diff preserved, approve commits edited text) · `R` reject (reason modal, mandatory, submit returns item to queue with reason attached). All three write `decision_audit` immediately [F-089].
- **Number drill-down:** click any metric → side panel lists the backing records (case IDs, per NFR-42) → click a record → S-05. Breadcrumb: origin › metric › record.
- **Low-context / low-confidence fallback:** flag state renders amber "insufficient context/confidence" banner with the *reason* (retrieval score / calibration band), the option to request re-enrichment, and suppressed fast-approve [F-054, P-3].
- **Run incremental sync now (demo only, corrected semantics):** enqueues an incremental pull/sync job against the emulators — a manual sync is a pull, not a webhook. A separate, explicitly demo-only **"Simulate incoming event"** control injects a synthetic source event (e.g. the live-meeting email) so a presenter can trigger source-push behaviour; the two controls are never conflated (§12.1 D-4).

---

## 6. Information architecture and global navigation

### 6.1 IA
Entry to the console is the auth-stub login (S-14), where role selection drives everything RBAC-conditional. Two-level IA. Level 1 (persistent left nav, RBAC-conditional [F-094]): **Overview** (Corpus dashboard) · **Queue** (Approval queue) · **Tickets** (S-13 list/search → Ticket 360) · **Knowledge** (KB draft review) · **Intelligence** (Weekly digest) · **Audit** (Audit viewer) · **Connections** (admin) · **Demo** (Demo Swim Lane — visible only to the demo role, visually fenced with a striped "DEMO" header). Level 2: panels within a ticket context — 360, Citations, Explainers, Analyst panel, Call player — presented as tabs/side panels inside the ticket detail, not separate nav destinations.

### 6.2 Global elements [F-079]
- **Top bar:** product mark (Motiveminds ITR) · tenant chip ("Halcyon Foods Group · Synthetic data" — the emulation label is part of the chip, non-dismissable [F-121]) · global search (⌘K: cases by ID/requester/subject; analysts; articles) · notification bell (approval outcomes, escalations to me, digest ready) · user menu (role shown; no tenant switcher exists [§1.4]).
- **Breadcrumbs:** always rendered under the top bar; every drill-down appends; every crumb navigable.
- **Notification model:** in-app only for POC. Three classes: *action needed* (assigned escalation, merge to confirm), *outcome* (your approval executed / failed-and-retried), *digest ready*. Click-through deep-links to the exact screen state. Full panel spec in §10.15. **[ASSUMPTION A-03: no email notifications in POC].**
- **Keyboard map (global):** `⌘K` search · `g q` queue · `g d` dashboard · `g a` audit · `Esc` close panel · `?` shortcut overlay. Queue-local keys in §10.4.
- **Empty/loading/error states [F-088]:** every route has all three designed (§11.5); skeleton loaders for lists, deterministic placeholders for panels, error states always name the failing dependency and the retry action.

### 6.3 Screen registry & route/deep-link contract
Routes are a UI design decision **[ASSUMPTION]** — logical, stable, and deep-linkable; the backend contract behind them is OD-5. Panel-capable screens accept their params as overlay state so deep links restore the exact screen state (§10.15 requirement).

| ID | Route (logical) | Params / URL state | Modes |
|---|---|---|---|
| S-14 | /login | ?next= (deep-link continuation) | page |
| S-01 | shell (all routes) | — | persistent |
| S-02 | /connections · /connections/identity | ?system=, identity: ?actor= | page |
| S-03 | /overview | ?period= | page |
| S-04 | /queue | ?type=&class=&risk=&band=&team=&sort=&item= | page |
| S-05 | /case/:id | ?tab=(360|citations|explainers|assignment)&entry= | page + panel |
| S-06/07/08 | /case/:id?tab=… | as above | panel (tabs) |
| S-09 | /audit | ?from=&to=&type=&actor=&outcome=&flagged=&row= | page |
| S-10 | /knowledge | ?tab=(drafts|updates|gaps)&draft= | page |
| S-11 | /intelligence | ?week= | page |
| S-12 | /case/:id?play=:commentId&t=:sec | timestamped deep link | inline expand |
| S-13 | /tickets | full filter set as query params; &panel=1 in drill mode | page + panel |
| §10.15 | overlay | ?note= marks read on land | overlay |
| §12 | /demo/connect/(1..4) | Demo role only; state per §5.3.7 | fenced pages |
Back-navigation: breadcrumb origin always encoded; Esc pops overlay state without touching the underlying route (§5.4).

## 7. Visual design system and tokens

### 7.1 Direction
Light mode only for the POC; dark mode noted as a future toggle and not designed. White/near-white surfaces; one primary hue — **deep purple** — plus black and a neutral grey ramp; no second *brand* accent hue. **Clarification (v3):** the semantic colours in §7.2 (success/warning/error/info/low-confidence/emulated) are permitted alongside the single brand primary — they are status semantics, not additional brand accents. All data/status colours are dark, saturated, Pantone-referenced shades; no pastels, no light orange/yellow, no salmon. **[ASSUMPTION A-04: purple chosen over blue per direction "blue or purple, pick one and hold it" — confirm.]**

### 7.2 Colour tokens (hex · nearest Pantone)
| Token | Hex | Pantone (nearest) | Use |
|---|---|---|---|
| `--surface-0` | #FFFFFF | — | Page background |
| `--surface-1` | #FAFAFB | — | Panel background |
| `--surface-2` | #F2F2F5 | Cool Gray 1 C | Table stripe, wells |
| `--border` | #D9D9DE | Cool Gray 3 C | Hairlines |
| `--ink-900` | #111114 | Black 6 C | Primary text |
| `--ink-600` | #4A4A52 | Cool Gray 9 C | Secondary text |
| `--ink-400` | #7C7C86 | Cool Gray 7 C | Tertiary/disabled text |
| `--primary-700` | #3B1E6E | 2695 C | Primary actions, active nav |
| `--primary-600` | #4C2A8C | 2685 C | Primary hover, links |
| `--primary-100` | #ECE6F7 | 2635 C (tint, UI-only) | Selected row wash — never in charts |
| `--success-700` | #0F5132 | 3435 C | Success/approved |
| `--warning-700` | #7A4E00 | 1405 C | Warning/medium confidence/SLA amber |
| `--danger-700` | #7F1D1D | 1815 C | Error/breach/rejected |
| `--info-700` | #1E3A5F | 534 C | Informational |
| `--emulated-700` | #5B21B6 on #EDE9FE | 2665 C | Emulated-source badge (icon+label, never colour alone) |
| Chart series 1–6 | #3B1E6E · #1E3A5F · #0F5132 · #7A4E00 · #7F1D1D · #111114 | 2695/534/3435/1405/1815/Black 6 | Dark, saturated only |
Semantic mapping: success/warning/error/info/low-confidence(=warning family + distinct icon)/emulated as above; every semantic colour pairs with an icon and a text label [P-5, §7.6].

### 7.3 Type
Font stack: `Inter, "Segoe UI", system-ui, sans-serif`; numerals tabular in tables. Scale: 12 (caption/meta) · 13 (table body) · 14 (body) · 16 (panel title) · 20 (page title) · 28 (dashboard KPI). Weights 400/500/600 only. Line height 1.45 body, 1.2 headings.

### 7.4 Space, radius, elevation, icons
Spacing scale 4/8/12/16/24/32/48. Radius: 6px controls, 10px cards, 0 tables. Elevation: level-0 flat with border; level-1 panels `0 1px 3px rgba(17,17,20,.08)`; level-2 modals `0 8px 24px rgba(17,17,20,.16)`. Icons: outline style, 1.5px stroke, 16/20px, single colour inherit — no duotone, no filled decorative icons.

### 7.5 Density
Analyst surfaces (S-04..S-08): row height 36px, 13px text, gutters 12px. Manager surfaces (S-03, S-11): row height 44px, 14px text, gutters 16–24px.

### 7.6 Colour never carries meaning alone
Every status pairs colour + icon + label (e.g. breach risk = danger red + alarm icon + "Breach 42m"). Verified against WCAG 2.2 AA (proposed target) (§10 accessibility notes per screen).

## 8. Component library
Each component lists states: default / hover / focus / loading / empty / error / disabled / **mutation-in-progress** (controls locked, §11.7) / success / failure, plus component-specific states (stale, partial, low-confidence, permission-denied where applicable).

1. **Button** — primary (purple-700 fill), secondary (outline), destructive (danger-700 outline; fill only in confirm modals), ghost. Loading = spinner replaces label, width locked. Destructive actions always require a modal or a typed reason, never fire on single keypress without focus.
2. **Input / textarea / select / combobox** — 6px radius, visible focus ring (2px primary-600), inline validation text in danger-700 with icon; reason-textarea variant enforces non-empty [F-081].
3. **Table** — sticky header, tabular numerals, sortable columns with aria-sort, row hover wash surface-2, selected row primary-100 wash + left 2px primary bar; keyboard row focus (`J/K`); virtualised beyond 200 rows.
4. **Card / Evidence card** — the signature component [F-083]. Anatomy: source-system icon+name+`Emulated` chip · snippet (≤3 lines, expandable) · provenance line (entity + id + timestamp) · relevance score · click-through affordance. **Structural rule: the body does not render without a source reference** [P-2]. States add: *redacted* (PII tokens shown as `⟨NAME⟩` chips) and *stale* (provenance older than pack compile time).
5. **Confidence indicator** — labelled band High/Medium/Low; numeric score on hover/focus tooltip; Low state adds icon + suppresses one-click approve wherever rendered [P-3, F-077]. Bands: High ≥0.85, Med 0.60–0.84, Low <0.60 **[ASSUMPTION A-05: thresholds owned by calibration F-077; UI reads them from config]**.
6. **Badge/chip** — status chip (case states §5.3.1), SLA risk chip (ok/amber/breach with countdown), `Emulated` chip, `DEMO` chip, `Stretch assignment` chip [F-128], `Shadow` chip [F-064].
7. **Modal** — confirm (merge, approve-edited), reason (reject; textarea mandatory), never stacked >1.
8. **Toast** — outcome only ("Approved · written to Zendesk · audit #A-99231"), 6s, links to audit row; error toast persists until dismissed and names the retry state.
9. **Side panel** — 480/640px right overlay for drill-downs; Esc closes; focus trapped; origin scroll preserved.
10. **Timeline** — vertical, typed entries (comment/event/decision/write), channel icons, immutable styling for audit variant (no hover-edit affordances exist) [F-085].
11. **Empty state** — icon + one-line cause + one action ("No items awaiting approval — see Audit for today's decisions").
12. **Skeleton loader** — list rows and card blocks; never longer than the NFR budget before degrading to an honest "slower than usual" notice (§11.5).
13. **Chart** — bar/line/donut in dark series only (§7.2); every segment clickable to its records [P-4]; axis text 12px ink-600; no 3D, no gradients.
14. **Audio player (call variant)** — waveform scrubber, play/pause/±10s, speed 1×/1.5×/2×, synced transcript pane; low-ASR-confidence words underlined dotted warning-700 with tooltip score [F-135].
15. **Diff view** — for edited drafts: left original, right edited, inline word-level marks; used in S-04 edit and S-09 audit.

---

## 9. Feature catalogue — every UI-bearing feature, PM-style
Format per entry: **Problem → Value → Behaviour → Key states → Main edge case.** Grouped by epic. Features with no UI surface are recorded once in §14 as *no-UI* and not catalogued here.

### E04 · Source systems & ingestion (UI-bearing subset)
- **F-120 Six-system reconciliation.** *Problem:* a gap anywhere hollows out the digital-twin claim. *Value:* the admin can prove completeness instead of asserting it. *Behaviour:* after every ingestion run, row counts per object, sampled field checksums and referential integrity render per system on S-02; any gap fails visibly. *States:* pass / running / failed(with named object + delta). *Edge:* checksum mismatch on one object ⇒ that system shows `attention`, others unaffected; drill-down lists the mismatched sample.
- **F-121 Emulated-vs-live labelling.** *Problem:* ambiguity between emulated and live is a governance failure [NFR-44]. *Value:* honesty a technical buyer can verify. *Behaviour:* `Emulated` chip on every source card, in the tenant bar, and on every evidence card's source line. *States:* emulated (POC-always) / live (future). *Edge:* none — the chip is non-conditional and non-dismissable in POC.
- **F-122 Connections view.** See screen spec §10.2.

### E05 · Identity & 360
- **F-045 Customer 360 summary card.** *Problem:* an analyst wastes minutes reassembling who a requester is. *Value:* who/account/tier/entitlements/assets/open tickets/history/CSAT trend in one cached card, <200ms warm [NFR-3]. *Behaviour:* renders atop S-05; refresh stamp shown; identity evidence expandable (which systems matched, on what fields). *States:* cached-fresh / refreshing / partial-match (one system unresolved — shown, not hidden) / conflict (two candidate matches ⇒ both shown with evidence, none auto-picked). *Edge:* partial match must not block the ticket — pack proceeds with a low-context annotation if material [F-054].

### E06 · Knowledge & context fabric
- **F-051 Context Compiler / F-050 Hybrid retriever.** *Problem:* single-system context proves nothing. *Value:* a cited pack spanning ≥3 systems [NFR-33] in p95 <2s [NFR-1]. *Behaviour:* pack renders as evidence cards (S-06) with per-source attribution retained for citation. *States:* compiled / compiling(skeleton ≤2s then honest-delay notice) / low-context [F-054]. *Edge:* budget miss ⇒ degrade notice, never a spinner past 4s (§11.5).
- **F-052 Trust filter & ACL.** *Problem:* a pack must never contain what the viewer's context shouldn't see. *Value:* provable permission hygiene. *Behaviour:* invisible when working; a "filtered items: n" count renders in the pack footer so reviewers know filtering occurred without seeing content. *Edge:* everything filtered ⇒ low-context flag with cause "access-filtered".
- **F-054 Low-context detection.** *Behaviour:* amber banner + cause + re-enrich action; fast-approve suppressed. *Edge:* repeated low-context on same class feeds a KB gap signal [F-073].

### E07/E08 · Understand & route (UI surface)
- **F-059 Triage/Classifier.** *Value:* consistent classification with honest confidence; Zendesk AI prior consumed and benchmarked [F-061]. *Behaviour:* classification block on S-07 with class, priority, sentiment, language, band, and "prior agreed/disagreed" note. *Edge:* low band ⇒ "needs human triage" state, never a guess.
- **F-060 Dedup & Linker.** *Behaviour:* duplicates block on S-07: candidate cases with similarity, side-by-side compare, Confirm merge / Keep link / Dismiss. Never auto-merges. *Edge:* false-merge risk is the costly error — precision favoured [08_Metrics]; confirm modal shows both timelines before commit.
- **F-062 Prioritisation & SLA risk.** *Behaviour:* deterministic score + countdown chip; LLM prose reason on hover/expand; recomputes on every SLAClock event. *Edge:* clock pause (pending state) shown as paused chip, not hidden.
- **F-063/064/065 Assignment + shadow + trigger-conflict.** *Behaviour:* S-08 panel; `Shadow` chip while proposing-only; conflicts annotated with the exact trigger name and held. *Edge:* no eligible analyst above floor ⇒ escalation suggestion instead of a forced pick.

### E09 · Resolve (UI surface)
- **F-066 Resolution drafting / F-067 runbook grounding / F-068 injection resistance.** *Value:* one in three tickets pre-drafted usably [08_Metrics]. *Behaviour:* draft pane on S-04 with per-sentence citation anchors; uncited sentence ⇒ withheld placeholder [P-2]; runbook-grounded steps show the runbook chip. *Edge:* embedded instruction in ticket text neutralised — if the guard fires, a shield note appears in the audit row, not in the customer draft.
- **F-069 Escalation.** *Behaviour:* structured card (summary, evidence, suggested owner) replacing the draft when no confident match; accept/reassign controls. *Edge:* never renders alongside an approvable draft — one path per ticket at a time.
- **F-070 Action Executor.** *Behaviour:* invisible until outcome; toast + audit row; retry-on-429 states visible in audit timeline. *Edge:* write fails after retries ⇒ item returns to queue flagged "write failed — action required", approval preserved.

### E10 · Learn (UI surface)
- **F-072 KB Curator / F-073 gap detection.** S-10: draft beside source resolution; dedupe warning if similar article exists; gaps ranked by volume × handling cost. *Edge:* curator proposes an *update* to an existing article ⇒ diff view, not a new draft.
- **F-074/075 Pattern Miner + weekly digest.** S-11: clusters with week-over-week movement; every cluster backed by its case IDs. *Edge:* pattern below significance ⇒ not shown (no teaser rows).
- **F-076/077 QA/Verifier + calibration.** Flags on S-09; calibration shifts band thresholds via config, UI re-reads. *Edge:* a flagged run renders a "QA-flagged" chip on its audit row.
- **F-078 Resolution feedback loop.** S-09 outcome column links the ResolutionRecord; S-06 cites prior resolutions with a "learned" chip.

### E11 · Console (all ten features are screens — specs in §10)
F-079 shell · F-080 dashboard · F-081 approval queue · F-082 ticket 360 · F-083 citations panel · F-084 explainers · F-085 audit viewer · F-086 KB review · F-087 digest · F-088 polish/replay. Replay mode [F-088]: a response cache + replay switch for stage safety; visible only to the demo role as a small "Replay" toggle in the demo header — never in the product chrome.

### E12/E13 · Governance & quality (UI surface)
- **F-089 Immutable decision audit** → S-09. - **F-090 PII redaction** → redacted tokens visible as chips on evidence cards; zero PII to LLM [NFR-10]. - **F-093 hard HITL gate** → structurally no ungated control exists in any screen. - **F-094 RBAC** → nav and actions role-conditional; permission-denied state on every screen (§11.6). - **F-101 audit completeness** → S-09 header shows the completeness check result for demo-path actions.

### E15 · Analyst intelligence (UI surface)
- **F-123..126 profile/skills/history/signals.** Surfaced inside S-08 and S-11: level, languages, working-hours availability; skills with provenance (self/manager/certified); derived class experience; signals with sample size + confidence + backing case IDs — signals below threshold are never emitted [NFR-41]. *Edge:* skill claimed 4–5 with no supporting history ⇒ `skill gap` marker (development context only, anonymised in digest [F-129]).
- **F-127 scoring / F-128 recommendation panel** → §10.8. - **F-129 development areas in digest** → §10.11, anonymised by employment type. - **F-130 WFM boundary guard** → the UI shows current open count + working-hours availability only; no schedule surface exists anywhere.

### E16 · Voice (UI surface)
- **F-133/134 real ASR + normalisation.** Voice comments in the timeline carry `channel=voice`, avg confidence, duration. - **F-135 call player** → §10.12. - **F-137 audio PII handling.** Audio via short-lived signed URLs only; player refreshes an expired URL transparently; audio never leaves for a model — the UI offers no "summarise audio" control, only transcript-based actions.

---

## 10. Screen specifications

Conventions: every spec below gives PM framing · rationale · IDs & scenes · micro-journeys · layout · components & states · data provenance (entity.field per `05_Data_Entities`) · interactions & effects · confidence/evidence treatment · entry/exit · responsive · accessibility · NFR constraints. Screens are S-01…S-12 matching §4 of the generation prompt.

### 10.1 · S-01 Console shell & navigation `[F-079, F-094, F-088]`
**Scope Class:** POC functional. *(Global search and the notification model are NOT auto-included under F-079 — carried as change requests CR-02/CR-03, §16, pending acceptance [OD-3].)*
**PM framing.** Persona: all three. Job: get any user to the one screen their role needs in ≤2 interactions, and never lose their place. Success: an analyst reaches her queue in one keystroke; an unfamiliar viewer identifies the synthetic tenant unprompted.
**Why it exists.** Twelve capable screens with a weak shell is an unusable product; the shell carries RBAC, search, notification and the emulation honesty chip.
**Scenes:** 1 (opening frame) and every scene thereafter.
**Micro-journeys.** (1) Analyst signs in → lands on Queue (role default) → `g d` to dashboard → `g q` back; position preserved. (2) Manager clicks bell → "Digest ready" → deep-link to S-11. (3) Unauthorised role opens Audit URL → permission-denied state names the required role and offers "back to my home" — no blank page.
**Layout.** Top bar 56px (mark · tenant chip w/ Synthetic-data label · ⌘K search · bell · user). Left nav 240px collapsible to 64px icon rail; sections per §6.1; active item primary-700 bar + wash. Content region with breadcrumb row. Demo section separated by divider + striped `DEMO` header.
**Components & states.** Nav item (default/hover/active/hidden-by-RBAC); search modal (default/results/empty "no matches for ___"/error); bell (badge count, empty "you're caught up"); route-level loading skeleton, error ("Console API unreachable — retry"), and empty per §11.5.
**Data.** Tenant chip ← config; role ← auth stub; notification items ← decision_audit outcomes + escalation assignments + digest publication events.
**Interactions.** All nav = navigation only; zero mutations exist in the shell. Search select → S-05 of case. Notification click → deep link, marks read.
**Confidence/evidence.** None in shell; the honesty surface is the Synthetic-data chip [F-121].
**Entry/exit.** Entry: login. Exit: none (shell persists).
**Responsive.** ≥1440 full; 1280–1439 nav auto-collapses to rail; <1280 unsupported banner (desktop-first).
**Accessibility.** Landmark roles (banner/nav/main); skip-to-content link; focus order top bar → nav → main; nav arrow-key navigable; `?` opens shortcut overlay; all chips have text labels.
**NFR.** Cold route load target within overall demo readiness; permission checks server-side, UI mirrors only [F-094].

### 10.2 · S-02 Connections view `[F-122, F-121, F-120]` — the opening shot
**Scope Class:** POC functional (Identity tab: POC functional per F-044, placement pending A-11).
**PM framing.** Persona: Platform Admin (primary), demo audience. Job: prove six systems are connected, complete and honestly labelled, in one glance. Success: scene 1 lands without a spoken caveat.
**Why.** The digital-twin claim rests on visible completeness [NFR-31]; this screen is that proof.
**Scenes:** 1; referenced in 2, 3.
**Micro-journeys.** (1) Admin scans six cards, all green, opens Zendesk card → object counts vs source, checksum pass, last sync 06:12. (2) Overnight 429 storm: Zendesk card shows `attention: rate-limited, resumed, 0 loss` → drill to run log → verify Temporal checkpoints [NFR-8/9/35]. (3) Reconciliation failure rehearsal: one object count mismatched → card `failed` names `ticket_audits Δ-14` → "re-run reconciliation" action.
**Layout.** Two tabs: **Systems** (default) and **Identity queue** `[F-044]` (badge = pending count). Systems tab — header (title · last full-run stamp · overall completeness %), then grid of six system cards (Zendesk · Salesforce · Workday · Jira · Entra · Slack/Teams), each: system icon+name+`Emulated` chip · connection state dot+label · last sync · object count summary · completeness bar · expand affordance. Expanded card: per-object table (object · source count · ingested · checksum · status) [F-120].
**Identity queue tab `[F-044]`** — the fifth human gate. *Why:* sub-threshold identity matches are queued for human resolution rather than guessed; without this surface the queue silently accumulates. *Layout:* list of unresolved actors (requester email/name · source case count · queued-at · best-candidate score), detail pane on selection: the incoming identity left, candidate matches right (one card per candidate: system, matched fields, per-field evidence, score), actions **Resolve as ⟨candidate⟩** / **Mark as new actor** / **Dismiss (needs data)** — resolve and mark write an audit row and retro-link the actor's cases; dismiss requires a reason. *Micro-journey:* two Salesforce contacts score 0.58/0.55 for "d.okafor@halcyon…" → admin opens field evidence → picks candidate A → toast + audit row → S-05 summary card for HFG-2214 flips from partial to matched on next load. *States:* pending / resolving / resolved(24h history) / empty ("no unresolved identities"); deep-link target from S-05's conflict/partial state ("resolve in Identity queue →"). *Keyboard:* J/K/Enter/1..n candidate select/⌘Enter resolve.
**Components & states.** System card: healthy / syncing / rate-limited(retrying) / attention / failed — each with icon+label+colour, never colour alone. Table rows: pass/fail per object. Empty (pre-first-sync): "awaiting first backfill". Error: reconciliation job unreachable.
**Data.** Card state ← connector run status; counts ← reconciliation job output (row counts, sampled field checksums, referential integrity) [F-120]; `Emulated` ← F-121 (unconditional); last sync ← connector_run.
**Interactions.** Expand card (no mutation); re-run reconciliation (admin only, audit-logged); identity resolve/mark/dismiss (admin, audited [F-089]) — these mutate canonical identity links only, never external systems; no external-write controls exist here (sync/event controls live in the demo lane only).
**Evidence.** Every count click-through to the object-level table [P-4].
**Entry/exit.** Nav › Connections; exits to run-log side panel or back.
**Responsive.** 3×2 card grid ≥1440; 2×3 at 1280.
**Accessibility.** Cards are buttons with aria-expanded; state changes announced via live region; completeness bar has text %.
**NFR.** #31 (100% completeness), #32 (connector_run_id traceability), #35 (chaos: zero loss), #44 (no emulated/live ambiguity — user-tested).

### 10.3 · S-03 Corpus dashboard `[F-080]`
**Scope Class:** POC functional.
**PM framing.** Persona: Ops Manager (primary), Admin. Job: is the world healthy and believable — volumes, mix, coverage — with every number live and drillable. Success: the manager answers "what changed this month" in three clicks.
**Why.** Live counts prove the twin is real; decoration would be indistinguishable from a mock-up.
**Scenes:** 1.
**Micro-journeys.** (1) Manager scans KPI band → clicks enterprise-tier bar → filtered case list (breadcrumb Dashboard › Tier: Enterprise) → opens one case. (2) Admin checks KB coverage donut → clicks "gap" segment → intents with no adequate article, ranked [F-073]. (3) Empty rehearsal: pre-seed the dashboard renders structured empty states, not zeros pretending to be data.
**Layout.** KPI band (Total cases 6,000 · Open · Solved-this-week · Analysts 240 · KB articles 900 · KB coverage %). Row 2: Volume by category (bar, 10 L1 categories) · by channel (bar, 12 channels) · by account tier (bar). Row 3: Volume by month (line) · Analyst roster summary (by level L1/L2/L3/SME with headcount) · KB coverage (donut: covered/thin/gap).
**Components & states.** Charts (§8.13) — loading skeleton, empty, error per chart; every segment clickable. KPI tiles with delta vs prior period (dark colours + arrow icon + label).
**Data.** Case counts ← `Case` aggregates; channel ← `Channel` join; tier ← `Account.tags/tier`; monthly ← `Case.generated_ts`; roster ← `analyst_profile.level`; KB ← `KnowledgeArticle` + gap detection [F-073]. All figures live queries; only `08_Metrics_KPIs` numbers may appear as targets/claims.
**Interactions.** Segment click → filtered list side panel → S-05. No mutations.
**Evidence.** Deltas and KPIs drill to record lists [P-4].
**Entry/exit.** Nav › Overview; exits into filtered lists/tickets, breadcrumb back.
**Responsive.** 3-col ≥1440, 2-col at 1280.
**Accessibility.** Charts carry data tables via toggle ("view as table"); colour series distinguishable by order+label, not hue alone.
**NFR.** Query latency within demo-hardware budgets [NFR-7]; counts reconcile with S-02 [NFR-31].

### 10.4 · S-04 Approval queue `[F-081, F-093, F-088]` — the workhorse
**Scope Class:** POC functional. Decision vs write-execution are separate visible states (§5.3.2a/b).
**PM framing.** Persona: Analyst. Job: judge and dispatch each recommendation — approve, edit, reject, confirm-merge, accept-escalation — in seconds, with the evidence one glance away and the keyboard doing everything. Success: median decision <60s on drafted tickets; zero decisions without an audit row (structurally guaranteed).
**Why.** This is where the recommendation-only stance becomes a working practice instead of a slogan; approval acceptance ≥80% and usable-draft ≥30% [08_Metrics] are measured from this screen's outcomes.
**Scenes:** 7; items from 4 (merge) and C-branches (escalation).
**Micro-journeys.** (1) *Fast approve:* `J` to item → list row shows case id, subject, class, SLA chip, confidence band, age → detail pane: draft left, evidence right → three citations scanned → `A` → confirm toast with audit link → auto-advance to next. (2) *Edit-approve:* Medium band, one step wrong → `E` opens inline editor with citation anchors preserved → change step 3 → `⌘Enter` approve-edited → diff stored [§8.15], edit distance recorded. (3) *Reject:* draft misreads the ask → `R` → reason modal (mandatory textarea, min 10 chars **[ASSUMPTION A-06]**) → submit → item returns to queue "rejected · redrafting"; audit row written. (4) *Merge confirm:* proposal card shows both cases side-by-side timelines + similarity 0.93 → Confirm merge modal → merged; or Keep-link. (5) *Low confidence:* band Low → one-click approve suppressed; evidence auto-expanded; approve requires opening the confirm modal (deliberate friction) [P-3]. (6) *Write failure:* post-approval 429s exhaust → item returns flagged "write failed" with retry state visible; approval preserved; analyst re-fires execution only (no re-approval needed) [F-070].
**Layout.** Left: queue list (filters: type [draft/merge/escalation], class, SLA risk, band, team; sort default = SLA risk desc, then age). Right (fills on selection): header (case id · subject · requester · status chip · SLA chip · band) · draft pane with per-sentence citation anchors · evidence rail (top 3 cards, "open full pack" → S-06) · action bar (Approve `A` · Edit `E` · Reject `R` · Open 360 `O`).
**Keyboard map (exact).** `J/K` next/prev · `Enter` open detail · `A` approve (High/Med only) · `E` edit · `R` reject · `M` confirm-merge dialog · `X` expand evidence · `O` open Ticket 360 panel · `C` open citations panel · `Esc` close panel/return to list · `⌘Enter` commit in editor/modal · `?` overlay. Every action reachable without mouse.
**Components & states.** List row (default/selected/low-conf/awaiting-context/write-failed/QA-flagged); draft pane (drafted/withheld-sentences/escalation-card-variant/redrafting); evidence card states incl. redacted [§8.4]; reason modal; toasts. Empty: "No items awaiting approval". Loading: skeleton rows. Error: queue service unreachable + retry.
**Data.** Row ← `Case` (id, subject, priority, status_category) + triage output (class, band) + `SLAClock` (deadline countdown) + recommendation state [§5.3.2]. Draft ← Resolution output; citations ← context pack attribution; merge ← Dedup proposal (similarity, candidate case ids); escalation ← Escalation output (summary, suggested owner).
**Interactions & effects.** Approve → approval record → Action Executor write → `decision_audit` + `ResolutionRecord` [F-070, F-089]. Edit-approve → same + diff. Reject → audit row + optional single redraft with reason as instruction. Merge confirm → case merge + audit. Escalation accept → assignment to owner + audit. **No control on this screen writes externally without producing an approval record — there is no such control to add [F-093, NFR-13/18].**
**Confidence/evidence.** Band chip on row and header; numeric on hover; Low behaviour per P-3; withheld-uncited-sentence placeholders visible so the analyst sees what the system would *not* claim [P-2].
**Entry/exit.** Default landing for analyst role; exits to S-05/S-06/S-07/S-08 as panels, Esc back with position preserved.
**Responsive.** ≥1440 list 380px + detail; 1280 list collapses to 320px.
**Accessibility.** Full keyboard path (above); focus visibly ringed; list is a listbox with aria-activedescendant; modals trap focus; toast announced polite; reject reason labelled and required-announced.
**NFR.** Full pipeline webhook→approval-pending p95 <30s [NFR-2] — items appear within this budget with an "arrived" subtle highlight; every action auditable [NFR-15]; uncited claims zero [NFR-16].

### 10.5 · S-05 Ticket 360 `[F-082, F-045]`
**Scope Class:** POC functional.
**PM framing.** Persona: Analyst (primary), Manager (drill-in). Job: know who this is and everything that has happened, across every channel and system, in one view. Success: identity question answered <5s; no channel's history missing.
**Why.** Scene 3's promise — identity across four systems in <2s — must be visible, evidenced and honest about partial matches.
**Scenes:** 3; used in 2, 7 drill-ins.
**Micro-journeys.** (1) From queue `O`: 360 card top — Daniel Okafor · Payroll Ops · Halcyon · Enterprise tier · 3 open cases · CSAT trend ↓ — identity line "matched across Zendesk · Workday · Entra · Salesforce" → expand: match fields per system with evidence [E05]. (2) Timeline scroll: voice comment (play affordance → S-12 inline), email, Slack thread, internal note, SLA events, decisions — filter by type/channel. (3) Partial match: Salesforce unresolved → card shows 3-of-4 with "unmatched: Salesforce (no contact on domain)" — visible, not hidden; conflict variant shows both candidates + evidence, none auto-picked, with "resolve in Identity queue →" deep-link to S-02's Identity tab [F-044]; on resolution there, this card updates on next load.
**Layout.** Top: 360 summary card [F-045] (identity, account, tier, entitlements count, assets count, open tickets, CSAT trend sparkline in dark ink, refresh stamp). Left rail: case facts (status chip, class, priority, SLA chip, team, assignee, linked Jira). Main: cross-channel timeline (§8.10) with channel icons (email/slack/voice/web/internal), each entry: author, time, snippet, expand. Right: tabs → Citations (S-06) · Explainers (S-07) · Analyst panel (S-08).
**Components & states.** Summary card (fresh/refreshing/partial/conflict); timeline (loading skeleton, empty "no activity yet", error); asset/entitlement chips expand to lists.
**Data.** Identity ← resolved `Actor` + per-system match evidence; account/tier ← `Account`; entitlements ← `Entitlement`(SF); assets ← `Asset` (assigned_worker_id); org chain ← `Worker.supervisor_id` ladder + `OrgUnit`; timeline ← `Comment` + `CaseEvent` + `SLAClock` + `decision_audit` entries; CSAT ← `SatisfactionRating`; voice entries ← `call_recording` metadata.
**Interactions.** Everything read-only except navigation; play → S-12; Jira link opens linked-issue panel (read-context adapter [F-119] — no write controls exist for non-Zendesk systems).
**Confidence/evidence.** Identity match confidence per system on expand; partial/conflict states honest by design.
**Entry/exit.** From queue/search/dashboard/digest/audit; back preserves origin.
**Responsive.** Right tab rail collapses to icons at 1280.
**Accessibility.** Timeline entries are articles with datetime; filters are checkboxes; sparkline has text alternative ("CSAT last 5: 4,4,3,3,2").
**NFR.** Identity <2s [scene 3 claim, NFR-3 warm <200ms for cached card]; timeline virtualised.

### 10.6 · S-06 Context & citations panel `[F-083, F-052, F-054, F-051]`
**Scope Class:** POC functional.
**PM framing.** Persona: Analyst. Job: see exactly what the system knows, where each piece came from, and what it deliberately withheld. Success: any claim in a draft traced to its source in ≤2 clicks; zero uncited claims rendered [NFR-16].
**Why.** The moat is the cited cross-system pack; this panel is the moat made visible.
**Scenes:** 5; supports 7.
**Micro-journeys.** (1) From draft citation anchor [3] → panel scrolls to card 3 (a prior ResolutionRecord, `learned` chip) → click-through → source case → back. (2) Low-context: amber banner "Insufficient context — retrieval below threshold (0.41). Cause: no KB coverage for class `sso-scim-sync`" + "Request re-enrichment" → status compiling → refreshed pack or persistent flag [F-054]. (3) Filtered items: footer "2 items access-filtered" — reviewer knows filtering occurred, content stays hidden [F-052].
**Layout.** Header: pack meta (compiled at, compile ms vs 2s budget, sources n systems [NFR-33], token budget used, `filtered: n`). Body: evidence cards (§8.4) grouped by source system, ranked by relevance; each: source icon + `Emulated` chip, snippet, provenance (entity + id + ts), score, click-through. Footer: withheld count (uncited-claim suppressions in the paired draft).
**Components & states.** Cards (default/expanded/redacted/stale/learned); banner (low-context with cause + action); compiling skeleton ≤2s then honest-delay notice.
**Data.** Cards ← context pack items with per-source attribution [F-050]; redaction ← PII tokens [F-090]; systems count ← `systems_in_pack` metric; prior resolutions ← `ResolutionRecord` retrievals [F-078].
**Interactions.** Card click-through → source (case/comment/article/graph path panel); re-enrich request (audited, no external write); nothing else mutates.
**Confidence/evidence.** Relevance scores shown; the panel is itself the evidence treatment for the whole product.
**Entry/exit.** Tab within ticket context or `C` from queue; Esc back.
**Responsive.** 480px side panel; 640px when opened from draft anchor.
**Accessibility.** Anchor↔card linkage navigable by keyboard (anchor Enter → card focus; Shift+Enter back); redacted chips announced as "redacted personal data".
**NFR.** #1 compile p95 <2s (skeleton budget), #16 zero uncited, #33 ≥3 systems (header count turns warning if <3 with reason).

### 10.7 · S-07 Triage, dedup & assignment explainers `[F-084, F-059, F-060, F-062, F-065]`
**Scope Class:** POC functional.
**PM framing.** Persona: Analyst; Manager on review. Job: understand *why* the system classified, linked and prioritised as it did — and correct it where wrong. Success: an analyst can articulate the system's reasoning to a customer without guessing.
**Scenes:** 4; supports 6, 7.
**Micro-journeys.** (1) Classification block: class `auth-sso` · band High (0.91 hover) · sentiment negative · language en · "Zendesk AI prior: agreed" [F-061] → expand: top-3 alternative classes with scores. (2) Duplicates: two candidates 0.93/0.71 → compare view (both timelines side-by-side) → Confirm merge (modal) or Keep link or Dismiss; mid-score renders link-only, no proposal [F-060]. (3) SLA: chip "Breach in 42m" + pause state when pending; expand → deterministic inputs (policy, elapsed, business hours) + LLM prose reason clearly marked "explanation" [F-062]. (4) Assignment summary strip → "view full shortlist" → S-08. (5) Trigger conflict: proposal held with note "conflicts with tenant trigger 'VIP auto-route' — held for human decision" [F-065].
**Layout.** Four stacked blocks: Classification · Duplicates · SLA & priority · Assignment (summary). Each block: verdict line, band, expand-for-reasoning.
**Components & states.** Blocks (default/expanded/low-conf/needs-human-triage/held-conflict); compare view; countdown chip (ok/amber/breach/paused).
**Data.** Class/sentiment/lang/conf ← Triage output on `Category/Intent`; alternatives ← classifier top-k; duplicates ← Dedup proposals (similarity, case ids); SLA ← `SLAClock` events + `SLAPolicy`; prior ← Zendesk AI fields [F-061]; triggers ← `AutomationRule`.
**Interactions.** Confirm-merge (gated, audited); class override proposal **[A-02]** (audited); everything else read/expand.
**Confidence/evidence.** Bands per block; deterministic vs LLM-prose visually separated (the number is never editable, the prose is labelled explanation) [F-062].
**Entry/exit.** Tab in ticket context; from queue badges.
**Responsive/accessibility.** Blocks collapse independently; compare view keyboard-toggleable; countdown announced at amber and breach only (not every tick).
**NFR.** Recompute-on-event live updates; triage F1 target context [NFR-21] is measured, not displayed per-ticket.

### 10.8 · S-08 Analyst recommendation panel `[F-128, F-127, F-126, F-063, F-064]`
**Scope Class:** POC functional — **shadow-only** [F-064, OD-2]: accept/override records feedback, never an external assignment write. Ordering is per-ticket only; no leaderboard, no overall score, no cross-ticket persistence of rank.
**PM framing.** Persona: Analyst lead / Manager at the routing gate. Job: accept the best-evidenced assignee, or pick an alternative, knowing exactly why each is ranked where they are. Success: acceptance ≥80% [08_Metrics]; every displayed number click-through to its tickets [NFR-42]; a team lead stops second-guessing.
**Why.** Evidence-based assignment is the anti-gut-feel claim; unexplained recommendations get ignored.
**Scenes:** 6; supports 4.
**Micro-journeys.** (1) Shortlist of 3: Priya 0.86 · Rahul 0.79 · Mei 0.74, each row expandable to component bars (class experience 0.30 wt · outcome quality 0.25 · skill match 0.20 · efficiency 0.10 · load & availability 0.10 · level appropriateness 0.05) [F-127] → click Priya's "41 tickets" → the 41 case IDs list → one case → back. (2) Stretch: Mei flagged `Stretch assignment` with development rationale ("5 handled, below strength threshold — growth in class") [F-128]. (3) Shadow: panel carries `Shadow` chip — accept records the proposal outcome without external routing action beyond the gate [F-064]. (4) No eligible above floor → escalation suggestion replaces shortlist.
**Layout.** Header (case class, needed skills, `Shadow` chip). Ranked rows: avatar-less name+level, composite score bar (dark), availability (within working hours y/n + open count — current state only [F-130]), top evidence line ("41 handled · 94% CSAT · 0.9h avg"), expand: component breakdown + measured history table (per `analyst_class_experience` fields) + signals with sample size, confidence, backing case IDs [F-126]. Footer: Accept proposal · Choose selected · Decline.
**Components & states.** Row (default/expanded/stretch/unavailable); every numeric a drill-link; empty ("no eligible analysts — escalate"); held-conflict banner when F-065 fired.
**Data.** Scores ← deterministic capability engine [F-127]; history ← `analyst_class_experience` (tickets_handled, avg_handle_time_min, reopen_rate, escalation_rate, csat_avg, qa_score_avg); signals ← `analyst_capability_signal` (type, metric, team_median, sample_size, confidence, evidence[]); availability ← `analyst_load` (open_tickets, within_working_hours) — **no schedule data exists to show** [F-130]; skills+provenance ← `analyst_skill`.
**Interactions.** Accept/choose/decline → routing-gate record + audit; number click → backing tickets panel. **Employment type is never displayed here and never scored [F-127]; no ranking export, no cross-class league table — this panel ranks fit-for-this-ticket, nothing else [§1.4].**
**Confidence/evidence.** Signals carry their own sample size + confidence; below-threshold signals absent by rule [NFR-41].
**Entry/exit.** From S-07 summary or queue routing items; back to origin.
**Responsive/accessibility.** Component bars have numeric text; rows keyboard-expandable; drill panels focus-trapped.
**NFR.** #40 stats reproducible from case data, #41 threshold enforcement, #42 100% evidence coverage.

### 10.9 · S-09 Audit viewer `[F-085, F-089, F-101, F-094]`
**Scope Class:** POC functional.
**PM framing.** Persona: Admin, Manager; Analyst for own decisions. Job: reconstruct any decision — what was recommended, on what evidence, at what confidence, by which model, what the human did, what happened — with zero gaps. Success: 100% of demo-path actions show a complete trail [NFR-15]; a sceptic finds no unexplained write.
**Scenes:** 7, 8.
**Micro-journeys.** (1) Per-ticket timeline: recommendation → evidence(citations) → confidence 0.87 → model sonnet-x.y → human: edited-approved by P.Nair 11:42 (diff view) → action: Zendesk comment #1182 → outcome: solved, CSAT 4 → ResolutionRecord link [F-078]. (2) Failure honesty: Executor 429×3 retries visible as timeline entries → success; or write-failed terminal state. (3) Manager filters: last week · rejected → reads reasons → clicks through to drafts. (4) Completeness header: "Demo-path audit completeness: 100% (checked 09:00)" [F-101]. (5) QA-flagged run carries chip → flag detail (groundedness score) [F-076].
**Layout.** Filters (date, decision type, human, agent, outcome, flagged). List of decision rows → expand to immutable timeline (§8.10 audit variant — no edit affordances exist). Header: completeness check result.
**Components & states.** Timeline entries typed (recommendation/evidence/decision/write/outcome/retry/flag); diff view for edits; export (RBAC: admin only) **[ASSUMPTION A-07: CSV export of audit rows permitted for admin]**.
**Data.** Everything ← `decision_audit` (case_id, agent, recommendation, evidence[], confidence, model, version, latency_ms, cost, human_decision, outcome, occurred_at); completeness ← F-101 check; flags ← QA/Verifier.
**Interactions.** Read-only + filter + export; every evidence item click-through to source.
**Confidence/evidence.** Historical bands shown as recorded (not recomputed) — the audit shows what was known then.
**Entry/exit.** Nav › Audit; per-ticket entry from S-05 decisions.
**Responsive/accessibility.** Timeline keyboard-navigable; immutability communicated ("append-only record" caption); per-entry timestamps absolute + relative.
**NFR.** #15 100% auditability, #13 no ungated write (this screen is where its absence is *demonstrated*), #20 per-agent cost/latency reportable (columns available in expanded entries).

### 10.10 · S-10 KB draft review `[F-086, F-072, F-073]`
**Scope Class:** POC functional. Approved verb = "Create/update Zendesk Guide draft (draft=true)"; no Publish-live control exists (§5.3.5).
**PM framing.** Persona: Analyst/KB owner. Job: turn a good resolution into a good article — or refuse — beside the evidence, in minutes. Success: ≥50% draft acceptance [08_Metrics]; no near-duplicate published.
**Scenes:** 8.
**Micro-journeys.** (1) Draft article left · source ResolutionRecord + originating case right → approve-as-draft (published to KB in draft status — publication remains the gated act per Zendesk scopes) · edit · reject-with-reason. (2) Dedupe: similarity 0.88 to existing article → warning banner with side-by-side → choose "update existing" → diff view of proposed update [E10 edge] → approve update-as-draft. (3) Gap queue tab: intents with no adequate article ranked by volume × handling cost [F-073] → "request draft" queues the Curator.
**Layout.** Two panes (draft | source) + top action bar + tabs (Pending drafts · Updates · Gaps).
**Components & states.** Draft pane (new/update-diff/dedupe-warned); reason modal; empty ("no drafts pending"); accepted/rejected chips in history list.
**Data.** Draft ← KB Curator output; source ← `ResolutionRecord` + `Case`; existing ← `KnowledgeArticle` (draft, promoted, outdated flags); gaps ← gap detection ranking.
**Interactions.** Approve-as-draft → article created in draft status + audit; reject → reason + audit; edit inline then approve. Publication beyond draft is out of this screen by design.
**Entry/exit.** Nav › Knowledge; from digest KB-gap items.
**Accessibility.** Panes independently scrollable, synced-scroll toggle; diff marks announced.
**NFR.** Draft-only guarantee mirrors F-072 guardrail; acceptance measured [NFR-27].

### 10.11 · S-11 Weekly intelligence digest `[F-087, F-075, F-129, F-074]`
**Scope Class:** POC functional.
**PM framing.** Persona: Support Director. Job: read Monday's briefing and leave with 3 actions, each evidence-backed. Success: a director acts on it without asking an analyst to "pull the data".
**Scenes:** 8.
**Micro-journeys.** (1) Narrative header ("Week 32: SSO recurrence is the story…") → clusters section: `sso-after-rotation` 14 tickets ↑ from 3 → click → case list → exemplar. (2) Deflection candidates with estimated volume; KB gaps → link to S-10 gap tab. (3) SLA hotspots by class/team → drill. (4) Capability map: classes × coverage depth (thin classes flagged); development areas **anonymised by employment type** ("2 FTE, 1 BPO analysts below median in `payroll-integrations`, samples ≥5") — no names in this section [F-129]; skills-claimed-without-history count. (5) Quality corner: QA/Verifier calibration summary, week-over-week [F-076].
**Layout.** Briefing-style single column: Narrative · Recurring clusters · Deflection candidates · KB gaps · SLA hotspots · Capability map & development areas · Quality. Every number a drill-link; written as prose-first briefing, charts supporting [P-7].
**Components & states.** Section cards; below-significance patterns not shown (no teasers); archive selector (prior weeks).
**Data.** Clusters/deflection/gaps ← Pattern Miner weekly batch [F-074]; capability ← `analyst_capability_signal` aggregated + anonymised [F-129]; SLA ← `SLAClock` aggregates; quality ← QA/Verifier outputs.
**Interactions.** Read + drill only; "open in KB gaps" cross-link; no per-person management actions exist [§1.4].
**Entry/exit.** Nav › Intelligence; bell deep-link on publication.
**Accessibility.** Prose-first structure is screen-reader-friendly by construction; charts have table toggles.
**NFR.** Pattern recall proven on seeded patterns [08_Metrics]; anonymisation verified in review [F-129].

### 10.12 · S-12 Call player with synced transcript `[F-135, F-133, F-134, F-137]`
**Scope Class:** POC functional — **POC demo voice feature**: a real transcribed call artefact, not a promise of live/streaming telephony (out of MVP scope).
**PM framing.** Persona: Analyst. Job: hear what the customer actually said, see where the machine was unsure, and jump to the moment that matters. Success: an analyst catches an ASR misread (as in J-DL-A) before approving a wrong draft.
**Scenes:** 2.
**Micro-journeys.** (1) From timeline voice entry → inline player expands: waveform, duration 6:12, speakers labelled (IVR/agent/customer) → play; transcript auto-scrolls, current word highlighted. (2) Low-confidence words dotted-underlined (warning-700) → hover: "0.54 — 'HFG-2214' may be 'HFG-2240'" → click any line → audio jumps to timestamp. (3) Expired signed URL mid-session → player refreshes URL transparently, position preserved [F-137].
**Layout.** Player bar (play/pause/±10s/speed 1·1.5·2×/waveform scrub) above transcript pane (speaker-tagged turns, timestamps, confidence marks). Meta line: ASR model, avg confidence, WER-disclosed note [NFR-38].
**Components & states.** §8.14 audio player; transcript (loading/ready/error "transcript unavailable — audio only"); no "summarise audio" control exists — analysis actions operate on the transcript text only [F-137].
**Data.** ← `call_recording` (audio_uri signed, duration_sec, speakers[], asr_model, asr_confidence_avg) + voice `Comment` (asr_segments with word timings + per-word confidence) [F-134].
**Interactions.** Playback + jump + speed; transcript text selectable for quoting into notes; nothing mutates.
**Confidence/evidence.** Per-word confidence is the treatment; voice-path metrics reported separately, never folded into headline numbers [F-136, NFR-37].
**Entry/exit.** Inline within S-05; Esc collapses to timeline.
**Accessibility.** Full keyboard transport (space/←/→/±10s); transcript is the accessible equivalent of audio; low-confidence marks conveyed by underline+tooltip text, not colour alone.
**NFR.** #36 200 calls transcribed, #38 WER disclosed, #39 zero audio objects to models (structural: no such control).

### 10.13 · S-13 Tickets list / search `[F-079, F-080, F-082]`
**Scope Class:** POC functional **as change request CR-01 [OD-3]** — required by the no-dead-end rule (§5.4 drill targets) but not itself a feature row; carried in §16 for the architect to ratify under F-079.
**PM framing.** Persona: all three. Job: find any set of cases — by filter, by drill-down, or by search — and get to the right Ticket 360 fast. Success: every drill-down in the product lands somewhere real; ⌘K to an open case in <3s. This is the most-landed-on surface in the product: S-03 chart segments, S-11 clusters, S-08 evidence numbers and ⌘K all terminate here.
**Why it exists.** §5.4's navigation graph promised "no dead ends"; a filtered case list with no spec was one. S-13 is the single list surface behind every drill.
**Scenes:** supports 1, 6, 8 (every "click a number" beat).
**Micro-journeys.** (1) *Nav mode:* Tickets in left nav → full page, default filter status=open, sort SLA-risk desc → type in filter bar → open case → breadcrumb back, filters preserved. (2) *Drill mode:* manager clicks the enterprise-tier bar on S-03 → S-13 opens as a 640px side panel, filter chip "Tier: Enterprise" applied and removable, origin chart still visible behind → open case → Esc twice back to chart, position preserved. (3) *Search mode:* ⌘K "okafor" → results grouped (Cases · Analysts · Articles); Enter on a case → S-05; an exact case-id query ("HFG-2214") skips the list entirely. (4) *Empty:* filter yields nothing → "No cases match — clear filters" one-click.
**Layout.** Filter bar (status, class, channel, tier, team, assignee, SLA risk, band, date range — same vocabulary as S-04's filters) + applied-filter chips (removable, shareable as URL state). Table: case id · subject · requester · class · status chip · SLA chip · band · age · assignee. Footer: count + "showing n of m".
**Modes.** *Full page* (nav destination): full chrome, saved-filter selector. *Side panel* (drill target): 640px overlay, filter chips pre-applied from the drill source, no saved-filter selector, breadcrumb carries origin › metric › list. Same component both ways — mode changes chrome, never columns or behaviour.
**Components & states.** Table (§8.3): loading skeleton rows, empty (cause + clear-filters), error (named dependency + retry); virtualised >200 rows; row states default/hover/focused.
**Data.** Row ← `Case` (id, subject, status_category, generated_ts→age) + `Actor` (requester) + triage class/band + `SLAClock` chip + assignee ← `TeamMembership`/assignment. Search ← case id/subject/requester index; analysts ← `analyst_profile`; articles ← `KnowledgeArticle`.
**Interactions.** Row click → S-05 (panel stack in drill mode, full page in nav mode); filter mutation = URL state only; zero external writes. Column sort persists per user.
**Confidence/evidence.** Band chips as elsewhere; the list itself is the evidence layer for every drilled metric [P-4].
**Entry/exit.** Nav › Tickets; S-03/S-11/S-08 drills; ⌘K. Exit: S-05, or Esc back with origin preserved.
**Responsive.** Full page: all columns ≥1440, drops age+assignee at 1280. Panel: fixed 640px, drops class+age.
**Accessibility.** Filter bar is a labelled group; chips deletable by keyboard; table keyboard row-nav (J/K/Enter) consistent with S-04; result counts announced on filter change.
**NFR.** List query within demo-hardware budget [NFR-7]; counts consistent with S-03 aggregates [NFR-31].

### 10.14 · S-14 Login & role selection (auth stub) `[F-079, F-094]`
**Scope Class:** POC functional — backed by F-079's auth stub; role selection is the RBAC demo mechanism.
**PM framing.** Persona: all; demo presenter above all. Job: enter the console as a chosen role in one screen — because role selection is the mechanism of the RBAC demonstration. Success: switching Analyst → Manager → Admin between demo beats takes <10s and visibly changes the product.
**Why.** F-079 specifies an auth stub; F-094 is only demonstrable if the audience watches the role change and the nav change with it.
**Scenes:** precedes 1; exercised whenever the demo switches persona.
**Micro-journeys.** (1) Presenter opens console → S-14: product mark, tenant line ("Halcyon Foods Group · Synthetic data" — the honesty chip starts here [F-121]), four role cards: **Analyst · Manager · Admin · Demo**, each with a one-line description of what it can see → picks Analyst → lands on S-04. (2) Mid-demo switch: user menu › "Switch role" → returns to S-14 with current role marked → picks Manager → lands on S-03; notification state and queue position are per-role. (3) Deep-link while logged out → S-14 with "continue to ⟨destination⟩" after role pick; if the picked role lacks permission, the §11.6 permission-denied state explains it — the stub never silently upgrades a role.
**Layout.** Centered card on surface-0: mark · tenant line · four role cards (name, description, icon) · continue. No password fields (stub) — a "stub authentication — POC" caption keeps it honest.
**Components & states.** Role card (default/hover/selected/current); loading (role context fetch); error ("console API unreachable"). No empty state (roles are static config).
**Data.** Roles ← auth-stub config; descriptions static; destination ← deep-link param.
**Interactions.** Role pick → session role → route to role default (Analyst→S-04, Manager→S-03, Admin→S-02, Demo→Demo lane D-1). Audit rows attribute to the named stub user of that role [F-094].
**Entry/exit.** Entry: cold open, sign-out, "Switch role". Exit: role-default screen or deep-link destination.
**Responsive/accessibility.** Single column; role cards are radio-group semantics; full keyboard; focus starts on first card.
**NFR.** Server-side permission checks remain authoritative; the stub changes identity, never bypasses gates [NFR-13].

### 10.15 · Notification panel (shell sub-surface) `[F-079]`
**Scope Class:** change request CR-03 [OD-3] — not committed by F-079; build only if accepted.
**PM framing.** Persona: all. Job: know what needs me, what happened to my decisions, and what's ready to read — without leaving my screen. Success: zero missed merge-confirms/escalations in a working day.
**Micro-journeys.** (1) Bell badge 3 → panel opens (right overlay 400px): items newest-first, grouped by the three classes (§6.2) — **Action needed** (merge to confirm, escalation assigned, identity queue past threshold count for admins) · **Outcome** (your approval executed / write-failed-retrying) · **Digest ready**. (2) Click an outcome → deep-link to the S-09 audit row → item marked read. (3) Write-failed outcome is sticky: stays bold until its case leaves the write-failed state, even if clicked — failure is not dismissable by reading [F-070]. (4) "Mark all read" affects non-sticky items only.
**Layout.** Header (title · mark-all-read) · grouped list (class label, item: icon, one-line text, relative time, unread dot) · footer link "open Audit".
**Components & states.** Item (unread/read/sticky-failure); empty ("you're caught up"); error (retry); badge = unread count, capped 9+.
**Data.** Action-needed ← merge proposals + escalation assignments + identity-queue count [F-044]; outcomes ← `decision_audit` executor results; digest ← publication event.
**Interactions.** Click = deep-link + mark read; no mutations beyond read state. Toast-confirmed outcomes (§8.8) arrive already-read **[ASSUMPTION A-12: a toast the user saw counts as read]**.
**Entry/exit.** Bell from any screen; Esc back, origin untouched.
**Accessibility.** Overlay focus-trapped; unread conveyed by dot + "unread" SR text, not weight alone; new action-needed items announced politely.
**NFR.** Deep-links land on exact screen state (§5.4); per-role state isolation (S-14).

---

## 11. Cross-cutting patterns

### 11.1 Evidence and citation
Every AI claim renders through the evidence-card system (§8.4). Draft sentences carry citation anchors `[n]` linked to cards; an uncited sentence is withheld with a visible placeholder [NFR-16, P-2]. Cards always show source system + `Emulated` chip + provenance (entity, id, timestamp) + relevance. Prior-resolution citations carry a `learned` chip [F-078]. Citation coverage ≥90% is a measured metric [NFR-24], not a UI aspiration — the pack header shows the pack's own coverage.

### 11.2 Confidence policy — per output type, never one generic score
Different agents' confidences mean different things; a single generic band would imply false equivalence. One row per output:

| Output | Meaning | Calibration source | Display | Low-confidence behaviour | Hard gate? |
|---|---|---|---|---|---|
| Triage class [F-059] | P(class correct) | Calibration layer [F-077] | Band + numeric on hover (S-07, S-04 badge) | "Needs human triage" state — never a guess | No write exists |
| Dedup similarity [F-060] | Pair similarity score | Deterministic + threshold | Numeric on proposal card | Mid-score ⇒ link-only, no merge proposal | Merge always human-gated |
| Resolution draft [F-066] | Groundedness/answer confidence | Calibration layer [F-077] | Band on queue row + header | One-click approve suppressed; evidence auto-expanded; confirm-modal friction | Write always human-gated |
| Assignment score [F-127] | Deterministic weighted fit (not a probability) | Reproducible from case data [NFR-40] | Numeric bars + components | No band language — it is a score, not confidence; below-floor ⇒ escalation suggestion | Shadow-only [OD-2] |
| ASR words [F-133] | Per-word transcription confidence | ASR engine | Dotted underline + tooltip numeric (S-12) | Visibly marked; transcript-based actions only | Audio never to models |

Bands where used: High ≥0.85 · Medium 0.60–0.84 · Low <0.60 — placeholders owned by calibration [F-077], read from config **[A-05]**; if an output is uncalibrated, its numeric is hidden and only the flag state shows. Deterministic numbers are visually distinct from LLM prose, which is always labelled "explanation" [F-062].

### 11.3 Human-in-the-loop approval
One approval grammar across drafts, merges, routing, KB: propose → review-with-evidence → approve / edit / reject-with-mandatory-reason → audit row → (for writes) deterministic execution [F-081, F-086, F-093]. Approve is one key on High/Medium; deliberate friction on Low. Reject reasons are structured data feeding redraft and QA. There is no bulk-approve. **[ASSUMPTION A-08: bulk actions excluded — approval is per-item by principle; flag if the demo needs otherwise.]**

### 11.4 Emulated-source labelling
Three layers, all mandatory: tenant chip ("Synthetic data"), per-system `Emulated` chip on S-02, per-card `Emulated` chip on every evidence card [F-121]. Copy never says "connected to Zendesk" without "(emulated)" in the same visual unit. Success test: an unfamiliar viewer identifies emulation unaided [NFR-44].

### 11.5 Empty, loading and error states [F-088]
Every route and panel ships all three. Loading: skeletons budgeted to the screen's NFR (e.g. 2s for the pack); past budget, the skeleton is replaced by an honest-delay notice ("compiling is slower than usual — 4.2s") — never an indefinite spinner. Empty: cause + one action. Error: names the failing dependency + retry + preserved user input (a typed reject reason survives an error). Write-path errors show retry state and never silently drop an approval [F-070].

### 11.6 Permissions and RBAC — persona is not role [F-094]
Personas (§4) are design lenses; RBAC roles are the implementation contract. POC roles: **Analyst · Manager · Admin · Demo**. Workbook secondary roles (team lead, knowledge manager, compliance reviewer, data steward) map onto these for POC: team lead → Analyst+assignment-gate, knowledge manager → Analyst+KB, compliance reviewer → Manager(read)+Audit, data steward → Admin **[ASSUMPTION A-13]**. "Demo prospect" is an audience, not a role. Unpermitted controls are **hidden** in nav, **disabled-with-explanation** at action level, and deep links land on a **permission-denied state** naming the required role — the three treatments are deliberate and per-action below.

**Role–permission matrix** (V=view, A=act; –=hidden; d=disabled w/ explanation):
| Action | Analyst | Manager | Admin | Demo |
|---|---|---|---|---|
| View approval queue (S-04) | V | V | V | V |
| Approve / edit / reject resolution | A | d | d | A(replay data) |
| Confirm / decline merge | A | d | d | A |
| Assignment shadow feedback (S-08) | A | A | d | A |
| View sensitive identity detail (S-05 expand) | V | V | V | V |
| Resolve identity queue (S-02 tab) [F-044] | – | – | A | A |
| KB draft create/update (S-10) | A | d | d | A |
| View audit detail incl. model/version/cost (S-09) | V(own) | V | V | V |
| Audit export [A-07] | – | – | A | – |
| Reconciliation re-run (S-02) | – | – | A | A |
| Replay / presenter controls [F-088] | – | – | – | A |
| Demo lane (§12) incl. sync/event controls | – | – | – | A |
Every permitted action is attributed to a named stub user in the audit [F-089]. Replay controls are demo-flag-gated so cached output can never be mistaken for live product behaviour by a product persona.

### 11.7 Concurrency, idempotency and duplicate actions
Trust-critical for an approval system. Contracts, applied to every mutation in §10/§12: (a) **Optimistic locking** — every decision object carries a version token; a decision submitted against a stale version returns a conflict, and the UI shows **"already decided by ⟨user⟩ at ⟨time⟩"** with the recorded outcome, never a second approval. (b) **Double-submit** — controls disable on first activation; commit keys (`A`, `⌘Enter`) are ignored while a mutation is in flight. (c) **Idempotency** — every mutation carries an idempotency key (decision id + version); safe to retry. (d) **Ambiguous timeout** — if the network fails with the server outcome unknown, the UI shows "outcome unconfirmed — checking…" and reconciles by re-reading the decision state before re-enabling controls; it never blind-retries a write. (e) **Same-item concurrency** — two analysts opening one item both see it; the first decision wins, the second gets (a). (f) Post-decision, WriteExecution states (§5.3.2b) are shared truth for all viewers.

### 11.8 Error taxonomy — one vocabulary, mapped per screen
| Class | UI behaviour | Retry | Stale data visible? |
|---|---|---|---|
| Permission (401/403) | §11.6 denied state, names required role | No | No |
| Not found (404) | "Record unavailable" + back | No | No |
| Conflict (409/version) | "Already decided by X" reconciliation (§11.7) | Re-read | Replaced by truth |
| Validation (422) | Inline field error (e.g. empty reject reason) | After fix | Input preserved |
| Throttle (429) | "Rate-limited — retrying (n)" | Auto, backoff | Yes, stamped |
| Timeout | "Outcome unconfirmed — checking…" | Reconcile-then-retry | Yes, stamped |
| Partial data | Section-level notice, rest renders | Per-section | Yes, marked partial |
| Service failure (5xx) | Named dependency + manual retry + trace ID | Manual | Yes, stamped stale |
| External write failure | Sticky flag on item; approval preserved; re-fire execution only [F-070] | Manual re-fire | Decision state true |
| Broken/restricted citation | Card "evidence unavailable"; dependent claim withheld (fail safe) [P-2] | Per-card | Never fabricated |
| Signed-URL expiry (audio) | Transparent refresh, position preserved [F-137] | Auto ×1 then notice | — |
Every error surface includes a trace/support reference (§11.11). Generic "something went wrong" copy is prohibited.

### 11.9 Time, dates and freshness
Timestamps stored ISO-8601 UTC; displayed in **tenant default timezone (Asia/Kolkata for the demo tenant [ASSUMPTION A-14])** with a user-timezone override in the user menu; every relative time ("3m ago") carries the absolute timestamp on hover/tooltip; SLA countdowns tick client-side against server deadlines and re-sync on refresh. Freshness: live-changing surfaces (queue, SLA chips, connections, WriteExecution states) poll or receive events **[API CONTRACT NEEDED — mechanism]** with a "last refreshed" stamp; stale threshold 60s shows a stale badge + manual refresh; in-place updates never steal selection or scroll (§10.4). Working-hours logic uses `Schedule` entities; audit timestamps always absolute.

### 11.10 Security rendering
Source HTML (ticket comments, emails) is sanitised before render — raw model/tool markup is never executed. Attachments render name+type+scan state; blocked when malware-flagged [E02 fixture]. PII redaction tokens display as labelled chips, never reversible client-side [F-090]. Audio via short-lived signed URLs (§11.8 expiry row); no audio object is ever sent to a model and no control exists that would [F-137, NFR-39]. Restricted context removed by the trust filter is represented only as the filtered-count (§10.6) [F-052].

### 11.11 Observability and instrumentation
Every critical interaction emits a named UI event carrying `trace_id`/`run_id` correlation [F-006]: screen_load, decision_open, citation_drilldown, draft_edit, decision_submit(approve|edit|reject), write_outcome, merge_confirm, identity_resolve, replay_toggle. Audit records (§10.9) are the governance trail; telemetry events are operational — the two are correlated by trace ID but never conflated, and audit is never used as product analytics. Error surfaces show the trace reference for support.

---

## 12. Demo Swim Lane — not part of the product console
> Demonstration surfaces, not product features; they exist to make the pipeline legible to a non-technical audience. Visually fenced (striped `DEMO` header), Demo role only (§11.6), and nothing here ships in the product console. **Fidelity label (mandatory, per v3):** the connector journey below is a **functional demo against the six emulators** — not a clickable mock, and not live onboarding. **Catalogue correction:** the functional catalogue is **only the six emulated systems in `10_Source_Systems`** — Zendesk · Salesforce Service Cloud · Workday · Jira · Microsoft Entra · Slack/Teams. No Gmail, no Outlook, no "others", no OAuth, no credential capture: extra tiles may appear **only** as clearly-labelled `Concept — not implemented` tiles that are non-selectable. Nothing here implies live tenant integration [09_Out_of_Scope].

### 12.1 Connector setup journey — four screens, specified to product depth
**Scope Class:** POC demo-only (functional demo). **State machine:** §5.3.7. **Personas:** Demo presenter / Platform Admin rehearsing. **Traceability:** [F-120, F-121, F-122 adjacency; emulator fidelity F-108..F-118].

**D-1 · Catalogue & selection.**
*Layout:* header ("Connect ⟨tenant⟩'s systems" + `DEMO` banner) · grid of tiles — six emulated systems (selectable, `Emulated` chip each) + up to four `Concept — not implemented` tiles (greyed, non-selectable, tooltip "illustrative only — no adapter exists in the POC") · summary rail (selected count, estimated onboarding envelope) · CTA "Initialise adapters".
*States:* tile default/selected/concept-locked; CTA disabled until ≥1 selected; error (config unreadable).
*Data:* tiles ← `10_Source_Systems`; estimates ← §D-3 model. *Interactions:* select/deselect (local state only); CTA → D-2. *Accessibility:* tiles are checkboxes; concept tiles `aria-disabled` with reason.

**D-2 · Adapter initialisation & metadata discovery.**
*Layout:* per-system progress rows (`initializing → discovering`), each expanding into the **discovered-inventory table: standard objects vs custom objects** per system with counts (e.g. Zendesk: 11 standard + 2 custom incl. Assets; Salesforce: cases, contacts, entitlements; Workday: workers, org units) — the dynamic-inventory claim, ≥98% accuracy [08_Metrics].
*States per row:* §5.3.7 `initializing` (indeterminate + elapsed) / `discovering` (found-so-far count ticking) / `failed(resumable)` (named cause + Resume — never a silent reset).
*Data:* inventory ← MetadataReader output against emulators [F-033, F-108..118]. *Interactions:* expand rows; Continue → D-3 when all rows ≥ `inventory_ready`. *Accessibility:* progress announced per system at state change, not per tick.

**D-3 · Confirmation gate & staged ingestion plan.**
*Layout:* left — scan summary (systems, objects, estimated record volumes from the emulator corpus); right — the **staged plan** with per-stage estimates rendered as a labelled timeline: `adapter init ~10 min · bulk extract ~4 h · normalisation ~1 h · graph build ~20 h · validation ~30 min`.
*Estimate honesty (corrected):* durations are **derived, not decorative** — each stage estimate shows its basis on hover: bulk extract from `06_Integrations_APIs` (Zendesk incremental export ~10 req/min, cursor-paged ⇒ the 6,000-ticket corpus paces out in hours; Salesforce daily API ceiling drawn as a budget bar; ticket updates capped ~100/min). Where a basis isn't in the workbook the estimate is tagged **[ASSUMPTION]** on-screen in demo mode. A fixed note: *"Real tenant onboarding at enterprise scale runs 2–5 days; this demo compresses honestly (see fast-forward)."*
*States:* plan ready / recalculating / blocked (a system failed D-2). *Interactions:* **Confirm & begin ingestion** (the human gate of §5.3.7 — an explicit, logged demo action) · Back. *Accessibility:* the plan timeline has a table equivalent.

**D-4 · Ingestion progress & results.**
*Layout:* two-phase board — **Phase 1 · Bulk backfill**: per-system progress with resumable checkpoints (Temporal), chaos events surfacing honestly ("429 rate-limited — resumed from checkpoint, 0 loss" [NFR-8/35]); **Phase 2 · Incremental sync**: live tail of applied events. Controls rail (Demo role): **Fast-forward** · **Run incremental sync now** · **Simulate incoming event**. Results panel on `reconciling → complete`: users · tickets · records · accounts · reconciliation status per system [F-120] → "Proceed to console" → S-02.
*Fast-forward (specified):* steps the presentation clock across stage/day boundaries like a scrubbed video — progress, timestamps and event stamps advance **consistently with the compressed clock** (every timestamp remains internally honest; nothing claims wall-clock completion). Stepping is per-stage; each step announces "advanced to ⟨stage⟩, T+⟨n⟩h".
*Run incremental sync now (corrected semantics):* **enqueues an incremental pull/sync job** against the emulators — a pull, not a webhook — and shows the job in the Phase-2 tail.
*Simulate incoming event (separate control):* injects a synthetic source event (the live-meeting email) into an emulator so source-push webhook flow fires end-to-end; the injected item then appears in S-04 within the NFR-2 budget. The two controls are labelled distinctly and never merged.
*States:* per §5.3.7 with `failed(resumable)` per system leaving others running; `complete` copy reads "emulated ingestion run complete" — never "live".
*Data:* progress ← connector runs (`connector_run_id` [NFR-32]); results ← reconciliation output [F-120]. *Accessibility:* phase board keyboard-navigable; chaos events announced; fast-forward steps announced once each.

### 12.2 Channel-parity storyboard — **storyboard-only appendix (not engineering scope)**
**Correction applied:** `09_Out_of_Scope` excludes an end-user chatbot/deflection UI, so the customer-facing chat portal is **removed from the engineering specification**. No feature ID, no console route, no API or mutation contract, no acceptance criteria, and nothing in §14 traces to it. What remains, for storytelling only, is a **non-implementation storyboard** the demo team may present as static frames: an end-user raises the SSO issue by email, by Teams, and (frame-only) in a web chat, and the same cited answer arrives in each channel — a three-column parity frame (Email · Teams · Chat) making multi-channel response parity visible. If the client later wants this surface, it enters as a change request with its own feature row — it is not built from this document. **[OPEN DECISION OD-4: architect/PO to confirm storyboard-only disposition — this reverses the earlier fenced-demo-screen approach.]**

---

## 13. User journeys — step-by-step (entry trigger · happy path · failure branch · recovery · exit state)
Step grammar: **sees / does / system does / screen / state change / risk.**

### 13.1 Demo-scene journeys (scenes 1–8)
**J-S1 · Six systems, one twin.** Entry: demo open. 1. Presenter opens S-02 — sees six healthy `Emulated` cards, completeness 100% [F-120..122]. 2. Expands Zendesk — object table, checksums pass. 3. Opens S-03 — live counts (6,000 cases, 240 analysts, 900 articles). Failure branch: one card `attention` ⇒ presenter drills the run log, shows Temporal resume + 0 loss — the recovery *is* the demo point [NFR-35]. Exit: audience accepts the twin is real and honestly labelled.
**J-S2 · An issue arrives.** Entry: "Simulate incoming event" (D-4) injects the synthetic email; the voice call already ingested. 1. S-04 shows the new item arrive (<30s highlight [NFR-2]). 2. Open S-05 — timeline shows voice+email+slack. 3. Expand S-12 — play 20s, show low-confidence marks. Failure: ASR misreads an ID ⇒ shown as the *reason* per-word confidence exists. Exit: multi-channel intake proven, incl. a real transcribed call [F-133..135].
**J-S3 · Who is this.** 1. S-05 summary card — matched across 4 systems <2s; expand match evidence. 2. Partial-match variant on a second ticket — "unmatched: Salesforce" honest state. Exit: identity claim proven with its limits visible [F-045].
**J-S4 · What is it.** 1. S-07 classification High + "prior agreed" [F-061]. 2. Duplicates 0.93 ⇒ Confirm merge modal ⇒ merged (audit row). 3. SLA chip amber with deterministic expansion. Failure: low-confidence variant ⇒ needs-human-triage state — never a guess [F-059]. Exit: understanding stage complete, one human gate exercised.
**J-S5 · What do we know.** 1. S-06 pack: 4 systems in header [NFR-33], compiled 1.4s [NFR-1]. 2. Click citation → source → back. 3. Show `filtered: 2` and a redacted chip [F-052, F-090]. Failure: low-context variant with cause + re-enrich. Exit: the moat, visible.
**J-S6 · Who should handle it.** 1. S-08 shortlist; expand Priya's components; click "41 tickets" → cases [F-126..128]. 2. Show stretch row + `Shadow` chip [F-064]. Failure: trigger-conflict hold [F-065] — shown as respect for the tenant's own rules. Exit: routing gate accepted.
**J-S7 · What should we do.** 1. S-04 draft + evidence; approve-with-edit (diff). 2. Toast → S-09 timeline: recommendation→decision→write→outcome. 3. Show a reject path with mandatory reason on a second item. Failure: write 429 retries visible in audit; write-failed state on exhaustion with preserved approval [F-070]. Exit: gated write proven end to end [F-093].
**J-S8 · What did we learn.** 1. S-10 approve an article as draft (dedupe check shown). 2. S-11 digest: SSO cluster 14↑, deflection candidate, KB gap → S-10 gaps tab; capability map + anonymised development areas [F-129]. 3. S-09 QA-flag chip on one run [F-076]. Exit: the compounding loop closed on screen [F-078].

### 13.2 Day-in-the-life journeys
**J-DL-A Analyst (Priya)** — full narrative in §4.1; formalised: entry = shift start → S-04; 23 items; paths exercised: fast-approve ×14, edit-approve ×5, reject ×2 (reasons recorded), merge ×1, escalation-accept ×1; failure: one write-failed retry; exit = queue ≤3, all decisions audited. **J-DL-B Manager (Marcus)** — §4.2; entry = digest notification; paths: cluster drill, capability review (anonymised), audit reject-reason review; failure: a below-significance pattern he expects is absent — by design, he requests it via the gap queue instead of the UI inventing it; exit = 3 actions noted. **J-DL-C Admin** — §4.3; entry = morning health check; paths: S-02 verification, chaos-event inspection, D-1..4 rehearsal, RBAC check; failure: reconciliation delta ⇒ re-run; exit = green board.

### 13.3 Critical task journeys
**J-CT-1 · Approve a drafted resolution with an edit.** Trigger: queue item, band Medium. 1. `J`→item; sees draft + 3 evidence cards. 2. Spots step-3 error via S-12 transcript check (risk: approving a misread — mitigated by per-word confidence). 3. `E` edit; anchors preserved; fixes step. 4. `⌘Enter` approve-edited → approval record → Executor write → toast with audit link. 5. Failure branch: Executor 429×3 → visible retries → success; alt: exhaustion → write-failed flag, approval preserved, re-fire execution. Exit: case pending-solved; ResolutionRecord created; diff in audit [F-070, F-078, F-089].
**J-CT-2 · Manager acts on a recurring pattern.** Trigger: digest published. 1. S-11 SSO cluster 14 ↑. 2. Drill → case list → exemplar S-05 → linked Jira AUTH-341 (root cause) . 3. Opens KB gap → requests draft (S-10 gap tab). 4. Notes engineering escalation outside the system (the UI does not pretend to manage Jira — read-context only [F-119]). Failure: cluster evidence questioned → every number resolves to case IDs [P-4]. Exit: deflection path started; gap queued.
**J-CT-3 · Admin onboards a client to first live sync.** Trigger: new client demo. 1. D-1 select systems → D-2 init+discovery (standard vs custom objects) → D-3 confirmation gate: reviews staged estimates grounded in API limits → confirms. 2. D-4 phase-1 bulk with a chaos 429 → resumed, 0 loss. 3. Fast-forward across day boundary → validation → results + reconciliation [F-120]. 4. "Simulate incoming event" during the session → injected email appears in S-04 (webhook path); "Run incremental sync now" separately demonstrates the pull path. Failure: one system `attention` at validation → resumable retry, others proceed. Exit: S-02 shows six live-incremental emulated systems; audience saw an honest multi-day process in ten minutes.

---

## 14. Feature ID → screen/flow traceability & UI-impact matrix (all 137)
Every feature is classified **Direct UI** (owns a screen/component) · **Indirect UI** (creates human-visible behaviour/state on an existing screen) · **Demo-only UI** · **No UI** (backend-only; reason implicit in the epic). Epic labels verified row-by-row against `02_Feature_List` — **A-09 closed** (the earlier E-range mislabelling hid exactly one item, F-044, now Direct).

| IDs | Surfaced on |
|---|---|
| F-001..F-009 (E01 platform) | No UI (F-006 trace correlation: Indirect — §11.11, S-09; F-008/009 demo-readiness) |
| F-010..F-021 (E02 corpus) | No UI (aggregates visible S-03; F-018 attachments: Indirect — open from S-05 w/ scan state §11.10) |
| F-022, F-023 (E02 datasheet, batch revocation) | No UI |
| F-024..F-029 (E03 canonical entities) | No UI — they are what every screen renders |
| F-030, F-031 (E03 provenance envelope, graph projection) | No UI (provenance surfaces on evidence cards; graph paths via S-06 click-through) |
| F-032 (E04 Miragent salvage) | No UI |
| F-033 (E04 metadata scan) | Demo-only UI — D-2 inventory table |
| F-034, F-038 (E04 backfill, rate-limit) | Indirect — S-02/D-4 resumable & 429 states |
| F-035..F-037, F-040, F-041 (E04 listener, normaliser, fixtures, native-shape, contract) | No UI |
| F-039 (E04 gated ActionExecutor) | Indirect — WriteExecution states §5.3.2b on S-04/S-09 |
| F-042, F-043 (E05 identity resolution, account inference) | Indirect — S-05 identity card + evidence |
| F-044 (E05 unresolved-identity queue) | **Direct — S-02 Identity tab (§10.2), fifth human gate; S-05 deep-link** |
| F-045 | Direct — S-05 |
| F-046 | No UI (result visible S-02) |
| F-047..F-050 | No UI (attribution surfaces S-06) |
| F-051 | Direct — S-06 |
| F-052 | Indirect — S-06 filtered count |
| F-053 | No UI (freshness stamp S-05) |
| F-054 | Indirect — S-04 state, S-06 banner |
| F-055..F-058 | No UI |
| F-059 | Indirect — S-07, S-04 badges |
| F-060 | Indirect — S-07/S-04 proposal + §5.3.3 |
| F-061 | Indirect — S-07 prior note |
| F-062 | Indirect — SLA chip S-04/05/07 |
| F-063 | Indirect — S-08 |
| F-064 | Indirect — S-08 `Shadow` chip + §5.3.4 |
| F-065 | Indirect — S-07/S-08 held-conflict |
| F-066..F-068 | Indirect — S-04 draft pane, S-06 citations, S-09 shield note |
| F-069 | Indirect — S-04 escalation card, S-05 timeline |
| F-070 | Indirect — WriteExecution UI §5.3.2b, S-09 timeline |
| F-071 | No UI (the flow itself) |
| F-072 | Indirect — S-10 + §5.3.5 verbs |
| F-073 | Indirect — S-10 gaps tab, S-03 donut |
| F-074/F-075 | Indirect/Direct — S-11 |
| F-076 | Indirect — S-09 flags, S-11 quality |
| F-077 | Indirect — §11.2 policy everywhere |
| F-078 | Indirect — S-09 outcome link, S-06 `learned` chip |
| F-079 | Direct — S-01, S-14 (auth stub); CR-01/02/03 pending [OD-3] |
| F-080 | Direct — S-03 |
| F-081 | Direct — S-04 |
| F-082 | Direct — S-05 |
| F-083 | Direct — S-06 |
| F-084 | Direct — S-07 |
| F-085 | Direct — S-09 |
| F-086 | Direct — S-10 |
| F-087 | Direct — S-11 |
| F-088 | Indirect — states everywhere; Replay = Demo-role control (§11.6) |
| F-089 | Direct — S-09 |
| F-090 | Indirect — redaction chips S-06, §11.10 |
| F-091/F-092 | No UI |
| F-093 | Indirect — structural absence of ungated writes, demonstrated S-04/S-09 |
| F-094 | Direct — S-14 role pick; Indirect everywhere via §11.6 matrix |
| F-095..F-100 | No UI (F-099 shapes NFR budgets per screen) |
| F-101 | Indirect — S-09 completeness header |
| F-102..F-107 (E14) | Demo-only — journeys §13.1; F-105..107 artefacts |
| F-108..F-118 (replica schemas/emulator APIs) | No UI (fidelity behind S-02/D-2 credibility) |
| F-119 | Indirect — read-context links on S-05; no write controls |
| F-120 | Direct — S-02 tables; Demo-only D-4 results |
| F-121 | Indirect — chips: tenant bar, S-02, every evidence card, D-1 tiles |
| F-122 | Direct — S-02 |
| F-123..F-125 | Indirect — S-08 expanded rows, S-11 capability map |
| F-126 | Indirect — S-08 signals + drill, S-11 |
| F-127 | Indirect — S-08 scores |
| F-128 | Direct — S-08 |
| F-129 | Indirect — S-11 anonymised section |
| F-130 | Indirect — S-08 availability line only |
| F-131/F-132 | No UI |
| F-133/F-134 | Indirect — S-05 voice entries, S-12 |
| F-135 | Direct — S-12 |
| F-136 | No UI (separate metrics pack) |
| F-137 | Indirect — S-12 signed-URL + control absence |

## 14A. Console API operation matrix (logical operations — frontend↔backend contract)
`06_Integrations_APIs` covers external systems only; the console's own API is undefined in the workbook, so operations below are **logical contracts** — names, read/write, key semantics — every one tagged **[API CONTRACT NEEDED]** for endpoint paths, full DTOs and transport. R=read, W=write(mutation). All W ops: idempotency key, version token, trace_id, audit effect per §11.7/§11.11.

| Op | R/W | Screen(s) | Key semantics |
|---|---|---|---|
| listConnections / getReconciliation | R | S-02, D-4 | per-system state, counts, completeness; refresh per §11.9 |
| listIdentityQueue / resolveIdentity | R/W | S-02 tab | W: candidate id or new-actor or dismiss(reason); audit row [F-044] |
| getDashboardAggregates | R | S-03 | named aggregate set; each drillable to case-id list |
| listQueueItems | R | S-04 | filters/sort as specified; cursor pagination; URL-state mirror |
| getRecommendation / getContextPack | R | S-04, S-06 | pack carries citation DTOs (below) |
| submitDecision | W | S-04 | approve/edit(edited_text,diff)/reject(reason); version token; returns RecommendationDecision state |
| getWriteExecution / refireExecution | R/W | S-04, S-09 | §5.3.2b states; refire only from `failed`, reuses approval |
| confirmMerge / declineMerge | W | S-04/S-07 | enters HITL write gate §5.3.3 |
| submitAssignmentFeedback | W | S-08 | shadow feedback only [OD-2]; audit row |
| getTicket360 / listTimeline | R | S-05 | identity evidence, partial/conflict states |
| listCases (search/filter) | R | S-13 | same filter vocabulary as S-04; panel + page modes |
| getCallRecording | R | S-12 | short-lived signed URL; refresh op on expiry |
| listAuditDecisions / getAuditTimeline / exportAudit | R | S-09 | export Admin-only [A-07] |
| listKbDrafts / submitKbDecision | R/W | S-10 | W verbs per §5.3.5 (draft=true only) |
| getWeeklyDigest | R | S-11 | every number carries backing case-id refs |
| listNotifications / markRead | R/W | §10.15 | sticky-failure rule; per-role state [CR-03] |
| demo: runIncrementalSync / simulateEvent / stepFastForward / setReplay | W | §12, demo header | Demo role only; replay flag-gated [F-088, §11.6] |

**Citation DTO (contract):** `{source_system, source_type(ticket|comment|article|resolution|graph_path), object_id, excerpt, source_ts, deep_link, access_status(ok|restricted|missing), relevance?}` — `restricted|missing` ⇒ fail-safe per §11.8; relevance shown only when genuinely produced by retrieval [F-050]. A citation is never fabricated; a claim without a resolvable citation is withheld [P-2].

## 14B. Screen acceptance-test matrix (Given/When/Then — representative, min. set per screen)
Five classes covered per screen: happy · permission · failure · keyboard/a11y · concurrency. Full suites extend these in QA.

**S-04 Approval queue.** G an item band=High W analyst presses `A` T decision `approved`, controls disable, WriteExecution `queued→…→succeeded`, toast links audit row, list auto-advances. · G band=Low W `A` T no approval fires; confirm-modal path required, evidence auto-expanded. · G another user already decided W submit T 409 path: "already decided by X", state replaces pane, no second approval (§11.7). · G write fails after retries W viewing item T flag "write failed — action required", approval preserved, refire control only. · G reject modal open W submit with empty reason T 422 inline, input preserved. · G keyboard-only session W full journey J/K/Enter/A/E/R/Esc T every action completes without pointer; focus visible throughout.
**S-02 Connections (+Identity tab).** G chaos 429 during backfill W viewing T card `rate-limited(retrying)` with "0 loss" copy; on resume `healthy`, run log shows checkpoints. · G an ambiguous identity queued W admin resolves candidate A T audit row written; S-05 card flips partial→matched on next load; queue count decrements. · G analyst role W deep-link to Identity tab T permission-denied names Admin (§11.6). · G reconciliation delta W expand system T failing object named with Δ; re-run control Admin-only.
**S-05/S-06.** G identity 3-of-4 W open 360 T unmatched system named, not hidden; deep-link to Identity tab shown. · G a citation `access_status=restricted` W pack renders T card "evidence unavailable", dependent draft sentence withheld (fail safe). · G pack compile exceeds 2s W waiting T skeleton replaced by honest-delay notice at budget [NFR-1, §11.5]. · G anchor [3] focused W Enter T card 3 focused; Shift+Enter returns (a11y).
**S-07/S-08.** G similarity 0.93 W confirm merge T modal shows both timelines; confirm enters write gate §5.3.3; audit row. · G similarity 0.71 T link-only, no proposal. · G shadow mode W accept proposal T feedback+audit recorded, **no external assignment write occurs**, chip states it. · G a displayed number "41 tickets" W click T the 41 case IDs list (S-13 panel) [NFR-42]. · G trigger conflict W viewing T proposal held with named trigger; no write path offered.
**S-09/S-10.** G any demo-path write W audit opened T full chain recommendation→evidence→confidence→model/version→decision(actor,time)→WriteExecution→outcome, immutable UI. · G KB approve W submit T "Create/update Zendesk Guide draft (draft=true)"; no publish-live control exists anywhere (negative test). · G reject W empty reason T 422.
**S-12.** G word confidence 0.54 W hover T numeric + alternative shown; click line T audio jumps. · G signed URL expired W playing T transparent refresh once, position preserved; second failure → §11.8 notice. · G keyboard W space/←/→ T full transport (a11y).
**S-13/S-14/§10.15.** G drill from S-03 segment W panel opens T filter chip applied+removable, origin preserved on Esc×2. · G ⌘K exact case id T S-05 direct. · G role picked at S-14 W landing T role-default route; audit attribution uses stub user. · G write-failed notification W clicked T stays sticky-bold until state clears. **§12 lane.** G "Run incremental sync now" W pressed T a pull job appears in Phase-2 tail (no webhook fired). · G "Simulate incoming event" W pressed T webhook path fires; item reaches S-04 within NFR-2. · G fast-forward step W pressed T clocks advance consistently; copy never claims wall-clock or "live".

## 14C. UI Data/ViewModel field matrix (consolidated contract)
Columns per v3: element · source type (C=canonical, A=agent-output, G=aggregate, D=DTO) · field · nullable behaviour · formatting · freshness · permission. The per-screen **Data** rows in §10 follow this same contract; the matrix below binds the highest-traffic elements; anything unmappable is [DATA CONTRACT NEEDED].

| Element (screen) | Src | Field | Null behaviour | Format | Freshness | Perm |
|---|---|---|---|---|---|---|
| Queue row subject/status (S-04) | C | Case.subject, status_category | never null; missing subject → "(no subject)" | text; chip per §5.3.1 | poll/event §11.9 | Analyst+ |
| SLA countdown (S-04/05/07) | C+G | SLAClock.deadline − now | no clock → no chip (not "0") | `Breach in 42m` / paused | client tick + resync | all |
| Confidence band (S-04/06/07) | A | calibrated score [F-077] | uncalibrated → flag only, numeric hidden | band + hover numeric | at draft version | all |
| Draft sentence + anchor (S-04) | A | resolution.draft[].text, citation_ref | uncited → withheld placeholder [P-2] | rich text, sanitised §11.10 | immutable per version | Analyst+ |
| Evidence card (S-06) | D | Citation DTO (§14A) | access_status≠ok → "evidence unavailable" | §8.4 anatomy | pack compile time | trust-filtered |
| Identity card (S-05) | C+A | Actor + per-system match evidence | partial → named unmatched system; conflict → both candidates | §10.5 | cached, stamp shown [NFR-3] | all; expand logs access |
| Component scores (S-08) | A | capability engine outputs [F-127] | below sample floor → signal absent [NFR-41] | bars + numerics, drillable | weekly batch + stamp | Analyst+/Manager |
| History numbers (S-08) | G | analyst_class_experience.* | n<floor → not emitted | tabular numerals | batch stamp | as above |
| Audit entry (S-09) | C | decision_audit.* | gaps impossible by F-101 check; missing → completeness alert | immutable timeline | append-only | §11.6 |
| Digest figures (S-11) | G | Pattern-Miner batch outputs | below significance → row absent | prose-first + drill | weekly, dated | Manager+ |
| Connection card (S-02) | D | connector run status + reconciliation | pre-first-sync → awaiting state | §10.2 | poll §11.9 | Admin (visible all) |
| Word confidence (S-12) | A | asr_segments[].confidence | missing timing → plain transcript, note shown | dotted underline + tooltip | immutable artefact | all |
| KPI tiles (S-03) | G | named aggregates over Case/Actor/KB | source empty → structured empty state, never fake zero | tabular + delta | query stamp | all |

## 15. Open Decisions & assumptions (owner needed)
Assumptions (A-nn) are proposed choices marked in place; Open Decisions (OD-n) are source conflicts or undefined contracts that must not be silently resolved.

| # | Item | Blocking? |
|---|---|---|
| OD-1 | **Case.status_category enum + legal transitions** — not defined in `05_Data_Entities`; §5.3.1's Zendesk-aligned set is a proposal held in config. | State machine sign-off |
| OD-2 | **Assignment mode** — POC strictly shadow-only (specified default), or is an approved-assignment write to the Zendesk emulator permitted? Determines §5.3.4 write states and S-08 labelling. | S-08 |
| OD-3 | **F-079 scope of shell extras** — S-13 tickets list (CR-01), global search (CR-02), notification panel (CR-03) are not committed by F-079. Ratify or drop; S-13 is required by the no-dead-end rule, so a drop needs an alternative drill target. | S-01/S-13/§10.15 |
| OD-4 | **Channel-parity portal disposition** — storyboard-only appendix (§12.2, current spec) vs. any implemented surface. `09_Out_of_Scope` says no end-user UI. | Demo lane |
| OD-5 | **Console API ownership** — every §14A operation is [API CONTRACT NEEDED]: endpoint paths, DTOs, transport, refresh mechanism (§11.9 poll vs events), frontend/backend split. | Build start |
| OD-6 | **Timezone policy** — tenant default (A-14 proposes Asia/Kolkata for demo) + user override; confirm for SLA and audit displays. | None |
| OD-7 | **Browser/viewport support** — proposed: latest Chrome + Edge, min 1280px [ASSUMPTION]; confirm test matrix. | QA |
| OD-8 | **QA/Verifier & calibration surfacing** — POC console shows flags (S-09) + digest quality section only; confirm that is the intended extent. | S-09/S-11 |
| A-01 | Demo tenant name "Halcyon Foods Group" (single config value `config.demo_tenant_name`); Motiveminds = provider. | Wireframes |
| A-02 | Class override on S-07 = audited proposal-correction; remove if out. | S-07 |
| A-03 | Notifications in-app only (moot if CR-03 dropped). | — |
| A-04 | Primary hue deep purple (hex tokens are implementation truth; Pantone refs move to design appendix). | Tokens |
| A-05 | Band thresholds 0.85/0.60 placeholders owned by calibration [F-077], read from config. | None |
| A-06 | Reject reason min 10 chars; free text for POC (reason codes = future). | None |
| A-07 | Admin CSV audit export. | S-09 |
| A-08 | No bulk approve (per-item by principle). | S-04 |
| A-12 | A toast the user saw counts as read (§10.15). | — |
| A-13 | Secondary workbook roles map onto four POC roles (§11.6). | RBAC |
| A-14 | Tenant timezone Asia/Kolkata for demo. | OD-6 |
| — | A-09 (F-022..044 verification) and A-10 (portal fencing) are **closed** — resolved into §14 and OD-4 respectively. | — |

## 16. Proposed additions / change requests (no existing feature ID)
None are committed scope until ratified [OD-3]; none silently became POC requirements.
**CR-01 · S-13 Tickets list/search** — required by the no-dead-end navigation rule; recommend accepting under F-079. **CR-02 · Global ⌘K search** — shell convenience; droppable without breaking any journey (S-13 filters substitute). **CR-03 · Notification panel** — merge/escalation/failure awareness; droppable for POC (queue badges substitute). Minor, rulable-on-sight: "view as table" chart toggle (a11y) · `?` shortcut overlay · honest-delay notice pattern (§11.5, policy not feature) · audit CSV export [A-07] · re-enrichment request control on S-06 (implied by F-054).

---

## Definition-of-done self-check (v3 contract)
1. Fourteen screens + notification panel carry the full implementation contract incl. Scope Class — §10.1–10.15 ✔
2. Every screen/flow/journey/control feature-backed or explicitly a CR (§16) ✔
3. All 137 features classified Direct / Indirect / Demo-only / No UI — §14 ✔ (A-09 closed)
4. Narrative + agent-to-UI map internally consistent — §3.4/§5.2 ✔
5. State machines: Case [OD-1 flagged, config-held] · RecommendationDecision · WriteExecution · Dedup · Assignment-shadow · KB draft · Identity · Connector — §5.3 ✔; decision ≠ write everywhere ✔
6. Every displayed value maps to canonical / agent-output / aggregate / DTO; no invented canonical fields; gaps tagged [DATA CONTRACT NEEDED] ✔
7. Every mutation: preconditions, permission, gate, audit, idempotency/concurrency (§11.7), write states, retry/failure, acceptance rows (§14B) ✔
8. `09_Out_of_Scope` respected; portal removed from engineering scope (§12.2, OD-4); anti-ranking guardrails on S-08/S-11 ✔
9. KPI claims only from `08_Metrics_KPIs`; operational values traceable (§1.4 corrected rule) ✔
10. Demo-only surfaces + replay controls fenced and role-gated (§11.6, §12); six emulated systems only; nothing labelled "live" ✔
11. Lists specify columns/filters/sort/virtualisation/URL state/refresh (S-04, S-13, §11.9) ✔
12. Accessibility (WCAG 2.2 AA target), latency, permission, error and concurrency criteria measurable per screen (§10, §11.8, §14B) ✔
13. API operation matrix (§14A), RBAC matrix (§11.6), acceptance matrix (§14B), ViewModel field matrix (§14C), glossary (§2A) and screen/route registry (§6.3) present ✔
14. All unresolved source conflicts live in §15 as Open Decisions, not hidden in assumptions ✔

*End of ITR_UI_MasterSpec — v2.0 (developer-ready)*