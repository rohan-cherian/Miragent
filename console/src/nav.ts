/** Nav items for the twelve demo screens (empty shells for now). */
export type NavItem = {
  to: string
  label: string
  scene?: string
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/connections', label: 'Connections', scene: 'Scene 1' },
  { to: '/corpus', label: 'Corpus', scene: 'Scene 1' },
  { to: '/ticket-360', label: 'Ticket 360', scene: 'Scene 2' },
  { to: '/context', label: 'Context & citations', scene: 'Scene 3' },
  { to: '/explainers', label: 'Explainers', scene: 'Scene 3' },
  { to: '/recommendation', label: 'Analyst recommendation', scene: 'Scene 4' },
  { to: '/call-player', label: 'Call player', scene: 'Scene 5' },
  { to: '/approvals', label: 'Approval queue', scene: 'Scene 6' },
  { to: '/audit', label: 'Audit viewer', scene: 'Scene 7' },
  { to: '/kb-review', label: 'KB review', scene: 'Scene 7' },
  { to: '/digest', label: 'Weekly digest', scene: 'Scene 8' },
  { to: '/home', label: 'Overview', scene: 'Shell' },
]
