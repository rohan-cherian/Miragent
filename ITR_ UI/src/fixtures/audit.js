/* decision_audit fixtures — the product's memory (P-6). Append-only, immutable in
   the UI: no hover-edit affordance exists anywhere in the audit variant (§8.10).
   The chain is always recommendation → evidence → confidence → model/version →
   human decision → write → outcome, with retries visible as their own entries. */

import { NOW, CASES, caseById } from './corpus.js'
import { CaseStatus } from '../contracts/state.js'

const MIN = 60000, HOUR = 3600000, DAY = 24 * HOUR

/* Bulk history IDs start below the hand-authored block (A-99174…A-99231) and
   count DOWN, so the two sets can never collide. */
let seq = 99000
const auditId = () => `A-${--seq}`

/* Hand-authored chains for the narrative cases. */
export const AUDIT_ROWS = [
  {
    id: 'A-99231', case_id: 'HFG-2402', agent: 'Resolution → Action Executor',
    decision_type: 'edited_approved', actor: 'A. Bello', actor_role: 'analyst',
    outcome: 'write_failed', flagged: false,
    confidence: 0.88, model: 'sonnet-4.6', model_version: '2026-06-11',
    latency_ms: 1840, cost_usd: 0.0142,
    occurred_at: new Date(NOW - 95 * MIN).toISOString(),
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 2.2 * HOUR).toISOString(), text: 'Resolution drafted for HFG-2402 · class payroll-integrations.', meta: 'model sonnet-4.6 · version 2026-06-11 · 1,840ms · $0.0142' },
      { type: 'evidence', ts: new Date(NOW - 2.2 * HOUR).toISOString(), text: '3 citations across Workday, Zendesk and an internal runbook. Context pack spans 3 systems.', links: ['RR-7712', 'KB-3009', 'WK-30188'] },
      { type: 'confidence', ts: new Date(NOW - 2.2 * HOUR).toISOString(), text: 'Groundedness confidence 0.88 — band High (recorded as known at the time).' },
      { type: 'decision', ts: new Date(NOW - 95 * MIN).toISOString(), text: 'Edited-approved by A. Bello. Edit distance 24 characters across 1 sentence.', diff: true },
      { type: 'write', ts: new Date(NOW - 94 * MIN).toISOString(), text: 'Write queued to Zendesk (public comment + solve).' },
      { type: 'retry', ts: new Date(NOW - 93 * MIN).toISOString(), text: 'Attempt 1 — HTTP 429 rate-limited. Backoff 2s. No data loss.' },
      { type: 'retry', ts: new Date(NOW - 92 * MIN).toISOString(), text: 'Attempt 2 — HTTP 429 rate-limited. Backoff 8s. No data loss.' },
      { type: 'retry', ts: new Date(NOW - 91 * MIN).toISOString(), text: 'Attempt 3 — HTTP 502 from the Zendesk emulator. Retries exhausted.' },
      { type: 'outcome', ts: new Date(NOW - 91 * MIN).toISOString(), text: 'WriteExecution FAILED. Approval record preserved; the item carries "write failed — action required" and offers re-fire of execution only — no re-approval.' },
    ],
    diff: {
      original: 'We have queued the mapping refresh; re-submitting the file after the next load window will clear the rejection.',
      edited: 'We have queued the mapping refresh for tonight; re-submitting the file after 02:00 IST will clear the rejection.',
    },
  },
  {
    id: 'A-99228', case_id: 'HFG-2088', agent: 'Resolution → Action Executor',
    decision_type: 'approved', actor: 'P. Nair', actor_role: 'analyst',
    outcome: 'succeeded', flagged: false,
    confidence: 0.91, model: 'sonnet-4.6', model_version: '2026-06-11',
    latency_ms: 1490, cost_usd: 0.0118,
    occurred_at: new Date(NOW - 30 * DAY).toISOString(),
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 30 * DAY - 4 * MIN).toISOString(), text: 'Resolution drafted for HFG-2088 · class auth-sso.', meta: 'model sonnet-4.6 · 1,490ms · $0.0118' },
      { type: 'evidence', ts: new Date(NOW - 30 * DAY - 4 * MIN).toISOString(), text: '4 citations across Entra, Jira, Zendesk Guide and a prior resolution.', links: ['AUTH-298', 'KB-3312', 'RR-8402'] },
      { type: 'confidence', ts: new Date(NOW - 30 * DAY - 4 * MIN).toISOString(), text: 'Groundedness confidence 0.91 — band High.' },
      { type: 'decision', ts: new Date(NOW - 30 * DAY).toISOString(), text: 'Approved without edit by P. Nair.' },
      { type: 'write', ts: new Date(NOW - 30 * DAY + 20000).toISOString(), text: 'Zendesk public comment #1182 created; ticket set to solved.' },
      { type: 'outcome', ts: new Date(NOW - 29 * DAY).toISOString(), text: 'Requester confirmed resolution. CSAT 4. ResolutionRecord RR-8871 created and added to the retrieval corpus.', resolution_record: 'RR-8871' },
    ],
  },
  {
    id: 'A-99219', case_id: 'HFG-2377', agent: 'Resolution', decision_type: 'rejected',
    actor: 'P. Nair', actor_role: 'analyst', outcome: 'no_write', flagged: false,
    confidence: 0.66, model: 'sonnet-4.6', model_version: '2026-06-11',
    latency_ms: 1720, cost_usd: 0.0131,
    occurred_at: new Date(NOW - 2 * DAY).toISOString(),
    reject_reason: 'Transcript misread the account ID — the draft answers for HFG-2240, not this case.',
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 2 * DAY - 6 * MIN).toISOString(), text: 'Resolution drafted for HFG-2377 · class order-edi.' },
      { type: 'evidence', ts: new Date(NOW - 2 * DAY - 6 * MIN).toISOString(), text: '2 citations. Context pack spans 2 systems — below the 3-system target, flagged in the pack header.' },
      { type: 'confidence', ts: new Date(NOW - 2 * DAY - 6 * MIN).toISOString(), text: 'Groundedness confidence 0.66 — band Medium.' },
      { type: 'decision', ts: new Date(NOW - 2 * DAY).toISOString(), text: 'Rejected by P. Nair. Reason: "Transcript misread the account ID — the draft answers for HFG-2240, not this case."' },
      { type: 'outcome', ts: new Date(NOW - 2 * DAY).toISOString(), text: 'No external write occurred. Case returned to the queue with the reject reason attached; Resolution may redraft once with the reason as added instruction.' },
    ],
  },
  {
    id: 'A-99205', case_id: 'HFG-2301', agent: 'QA/Verifier', decision_type: 'approved',
    actor: 'R. Bose', actor_role: 'analyst', outcome: 'succeeded', flagged: true,
    flag_detail: { groundedness: 0.61, note: 'Sampled run: one approved sentence traced to a citation whose excerpt only partially supports it. Calibration input, not a reversal.' },
    confidence: 0.87, model: 'sonnet-4.6', model_version: '2026-06-11',
    latency_ms: 1610, cost_usd: 0.0126,
    occurred_at: new Date(NOW - 4 * DAY).toISOString(),
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 4 * DAY - 5 * MIN).toISOString(), text: 'Resolution drafted for HFG-2301 · class billing-invoice.' },
      { type: 'evidence', ts: new Date(NOW - 4 * DAY - 5 * MIN).toISOString(), text: '3 citations across Salesforce, Zendesk and a prior resolution.' },
      { type: 'confidence', ts: new Date(NOW - 4 * DAY - 5 * MIN).toISOString(), text: 'Groundedness confidence 0.87 — band High.' },
      { type: 'decision', ts: new Date(NOW - 4 * DAY).toISOString(), text: 'Approved without edit by R. Bose.' },
      { type: 'write', ts: new Date(NOW - 4 * DAY + 18000).toISOString(), text: 'Zendesk public comment #1149 created.' },
      { type: 'flag', ts: new Date(NOW - 3 * DAY).toISOString(), text: 'QA/Verifier sampled this run. Groundedness 0.61 — below the 0.75 review threshold. Flagged for calibration review.' },
      { type: 'outcome', ts: new Date(NOW - 3 * DAY).toISOString(), text: 'Case solved. CSAT 4. Flag retained on the record — the audit shows what was known then, not a recomputation.' },
    ],
  },
  {
    id: 'A-99198', case_id: 'HFG-2214', agent: 'Dedup & Linker', decision_type: 'merge_declined',
    actor: 'P. Nair', actor_role: 'analyst', outcome: 'no_write', flagged: false,
    confidence: 0.71, model: 'deterministic', model_version: 'sim-v3',
    latency_ms: 210, cost_usd: 0,
    occurred_at: new Date(NOW - 70 * MIN).toISOString(),
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 84 * MIN).toISOString(), text: 'Link proposed between HFG-2214 and HFG-2244 at similarity 0.71 (mid-score — link only, no merge proposal).' },
      { type: 'decision', ts: new Date(NOW - 70 * MIN).toISOString(), text: 'Kept as a link by P. Nair. No merge performed.' },
      { type: 'outcome', ts: new Date(NOW - 70 * MIN).toISOString(), text: 'Cases linked. No external write; a merge would have entered the same HITL write gate.' },
    ],
  },
  {
    id: 'A-99187', case_id: '—', agent: 'Identity resolution', decision_type: 'identity_resolved',
    actor: 'S. Rao', actor_role: 'admin', outcome: 'succeeded', flagged: false,
    confidence: null, model: 'deterministic', model_version: 'sim-v3',
    latency_ms: 90, cost_usd: 0,
    occurred_at: new Date(NOW - 3 * DAY).toISOString(),
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 3 * DAY - 2 * MIN).toISOString(), text: 'Two Salesforce contacts scored 0.61 / 0.57 for l.hartmann@halcyonfoods.example — below threshold, queued rather than guessed.' },
      { type: 'decision', ts: new Date(NOW - 3 * DAY).toISOString(), text: 'Resolved as candidate A by S. Rao (Admin).' },
      { type: 'outcome', ts: new Date(NOW - 3 * DAY).toISOString(), text: 'Actor link written to the canonical model; 3 prior cases retro-linked. No external system was mutated.' },
    ],
  },
  {
    id: 'A-99174', case_id: 'HFG-2266', agent: 'KB Curator', decision_type: 'approved',
    actor: 'P. Nair', actor_role: 'analyst', outcome: 'succeeded', flagged: false,
    confidence: 0.83, model: 'sonnet-4.6', model_version: '2026-06-11',
    latency_ms: 2210, cost_usd: 0.0188,
    occurred_at: new Date(NOW - 5 * DAY).toISOString(),
    entries: [
      { type: 'recommendation', ts: new Date(NOW - 5 * DAY - 10 * MIN).toISOString(), text: 'KB draft generated from ResolutionRecord RR-8871.' },
      { type: 'evidence', ts: new Date(NOW - 5 * DAY - 10 * MIN).toISOString(), text: 'Source: RR-8871 + originating case HFG-2088. Dedupe check against 900 articles — nearest 0.62, below the warning threshold.' },
      { type: 'decision', ts: new Date(NOW - 5 * DAY).toISOString(), text: 'Approved as draft by P. Nair.' },
      { type: 'write', ts: new Date(NOW - 5 * DAY + 15000).toISOString(), text: 'Create Zendesk Guide draft (draft=true) — article 4471. Publication remains a separate gated act outside this console.' },
      { type: 'outcome', ts: new Date(NOW - 5 * DAY + 15000).toISOString(), text: 'Draft created. No content is publicly live.' },
    ],
  },
]

