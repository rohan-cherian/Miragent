/* Per-case detail fixtures: identity, timeline, context pack, draft, explainers,
   assignment shortlist, call artefact. Every claim carries a citation; every card
   carries a source reference — an evidence card without one structurally cannot
   render (§8.4, P-2). Cases without a hand-authored detail fall back to a
   generated one so no drill-down ever dead-ends. */

import { NOW, caseById, actorMeta, classMeta, channelMeta, ANALYSTS, TEAMS } from './corpus.js'
import { IdentityState } from '../contracts/state.js'

const MIN = 60000, HOUR = 3600000

/* ---------- Identity cards (§10.5, F-045) ---------- */
export const IDENTITY = {
  'act-001': {
    state: IdentityState.MATCHED,
    matched_systems: ['zendesk', 'workday', 'entra', 'salesforce'],
    unmatched_systems: [],
    resolve_ms: 1840,
    account: 'Halcyon Foods Group — Group IT',
    tier: 'Enterprise',
    org_unit: 'Payroll Ops',
    manager: 'Aisha Bello',
    entitlements: 4,
    assets: 2,
    open_cases: 3,
    csat_trend: [4, 4, 3, 3, 2],
    refreshed_at: new Date(NOW - 3 * MIN).toISOString(),
    evidence: [
      { system: 'zendesk',    fields: ['requester_email', 'organization_id'], confidence: 0.97, note: 'Exact email match on requester record #48120.' },
      { system: 'workday',    fields: ['work_email', 'employee_id', 'supervisory_org'], confidence: 0.95, note: 'Worker 30042 · Payroll Ops · reports to A. Bello.' },
      { system: 'entra',      fields: ['userPrincipalName', 'objectId'], confidence: 0.99, note: 'UPN match; 2 registered devices; last sign-in 07:58.' },
      { system: 'salesforce', fields: ['contact_email', 'account_domain'], confidence: 0.88, note: 'Contact on account "Halcyon Foods Group".' },
    ],
  },
  // 3-of-4: an honest partial. Never hidden, never blocking (§10.5).
  'act-014': {
    state: IdentityState.PARTIAL,
    matched_systems: ['zendesk', 'workday', 'entra'],
    unmatched_systems: ['salesforce'],
    unmatched_reason: 'no contact on domain halcyonfoods.example',
    resolve_ms: 2110,
    account: 'Halcyon Foods Group — Group IT',
    tier: 'Enterprise', org_unit: 'IT Service Desk', manager: 'Tomas Novak',
    entitlements: 2, assets: 1, open_cases: 5,
    csat_trend: [5, 4, 4, 4, 4],
    refreshed_at: new Date(NOW - 11 * MIN).toISOString(),
    evidence: [
      { system: 'zendesk', fields: ['requester_email'], confidence: 0.96, note: 'Exact email match.' },
      { system: 'workday', fields: ['work_email', 'employee_id'], confidence: 0.93, note: 'Worker 31188 · IT Service Desk.' },
      { system: 'entra',   fields: ['userPrincipalName'], confidence: 0.98, note: 'UPN match; 1 registered device.' },
    ],
  },
}

export const identityFor = (actorId) => IDENTITY[actorId] || {
  state: IdentityState.MATCHED,
  matched_systems: ['zendesk', 'workday', 'entra'],
  unmatched_systems: [],
  resolve_ms: 1600 + (actorId.charCodeAt(4) % 9) * 60,
  account: 'Halcyon Foods Group — Group IT',
  tier: actorMeta(actorId).tier,
  org_unit: actorMeta(actorId).org_unit,
  manager: 'Aisha Bello',
  entitlements: 2, assets: 1,
  open_cases: 1 + (actorId.charCodeAt(5) % 4),
  csat_trend: [4, 4, 5, 4, 4],
  refreshed_at: new Date(NOW - 9 * MIN).toISOString(),
  evidence: [
    { system: 'zendesk', fields: ['requester_email'], confidence: 0.96, note: 'Exact email match on requester record.' },
    { system: 'workday', fields: ['work_email'], confidence: 0.92, note: 'Worker record matched on work email.' },
    { system: 'entra',   fields: ['userPrincipalName'], confidence: 0.97, note: 'UPN match.' },
  ],
}

