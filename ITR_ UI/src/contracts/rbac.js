/* RBAC contract — Spec §11.6. Persona is a design lens; ROLE is the contract.
   Three deliberate treatments: hidden in nav · disabled-with-explanation at
   action level · permission-denied state on deep link. */

export const Role = { ANALYST: 'analyst', MANAGER: 'manager', ADMIN: 'admin', DEMO: 'demo' }

export const ROLES = [
  {
    id: Role.ANALYST,
    name: 'Analyst',
    stubUser: 'P. Nair',
    stubFull: 'Priya Nair · L2 Analyst',
    description: 'Works the approval queue. Approves, edits and rejects drafted resolutions.',
    home: '/queue',
  },
  {
    id: Role.MANAGER,
    name: 'Manager',
    stubUser: 'M. Adeyemi',
    stubFull: 'Marcus Adeyemi · Support Director',
    description: 'Runs the operation. Reads the digest, the dashboard and the audit trail — decides nothing per-ticket.',
    home: '/overview',
  },
  {
    id: Role.ADMIN,
    name: 'Admin',
    stubUser: 'S. Rao',
    stubFull: 'Sutej Rao · Platform Admin',
    description: 'Owns connections, ingestion completeness, identity resolution and audit export.',
    home: '/connections',
  },
  {
    id: Role.DEMO,
    name: 'Demo',
    stubUser: 'Demo presenter',
    stubFull: 'Demo presenter',
    description: 'Presenter role. Sees the fenced demo swim lane and the Replay control — no product persona can.',
    home: '/demo/connect/1',
  },
]

export const roleMeta = (id) => ROLES.find((r) => r.id === id) || ROLES[0]

/* V = view · A = act · d = disabled with explanation · '-' = hidden.
   Verbatim from the §11.6 matrix — do not widen a cell without a changelog entry. */
export const PERMISSIONS = {
  'queue.view':            { analyst: 'V', manager: 'V', admin: 'V', demo: 'V' },
  'resolution.decide':     { analyst: 'A', manager: 'd', admin: 'd', demo: 'A' },
  'merge.confirm':         { analyst: 'A', manager: 'd', admin: 'd', demo: 'A' },
  'assignment.feedback':   { analyst: 'A', manager: 'A', admin: 'd', demo: 'A' },
  'identity.detail.view':  { analyst: 'V', manager: 'V', admin: 'V', demo: 'V' },
  'identity.resolve':      { analyst: '-', manager: '-', admin: 'A', demo: 'A' },
  'kb.draft.decide':       { analyst: 'A', manager: 'd', admin: 'd', demo: 'A' },
  'audit.view':            { analyst: 'V-own', manager: 'V', admin: 'V', demo: 'V' },
  'audit.export':          { analyst: '-', manager: '-', admin: 'A', demo: '-' },
  'reconciliation.rerun':  { analyst: '-', manager: '-', admin: 'A', demo: 'A' },
  'presenter.replay':      { analyst: '-', manager: '-', admin: '-', demo: 'A' },
  'demo.lane':             { analyst: '-', manager: '-', admin: '-', demo: 'A' },
}

/* The reason strings a disabled control must show — generic copy is prohibited (§11.8). */
export const DENY_REASON = {
  'resolution.decide': 'Only the Analyst role decides resolutions. You are viewing this queue read-only.',
  'merge.confirm':     'Merge confirmation is an Analyst action. You can review the proposal, not commit it.',
  'assignment.feedback': 'Assignment feedback is recorded by Analyst and Manager roles.',
  'kb.draft.decide':   'KB draft decisions are an Analyst/KB-owner action.',
  'identity.resolve':  'Identity resolution is an Admin action.',
  'audit.export':      'Audit export is restricted to the Admin role [A-07].',
  'reconciliation.rerun': 'Re-running reconciliation is an Admin action.',
}

export function permission(role, action) {
  const row = PERMISSIONS[action]
  if (!row) return '-'
  return row[role] ?? '-'
}
export const canAct     = (role, action) => permission(role, action) === 'A'
export const isDisabled = (role, action) => permission(role, action) === 'd'
export const canView    = (role, action) => {
  const p = permission(role, action)
  return p === 'V' || p === 'A' || p === 'd' || p === 'V-own'
}
export const isHidden   = (role, action) => permission(role, action) === '-'

/* Which role a hidden surface would require — the denied state must NAME it (§11.6). */
export function requiredRoles(action) {
  const row = PERMISSIONS[action] || {}
  return Object.entries(row)
    .filter(([, v]) => v === 'A' || v === 'V')
    .map(([r]) => roleMeta(r).name)
}
