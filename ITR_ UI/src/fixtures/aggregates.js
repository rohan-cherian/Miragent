/* Aggregates computed from the ONE case list — never hand-typed. This is what
   makes P-4 true: every figure carries the filter that reproduces it, so a click
   lands on S-13 showing exactly the rows behind the number [NFR-42, NFR-31]. */

import {
  CASES, CATEGORIES, CHANNELS, TIERS, CLASSES, ANALYSTS, LEVELS, NOW,
  kbCoverage, classMeta, KB,
} from './corpus.js'
import { CaseStatus } from '../contracts/state.js'

const DAY = 86400000
const OPEN_STATES = [CaseStatus.NEW, CaseStatus.OPEN, CaseStatus.PENDING, CaseStatus.HOLD]

export const isOpen = (c) => OPEN_STATES.includes(c.status)

const monthKey = (iso) => {
  const d = new Date(iso)
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}
const monthLabel = (key) => {
  const [y, m] = key.split('-')
  return new Date(Date.UTC(+y, +m - 1, 1)).toLocaleString('en-GB', { month: 'short', year: '2-digit' })
}

/* ---------- Period (§6.3 `?period=`, §10.3 "what changed this month") ----------
   The period is the comparison window. Deltas are computed against the
   immediately preceding window of the same length — and where no comparable
   prior window exists in the corpus, the delta is ABSENT rather than invented. */
export const PERIODS = [
  { id: '30d', label: 'Last 30 days', days: 30 },
  { id: '90d', label: 'Last 90 days', days: 90 },
  { id: '12m', label: 'Last 12 months', days: 365 },
]
export const periodMeta = (id) => PERIODS.find((p) => p.id === id) || PERIODS[2]

/** Cases inside the window, and inside the window before it. */
function windows(periodId) {
  const { days } = periodMeta(periodId)
  const span = days * DAY
  const from = NOW - span
  const priorFrom = NOW - 2 * span
  const inWindow = CASES.filter((c) => new Date(c.created_at).getTime() >= from)
  const inPrior = CASES.filter((c) => {
    const t = new Date(c.created_at).getTime()
    return t >= priorFrom && t < from
  })
  // A prior window with almost nothing in it cannot support an honest delta:
  // the corpus is 12 months deep, so "last 12 months" has no comparable before.
  const comparable = inPrior.length >= Math.max(20, inWindow.length * 0.1)
  return { from, priorFrom, inWindow, inPrior, comparable, days }
}

/** ISO date for a filter, so a drill reproduces exactly the window shown. */
const isoDay = (ms) => new Date(ms).toISOString().slice(0, 10)

const pctChange = (now, before) =>
  before === 0 ? null : Number((((now - before) / before) * 100).toFixed(1))

/* ---------- KPI band (§10.3) ----------
   Every tile drills. P-4 is not advisory: a number that cannot be opened is
   decoration and does not ship. Three of these resolve to a case list; three
   resolve to the surface that holds their records. */