/* ---------- Unresolved identity queue (S-02 Identity tab, F-044) ---------- */
export const IDENTITY_QUEUE = [
  {
    id: 'idq-1',
    incoming: { name: 'D. Okafor', email: 'd.okafor@halcyon-foods.example', source: 'salesforce', first_seen: new Date(NOW - 4 * HOUR).toISOString() },
    case_count: 2, queued_at: new Date(NOW - 4 * HOUR).toISOString(),
    best_score: 0.58,
    candidates: [
      { id: 'cand-a', system: 'salesforce', label: 'Daniel Okafor · Contact 0035g00000A', score: 0.58,
        fields: [
          { field: 'email', incoming: 'd.okafor@halcyon-foods.example', candidate: 'd.okafor@halcyonfoods.example', verdict: 'near — domain hyphen differs' },
          { field: 'name', incoming: 'D. Okafor', candidate: 'Daniel Okafor', verdict: 'initial vs full given name' },
          { field: 'account', incoming: '(none)', candidate: 'Halcyon Foods Group', verdict: 'no incoming value' },
        ] },
      { id: 'cand-b', system: 'salesforce', label: 'Danielle Okafor · Contact 0035g00000B', score: 0.55,
        fields: [
          { field: 'email', incoming: 'd.okafor@halcyon-foods.example', candidate: 'danielle.okafor@halcyonfoods.example', verdict: 'different local part' },
          { field: 'name', incoming: 'D. Okafor', candidate: 'Danielle Okafor', verdict: 'initial matches both candidates' },
          { field: 'account', incoming: '(none)', candidate: 'Halcyon Foods Group', verdict: 'no incoming value' },
        ] },
    ],
  },
  {
    id: 'idq-2',
    incoming: { name: 'plantops.dublin', email: 'plantops.dublin@halcyonfoods.example', source: 'slack', first_seen: new Date(NOW - 26 * HOUR).toISOString() },
    case_count: 1, queued_at: new Date(NOW - 26 * HOUR).toISOString(),
    best_score: 0.44,
    candidates: [
      { id: 'cand-c', system: 'workday', label: 'Shared mailbox — Plant Ops Dublin', score: 0.44,
        fields: [
          { field: 'email', incoming: 'plantops.dublin@halcyonfoods.example', candidate: 'plantops.dublin@halcyonfoods.example', verdict: 'exact — but the mailbox is shared, not a person' },
          { field: 'worker_id', incoming: '(none)', candidate: '(none)', verdict: 'no worker record exists' },
        ] },
    ],
  },
]

/* ---------- Timelines (§10.5) ---------- */
export const TIMELINES = {
  'HFG-2214': [
    { id: 'c1', type: 'comment', channel: 'voice', author: 'Daniel Okafor', ts: new Date(NOW - 3.5 * HOUR).toISOString(),
      text: 'Inbound call, 6:12. "I cannot get in since the password rotation on Friday — it takes my password then loops straight back to the login page."',
      call_id: 'call-2214', asr_confidence_avg: 0.91 },
    { id: 'c2', type: 'event', channel: 'system', author: 'Listener', ts: new Date(NOW - 3.48 * HOUR).toISOString(),
      text: 'Canonical Case created from Zendesk ticket #48120 (idempotent on external_id).' },
    { id: 'c3', type: 'event', channel: 'system', author: 'Context Enricher', ts: new Date(NOW - 3.47 * HOUR).toISOString(),
      text: 'Identity resolved across Zendesk · Workday · Entra · Salesforce in 1.84s.' },
    { id: 'c4', type: 'comment', channel: 'email', author: 'Daniel Okafor', ts: new Date(NOW - 2.1 * HOUR).toISOString(),
      text: 'Following up on my call — still cannot sign in. I tried the self-service reset twice. Payroll run is Thursday so this is blocking.' },
    { id: 'c5', type: 'comment', channel: 'slack', author: 'Daniel Okafor', ts: new Date(NOW - 1.4 * HOUR).toISOString(),
      text: '#it-help — "anyone else in Payroll Ops locked out of SSO? third person here today"' },
    { id: 'c6', type: 'event', channel: 'system', author: 'Dedup & Linker', ts: new Date(NOW - 1.38 * HOUR).toISOString(),
      text: 'Merge proposed: HFG-2231 (0.93) and HFG-2244 (0.89) appear to be the same issue. Proposal only — no merge performed.' },
    { id: 'c7', type: 'event', channel: 'system', author: 'Prioritisation', ts: new Date(NOW - 1.3 * HOUR).toISOString(),
      text: 'SLA breach risk raised to amber. Deterministic score 0.72 from policy "Enterprise · P2 · business hours".' },
    { id: 'c8', type: 'comment', channel: 'internal', author: 'Rahul Bose', ts: new Date(NOW - 55 * MIN).toISOString(),
      text: 'Internal note: Jira AUTH-341 looks like the root cause — conditional access policy change shipped Friday.' },
    { id: 'c9', type: 'event', channel: 'system', author: 'Resolution', ts: new Date(NOW - 40 * MIN).toISOString(),
      text: 'Cited draft resolution produced. Confidence 0.78 (Medium). Awaiting human decision.' },
  ],
  'HFG-2402': [
    { id: 'p1', type: 'comment', channel: 'email', author: 'Lena Hartmann', ts: new Date(NOW - 7 * HOUR).toISOString(),
      text: 'The Ireland payroll interface file was rejected again this morning — cost centre IE-4402 is not recognised.' },
    { id: 'p2', type: 'event', channel: 'system', author: 'Resolution', ts: new Date(NOW - 2.2 * HOUR).toISOString(),
      text: 'Cited draft produced. Confidence 0.88 (High).' },
    { id: 'p3', type: 'decision', channel: 'system', author: 'Aisha Bello', ts: new Date(NOW - 95 * MIN).toISOString(),
      text: 'Approved without edit. Decision recorded — audit #A-99231.' },
    { id: 'p4', type: 'write', channel: 'system', author: 'Action Executor', ts: new Date(NOW - 94 * MIN).toISOString(),
      text: 'Write queued to Zendesk (public comment + solve).' },
    { id: 'p5', type: 'write', channel: 'system', author: 'Action Executor', ts: new Date(NOW - 93 * MIN).toISOString(),
      text: 'Attempt 1 — 429 rate-limited. Backing off 2s.' },
    { id: 'p6', type: 'write', channel: 'system', author: 'Action Executor', ts: new Date(NOW - 92 * MIN).toISOString(),
      text: 'Attempt 2 — 429 rate-limited. Backing off 8s.' },
    { id: 'p7', type: 'write', channel: 'system', author: 'Action Executor', ts: new Date(NOW - 91 * MIN).toISOString(),
      text: 'Attempt 3 — 502 from Zendesk emulator. Retries exhausted; write FAILED. Approval preserved; item flagged for re-fire.' },
  ],
}