/* Bulk history so the manager's "last week · rejected" filter returns real volume. */
export const AUDIT_HISTORY = (() => {
  const rows = []
  const decided = CASES.filter((c) => c.status === CaseStatus.SOLVED || c.status === CaseStatus.CLOSED).slice(0, 260)
  decided.forEach((c, i) => {
    const type = i % 11 === 0 ? 'rejected' : i % 4 === 0 ? 'edited_approved' : 'approved'
    const actor = ['P. Nair', 'R. Bose', 'M. Chen', 'A. Bello'][i % 4]
    const ts = NOW - (i % 21) * DAY - (i % 17) * HOUR
    rows.push({
      id: auditId(),
      case_id: c.id,
      agent: 'Resolution → Action Executor',
      decision_type: type,
      actor, actor_role: 'analyst',
      outcome: type === 'rejected' ? 'no_write' : 'succeeded',
      flagged: c.qa_flagged,
      confidence: c.confidence,
      model: 'sonnet-4.6', model_version: '2026-06-11',
      latency_ms: 1200 + (i % 9) * 130,
      cost_usd: Number((0.009 + (i % 7) * 0.001).toFixed(4)),
      occurred_at: new Date(ts).toISOString(),
      reject_reason: type === 'rejected'
        ? ['Draft cites a resolution for a different account.',
           'Steps are right but the tone is wrong for an Enterprise contact.',
           'Transcript misread the account ID.',
           'Evidence is thin — only one system in the pack.'][i % 4]
        : undefined,
      entries: null, // expanded lazily by the mock API
    })
  })
  return rows
})()