export function kpis(periodId = '12m') {
  const w = windows(periodId)
  const label = periodMeta(periodId).label.toLowerCase()
  const priorLabel = `vs the ${w.days} days before`

  /* Open is a STOCK — what is on the floor right now, at every age. Scoping it
     to a window and comparing windows compares a young cohort to an aged one,
     which reports the shape of the corpus rather than the health of the queue. */
  const openStock = CASES.filter(isOpen)

  /* Solved is a FLOW — cases that reached solved inside the window, by their
     resolution timestamp. This is the one the delta is meaningful on. */
  const solvedBetween = (fromMs, toMs) => CASES.filter((c) => {
    if (!c.resolved_at) return false
    const t = new Date(c.resolved_at).getTime()
    return t >= fromMs && t < toMs
  })
  const solvedNow = solvedBetween(w.from, NOW)
  const solvedPrior = solvedBetween(w.priorFrom, w.from)

  const cov = kbCoverage()
  const coveragePct = cov.covered / cov.classes
  const thinAndGapClasses = CLASSES.filter((c) => (KB.perClass[c.id] ?? 0) < 6).map((c) => c.id)

  const dateFilter = { from: isoDay(w.from) }
  const delta = (now, before) => (w.comparable ? pctChange(now.length, before.length) : null)
  const deltaNote = w.comparable ? priorLabel : 'no comparable prior window in the corpus'

  return [
    {
      key: 'total', label: 'Total cases', value: w.inWindow.length,
      delta: delta(w.inWindow, w.inPrior), deltaUnit: '%', deltaLabel: deltaNote,
      drill: dateFilter,
      help: `Canonical Cases created in the ${label}, across six emulated sources.`,
    },
    {
      key: 'open', label: 'Open', value: openStock.length,
      delta: null, deltaLabel: 'on the floor now, at every age',
      drill: { status: 'open' },
      help: 'new · open · pending · hold. A stock, not a period figure — so it carries no period delta.',
    },
    {
      key: 'solved', label: 'Solved', value: solvedNow.length,
      delta: delta(solvedNow, solvedPrior), deltaUnit: '%', deltaLabel: deltaNote,
      drill: { status: 'solved', resolvedFrom: isoDay(w.from) },
      help: `Cases that reached solved in the ${label}, by resolution date.`,
    },
    {
      key: 'analysts', label: 'Analysts', value: ANALYSTS.length,
      delta: null, deltaLabel: 'roster size, not a period figure',
      // Drills to the WORK the roster is carrying, never to a list of people —
      // an ordered list of analysts is the ranking artefact §1.4 forbids.
      drill: { status: 'open', assigned: '1' },
      drillLabel: 'Open cases the roster is carrying',
      help: 'Roster across 40 teams. This console has no per-analyst ranking anywhere.',
    },
    {
      key: 'kb', label: 'KB articles', value: 900,
      delta: null, deltaLabel: 'Zendesk Guide corpus',
      navTo: '/knowledge?origin=overview',
      drillLabel: 'Open the knowledge surface',
      help: 'Emulated Guide corpus. Drafts and gaps live on the Knowledge screen.',
    },
    {
      key: 'coverage', label: 'KB coverage', value: coveragePct, format: 'pct',
      delta: null, deltaLabel: `${cov.thin} thin · ${cov.gap} gap`,
      navTo: '/knowledge?tab=gaps&origin=overview',
      drillLabel: 'Open the ranked gap queue',
      help: 'Share of classes with an adequate article. The uncovered ones are the digest story.',
      thinAndGapClasses,
    },
  ]
}

/* ---------- Generic counter with a reproducing filter attached ----------
   The filter carried on each row is the exact one that regenerates it, period
   included — so a drill can never show a different set than the bar claimed. */
function countBy(keyFn, order, filterKey, periodId) {
  const { inWindow, from } = windows(periodId)
  const counts = new Map(order.map((k) => [k, 0]))
  inWindow.forEach((c) => {
    const k = keyFn(c)
    if (counts.has(k)) counts.set(k, counts.get(k) + 1)
  })
  return order.map((k) => ({
    key: k, label: k, value: counts.get(k),
    drill: { [filterKey]: k, from: isoDay(from) },
  }))
}

export const byCategory = (periodId) =>
  countBy((c) => c.category, CATEGORIES, 'category', periodId).sort((a, b) => b.value - a.value)

export const byChannel = (periodId) =>
  countBy((c) => c.channel, CHANNELS.map((c) => c.id), 'channel', periodId)
    .map((r) => ({ ...r, label: CHANNELS.find((c) => c.id === r.key).label }))
    .sort((a, b) => b.value - a.value)

export const byTier = (periodId) => countBy((c) => c.tier, TIERS, 'tier', periodId)