/** Generated fallback so every case in the 6,000 opens onto a real timeline. */
export function timelineFor(caseId) {
  if (TIMELINES[caseId]) return TIMELINES[caseId]
  const c = caseById(caseId)
  if (!c) return []
  const a = actorMeta(c.requester)
  const t0 = new Date(c.created_at).getTime()
  return [
    { id: `${caseId}-1`, type: 'comment', channel: c.channel, author: a.name, ts: new Date(t0).toISOString(),
      text: `${c.subject}. Reported from ${a.org_unit}.` },
    { id: `${caseId}-2`, type: 'event', channel: 'system', author: 'Listener', ts: new Date(t0 + 60000).toISOString(),
      text: `Canonical Case created from the ${channelMeta(c.channel).label.toLowerCase()} intake path (idempotent on external_id).` },
    { id: `${caseId}-3`, type: 'event', channel: 'system', author: 'Triage/Classifier', ts: new Date(t0 + 90000).toISOString(),
      text: `Classified ${c.class} at confidence ${c.confidence.toFixed(2)} (${c.band}).` },
    { id: `${caseId}-4`, type: 'event', channel: 'system', author: 'Context Enricher', ts: new Date(t0 + 120000).toISOString(),
      text: 'Context pack compiled across 3 systems.' },
  ]
}