/* Routing-gate and curator records. These exist so the adoption metrics in the
   digest are DERIVED from decision rows rather than stated as constants — every
   one of those percentages has to open onto the records behind it. */
export const ASSIGNMENT_HISTORY = (() => {
  const rows = []
  const pool = CASES.filter((c) => c.assignee).slice(0, 58)
  pool.forEach((c, i) => {
    // 47 of 58 accepted — the acceptance rate falls out of the rows, not a constant.
    const accepted = i % 5 !== 0 || i % 20 === 0
    rows.push({
      id: auditId(),
      case_id: c.id,
      agent: 'Assignment',
      decision_type: accepted ? 'feedback_accepted' : 'feedback_overridden',
      actor: ['P. Nair', 'M. Adeyemi', 'A. Bello'][i % 3], actor_role: i % 3 === 1 ? 'manager' : 'analyst',
      outcome: 'no_write',
      flagged: false,
      confidence: null,
      model: 'deterministic', model_version: 'cap-v2',
      latency_ms: 120 + (i % 6) * 20, cost_usd: 0,
      occurred_at: new Date(NOW - (i % 13) * DAY - (i % 11) * HOUR).toISOString(),
      shadow: true,
      entries: null,
    })
  })
  return rows
})()

export const KB_HISTORY = (() => {
  const rows = []
  for (let i = 0; i < 18; i++) {
    const approved = i % 3 !== 0          // 12 of 18 → 67%, above the 50% target
    rows.push({
      id: auditId(),
      case_id: CASES[100 + i * 7]?.id || '—',
      agent: 'KB Curator',
      decision_type: approved ? 'approved' : 'rejected',
      actor: ['P. Nair', 'R. Bose'][i % 2], actor_role: 'analyst',
      outcome: approved ? 'succeeded' : 'no_write',
      flagged: false,
      confidence: Number((0.72 + (i % 9) * 0.02).toFixed(2)),
      model: 'sonnet-4.6', model_version: '2026-06-11',
      latency_ms: 2000 + (i % 5) * 180, cost_usd: Number((0.017 + (i % 4) * 0.001).toFixed(4)),
      occurred_at: new Date(NOW - (i % 19) * DAY - (i % 7) * HOUR).toISOString(),
      reject_reason: approved ? undefined
        : ['Near-duplicate of an existing article — an update is the right shape.',
           'Resolution was a one-off configuration fix; it does not generalise.',
           'Steps are correct but the article assumes access the requester will not have.'][i % 3],
      entries: null,
    })
  }
  return rows
})()

