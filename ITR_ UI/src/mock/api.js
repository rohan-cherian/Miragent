/* Mock API plane — every §14A logical operation, backed by fixtures with scripted
   latency and failure hooks. There is no backend; the honesty behaviours
   (approved ≠ written, 429-resume, honest-delay notices, 409 conflicts) are
   SIMULATED here with real timing so they are demonstrable, not decorative.

   Scripted hooks (URL query, any screen):
     ?fail=429    next mutation rate-limits then recovers
     ?fail=write  next write exhausts its retries and lands in `failed`
     ?conflict=1  next decision returns 409 "already decided by X"
     ?slow=3000   reads take 3s so the honest-delay notice (§11.5) fires
     ?empty=1     list reads return empty so empty states are reviewable
     ?error=1     reads fail so error states are reviewable
     ?replay=1    demo replay cache (Demo role only) — served from recorded state */

import {
  CASES, caseById, ANALYSTS, actorMeta, classMeta, NOW, TEAMS,
} from '../fixtures/corpus.js'
import * as agg from '../fixtures/aggregates.js'
import {
  timelineFor, packFor, draftFor, explainerFor, shortlistFor, identityFor,
  callFor, LINKED_ISSUES, ESCALATIONS, IDENTITY_QUEUE,
} from '../fixtures/details.js'
import { ALL_AUDIT, entriesFor, AUDIT_COMPLETENESS } from '../fixtures/audit.js'
import { weeklyDigest } from '../fixtures/digest.js'
import {
  CONNECTIONS, overallCompleteness, inFlightObjects, lastFullRun, KB_DRAFTS, KB_DECIDED, KB_GAPS,
  NOTIFICATIONS, DEMO_CATALOGUE, DISCOVERY, INGESTION_PLAN,
} from '../fixtures/ops.js'
import {
  DecisionState, WriteState, ItemType, Band, AssignmentState,
} from '../contracts/state.js'
import { config } from '../contracts/config.js'

/* ---------------- scripted-behaviour plumbing ---------------- */

const q = () => new URLSearchParams(window.location.search)
const hook = (k) => q().get(k)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function read(fn, { base = 240 } = {}) {
  if (hook('error')) { await sleep(300); throw new ApiError('service', 'Console API unreachable', 'listCases') }
  const slow = Number(hook('slow') || 0)
  await sleep(slow || base + Math.random() * 160)
  return fn()
}

export class ApiError extends Error {
  constructor(kind, message, dependency, extra = {}) {
    super(message)
    this.kind = kind            // permission | notfound | conflict | validation | throttle | timeout | partial | service
    this.dependency = dependency
    this.trace_id = `tr-${Math.random().toString(36).slice(2, 8)}`
    Object.assign(this, extra)
  }
}

/* ---------------- decision + write state store ----------------
   Decision and WriteExecution are SEPARATE records, exactly as §5.3.2a/b
   requires. Nothing in this store can produce a write without a decision. */

const decisions = new Map()   // caseId -> { state, actor, at, version, edited_text, reason }
const writes = new Map()      // caseId -> { state, attempts, audit_id, error }
const assignmentFeedback = new Map()
const listeners = new Set()

export const subscribe = (fn) => { listeners.add(fn); return () => listeners.delete(fn) }
const notify = () => listeners.forEach((f) => f())

export const decisionFor = (caseId) => decisions.get(caseId) || null
export const writeFor = (caseId) => writes.get(caseId) || { state: WriteState.NOT_STARTED, attempts: 0 }

/* Pre-seed the write-failed narrative case (HFG-2402) so the state is reviewable
   from a cold start — the approval exists, the write does not. */
decisions.set('HFG-2402', {
  state: DecisionState.EDITED_APPROVED, actor: 'A. Bello',
  at: new Date(NOW - 95 * 60000).toISOString(), version: 'v1',
})
writes.set('HFG-2402', {
  state: WriteState.FAILED, attempts: 3, audit_id: 'A-99231',
  error: 'HTTP 502 from the Zendesk emulator after 2 rate-limit retries.',
})

let auditSeq = 99300

/* ---------------- §14A: reads ---------------- */

export const getConfig = () => ({ ...config })

export async function listConnections() {
  return read(() => ({
    systems: CONNECTIONS,
    completeness: overallCompleteness(),
    in_flight: inFlightObjects(),
    last_full_run: lastFullRun(),
  }))
}

export async function listIdentityQueue() {
  return read(() => (hook('empty') ? [] : IDENTITY_QUEUE))
}