/* ---------- Context packs (§10.6) ---------- */
export const PACKS = {
  'HFG-2214': {
    compiled_at: new Date(NOW - 41 * MIN).toISOString(),
    compile_ms: 1420,
    systems_in_pack: 4,
    token_budget_used: 0.63,
    filtered_count: 2,
    withheld_count: 1,
    citation_coverage: 0.94,
    low_context: false,
    cards: [
      { n: 1, source_system: 'zendesk', source_type: 'resolution', object_id: 'RR-8871',
        excerpt: 'Resolved 11 Jul: after the quarterly password rotation, users in the Payroll Ops group must re-consent the Entra conditional-access policy. Clearing the cached SAML session and re-authenticating resolves the loop.',
        source_ts: new Date(NOW - 30 * 24 * HOUR).toISOString(), relevance: 0.94,
        access_status: 'ok', learned: true, deep_link: '/case/HFG-2088' },
      { n: 2, source_system: 'jira', source_type: 'ticket', object_id: 'AUTH-341',
        excerpt: 'Conditional access policy "Require re-consent after credential change" shipped Fri 07:00. Known side effect: cached SAML sessions loop at the IdP for members of dynamic group PayrollOps-All.',
        source_ts: new Date(NOW - 3 * 24 * HOUR).toISOString(), relevance: 0.91,
        access_status: 'ok', deep_link: null },
      { n: 3, source_system: 'entra', source_type: 'graph_path',
        object_id: 'signIn/30042',
        excerpt: 'Sign-in log for worker 30042: 6 failures 08:02–08:41, all AADSTS50105 "user not assigned to a role for the application". Device compliant. Last successful sign-in Thu 17:22.',
        source_ts: new Date(NOW - 4 * HOUR).toISOString(), relevance: 0.88,
        access_status: 'ok', deep_link: null },
      { n: 4, source_system: 'zendesk', source_type: 'article', object_id: 'KB-3312',
        excerpt: 'Runbook R-07 · SSO loop after credential change — 1. Confirm the user is in PayrollOps-All. 2. Clear the cached SAML session. 3. Ask the user to re-authenticate and accept the consent prompt. 4. If the loop persists, raise to IAM with the sign-in correlation ID.',
        source_ts: new Date(NOW - 120 * 24 * HOUR).toISOString(), relevance: 0.86,
        access_status: 'ok', runbook: 'R-07', deep_link: null },
      { n: 5, source_system: 'workday', source_type: 'ticket', object_id: 'WK-30042',
        excerpt: 'Worker 30042 · ⟨NAME⟩ · Payroll Ops · supervisory org PAY-IE · employment status active. Manager ⟨NAME⟩.',
        source_ts: new Date(NOW - 26 * HOUR).toISOString(), relevance: 0.72,
        access_status: 'ok', redacted: true, deep_link: null },
      { n: 6, source_system: 'salesforce', source_type: 'ticket', object_id: 'ENT-2201',
        excerpt: null,
        source_ts: new Date(NOW - 60 * 24 * HOUR).toISOString(), relevance: null,
        access_status: 'restricted', deep_link: null },
      { n: 7, source_system: 'slack', source_type: 'comment', object_id: 'C0192/17281',
        excerpt: '#it-help — three separate Payroll Ops users reporting the same login loop this morning. Thread started 08:44.',
        source_ts: new Date(NOW - 90 * MIN).toISOString(), relevance: 0.64,
        access_status: 'ok', stale: false, deep_link: null },
    ],
  },
  // Low-context: retrieval below threshold, named cause, re-enrich offered [F-054].
  'HFG-2308': {
    compiled_at: new Date(NOW - 12 * MIN).toISOString(),
    compile_ms: 4210,
    systems_in_pack: 1,
    token_budget_used: 0.11,
    filtered_count: 0,
    withheld_count: 4,
    citation_coverage: 0.31,
    low_context: true,
    low_context_cause: 'Retrieval below threshold (0.41). Cause: no KB coverage for class `sso-scim-sync`.',
    cards: [
      { n: 1, source_system: 'entra', source_type: 'graph_path', object_id: 'provisioning/log/8821',
        excerpt: 'SCIM provisioning job 8821: 40 users removed from scope at 02:14 following a dynamic-group rule change. No error raised by the job.',
        source_ts: new Date(NOW - 8 * HOUR).toISOString(), relevance: 0.53,
        access_status: 'ok', deep_link: null },
    ],
  },
}

export function packFor(caseId) {
  if (PACKS[caseId]) return PACKS[caseId]
  const c = caseById(caseId)
  if (!c) return null
  const cls = classMeta(c.class)
  return {
    compiled_at: new Date(NOW - 20 * MIN).toISOString(),
    compile_ms: 1180 + (c.id.charCodeAt(6) % 7) * 90,
    systems_in_pack: 3, token_budget_used: 0.48, filtered_count: 0, withheld_count: 0,
    citation_coverage: 0.92, low_context: false,
    cards: [
      { n: 1, source_system: 'zendesk', source_type: 'resolution', object_id: `RR-${7000 + (c.id.charCodeAt(5) % 900)}`,
        excerpt: `Prior resolution in class ${cls.label}: the fix applied on the last three occurrences was a configuration correction on the ${cls.cat.toLowerCase()} side, verified by the requester.`,
        source_ts: new Date(NOW - 21 * 24 * HOUR).toISOString(), relevance: 0.89, access_status: 'ok', learned: true, deep_link: null },
      { n: 2, source_system: 'zendesk', source_type: 'article', object_id: `KB-${3000 + (c.id.charCodeAt(6) % 700)}`,
        excerpt: `Guide article covering ${cls.label}: symptom, checks, and the standard remediation sequence.`,
        source_ts: new Date(NOW - 90 * 24 * HOUR).toISOString(), relevance: 0.81, access_status: 'ok', deep_link: null },
      { n: 3, source_system: 'workday', source_type: 'ticket', object_id: `WK-${30000 + (c.id.charCodeAt(5) % 800)}`,
        excerpt: 'Worker record · ⟨NAME⟩ · org unit and manager chain confirmed active.',
        source_ts: new Date(NOW - 30 * HOUR).toISOString(), relevance: 0.66, access_status: 'ok', redacted: true, deep_link: null },
    ],
  }
}