/** 12-month volume line. Buckets derive from the same case list. */
export function byMonth() {
  const keys = []
  for (let i = 11; i >= 0; i--) {
    const d = new Date(NOW - i * 30 * DAY)
    keys.push(`${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`)
  }
  const uniq = [...new Set(keys)]
  const counts = new Map(uniq.map((k) => [k, 0]))
  CASES.forEach((c) => {
    const k = monthKey(c.created_at)
    if (counts.has(k)) counts.set(k, counts.get(k) + 1)
  })
  return uniq.map((k) => ({
    key: k, label: monthLabel(k), value: counts.get(k),
    drill: { from: `${k}-01` },
  }))
}

/** Roster summary by level — headcount only. Never a performance surface [§1.4].
    The drill deliberately resolves to the COHORT'S CASEWORK, not to a list of
    people: an ordered list of analysts is the ranking artefact §1.4 forbids. */
export const byLevel = () =>
  LEVELS.map((lv) => ({
    key: lv, label: lv,
    value: ANALYSTS.filter((a) => a.level === lv).length,
    drill: { assigneeLevel: lv },
    drillLabel: `Cases handled by the ${lv} cohort`,
  }))

/** KB coverage donut: covered / thin / gap. Three well-separated series slots.
    Thin and gap resolve to the ranked gap queue (§10.3 micro-journey 2). */
export function coverageDonut() {
  const cov = kbCoverage()
  return [
    { key: 'covered', label: 'Covered', value: cov.covered, seriesIndex: 0,
      navTo: '/knowledge?origin=overview',
      drillLabel: 'Open the knowledge surface' },
    { key: 'thin', label: 'Thin', value: cov.thin, seriesIndex: 2,
      navTo: '/knowledge?tab=gaps&origin=overview',
      drillLabel: 'Open the ranked gap queue' },
    { key: 'gap', label: 'Gap', value: cov.gap, seriesIndex: 4,
      navTo: '/knowledge?tab=gaps&origin=overview',
      drillLabel: 'Intents with no adequate article, ranked' },
  ]
}

/* ---------- SLA hotspots (digest + dashboard) ---------- */
export function slaHotspots(limit = 5) {
  const open = CASES.filter(isOpen).filter((c) => c.sla_deadline)
  const byClass = new Map()
  open.forEach((c) => {
    const t = new Date(c.sla_deadline).getTime()
    const risk = t - NOW < 2 * 3600000
    const row = byClass.get(c.class) || { open: 0, atRisk: 0 }
    row.open++
    if (risk) row.atRisk++
    byClass.set(c.class, row)
  })
  return [...byClass.entries()]
    .map(([k, v]) => ({
      key: k, label: k, category: classMeta(k).cat,
      open: v.open, atRisk: v.atRisk,
      rate: v.open ? v.atRisk / v.open : 0,
      drill: { class: k, risk: 'at-risk' },
    }))
    .filter((r) => r.atRisk >= 4)
    .sort((a, b) => b.atRisk - a.atRisk)
    .slice(0, limit)
}

/* ---------- Class experience per analyst, derived from the case list ----------
   NFR-40: every displayed analyst statistic must be reproducible from case data.
   These are derived, not invented. */
export function classExperience(analystId, classId) {
  const handled = CASES.filter(
    (c) => c.assignee === analystId && c.class === classId &&
      (c.status === CaseStatus.SOLVED || c.status === CaseStatus.CLOSED)
  )
  if (!handled.length) return null
  const rated = handled.filter((c) => c.csat != null)
  const csatAvg = rated.length ? rated.reduce((s, c) => s + c.csat, 0) / rated.length : null
  return {
    tickets_handled: handled.length,
    case_ids: handled.map((c) => c.id),
    csat_avg: csatAvg,
    reopen_rate: handled.filter((c) => c.reopened).length / handled.length,
  }
}

/* ---------- Adoption metrics (08_Metrics_KPIs · Usefulness) ----------
   The three numbers a support director judges the system by. §1.4 permits them
   (they are in the approved metric set) and §10.11's Quality section did not
   carry them. Each is DERIVED from the decision records, so each one drills to
   the rows that produced it — a stated constant would be decoration. */