export async function resolveIdentity(id, action, payload = {}) {
  await sleep(420)
  if (action === 'dismiss' && !payload.reason?.trim()) {
    throw new ApiError('validation', 'A dismissal reason is required.', 'resolveIdentity')
  }
  const audit_id = `A-${++auditSeq}`
  notify()
  return { ok: true, audit_id, retro_linked: 3 }
}

export async function getDashboardAggregates(period = '12m') {
  return read(() => {
    if (hook('empty')) {
      return { empty: true, kpis: [], byCategory: [], byChannel: [], byTier: [], byMonth: [], byLevel: [], coverage: [] }
    }
    return {
      empty: false,
      period,
      periods: agg.PERIODS,
      kpis: agg.kpis(period),
      byCategory: agg.byCategory(period),
      byChannel: agg.byChannel(period),
      byTier: agg.byTier(period),
      // The trend line is always trailing-12-months: it is the baseline the
      // period is read against, so narrowing it would remove the comparison.
      byMonth: agg.byMonth(),
      byLevel: agg.byLevel(),
      coverage: agg.coverageDonut(),
      generated_at: new Date().toISOString(),
    }
  }, { base: 380 })
}

/* ---------------- S-13 list / search ---------------- */

const RISK_BUCKETS = {
  'at-risk': (c) => c.sla_deadline && new Date(c.sla_deadline) - NOW > 0 && new Date(c.sla_deadline) - NOW < 2 * 3600000,
  breached: (c) => c.sla_deadline && new Date(c.sla_deadline) - NOW <= 0,
  ok: (c) => c.sla_deadline && new Date(c.sla_deadline) - NOW >= 2 * 3600000,
}

export function filterCases(f = {}) {
  let rows = CASES
  if (f.status === 'open') rows = rows.filter(agg.isOpen)
  else if (f.status === 'solved') rows = rows.filter((c) => c.status === 'solved' || c.status === 'closed')
  else if (f.status) rows = rows.filter((c) => c.status === f.status)
  if (f.class) rows = rows.filter((c) => c.class === f.class)
  if (f.category) rows = rows.filter((c) => c.category === f.category)
  if (f.channel) rows = rows.filter((c) => c.channel === f.channel)
  if (f.tier) rows = rows.filter((c) => c.tier === f.tier)
  if (f.team) rows = rows.filter((c) => c.team === f.team)
  if (f.assignee) rows = rows.filter((c) => c.assignee === f.assignee)
  if (f.assigned === '1') rows = rows.filter((c) => !!c.assignee)
  // Cohort filter for the roster drill — a cohort's CASEWORK, never a list of
  // people ordered by anything (§1.4 forbids the ranking artefact).
  if (f.assigneeLevel) {
    const ids = new Set(ANALYSTS.filter((a) => a.level === f.assigneeLevel).map((a) => a.id))
    rows = rows.filter((c) => c.assignee && ids.has(c.assignee))
  }
  if (f.band) rows = rows.filter((c) => c.band === f.band)
  if (f.risk && RISK_BUCKETS[f.risk]) rows = rows.filter(RISK_BUCKETS[f.risk])
  if (f.ids) { const set = new Set(f.ids.split(',')); rows = rows.filter((c) => set.has(c.id)) }
  if (f.from) rows = rows.filter((c) => new Date(c.created_at) >= new Date(f.from))
  if (f.to) rows = rows.filter((c) => new Date(c.created_at) <= new Date(f.to))
  // Resolution-date window, so the "Solved" drill reproduces the flow figure
  // rather than a cohort of cases that merely started in the period.
  if (f.resolvedFrom) {
    rows = rows.filter((c) => c.resolved_at && new Date(c.resolved_at) >= new Date(f.resolvedFrom))
  }
  if (f.qa === '1') rows = rows.filter((c) => c.qa_flagged)
  if (f.query) {
    const s = f.query.toLowerCase()
    rows = rows.filter((c) =>
      c.id.toLowerCase().includes(s) || c.subject.toLowerCase().includes(s) ||
      actorMeta(c.requester).name.toLowerCase().includes(s))
  }
  return rows
}

export async function listCases(filters = {}, { sort = 'risk', limit = 400 } = {}) {
  return read(() => {
    if (hook('empty')) return { rows: [], total: 0, showing: 0 }
    const rows = filterCases(filters)
    const sorted = [...rows].sort((a, b) => {
      if (sort === 'age') return new Date(a.created_at) - new Date(b.created_at)
      if (sort === 'id') return a.id.localeCompare(b.id)
      const av = a.sla_deadline ? new Date(a.sla_deadline).getTime() : Infinity
      const bv = b.sla_deadline ? new Date(b.sla_deadline).getTime() : Infinity
      return av - bv
    })
    return { rows: sorted.slice(0, limit), total: sorted.length, showing: Math.min(limit, sorted.length) }
  })
}