/* ---------- Drafts (§10.4). Uncited sentences are WITHHELD, not rendered. ---------- */
export const DRAFTS = {
  'HFG-2214': {
    band: 'Medium', confidence: 0.78, model: 'sonnet-4.6', version: 'res-2214-v1',
    version_token: 'v1', runbook: 'R-07',
    sentences: [
      { text: 'Hello Daniel — thanks for the call this morning, and apologies for the disruption ahead of Thursday\'s payroll run.', cite: null, boilerplate: true },
      { text: 'The sign-in loop you are seeing started with a conditional-access policy change that shipped on Friday and affects members of the PayrollOps-All group.', cite: [2] },
      { text: 'Your sign-in log shows six failures between 08:02 and 08:41, all with the same assignment error, from a compliant device.', cite: [3] },
      { text: 'This is the same pattern we resolved on 11 July: the cached SAML session has to be cleared before the new consent prompt can be accepted.', cite: [1] },
      { text: 'Please do the following: 1) sign out of all Halcyon apps; 2) clear the cached session at portal.halcyonfoods.example/logout; 3) sign in again and accept the consent prompt when it appears.', cite: [4] },
      { text: 'This will be permanently fixed for all Payroll Ops users by Wednesday.', withheld: true,
        withheld_reason: 'no supporting evidence — no cited source states a fix date' },
      { text: 'If the loop persists after step 3, reply here with the correlation ID from the error page and we will raise it to IAM against AUTH-341.', cite: [2, 4] },
    ],
  },
  'HFG-2402': {
    band: 'High', confidence: 0.88, model: 'sonnet-4.6', version: 'res-2402-v1', version_token: 'v1',
    sentences: [
      { text: 'Hi Lena — the interface file was rejected because cost centre IE-4402 has not been created in the payroll target system.', cite: [1] },
      { text: 'The Workday side shows the cost centre active from 01 August; the payroll mapping table was last loaded on 28 July, before it existed.', cite: [2] },
      { text: 'We have queued the mapping refresh; re-submitting the file after the next load window will clear the rejection.', cite: [1] },
    ],
  },
}

export function draftFor(caseId) {
  if (DRAFTS[caseId]) return DRAFTS[caseId]
  const c = caseById(caseId)
  if (!c) return null
  const cls = classMeta(c.class)
  return {
    band: c.band, confidence: c.confidence, model: 'sonnet-4.6',
    version: `res-${caseId}-v1`, version_token: 'v1',
    sentences: [
      { text: `Thanks for raising this — we have looked at the ${cls.label} issue you reported.`, cite: null, boilerplate: true },
      { text: 'The prior resolution for this class points at a configuration correction that resolved the same symptom on the last three occurrences.', cite: [1] },
      { text: 'The Guide article for this class sets out the checks and the standard remediation sequence; we have applied the same sequence here.', cite: [2] },
      { text: 'Your worker record and manager chain are confirmed active, so no access change is needed on the HR side.', cite: [3] },
    ],
  }
}

/* ---------- Escalations (§10.4, F-069) ---------- */
export const ESCALATIONS = {
  'HFG-2455': {
    reason: 'No confident resolution match. Retrieval returned no in-class prior resolution and classification confidence is 0.36 (Low).',
    summary: 'Batch record 7712 on line 3 cannot be closed: the electronic signature step returns "signer not in approver list" for two QA operators. QA release is blocked, and the batch is held at 14h of its 24h window.',
    suggested_owner: { name: 'Manufacturing Systems · EMEA', kind: 'team', rationale: 'Owns the batch-record application; handled the last 4 signature-authority cases.' },
    evidence: [
      { label: 'Batch 7712 held 14h', source: 'zendesk' },
      { label: 'Signature step error log', source: 'jira' },
      { label: 'Approver group unchanged since Jun', source: 'entra' },
    ],
  },
}

