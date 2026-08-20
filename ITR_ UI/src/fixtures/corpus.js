/* Synthetic corpus — the shared world. ONE corpus, no screen-local data.
   Everything here is fabricated for the POC and labelled Emulated/Synthetic
   at three layers (§11.4). Deterministic: a seeded PRNG so every reload shows
   the same numbers and S-03's aggregates reconcile with S-13's rows [NFR-31]. */

import { config } from '../contracts/config.js'
import { CaseStatus, Band } from '../contracts/state.js'

/* ---------- deterministic PRNG (mulberry32) ---------- */
function rng(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const pick = (r, arr) => arr[Math.floor(r() * arr.length)]
/** Weighted pick: [[value, weight], …] */
const weighted = (r, pairs) => {
  const total = pairs.reduce((s, [, w]) => s + w, 0)
  let x = r() * total
  for (const [v, w] of pairs) { if ((x -= w) <= 0) return v }
  return pairs[pairs.length - 1][0]
}

/** Demo clock. Fixed at module load so relative times stay honest in a session. */
export const NOW = Date.now()
const HOUR = 3600000, DAY = 24 * HOUR

/* ---------- The six emulated source systems (10_Source_Systems) ---------- */
export const SYSTEMS = [
  { id: 'zendesk',    name: 'Zendesk',                 short: 'ZD', role: 'Ticketing & Guide' },
  { id: 'salesforce', name: 'Salesforce Service Cloud', short: 'SF', role: 'Accounts, contacts, entitlements' },
  { id: 'workday',    name: 'Workday',                 short: 'WD', role: 'Workers, org units, schedules' },
  { id: 'jira',       name: 'Jira',                    short: 'JR', role: 'Engineering defects (read-context)' },
  { id: 'entra',      name: 'Microsoft Entra',         short: 'EN', role: 'Groups, devices, sign-ins' },
  { id: 'slack',      name: 'Slack / Teams',           short: 'SL', role: 'Conversation threads' },
]
export const systemName = (id) => SYSTEMS.find((s) => s.id === id)?.name || id

/* ---------- Taxonomy: 10 L1 categories, classes beneath them ---------- */
export const CATEGORIES = [
  'Identity & Access', 'Payroll & HR Systems', 'Order & Fulfilment', 'Finance & Billing',
  'Cold Chain & Logistics', 'Manufacturing Systems', 'Retail POS', 'Data & Reporting',
  'Collaboration Tools', 'Network & Devices',
]

export const CLASSES = [
  { id: 'auth-sso',              label: 'auth-sso',              cat: 'Identity & Access',      weight: 9 },
  { id: 'auth-mfa',              label: 'auth-mfa',              cat: 'Identity & Access',      weight: 6 },
  { id: 'auth-provisioning',     label: 'auth-provisioning',     cat: 'Identity & Access',      weight: 4 },
  { id: 'sso-scim-sync',         label: 'sso-scim-sync',         cat: 'Identity & Access',      weight: 2 },
  { id: 'payroll-integrations',  label: 'payroll-integrations',  cat: 'Payroll & HR Systems',   weight: 5 },
  { id: 'payroll-payslip',       label: 'payroll-payslip',       cat: 'Payroll & HR Systems',   weight: 4 },
  { id: 'hr-workday-org',        label: 'hr-workday-org',        cat: 'Payroll & HR Systems',   weight: 3 },
  { id: 'order-edi',             label: 'order-edi',             cat: 'Order & Fulfilment',     weight: 7 },
  { id: 'order-shortship',       label: 'order-shortship',       cat: 'Order & Fulfilment',     weight: 6 },
  { id: 'order-portal',          label: 'order-portal',          cat: 'Order & Fulfilment',     weight: 5 },
  { id: 'billing-invoice',       label: 'billing-invoice',       cat: 'Finance & Billing',      weight: 6 },
  { id: 'billing-credit-note',   label: 'billing-credit-note',   cat: 'Finance & Billing',      weight: 3 },
  { id: 'coldchain-telemetry',   label: 'coldchain-telemetry',   cat: 'Cold Chain & Logistics', weight: 5 },
  { id: 'coldchain-route',       label: 'coldchain-route',       cat: 'Cold Chain & Logistics', weight: 4 },
  { id: 'mfg-line-sensor',       label: 'mfg-line-sensor',       cat: 'Manufacturing Systems',  weight: 4 },
  { id: 'mfg-batch-record',      label: 'mfg-batch-record',      cat: 'Manufacturing Systems',  weight: 3 },
  { id: 'pos-terminal',          label: 'pos-terminal',          cat: 'Retail POS',             weight: 5 },
  { id: 'pos-pricing',           label: 'pos-pricing',           cat: 'Retail POS',             weight: 4 },
  { id: 'report-latency',        label: 'report-latency',        cat: 'Data & Reporting',       weight: 4 },
  { id: 'data-export',           label: 'data-export',           cat: 'Data & Reporting',       weight: 3 },
  { id: 'collab-teams',          label: 'collab-teams',          cat: 'Collaboration Tools',    weight: 4 },
  { id: 'collab-sharepoint',     label: 'collab-sharepoint',     cat: 'Collaboration Tools',    weight: 3 },
  { id: 'device-laptop',         label: 'device-laptop',         cat: 'Network & Devices',      weight: 5 },
  { id: 'network-vpn',           label: 'network-vpn',           cat: 'Network & Devices',      weight: 4 },
]
export const classMeta = (id) => CLASSES.find((c) => c.id === id) || CLASSES[0]

export const CHANNELS = [
  { id: 'email',      label: 'Email',        icon: '✉' },
  { id: 'web',        label: 'Web form',     icon: '▤' },
  { id: 'voice',      label: 'Voice',        icon: '☎' },
  { id: 'slack',      label: 'Slack',        icon: '#' },
  { id: 'teams',      label: 'Teams',        icon: '⧉' },
  { id: 'portal',     label: 'Portal',       icon: '◫' },
  { id: 'api',        label: 'API',          icon: '⌁' },
  { id: 'edi',        label: 'EDI',          icon: '⇄' },
  { id: 'sms',        label: 'SMS',          icon: '✆' },
  { id: 'mobile',     label: 'Mobile app',   icon: '▯' },
  { id: 'walkup',     label: 'Walk-up',      icon: '☗' },
  { id: 'partner',    label: 'Partner desk', icon: '⛭' },
]
export const channelMeta = (id) => CHANNELS.find((c) => c.id === id) || CHANNELS[0]

export const TIERS = ['Enterprise', 'Mid-market', 'SMB', 'Internal']
export const LEVELS = ['L1', 'L2', 'L3', 'SME']

/* ---------- 40 teams ---------- */
const TEAM_STEMS = [
  'IAM Support', 'Payroll Ops Support', 'Order Desk', 'Billing Support', 'Cold Chain Desk',
  'Plant Systems', 'Retail Systems', 'Data Services', 'Workplace IT', 'Network Ops',
]
export const TEAMS = Array.from({ length: 40 }, (_, i) => {
  const stem = TEAM_STEMS[i % TEAM_STEMS.length]
  const region = ['EMEA', 'APAC', 'AMER', 'UK&I'][Math.floor(i / TEAM_STEMS.length)]
  return { id: `team-${i + 1}`, name: `${stem} · ${region}` }
})

/* ---------- 240 analysts ---------- */
const FIRST = ['Priya', 'Rahul', 'Mei', 'Daniel', 'Aisha', 'Tomas', 'Lena', 'Ravi', 'Grace', 'Omar',
  'Sofia', 'Jonas', 'Nadia', 'Hugo', 'Kiran', 'Elena', 'Marcus', 'Ines', 'Yusuf', 'Clara',
  'Arun', 'Freya', 'Diego', 'Anya', 'Noah', 'Leila', 'Sven', 'Divya', 'Pablo', 'Mira']
const LAST = ['Nair', 'Bose', 'Chen', 'Okafor', 'Bello', 'Novak', 'Hartmann', 'Iyer', 'Mbeki', 'Haddad',
  'Duarte', 'Lindqvist', 'Rahman', 'Ferreira', 'Menon', 'Petrova', 'Adeyemi', 'Costa', 'Demir', 'Vogel']

export const ANALYSTS = (() => {
  const r = rng(1042)
  const out = []
  const levelPlan = [...Array(110).fill('L1'), ...Array(85).fill('L2'), ...Array(35).fill('L3'), ...Array(10).fill('SME')]
  for (let i = 0; i < 240; i++) {
    const name = `${FIRST[i % FIRST.length]} ${LAST[(i * 7 + 3) % LAST.length]}`
    out.push({
      id: `an-${(i + 1).toString().padStart(3, '0')}`,
      name,
      level: levelPlan[i],
      team: TEAMS[i % TEAMS.length].id,
      languages: weighted(r, [[['en'], 5], [['en', 'de'], 2], [['en', 'hi'], 2], [['en', 'es'], 1]]),
      open_tickets: Math.floor(r() * 12),
      within_working_hours: r() > 0.25,
      // employment_type exists in the source data but is NEVER displayed or
      // scored [F-127, F-129] — kept here only to prove the anonymisation rule.
      _employment_type: weighted(r, [['FTE', 7], ['BPO', 3]]),
    })
  }
  // Named characters the demo narrative depends on.
  out[0] = { ...out[0], id: 'an-001', name: 'Priya Nair', level: 'L2', team: 'team-1', open_tickets: 6, within_working_hours: true }
  out[1] = { ...out[1], id: 'an-002', name: 'Rahul Bose', level: 'L2', team: 'team-1', open_tickets: 9, within_working_hours: true }
  out[2] = { ...out[2], id: 'an-003', name: 'Mei Chen',   level: 'L1', team: 'team-11', open_tickets: 4, within_working_hours: true }
  out[3] = { ...out[3], id: 'an-004', name: 'Aisha Bello', level: 'L3', team: 'team-2', open_tickets: 11, within_working_hours: false }
  return out
})()
export const analystMeta = (id) => ANALYSTS.find((a) => a.id === id)

/* ---------- Requesters (actors) ---------- */
const ORG_UNITS = ['Payroll Ops', 'Plant Ops — Dublin', 'Retail Ops', 'Finance Shared Services',
  'Logistics Control', 'Quality Assurance', 'IT Service Desk', 'Commercial', 'HR Operations']

export const ACTORS = (() => {
  const r = rng(77)
  const out = []
  for (let i = 0; i < 420; i++) {
    const name = `${FIRST[(i * 3 + 1) % FIRST.length]} ${LAST[(i * 5) % LAST.length]}`
    const [f, l] = name.toLowerCase().split(' ')
    out.push({
      id: `act-${(i + 1).toString().padStart(3, '0')}`,
      name,
      email: `${f[0]}.${l}@halcyonfoods.example`,
      org_unit: pick(r, ORG_UNITS),
      tier: weighted(r, [['Enterprise', 4], ['Mid-market', 3], ['SMB', 2], ['Internal', 3]]),
      identity_state: weighted(r, [['matched', 88], ['partial', 8], ['ambiguous', 4]]),
    })
  }
  out[0] = {
    id: 'act-001', name: 'Daniel Okafor', email: 'd.okafor@halcyonfoods.example',
    org_unit: 'Payroll Ops', tier: 'Enterprise', identity_state: 'matched',
  }
  return out
})()
export const actorMeta = (id) => ACTORS.find((a) => a.id === id) || ACTORS[0]

/* ---------- Subject phrasing per class, so rows read like real tickets ---------- */
const SUBJECTS = {
  'auth-sso': ['SSO login fails since the password rotation', 'Cannot sign in via SSO after MFA reset', 'SAML assertion rejected at login', 'Okta-to-Entra handoff loops back to login'],
  'auth-mfa': ['MFA push never arrives', 'Authenticator app out of sync', 'Locked out after 5 MFA attempts'],
  'auth-provisioning': ['New starter has no Zendesk access', 'Leaver account still active', 'Role change did not propagate'],
  'sso-scim-sync': ['SCIM sync dropped 40 users overnight', 'Group membership not flowing to Entra'],
  'payroll-integrations': ['Workday-to-payroll feed failed for Ireland', 'Payroll interface file rejected', 'Cost centre mapping missing for new plant'],
  'payroll-payslip': ['Payslip missing for July', 'Payslip shows wrong tax code'],
  'hr-workday-org': ['Manager chain wrong after reorg', 'Org unit missing for Dublin plant'],
  'order-edi': ['EDI 850 rejected by partner', 'Duplicate purchase orders on the EDI feed', 'EDI acknowledgement never received'],
  'order-shortship': ['Short shipment on chilled order 88213', 'Pallet count mismatch at goods-in'],
  'order-portal': ['Customer portal will not accept the order', 'Order status stuck at "picking"'],
  'billing-invoice': ['Invoice total does not match delivery note', 'Invoice not received for August'],
  'billing-credit-note': ['Credit note not applied to the account', 'Duplicate credit note raised'],
  'coldchain-telemetry': ['Temperature probe offline on trailer 42', 'Cold chain alert storm overnight'],
  'coldchain-route': ['Route plan missing the Cork drop', 'Delivery window recalculated incorrectly'],
  'mfg-line-sensor': ['Line 3 sensor reporting null weights', 'Batch weigher drifting out of tolerance'],
  'mfg-batch-record': ['Batch record will not close', 'Electronic signature rejected on batch 7712'],
  'pos-terminal': ['POS terminal offline at store 214', 'Card reader will not pair'],
  'pos-pricing': ['Promotion price not applied at till', 'Price file did not reach 12 stores'],
  'report-latency': ['Daily sales report ran 4 hours late', 'Dashboard refresh timing out'],
  'data-export': ['Scheduled export missing rows', 'Export file encoding broken'],
  'collab-teams': ['Teams channel missing after migration', 'Cannot share files in Teams'],
  'collab-sharepoint': ['SharePoint permissions lost on the QA site', 'Document library read-only unexpectedly'],
  'device-laptop': ['Laptop will not boot after update', 'Docking station not detected'],
  'network-vpn': ['VPN drops every 10 minutes', 'Cannot reach plant network over VPN'],
}

/* ---------- The 6,000-case corpus ---------- */
const CLASS_POOL = CLASSES.flatMap((c) => Array(c.weight).fill(c.id))

/* Real support orgs are not uniformly staffed: each class has a handful of
   people who actually handle it, and the top one or two carry most of it. That
   skew is the whole reason the capability map is worth reading, so the corpus
   has to contain it rather than have the UI assert it. */
const CLASS_SPECIALISTS = (() => {
  const r = rng(3301)
  const map = {}
  CLASSES.forEach((cls, idx) => {
    const size = cls.id === 'payroll-integrations' ? 3
      : cls.id === 'coldchain-telemetry' ? 3
      : cls.id === 'sso-scim-sync' ? 4
      : 6 + Math.floor(r() * 5)
    const pool = []
    for (let i = 0; i < size; i++) {
      pool.push(ANALYSTS[(idx * 17 + i * 41 + Math.floor(r() * 7)) % ANALYSTS.length].id)
    }
    // Weighted so the first two names carry the bulk of the class.
    map[cls.id] = pool.flatMap((id, i) => Array(Math.max(1, 9 - i * 3)).fill(id))
  })
  // The named characters own auth-sso, per the demo narrative.
  map['auth-sso'] = [
    ...Array(9).fill('an-001'), ...Array(6).fill('an-002'),
    ...Array(2).fill('an-003'), ...map['auth-sso'].slice(0, 6),
  ]
  return map
})()

export const CASES = (() => {
  const r = rng(20260810)
  const out = []
  for (let i = 0; i < 6000; i++) {
    // The first slice is this week's AUTH-341 recurrence — the digest's story.
    const surge = i < 26
    const classId = surge ? 'auth-sso' : pick(r, CLASS_POOL)
    const cls = classMeta(classId)
    const actor = ACTORS[Math.floor(r() * ACTORS.length)]
    // Volume skews toward recent months so month-over-month movement is readable.
    const monthsBack = surge ? 0 : weighted(r, [[0, 14], [1, 12], [2, 11], [3, 10], [4, 9], [5, 8],
      [6, 7], [7, 7], [8, 6], [9, 6], [10, 5], [11, 5]])
    const created = surge
      ? NOW - Math.floor(r() * 6.4 * DAY)                       // inside this week
      : NOW - monthsBack * 30 * DAY - Math.floor(r() * 30 * DAY)
    /* Status decays smoothly with age rather than by month bucket. Bucketing
       made almost nothing older than 30 days open, so a month-over-month
       comparison of the open count produced absurd swings — the dashboard was
       reporting a property of the generator, not of the operation. */
    const ageDays = (NOW - created) / DAY
    const openShare =
      ageDays < 2 ? 74 : ageDays < 5 ? 58 : ageDays < 10 ? 42 :
      ageDays < 21 ? 30 : ageDays < 45 ? 20 : ageDays < 90 ? 12 :
      ageDays < 180 ? 7 : 4
    const stillOpen = r() * 100 < openShare
    const status = stillOpen
      ? weighted(r, ageDays < 2
          ? [[CaseStatus.NEW, 40], [CaseStatus.OPEN, 45], [CaseStatus.PENDING, 12], [CaseStatus.HOLD, 3]]
          : [[CaseStatus.OPEN, 55], [CaseStatus.PENDING, 30], [CaseStatus.HOLD, 15]])
      : weighted(r, ageDays < 30
          ? [[CaseStatus.SOLVED, 70], [CaseStatus.CLOSED, 30]]
          : [[CaseStatus.SOLVED, 15], [CaseStatus.CLOSED, 85]])
    const bandRoll = r()
    const band = bandRoll > 0.42 ? Band.HIGH : bandRoll > 0.13 ? Band.MEDIUM : Band.LOW
    const confidence = band === Band.HIGH ? 0.85 + r() * 0.14
      : band === Band.MEDIUM ? 0.60 + r() * 0.24 : 0.22 + r() * 0.37
    const openish = status === CaseStatus.OPEN || status === CaseStatus.NEW || status === CaseStatus.PENDING
    const subjects = SUBJECTS[classId] || ['Support request']
    out.push({
      id: `HFG-${2000 + i}`,
      subject: subjects[Math.floor(r() * subjects.length)],
      class: classId,
      category: cls.cat,
      channel: weighted(r, [['email', 26], ['web', 18], ['portal', 11], ['slack', 9], ['teams', 8],
        ['voice', 8], ['api', 5], ['edi', 5], ['mobile', 3], ['sms', 3], ['walkup', 2], ['partner', 2]]),
      tier: actor.tier,
      requester: actor.id,
      team: TEAMS[Math.floor(r() * TEAMS.length)].id,
      assignee: r() > 0.14 ? pick(r, CLASS_SPECIALISTS[classId]) : null,
      status,
      created_at: new Date(created).toISOString(),
      /* When the case actually reached solved. Without it, "solved this week"
         can only mean "created this week and solved by now" — a cohort measure
         masquerading as a throughput one. */
      resolved_at: stillOpen ? null
        : new Date(created + (0.5 + r() * 3.5) * DAY).toISOString(),
      /* What the Resolution agent produced for this ticket, if anything. The
         "usable draft rate" target is measured over TICKETS — one in three
         pre-drafted usably — so it needs a per-ticket outcome, not a ratio over
         the drafts that happened to reach a decision. */
      draft_outcome: weighted(r, [
        ['approved', 27],   // drafted and approved as written
        ['edited', 13],     // drafted, edited, approved — still usable
        ['rejected', 11],   // drafted but not usable
        ['none', 49],       // escalation or no confident draft
      ]),
      // Only open work carries a live clock; solved/closed cases have none (§14C:
      // "no clock ⇒ no chip", never a fake zero).
      sla_deadline: openish
        ? new Date(NOW + (r() * 40 - 6) * HOUR).toISOString()
        : null,
      sla_paused: openish && status === CaseStatus.PENDING && r() > 0.6,
      band,
      confidence: Number(confidence.toFixed(2)),
      reopened: status === CaseStatus.OPEN && monthsBack > 0,
      csat: status === CaseStatus.CLOSED || status === CaseStatus.SOLVED
        ? weighted(r, [[5, 46], [4, 30], [3, 12], [2, 7], [1, 5]]) : null,
      qa_flagged: r() > 0.965,
    })
  }
  return out
})()

/* ---------- Narrative overrides ----------
   A handful of rows are pinned so the demo scenes are reproducible. They stay
   inside the same corpus (no lane-local data) and still count in every aggregate. */
const OVERRIDES = {
  'HFG-2214': {
    subject: 'SSO login fails since the password rotation',
    class: 'auth-sso', category: 'Identity & Access', channel: 'voice',
    tier: 'Enterprise', requester: 'act-001', team: 'team-1', assignee: null,
    status: CaseStatus.OPEN, band: Band.MEDIUM, confidence: 0.78,
    sla_deadline: new Date(NOW + 42 * 60000).toISOString(), sla_paused: false,
    created_at: new Date(NOW - 3.5 * HOUR).toISOString(), csat: null, qa_flagged: false,
  },
  // The two siblings Dedup proposes to merge into HFG-2214.
  'HFG-2231': {
    subject: 'Cannot sign in — password reset did not help',
    class: 'auth-sso', category: 'Identity & Access', channel: 'email',
    tier: 'Enterprise', requester: 'act-001', team: 'team-1', assignee: null,
    status: CaseStatus.NEW, band: Band.HIGH, confidence: 0.93,
    sla_deadline: new Date(NOW + 5.2 * HOUR).toISOString(), sla_paused: false,
    created_at: new Date(NOW - 2.1 * HOUR).toISOString(), csat: null, qa_flagged: false,
  },
  'HFG-2244': {
    subject: 'SSO broken for Payroll Ops — thread from #it-help',
    class: 'auth-sso', category: 'Identity & Access', channel: 'slack',
    tier: 'Enterprise', requester: 'act-001', team: 'team-1', assignee: null,
    status: CaseStatus.NEW, band: Band.MEDIUM, confidence: 0.71,
    sla_deadline: new Date(NOW + 6.8 * HOUR).toISOString(), sla_paused: false,
    created_at: new Date(NOW - 1.4 * HOUR).toISOString(), csat: null, qa_flagged: false,
  },
  // A low-context case: retrieval below threshold, no KB coverage for the class.
  'HFG-2308': {
    subject: 'SCIM sync dropped 40 users overnight',
    class: 'sso-scim-sync', category: 'Identity & Access', channel: 'email',
    tier: 'Enterprise', requester: 'act-014', team: 'team-1', assignee: null,
    status: CaseStatus.OPEN, band: Band.LOW, confidence: 0.41,
    sla_deadline: new Date(NOW + 1.3 * HOUR).toISOString(), sla_paused: false,
    created_at: new Date(NOW - 5 * HOUR).toISOString(), csat: null, qa_flagged: false,
  },
  // A case whose external write failed after retries — approval preserved [F-070].
  'HFG-2402': {
    subject: 'Payroll interface file rejected for Ireland',
    class: 'payroll-integrations', category: 'Payroll & HR Systems', channel: 'email',
    tier: 'Internal', requester: 'act-027', team: 'team-2', assignee: 'an-004',
    status: CaseStatus.OPEN, band: Band.HIGH, confidence: 0.88,
    sla_deadline: new Date(NOW + 9 * HOUR).toISOString(), sla_paused: false,
    created_at: new Date(NOW - 7 * HOUR).toISOString(), csat: null, qa_flagged: false,
  },
  // An escalation: no confident match, so Agent 8 guarantees a path [F-069].
  'HFG-2455': {
    subject: 'Batch record will not close on line 3 — QA blocked',
    class: 'mfg-batch-record', category: 'Manufacturing Systems', channel: 'teams',
    tier: 'Internal', requester: 'act-033', team: 'team-6', assignee: null,
    status: CaseStatus.OPEN, band: Band.LOW, confidence: 0.36,
    sla_deadline: new Date(NOW - 18 * 60000).toISOString(), sla_paused: false,
    created_at: new Date(NOW - 11 * HOUR).toISOString(), csat: null, qa_flagged: true,
  },
}
Object.entries(OVERRIDES).forEach(([id, patch]) => {
  const i = CASES.findIndex((c) => c.id === id)
  if (i >= 0) CASES[i] = { ...CASES[i], ...patch }
})

export const caseById = (id) => CASES.find((c) => c.id === id)

/* ---------- Knowledge base: 900 articles with coverage per class ---------- */
export const KB = (() => {
  const r = rng(555)
  const perClass = {}
  CLASSES.forEach((c) => {
    // Coverage is deliberately uneven — thin and gap classes are the digest's story.
    const cover = c.id === 'sso-scim-sync' ? 0 : c.id === 'payroll-integrations' ? 3
      : c.id === 'coldchain-telemetry' ? 4 : Math.floor(6 + r() * 60)
    perClass[c.id] = cover
  })
  const total = Object.values(perClass).reduce((a, b) => a + b, 0)
  // Pad to the headline 900-article corpus with general/how-to material.
  const general = 900 - total
  return { perClass, total: 900, general: Math.max(0, general) }
})()

export const kbCoverage = () => {
  let covered = 0, thin = 0, gap = 0
  CLASSES.forEach((c) => {
    const n = KB.perClass[c.id]
    if (n === 0) gap++
    else if (n < 6) thin++
    else covered++
  })
  return { covered, thin, gap, classes: CLASSES.length }
}

export const TENANT = config.demo_tenant_name
