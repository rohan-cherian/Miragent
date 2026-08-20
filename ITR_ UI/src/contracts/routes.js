/* Route registry — Spec §6.3, verbatim. Cross-screen navigation happens BY ROUTE,
   never by importing another screen's components. Panel-capable screens take
   their params as URL state so a deep link restores the exact screen state. */

export const ROUTES = {
  login:       { id: 'S-14', path: '/login',            params: ['next'] },
  connections: { id: 'S-02', path: '/connections',      params: ['system'] },
  identity:    { id: 'S-02', path: '/connections/identity', params: ['actor'] },
  overview:    { id: 'S-03', path: '/overview',         params: ['period'] },
  queue:       { id: 'S-04', path: '/queue',            params: ['type', 'class', 'risk', 'band', 'team', 'sort', 'item'] },
  case:        { id: 'S-05', path: '/case/:id',         params: ['tab', 'entry', 'play', 't'] },
  audit:       { id: 'S-09', path: '/audit',            params: ['from', 'to', 'type', 'actor', 'outcome', 'flagged', 'row'] },
  knowledge:   { id: 'S-10', path: '/knowledge',        params: ['tab', 'draft'] },
  intelligence:{ id: 'S-11', path: '/intelligence',     params: ['week'] },
  tickets:     { id: 'S-13', path: '/tickets',          params: ['status', 'class', 'channel', 'tier', 'team', 'assignee', 'risk', 'band', 'from', 'to', 'panel', 'origin'] },
  demo:        { id: '§12',  path: '/demo/connect/:step', params: [] },
}

export const casePath = (id, params = {}) => {
  const q = new URLSearchParams(params).toString()
  return `/case/${id}${q ? `?${q}` : ''}`
}

/** Every drill-down keeps its origin so the breadcrumb can walk back (§5.4). */
export const ticketsPath = (filters = {}, { panel = false, origin } = {}) => {
  const q = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => { if (v != null && v !== '') q.set(k, v) })
  if (panel) q.set('panel', '1')
  if (origin) q.set('origin', origin)
  const s = q.toString()
  return `/tickets${s ? `?${s}` : ''}`
}

/* Level-1 IA (§6.1). `perm` maps an item to its RBAC action; `roles` narrows
   further where the nav item itself is role-scoped. */
export const NAV = [
  { key: 'overview',     label: 'Overview',    path: '/overview',     hint: 'Corpus dashboard',   screen: 'S-03', roles: ['analyst', 'manager', 'admin', 'demo'] },
  { key: 'queue',        label: 'Queue',       path: '/queue',        hint: 'Approval queue',     screen: 'S-04', roles: ['analyst', 'manager', 'admin', 'demo'] },
  { key: 'tickets',      label: 'Tickets',     path: '/tickets',      hint: 'List & search',      screen: 'S-13', roles: ['analyst', 'manager', 'admin', 'demo'] },
  { key: 'knowledge',    label: 'Knowledge',   path: '/knowledge',    hint: 'KB draft review',    screen: 'S-10', roles: ['analyst', 'manager', 'admin', 'demo'] },
  { key: 'intelligence', label: 'Intelligence',path: '/intelligence', hint: 'Weekly digest',      screen: 'S-11', roles: ['analyst', 'manager', 'admin', 'demo'] },
  { key: 'audit',        label: 'Audit',       path: '/audit',        hint: 'Decision audit',     screen: 'S-09', roles: ['analyst', 'manager', 'admin', 'demo'] },
  { key: 'connections',  label: 'Connections', path: '/connections',  hint: 'Six emulated systems', screen: 'S-02', roles: ['admin', 'demo', 'manager'] },
]

export const DEMO_NAV = [
  { key: 'demo', label: 'Connector journey', path: '/demo/connect/1', hint: 'D-1 … D-4', screen: '§12', roles: ['demo'] },
]

/* Global keyboard map (§6.2). Queue-local keys live with S-04. */
export const GLOBAL_KEYS = [
  { keys: '⌘K / Ctrl-K', action: 'Global search' },
  { keys: 'g then q',    action: 'Go to Queue' },
  { keys: 'g then d',    action: 'Go to Dashboard' },
  { keys: 'g then a',    action: 'Go to Audit' },
  { keys: 'g then i',    action: 'Go to Intelligence (digest)' },
  { keys: 'g then t',    action: 'Go to Tickets' },
  { keys: 'Esc',         action: 'Close the topmost panel' },
  { keys: '?',           action: 'This shortcut overlay' },
]

export const QUEUE_KEYS = [
  { keys: 'J / K',   action: 'Next / previous item' },
  { keys: 'Enter',   action: 'Open detail' },
  { keys: 'A',       action: 'Approve (High/Medium band only)' },
  { keys: 'E',       action: 'Edit draft' },
  { keys: 'R',       action: 'Reject (reason mandatory)' },
  { keys: 'M',       action: 'Confirm-merge dialog' },
  { keys: 'X',       action: 'Expand evidence' },
  { keys: 'O',       action: 'Open Ticket 360 panel' },
  { keys: 'C',       action: 'Open citations panel' },
  { keys: '⌘Enter',  action: 'Commit in editor / modal' },
]