/* ---------- Explainers (§10.7) ---------- */
export const EXPLAINERS = {
  'HFG-2214': {
    classification: {
      class: 'auth-sso', band: 'High', confidence: 0.91,
      sentiment: 'negative', language: 'en',
      prior: { source: 'Zendesk AI', value: 'auth-sso', agreed: true },
      alternatives: [
        { class: 'auth-mfa', score: 0.06 },
        { class: 'auth-provisioning', score: 0.02 },
        { class: 'network-vpn', score: 0.01 },
      ],
    },
    duplicates: [
      { case_id: 'HFG-2231', similarity: 0.93, proposal: 'merge',
        why: 'Same requester, same class, overlapping symptom phrasing, 84 minutes apart.' },
      { case_id: 'HFG-2244', similarity: 0.71, proposal: 'link',
        why: 'Same class and requester, but the Slack thread describes a group-wide symptom rather than this user\'s session.' },
    ],
    sla: {
      policy: 'Enterprise · P2 · business hours (Asia/Kolkata)',
      elapsed_min: 210, target_min: 252, remaining_min: 42,
      paused: false, score: 0.72,
      inputs: [
        { label: 'Policy target', value: '4h 12m (Enterprise P2)' },
        { label: 'Elapsed business time', value: '3h 30m' },
        { label: 'Pause events', value: 'none' },
        { label: 'Reopen history', value: 'none' },
      ],
      explanation: 'Breach risk is elevated because the case has consumed 83% of its target inside business hours with no requester-side pause, and the class median handling time is 51 minutes.',
    },
    assignment_summary: { top: 'Priya Nair', score: 0.86, alternatives: 2, shadow: true, held: false },
  },
  'HFG-2455': {
    classification: {
      class: 'mfg-batch-record', band: 'Low', confidence: 0.36,
      sentiment: 'negative', language: 'en',
      needs_human_triage: true,
      prior: { source: 'Zendesk AI', value: 'mfg-line-sensor', agreed: false },
      alternatives: [
        { class: 'auth-provisioning', score: 0.31 },
        { class: 'mfg-line-sensor', score: 0.22 },
      ],
    },
    duplicates: [],
    sla: {
      policy: 'Internal · P1 · 24×7',
      elapsed_min: 678, target_min: 660, remaining_min: -18, paused: false, score: 0.98,
      inputs: [
        { label: 'Policy target', value: '11h (Internal P1)' },
        { label: 'Elapsed', value: '11h 18m' },
        { label: 'Pause events', value: 'none' },
        { label: 'Reopen history', value: 'none' },
      ],
      explanation: 'The target elapsed 18 minutes ago. The clock did not pause because the requester responded within every window.',
    },
    assignment_summary: { top: null, score: null, alternatives: 0, shadow: true, held: true,
      held_trigger: 'VIP auto-route' },
  },
}

export function explainerFor(caseId) {
  if (EXPLAINERS[caseId]) return EXPLAINERS[caseId]
  const c = caseById(caseId)
  if (!c) return null
  const cls = classMeta(c.class)
  return {
    classification: {
      class: c.class, band: c.band, confidence: c.confidence,
      sentiment: c.band === 'Low' ? 'negative' : 'neutral', language: 'en',
      needs_human_triage: c.band === 'Low',
      prior: { source: 'Zendesk AI', value: c.class, agreed: c.band !== 'Low' },
      alternatives: [{ class: cls.cat === 'Identity & Access' ? 'auth-mfa' : 'report-latency', score: 0.05 }],
    },
    duplicates: [],
    sla: c.sla_deadline ? {
      policy: `${c.tier} · P3 · business hours (Asia/Kolkata)`,
      elapsed_min: Math.round((NOW - new Date(c.created_at).getTime()) / MIN),
      target_min: 480,
      remaining_min: Math.round((new Date(c.sla_deadline).getTime() - NOW) / MIN),
      paused: !!c.sla_paused, score: 0.4,
      inputs: [
        { label: 'Policy target', value: '8h' },
        { label: 'Elapsed business time', value: `${Math.round((NOW - new Date(c.created_at).getTime()) / HOUR)}h` },
        { label: 'Pause events', value: c.sla_paused ? '1 (awaiting requester)' : 'none' },
        { label: 'Reopen history', value: c.reopened ? '1 reopen' : 'none' },
      ],
      explanation: 'Breach risk tracks the deterministic policy clock; this case is inside its target with no pause events recorded.',
    } : null,
    assignment_summary: { top: null, score: null, alternatives: 0, shadow: true, held: false },
  }
}

/* ---------- Assignment shortlists (§10.8) ----------
   Ordering is per-ticket fit only. No leaderboard, no cross-ticket rank,
   employment type absent by rule [F-127, §1.4]. */
const COMPONENTS = [
  { key: 'class_experience', label: 'Class experience', weight: 0.30 },
  { key: 'outcome_quality',  label: 'Outcome quality',  weight: 0.25 },
  { key: 'skill_match',      label: 'Skill match',      weight: 0.20 },
  { key: 'efficiency',       label: 'Efficiency',       weight: 0.10 },
  { key: 'load',             label: 'Load & availability', weight: 0.10 },
  { key: 'level',            label: 'Level appropriateness', weight: 0.05 },
]
export { COMPONENTS as SCORE_COMPONENTS }