export async function search(term) {
  return read(() => {
    const s = (term || '').trim().toLowerCase()
    if (!s) return { cases: [], analysts: [], articles: [] }
    const exact = CASES.find((c) => c.id.toLowerCase() === s)
    return {
      exact_case: exact ? exact.id : null,
      cases: filterCases({ query: s }).slice(0, 8),
      analysts: ANALYSTS.filter((a) => a.name.toLowerCase().includes(s)).slice(0, 5),
      articles: KB_DRAFTS.filter((d) => d.title.toLowerCase().includes(s)).slice(0, 4),
    }
  }, { base: 120 })
}

/* ---------------- S-04 queue ---------------- */

/** Queue items are recommendations awaiting a decision — not "all open cases". */
export function buildQueue() {
  const items = []
  const DAY = 86400000
  // A queue holds recommendations awaiting a decision on CURRENT work — not
  // every open case in the corpus. Anything older than a week has long since
  // been decided; it lives in Audit, not here.
  const pool = CASES
    .filter(agg.isOpen)
    .filter((c) => NOW - new Date(c.created_at).getTime() < 7 * DAY)
    .filter((c) => !decisions.has(c.id) || c.id === 'HFG-2402')
  const pinned = ['HFG-2214', 'HFG-2308', 'HFG-2402', 'HFG-2455']
  const rest = pool.filter((c) => !pinned.includes(c.id)).slice(0, 19)
  const ordered = [...pinned.map(caseById).filter(Boolean), ...rest]

  ordered.forEach((c) => {
    let type = ItemType.DRAFT
    if (c.id === 'HFG-2214') type = ItemType.MERGE
    if (c.id === 'HFG-2455') type = ItemType.ESCALATION
    const d = decisions.get(c.id)
    const w = writes.get(c.id)
    items.push({
      case_id: c.id, subject: c.subject, class: c.class, tier: c.tier,
      team: c.team, band: c.band, confidence: c.confidence,
      sla_deadline: c.sla_deadline, sla_paused: c.sla_paused,
      created_at: c.created_at, requester: c.requester,
      type,
      awaiting_context: c.id === 'HFG-2308',
      qa_flagged: c.qa_flagged,
      decision: d ? d.state : DecisionState.DRAFT_PENDING,
      write: w ? w.state : WriteState.NOT_STARTED,
      write_attempts: w ? w.attempts : 0,
      version: 'v1',
    })
  })
  return items
}

export async function listQueueItems(filters = {}) {
  return read(() => {
    if (hook('empty')) return []
    let items = buildQueue()
    if (filters.type) items = items.filter((i) => i.type === filters.type)
    if (filters.class) items = items.filter((i) => i.class === filters.class)
    if (filters.band) items = items.filter((i) => i.band === filters.band)
    if (filters.team) items = items.filter((i) => i.team === filters.team)
    if (filters.risk === 'at-risk') items = items.filter((i) => i.sla_deadline && new Date(i.sla_deadline) - NOW < 2 * 3600000)
    /* Default sort = SLA risk desc, then age (§10.4). A paused clock carries no
       live risk, so it sorts below every running one rather than jumping the
       queue on a deadline it is not counting down to. */
    const riskKey = (i) => {
      if (!i.sla_deadline || i.sla_paused) return Infinity
      return new Date(i.sla_deadline).getTime()
    }
    return items.sort((a, b) => {
      const ra = riskKey(a), rb = riskKey(b)
      if (ra !== rb) return ra - rb           // Infinity sorts last, as intended
      return new Date(a.created_at) - new Date(b.created_at)
    })
  })
}

export async function getRecommendation(caseId) {
  return read(() => ({
    draft: draftFor(caseId),
    escalation: ESCALATIONS[caseId] || null,
    merge: caseId === 'HFG-2214'
      ? { candidates: explainerFor(caseId).duplicates.filter((d) => d.proposal === 'merge') }
      : null,
    decision: decisions.get(caseId)?.state || DecisionState.DRAFT_PENDING,
    decided_by: decisions.get(caseId)?.actor || null,
    decided_at: decisions.get(caseId)?.at || null,
    write: writeFor(caseId),
    version: 'v1',
  }))
}

export async function getContextPack(caseId) {
  const pack = packFor(caseId)
  const budget = config.budgets_ms.context_pack
  const slow = Number(hook('slow') || 0)
  await sleep(slow || Math.min(pack?.compile_ms ?? 900, 1600))
  return { ...pack, over_budget: (slow || pack?.compile_ms || 0) > budget }
}