export const ALL_AUDIT = [...AUDIT_ROWS, ...AUDIT_HISTORY, ...ASSIGNMENT_HISTORY, ...KB_HISTORY]
  .sort((a, b) => new Date(b.occurred_at) - new Date(a.occurred_at))

/** Synthesised chain for bulk rows, so every row expands to a complete trail. */
export function entriesFor(row) {
  if (row.entries) return row.entries
  const c = caseById(row.case_id)
  const t = new Date(row.occurred_at).getTime()

  if (row.agent === 'Assignment') {
    const accepted = row.decision_type === 'feedback_accepted'
    return [
      { type: 'recommendation', ts: new Date(t - 3 * MIN).toISOString(),
        text: `Capability engine proposed a shortlist for ${row.case_id}. Deterministic weighted fit — reproducible from case data.`,
        meta: `${row.model} · ${row.model_version} · ${row.latency_ms}ms` },
      { type: 'evidence', ts: new Date(t - 3 * MIN).toISOString(),
        text: 'Component scores backed by measured class experience, outcome quality and current load. Employment type is not an input.' },
      { type: 'decision', ts: row.occurred_at,
        text: `${accepted ? 'Proposal accepted' : 'Proposal overridden'} at the routing gate by ${row.actor}.` },
      { type: 'outcome', ts: row.occurred_at,
        text: 'Shadow mode: evaluation feedback and this audit row were recorded. No external assignment write occurred — the ticket\'s assignee is unchanged.' },
    ]
  }

  if (row.agent === 'KB Curator') {
    const approved = row.decision_type === 'approved'
    return [
      { type: 'recommendation', ts: new Date(t - 8 * MIN).toISOString(),
        text: `KB draft generated from the ResolutionRecord for ${row.case_id}.`,
        meta: `${row.model} · ${row.model_version} · ${row.latency_ms}ms · $${row.cost_usd}` },
      { type: 'evidence', ts: new Date(t - 8 * MIN).toISOString(),
        text: 'Dedupe check run against the 900-article corpus before the draft was offered for review.' },
      { type: 'decision', ts: row.occurred_at,
        text: approved
          ? `Approved as draft by ${row.actor}.`
          : `Rejected by ${row.actor}. Reason: "${row.reject_reason}"` },
      { type: 'outcome', ts: row.occurred_at,
        text: approved
          ? 'Create/update Zendesk Guide draft (draft=true). No content is publicly live.'
          : 'No article was created. The reason feeds the Curator\'s next attempt.' },
    ]
  }

  const base = [
    { type: 'recommendation', ts: new Date(t - 6 * MIN).toISOString(),
      text: `Resolution drafted for ${row.case_id}${c ? ` · class ${c.class}` : ''}.`,
      meta: `model ${row.model} · version ${row.model_version} · ${row.latency_ms}ms · $${row.cost_usd}` },
    { type: 'evidence', ts: new Date(t - 6 * MIN).toISOString(),
      text: '3 citations retained with per-source attribution. Context pack spans 3 systems.' },
    { type: 'confidence', ts: new Date(t - 6 * MIN).toISOString(),
      text: `Groundedness confidence ${row.confidence?.toFixed(2)} — recorded as known at the time.` },
  ]
  if (row.decision_type === 'rejected') {
    return [...base,
      { type: 'decision', ts: row.occurred_at, text: `Rejected by ${row.actor}. Reason: "${row.reject_reason}"` },
      { type: 'outcome', ts: row.occurred_at, text: 'No external write occurred. Case returned to the queue with the reason attached.' }]
  }
  return [...base,
    { type: 'decision', ts: row.occurred_at,
      text: `${row.decision_type === 'edited_approved' ? 'Edited-approved' : 'Approved'} by ${row.actor}.`,
      diff: row.decision_type === 'edited_approved' },
    { type: 'write', ts: new Date(t + 20000).toISOString(), text: 'Zendesk public comment created; ticket set to solved.' },
    { type: 'outcome', ts: new Date(t + 8 * HOUR).toISOString(),
      text: `Case solved${c?.csat ? `. CSAT ${c.csat}` : ''}. ResolutionRecord created and added to the retrieval corpus.` },
  ]
}

/** F-101 completeness check shown in the S-09 header. */
export const AUDIT_COMPLETENESS = {
  pct: 1.0,
  checked_at: new Date(new Date(NOW).setHours(9, 0, 0, 0)).toISOString(),
  demo_path_actions: 268,
  with_complete_chain: 268,
}