export const SHORTLISTS = {
  'HFG-2214': {
    shadow: true, held: false,
    needed_skills: ['sso', 'entra-conditional-access', 'payroll-domain'],
    candidates: [
      {
        analyst_id: 'an-001', name: 'Priya Nair', level: 'L2', score: 0.86,
        components: { class_experience: 0.94, outcome_quality: 0.91, skill_match: 0.88, efficiency: 0.74, load: 0.62, level: 0.90 },
        evidence_line: '41 handled · 94% CSAT · 0.9h avg',
        history: { tickets_handled: 41, avg_handle_time_min: 54, reopen_rate: 0.05, escalation_rate: 0.07, csat_avg: 4.7, qa_score_avg: 0.92 },
        availability: { open_tickets: 6, within_working_hours: true },
        skills: [
          { name: 'sso', level: 5, provenance: 'certified' },
          { name: 'entra-conditional-access', level: 4, provenance: 'manager' },
          { name: 'payroll-domain', level: 3, provenance: 'self' },
        ],
        signals: [
          { type: 'class_strength', metric: 'auth-sso resolution rate 0.93', team_median: 0.81, sample_size: 41, confidence: 0.88 },
          { type: 'low_reopen', metric: 'reopen rate 0.05', team_median: 0.11, sample_size: 41, confidence: 0.84 },
        ],
      },
      {
        analyst_id: 'an-002', name: 'Rahul Bose', level: 'L2', score: 0.79,
        components: { class_experience: 0.81, outcome_quality: 0.84, skill_match: 0.79, efficiency: 0.81, load: 0.44, level: 0.90 },
        evidence_line: '27 handled · 89% CSAT · 1.1h avg',
        history: { tickets_handled: 27, avg_handle_time_min: 66, reopen_rate: 0.08, escalation_rate: 0.11, csat_avg: 4.5, qa_score_avg: 0.88 },
        availability: { open_tickets: 9, within_working_hours: true },
        skills: [
          { name: 'sso', level: 4, provenance: 'manager' },
          { name: 'entra-conditional-access', level: 3, provenance: 'self' },
        ],
        signals: [
          { type: 'class_strength', metric: 'auth-sso resolution rate 0.86', team_median: 0.81, sample_size: 27, confidence: 0.79 },
        ],
      },
      {
        analyst_id: 'an-003', name: 'Mei Chen', level: 'L1', score: 0.74, stretch: true,
        stretch_rationale: '5 handled — below the strength threshold for this class, but the two most recent were resolved without escalation. Growth opportunity in class.',
        components: { class_experience: 0.41, outcome_quality: 0.86, skill_match: 0.71, efficiency: 0.88, load: 0.91, level: 0.55 },
        evidence_line: '5 handled · 92% CSAT · 0.8h avg',
        history: { tickets_handled: 5, avg_handle_time_min: 48, reopen_rate: 0.0, escalation_rate: 0.20, csat_avg: 4.6, qa_score_avg: 0.90 },
        availability: { open_tickets: 4, within_working_hours: true },
        skills: [{ name: 'sso', level: 3, provenance: 'self' }],
        // Below the sample floor, so no class_strength signal is emitted at all [NFR-41].
        signals: [],
        signals_suppressed: 'Class-strength signal not emitted: sample size 5 is below the reporting floor.',
      },
    ],
  },
  'HFG-2455': {
    shadow: true, held: true, held_trigger: 'VIP auto-route',
    needed_skills: ['batch-records', 'e-signature'],
    candidates: [],
    no_eligible_reason: 'No analyst scores above the eligibility floor for class `mfg-batch-record` with the e-signature skill. An escalation to Manufacturing Systems · EMEA is suggested instead of a forced pick.',
  },
}

export function shortlistFor(caseId) {
  if (SHORTLISTS[caseId]) return SHORTLISTS[caseId]
  const c = caseById(caseId)
  if (!c) return null
  const pool = ANALYSTS.slice(4, 7)
  return {
    shadow: true, held: false,
    needed_skills: [classMeta(c.class).id],
    candidates: pool.map((a, i) => ({
      analyst_id: a.id, name: a.name, level: a.level, score: [0.83, 0.77, 0.71][i],
      components: { class_experience: 0.8 - i * 0.1, outcome_quality: 0.85 - i * 0.06, skill_match: 0.78 - i * 0.05, efficiency: 0.7, load: 0.6, level: 0.8 },
      evidence_line: `${22 - i * 6} handled · ${91 - i * 2}% CSAT · 1.0h avg`,
      history: { tickets_handled: 22 - i * 6, avg_handle_time_min: 60 + i * 6, reopen_rate: 0.07, escalation_rate: 0.1, csat_avg: 4.5, qa_score_avg: 0.87 },
      availability: { open_tickets: a.open_tickets, within_working_hours: a.within_working_hours },
      skills: [{ name: classMeta(c.class).id, level: 4 - i, provenance: i === 0 ? 'certified' : 'manager' }],
      signals: [{ type: 'class_strength', metric: `${c.class} resolution rate ${(0.9 - i * 0.05).toFixed(2)}`, team_median: 0.81, sample_size: 22 - i * 6, confidence: 0.8 }],
    })),
  }
}