/* ---------------- the write gate ----------------
   submitDecision records a DECISION. It then, and only then, starts a separate
   WriteExecution. There is no path here that writes without a decision record. */

export async function submitDecision(caseId, action, payload = {}) {
  const actor = payload.actor || 'P. Nair'

  // (b) double-submit: the caller disables its control; the plane also rejects.
  if (writeFor(caseId).state !== WriteState.NOT_STARTED && writeFor(caseId).state !== WriteState.FAILED) {
    throw new ApiError('conflict', 'A decision on this item is already in flight.', 'submitDecision')
  }

  // (a) optimistic locking — stale version ⇒ 409, never a second approval.
  if (hook('conflict') && !decisions.has(caseId)) {
    await sleep(340)
    const at = new Date(NOW - 4 * 60000).toISOString()
    decisions.set(caseId, { state: DecisionState.APPROVED, actor: 'R. Bose', at, version: 'v2' })
    writes.set(caseId, { state: WriteState.SUCCEEDED, attempts: 1, audit_id: `A-${++auditSeq}` })
    notify()
    throw new ApiError('conflict', 'Already decided by R. Bose', 'submitDecision',
      { decided_by: 'R. Bose', decided_at: at, recorded_outcome: 'approved · written' })
  }

  if (action === 'reject') {
    const reason = (payload.reason || '').trim()
    if (reason.length < config.reject_reason_min_chars) {
      throw new ApiError('validation',
        `A reason of at least ${config.reject_reason_min_chars} characters is required.`, 'submitDecision')
    }
    await sleep(380)
    decisions.set(caseId, { state: DecisionState.REJECTED, actor, at: new Date().toISOString(), version: 'v1', reason })
    notify()
    // Rejection writes an audit row and NO external write (§5.1 step 7).
    return { decision: DecisionState.REJECTED, audit_id: `A-${++auditSeq}`, write: null }
  }

  const state = action === 'edit' ? DecisionState.EDITED_APPROVED : DecisionState.APPROVED
  await sleep(360)
  decisions.set(caseId, {
    state, actor, at: new Date().toISOString(), version: 'v1',
    edited_text: payload.edited_text || null,
  })
  const audit_id = `A-${++auditSeq}`
  notify()

  // The write is a SEPARATE machine, started after the decision is recorded.
  runWrite(caseId, audit_id)
  return { decision: state, audit_id, write: WriteState.QUEUED }
}

/** WriteExecution: not_started → queued → executing → retrying(n) → succeeded|failed */
async function runWrite(caseId, audit_id) {
  const set = (patch) => { writes.set(caseId, { ...writeFor(caseId), audit_id, ...patch }); notify() }
  const failMode = hook('fail')

  set({ state: WriteState.QUEUED, attempts: 0 })
  await sleep(700)
  set({ state: WriteState.EXECUTING, attempts: 1 })
  await sleep(900)

  if (failMode === '429' || failMode === 'write') {
    set({ state: WriteState.RETRYING, attempts: 2 })
    await sleep(1400)
    set({ state: WriteState.RETRYING, attempts: 3 })
    await sleep(1400)
    if (failMode === 'write') {
      set({ state: WriteState.FAILED, attempts: 3, error: 'HTTP 502 from the Zendesk emulator after 2 rate-limit retries.' })
      return
    }
    set({ state: WriteState.SUCCEEDED, attempts: 3 })
    return
  }
  set({ state: WriteState.SUCCEEDED, attempts: 1 })
}

/** Re-fire execution only. The approval is NOT re-taken [F-070]. */
export async function refireExecution(caseId) {
  const d = decisions.get(caseId)
  if (!d) throw new ApiError('validation', 'No approval record exists to re-fire.', 'refireExecution')
  const audit_id = writeFor(caseId).audit_id || `A-${++auditSeq}`
  writes.set(caseId, { state: WriteState.QUEUED, attempts: 0, audit_id })
  notify()
  await sleep(800)
  writes.set(caseId, { state: WriteState.EXECUTING, attempts: 1, audit_id })
  notify()
  await sleep(1100)
  writes.set(caseId, { state: WriteState.SUCCEEDED, attempts: 1, audit_id })
  notify()
  return { write: WriteState.SUCCEEDED, audit_id }
}