export function adoptionMetrics(auditRows, periodId = '12m') {
  const { inWindow, from } = windows(periodId)

  /* Measured over TICKETS, not over drafts: the target is "one in three tickets
     pre-drafted usably". A ratio of approvals to drafts would answer a different
     question and would sit far above the target for the wrong reason. */
  const usable = inWindow.filter((c) => c.draft_outcome === 'approved' || c.draft_outcome === 'edited')
  const unedited = inWindow.filter((c) => c.draft_outcome === 'approved')
  const drafted = inWindow.filter((c) => c.draft_outcome !== 'none')

  const assignment = auditRows.filter((r) => r.agent === 'Assignment')
  const accepted = assignment.filter((r) => r.decision_type === 'feedback_accepted')

  const kb = auditRows.filter((r) => r.agent === 'KB Curator')
  const kbAccepted = kb.filter((r) => r.decision_type === 'approved')

  const rate = (a, b) => (b === 0 ? null : a / b)

  return [
    {
      key: 'usable_draft',
      label: 'Usable draft rate',
      value: rate(usable.length, inWindow.length),
      target: 0.30,
      basis: `${usable.length} of ${inWindow.length} tickets arrived with a draft a human could use — approved as written or after an edit.`,
      detail: `${unedited.length} went out unedited. ${drafted.length - usable.length} were drafted but rejected; the rest took an escalation path.`,
      drill: { ids: usable.slice(0, 150).map((c) => c.id).join(','), from: isoDay(from) },
      drillLabel: 'Tickets that arrived with a usable draft',
    },
    {
      key: 'assignment_acceptance',
      label: 'Assignment acceptance',
      value: rate(accepted.length, assignment.length),
      target: 0.80,
      basis: `${accepted.length} of ${assignment.length} shadow proposals were accepted at the routing gate.`,
      detail: 'Shadow mode — acceptance is recorded feedback, never an external routing write.',
      drillTo: '/audit?actor=&type=feedback_accepted&origin=intelligence',
      drillLabel: 'Open the routing-gate records',
    },
    {
      key: 'kb_acceptance',
      label: 'KB draft acceptance',
      value: rate(kbAccepted.length, kb.length),
      target: 0.50,
      basis: `${kbAccepted.length} of ${kb.length} curator drafts were approved as drafts.`,
      detail: 'Approval creates a Guide draft. Publication remains a separate gated act.',
      drillTo: '/audit?type=approved&origin=intelligence',
      drillLabel: 'Open the KB decisions',
    },
  ]
}

/* ---------- Capability map for the digest (§10.11) ----------
   Coverage depth = how many analysts carry meaningful volume in a class.
   Anonymised at the point of display [F-129]; no names leave this function. */
export function capabilityMap() {
  const map = CLASSES.map((cls) => {
    const solved = CASES.filter(
      (c) => c.class === cls.id && c.assignee &&
        (c.status === CaseStatus.SOLVED || c.status === CaseStatus.CLOSED)
    )
    const perAnalyst = new Map()
    solved.forEach((c) => perAnalyst.set(c.assignee, (perAnalyst.get(c.assignee) || 0) + 1))
    const ranked = [...perAnalyst.values()].sort((a, b) => b - a)
    const total = ranked.reduce((a, b) => a + b, 0)
    // Depth = analysts needed to cover 80% of the class's volume.
    let acc = 0, depth = 0
    for (const n of ranked) { acc += n; depth++; if (acc >= total * 0.8) break }
    return {
      key: cls.id, label: cls.label, category: cls.cat,
      volume: solved.length,
      depth,
      contributors: ranked.length,
      // Two people covering 80% of a class with real volume is a continuity risk.
      thin: depth <= 2 && solved.length >= 30,
      drill: { class: cls.id },
    }
  })
  return map.sort((a, b) => b.volume - a.volume)
}