/* ---------- Call artefact (§10.12) ----------
   Fabricated timing JSON over a generated tone — labelled as such in LANE_NOTES.
   No audio is ever sent to a model; no control exists that would [F-137]. */
export const CALLS = {
  'call-2214': {
    id: 'call-2214', case_id: 'HFG-2214',
    duration_sec: 372,
    asr_model: 'whisper-large-v3 (emulated engine)',
    asr_confidence_avg: 0.91,
    wer_note: 'Word error rate is measured and reported separately, never folded into headline numbers [NFR-37/38].',
    signed_url_expires_in_sec: 45,
    speakers: [
      { id: 'ivr', label: 'IVR' },
      { id: 'agent', label: 'Agent (L1)' },
      { id: 'customer', label: 'Daniel Okafor' },
    ],
    turns: [
      { t: 0,   speaker: 'ivr',      words: [['Thank', .99], ['you', .99], ['for', .99], ['calling', .98], ['Halcyon', .93], ['IT', .97], ['support.', .96]] },
      { t: 9,   speaker: 'agent',    words: [['Good', .98], ['morning,', .97], ['how', .99], ['can', .99], ['I', .99], ['help?', .98]] },
      { t: 14,  speaker: 'customer', words: [['Hi,', .97], ['I', .98], ['cannot', .96], ['get', .97], ['into', .96], ['any', .97], ['of', .98], ['the', .99], ['systems', .95], ['since', .94], ['the', .98], ['password', .93], ['rotation', .91], ['on', .97], ['Friday.', .95]] },
      { t: 31,  speaker: 'agent',    words: [['Can', .98], ['I', .99], ['take', .98], ['your', .98], ['ticket', .95], ['reference?', .94]] },
      { t: 37,  speaker: 'customer', words: [['It', .97], ['is', .98], ['H', .88], ['F', .86], ['G', .87], ['two', .74], ['two', .61], ['one', .54], ['four.', .58]] },
      { t: 48,  speaker: 'agent',    words: [['Thank', .98], ['you.', .98], ['And', .97], ['what', .98], ['exactly', .96], ['happens', .96], ['when', .98], ['you', .98], ['sign', .96], ['in?', .97]] },
      { t: 59,  speaker: 'customer', words: [['It', .97], ['takes', .96], ['my', .98], ['password', .95], ['and', .98], ['then', .97], ['loops', .89], ['straight', .92], ['back', .96], ['to', .98], ['the', .98], ['login', .95], ['page.', .96]] },
      { t: 76,  speaker: 'customer', words: [['I', .98], ['tried', .96], ['the', .98], ['self', .93], ['service', .94], ['reset', .95], ['twice.', .93]] },
      { t: 88,  speaker: 'agent',    words: [['Understood.', .95], ['Payroll', .93], ['run', .96], ['is', .98], ['Thursday,', .92], ['is', .98], ['that', .98], ['right?', .97]] },
      { t: 99,  speaker: 'customer', words: [['Yes,', .98], ['so', .98], ['this', .98], ['is', .98], ['blocking', .94], ['for', .98], ['me.', .98]] },
    ],
    low_confidence_hints: {
      'HFG-2214-ref': { at: 37, note: '0.54 — "HFG-2214" may be "HFG-2240"' },
    },
  },
}
export const callFor = (id) => CALLS[id] || null

/* ---------- Read-context links (F-119 — no write controls exist) ---------- */
export const LINKED_ISSUES = {
  'HFG-2214': [
    { system: 'jira', key: 'AUTH-341', title: 'Conditional access re-consent loops for dynamic group members',
      status: 'In progress', assignee: 'Platform Identity', updated: new Date(NOW - 5 * HOUR).toISOString() },
  ],
}

/* Cases carrying hand-authored cross-system evidence — a full timeline, a
   context pack, and in HFG-2214's case a linked engineering defect. The digest
   prefers these as cluster exemplars so a manager drilling from a pattern lands
   somewhere that can actually answer "why is this happening" (J-CT-2). */
export const EVIDENCE_RICH_CASES = ['HFG-2214', 'HFG-2308', 'HFG-2402', 'HFG-2455']

export const teamName = (id) => TEAMS.find((t) => t.id === id)?.name || '—'
export const analystName = (id) => ANALYSTS.find((a) => a.id === id)?.name || null