export async function confirmMerge(caseId, targetId, { decline = false, actor = 'P. Nair' } = {}) {
  await sleep(520)
  const audit_id = `A-${++auditSeq}`
  if (decline) {
    decisions.set(caseId, { state: DecisionState.REJECTED, actor, at: new Date().toISOString(), version: 'v1', reason: 'Kept as a link' })
    notify()
    return { merged: false, linked: true, audit_id }
  }
  /* A merge IS an external write, so it takes the same route as any other:
     the human confirmation is recorded as a decision FIRST, and only then does
     a write state exist. Nothing here can produce a write without that record. */
  decisions.set(caseId, { state: DecisionState.APPROVED, actor, at: new Date().toISOString(), version: 'v1' })
  writes.set(caseId, { state: WriteState.SUCCEEDED, attempts: 1, audit_id })
  notify()
  return { merged: true, target: targetId, audit_id }
}

export async function submitAssignmentFeedback(caseId, analystId, kind) {
  await sleep(400)
  const state = kind === 'accept' ? AssignmentState.FEEDBACK_ACCEPTED : AssignmentState.FEEDBACK_OVERRIDDEN
  assignmentFeedback.set(caseId, { analystId, state, at: new Date().toISOString() })
  notify()
  // Shadow-only: an audit row, evaluation feedback, and NO external routing write.
  return { state, audit_id: `A-${++auditSeq}`, external_write: false }
}
export const assignmentFeedbackFor = (caseId) => assignmentFeedback.get(caseId) || null

/* ---------------- S-05 ---------------- */

export async function getTicket360(caseId) {
  return read(() => {
    const c = caseById(caseId)
    if (!c) throw new ApiError('notfound', 'Record unavailable', 'getTicket360')
    const actor = actorMeta(c.requester)
    return {
      case: c,
      actor,
      identity: identityFor(c.requester),
      class_meta: classMeta(c.class),
      team_name: TEAMS.find((t) => t.id === c.team)?.name,
      assignee: ANALYSTS.find((a) => a.id === c.assignee) || null,
      linked_issues: LINKED_ISSUES[caseId] || [],
      decision: decisions.get(caseId) || null,
      write: writeFor(caseId),
    }
  })
}

export async function listTimeline(caseId) {
  return read(() => timelineFor(caseId))
}

export const getExplainers = (caseId) => read(() => explainerFor(caseId))
export const getShortlist = (caseId) => read(() => shortlistFor(caseId))
export const getCallRecording = (id) => read(() => callFor(id), { base: 320 })

/* ---------------- S-09 audit ---------------- */

export async function listAuditDecisions(filters = {}) {
  return read(() => {
    let rows = ALL_AUDIT
    if (filters.from) rows = rows.filter((r) => new Date(r.occurred_at) >= new Date(filters.from))
    if (filters.to) rows = rows.filter((r) => new Date(r.occurred_at) <= new Date(filters.to))
    if (filters.type) rows = rows.filter((r) => r.decision_type === filters.type)
    if (filters.actor) rows = rows.filter((r) => r.actor === filters.actor)
    if (filters.outcome) rows = rows.filter((r) => r.outcome === filters.outcome)
    if (filters.flagged === '1') rows = rows.filter((r) => r.flagged)
    if (filters.case_id) rows = rows.filter((r) => r.case_id === filters.case_id)
    if (filters.own) rows = rows.filter((r) => r.actor === filters.own)
    return { rows: rows.slice(0, 300), total: rows.length, completeness: AUDIT_COMPLETENESS }
  })
}
export const getAuditTimeline = (row) => entriesFor(row)
export const auditActors = () => [...new Set(ALL_AUDIT.map((r) => r.actor))]

/* ---------------- S-10 / S-11 / notifications / demo ---------------- */

export const listKbDrafts = () => read(() => ({ drafts: KB_DRAFTS, decided: KB_DECIDED, gaps: KB_GAPS }))

export async function submitKbDecision(draftId, action, payload = {}) {
  await sleep(460)
  if (action === 'reject' && (payload.reason || '').trim().length < config.reject_reason_min_chars) {
    throw new ApiError('validation',
      `A reason of at least ${config.reject_reason_min_chars} characters is required.`, 'submitKbDecision')
  }
  return { ok: true, audit_id: `A-${++auditSeq}`, verb: action === 'reject' ? 'rejected' : 'Create/update Zendesk Guide draft (draft=true)' }
}

export const getWeeklyDigest = () => read(() => weeklyDigest(), { base: 420 })

export const listNotifications = (role) => read(() =>
  NOTIFICATIONS.filter((n) => !n.admin_only || role === 'admin' || role === 'demo'), { base: 150 })

export const getDemoCatalogue = () => read(() => ({ tiles: DEMO_CATALOGUE, discovery: DISCOVERY, plan: INGESTION_PLAN }))

/* Manager drill support: analyst-level backing cases for an S-08 number [NFR-42]. */
export const getBackingCases = (ids) => read(() => filterCases({ ids: ids.join(',') }))
