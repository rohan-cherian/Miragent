/* S-01 · Console shell & navigation [F-079, F-094, F-088].
   Scope Class: POC functional. Global search and the notification panel are
   change requests CR-02/CR-03 [OD-3] and sit behind config flags — they are not
   silently assumed into F-079's scope.

   Zero mutations exist in this shell: every control navigates. */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useSession } from './session.jsx'
import { config, TENANT } from '../contracts/config.js'
import { NAV, DEMO_NAV, GLOBAL_KEYS, QUEUE_KEYS } from '../contracts/routes.js'
import { Button, Chip } from '../ui/primitives.jsx'
import { Modal, SidePanel } from '../ui/overlays.jsx'
import { EmptyState } from '../ui/feedback.jsx'
import { relative, absolute } from '../contracts/format.js'
import * as api from '../mock/api.js'
import { caseById } from '../fixtures/corpus.js'
import { emit } from '../contracts/telemetry.js'

const NAV_GLYPH = {
  overview: '▤', queue: '☰', tickets: '⛁', knowledge: '▦',
  intelligence: '◈', audit: '⧉', connections: '⌬', demo: '▨',
}

/* ---------------- Breadcrumbs (§6.2) ----------------
   Always rendered; every drill-down appends; every crumb navigable. The origin
   of a drill is carried in the URL so the trail survives a deep link. */
function useCrumbs() {
  const { pathname, search } = useLocation()
  const params = new URLSearchParams(search)
  const origin = params.get('origin')

  return useMemo(() => {
    const crumbs = []
    const seg = pathname.split('/').filter(Boolean)

    const ORIGINS = {
      overview: { label: 'Overview', to: '/overview' },
      intelligence: { label: 'Weekly digest', to: '/intelligence' },
      assignment: { label: 'Analyst panel', to: '/queue' },
      audit: { label: 'Audit', to: '/audit' },
      tickets: { label: 'Tickets', to: '/tickets' },
      queue: { label: 'Queue', to: '/queue' },
      connections: { label: 'Connections', to: '/connections' },
    }
    if (origin && ORIGINS[origin]) crumbs.push(ORIGINS[origin])

    const top = {
      overview: 'Overview', queue: 'Queue', tickets: 'Tickets', knowledge: 'Knowledge',
      intelligence: 'Intelligence', audit: 'Audit', connections: 'Connections',
      case: 'Case', demo: 'Demo',
    }[seg[0]]
    if (top && !(origin && ORIGINS[origin]?.label === top)) {
      crumbs.push({ label: top, to: `/${seg[0]}` })
    }
    if (seg[0] === 'case' && seg[1]) crumbs.push({ label: seg[1], to: null })
    if (seg[0] === 'connections' && seg[1] === 'identity') crumbs.push({ label: 'Identity queue', to: null })
    if (seg[0] === 'demo') crumbs.push({ label: `Connector journey · D-${seg[2] || 1}`, to: null })

    const metric = params.get('metric')
    if (metric) crumbs.push({ label: metric, to: null })
    return crumbs
  }, [pathname, search])
}

/* ---------------- Global search (CR-02) ---------------- */
function SearchModal({ onClose }) {
  const [term, setTerm] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()

  useEffect(() => {
    if (!term.trim()) { setRes(null); return }
    let live = true
    setBusy(true)
    const t = setTimeout(() => {
      api.search(term).then((r) => { if (live) { setRes(r); setBusy(false) } })
    }, 140)
    return () => { live = false; clearTimeout(t) }
  }, [term])

  const go = (to) => { onClose(); nav(to) }

  return (
    <Modal title="Search" subtitle="Cases by ID, requester or subject · analysts · articles" onClose={onClose}>
      <input
        className="input" autoFocus placeholder="Try “okafor”, “HFG-2214”, or “SSO”"
        value={term} onChange={(e) => setTerm(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && res?.exact_case) go(`/case/${res.exact_case}`)
          else if (e.key === 'Enter' && res?.cases?.[0]) go(`/case/${res.cases[0].id}`)
        }}
        aria-label="Search the console"
      />
      <div className="search-results">
        {!term.trim() && <p className="caption" style={{ marginTop: 12 }}>Type to search. An exact case ID goes straight to Ticket 360.</p>}
        {busy && <p className="caption" style={{ marginTop: 12 }}>Searching…</p>}
        {res && !busy && !res.cases.length && !res.analysts.length && !res.articles.length && (
          <EmptyState icon="∅" title={`No matches for “${term}”`}
                      message="Try a case ID (HFG-####), a requester surname, or a class name." />
        )}
        {res?.exact_case && (
          <>
            <div className="search-group-label">Exact case</div>
            <button className="search-row active" onClick={() => go(`/case/${res.exact_case}`)}>
              <Chip tone="primary" icon="→">{res.exact_case}</Chip>
              <span className="grow truncate">{caseById(res.exact_case)?.subject}</span>
              <span className="meta">Enter</span>
            </button>
          </>
        )}
        {!!res?.cases.length && (
          <>
            <div className="search-group-label">Cases</div>
            {res.cases.map((c) => (
              <button key={c.id} className="search-row" onClick={() => go(`/case/${c.id}`)}>
                <span className="mono caption">{c.id}</span>
                <span className="grow truncate">{c.subject}</span>
                <Chip>{c.class}</Chip>
              </button>
            ))}
          </>
        )}
        {!!res?.analysts.length && (
          <>
            <div className="search-group-label">Analysts</div>
            {res.analysts.map((a) => (
              <button key={a.id} className="search-row"
                      onClick={() => go(`/tickets?assignee=${a.id}&origin=tickets&metric=${encodeURIComponent(a.name)}`)}>
                <span className="grow">{a.name}</span>
                <Chip>{a.level}</Chip>
              </button>
            ))}
          </>
        )}
        {!!res?.articles.length && (
          <>
            <div className="search-group-label">Articles</div>
            {res.articles.map((d) => (
              <button key={d.id} className="search-row" onClick={() => go(`/knowledge?draft=${d.id}`)}>
                <span className="grow truncate">{d.title}</span>
                <Chip tone="info">draft</Chip>
              </button>
            ))}
          </>
        )}
      </div>
    </Modal>
  )
}

/* ---------------- Notification panel (CR-03, §10.15) ---------------- */
function NotificationPanel({ onClose, items, onRead }) {
  const nav = useNavigate()
  const groups = [
    { key: 'action', label: 'Action needed' },
    { key: 'outcome', label: 'Outcome' },
    { key: 'digest', label: 'Digest ready' },
  ]
  const open = (n) => {
    onRead(n.id)
    onClose()
    nav(n.link)
  }
  return (
    <SidePanel
      title="Notifications"
      subtitle="In-app only for the POC [A-03]"
      onClose={onClose}
      footer={<Link className="btn btn-secondary" to="/audit" onClick={onClose}>Open Audit</Link>}
    >
      <div className="row">
        <span className="caption grow">{items.filter((i) => !i.read).length} unread</span>
        <Button variant="ghost" size="sm" onClick={() => onRead('all')}>Mark all read</Button>
      </div>
      {!items.length && <EmptyState icon="✓" title="You're caught up" message="Nothing needs you right now." />}
      {groups.map((g) => {
        const rows = items.filter((i) => i.class === g.key)
        if (!rows.length) return null
        return (
          <section key={g.key}>
            <div className="notif-group-label">{g.label}</div>
            {rows.map((n) => (
              <button key={n.id} className={`notif-item ${!n.read ? 'notif-unread' : ''}`} onClick={() => open(n)}>
                <span className={`notif-dot ${n.sticky ? 'sticky' : ''}`} aria-hidden="true"
                      style={{ visibility: n.read ? 'hidden' : 'visible' }} />
                <span className="grow">
                  {n.text}
                  {!n.read && <span className="sr-only"> (unread)</span>}
                  <span className="meta" style={{ display: 'block' }} title={absolute(n.ts)}>{relative(n.ts)}</span>
                  {n.sticky && (
                    <span className="meta" style={{ display: 'block', color: 'var(--danger-700)' }}>
                      Stays until the write leaves the failed state — a failure is not dismissable by reading.
                    </span>
                  )}
                </span>
              </button>
            ))}
          </section>
        )
      })}
    </SidePanel>
  )
}

/* ---------------- Shortcut overlay (?) ---------------- */
const ShortcutOverlay = ({ onClose }) => (
  <Modal title="Keyboard shortcuts" subtitle="Every action in the console is reachable without a pointer" onClose={onClose} wide>
    <div className="shortcut-grid">
      <div>
        <div className="search-group-label">Global</div>
        {GLOBAL_KEYS.map((k) => (
          <div className="shortcut-row" key={k.keys}>
            <span className="keys"><span className="kbd">{k.keys}</span></span>
            <span>{k.action}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="search-group-label">Approval queue (S-04)</div>
        {QUEUE_KEYS.map((k) => (
          <div className="shortcut-row" key={k.keys}>
            <span className="keys"><span className="kbd">{k.keys}</span></span>
            <span>{k.action}</span>
          </div>
        ))}
      </div>
    </div>
  </Modal>
)

/* ---------------- Shell ---------------- */
export default function Shell({ children }) {
  const { role, meta, signOut } = useSession()
  const nav = useNavigate()
  const loc = useLocation()
  const crumbs = useCrumbs()

  const [searchOpen, setSearchOpen] = useState(false)
  const [notifOpen, setNotifOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [notifs, setNotifs] = useState([])
  const [rail, setRail] = useState(() => window.innerWidth < 1440)
  const chord = useRef(null)

  useEffect(() => {
    if (!config.flags.CR_03_notifications || !role) return
    // A notification read that fails must not take the shell down with it —
    // the bell degrades to empty and the screen underneath keeps working.
    api.listNotifications(role).then(setNotifs).catch(() => setNotifs([]))
  }, [role])

  useEffect(() => {
    const onResize = () => setRail(window.innerWidth < 1440)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const markRead = useCallback((id) => {
    setNotifs((prev) => prev.map((n) =>
      (id === 'all' ? (n.sticky ? n : { ...n, read: true }) : (n.id === id && !n.sticky ? { ...n, read: true } : n))
    ))
  }, [])

  /* Global keyboard map (§6.2). Chords: `g` then a destination key. */
  useEffect(() => {
    const onKey = (e) => {
      const tag = document.activeElement?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || document.activeElement?.isContentEditable
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        if (config.flags.CR_02_global_search) setSearchOpen(true)
        return
      }
      if (typing) return
      if (e.key === '?') { e.preventDefault(); setHelpOpen(true); return }
      if (e.key === 'Escape') { setSearchOpen(false); setNotifOpen(false); setHelpOpen(false); setMenuOpen(false); return }
      if (e.key === 'g') { chord.current = 'g'; setTimeout(() => { chord.current = null }, 1200); return }
      if (chord.current === 'g') {
        const to = { q: '/queue', d: '/overview', a: '/audit', i: '/intelligence', t: '/tickets', c: '/connections' }[e.key]
        chord.current = null
        if (to) { e.preventDefault(); emit('screen_load', { via: 'chord', to }); nav(to) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nav])

  const unread = notifs.filter((n) => !n.read).length
  const navItems = NAV.filter((n) => n.roles.includes(role))
  const demoItems = DEMO_NAV.filter((n) => n.roles.includes(role))

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <div className="viewport-warning" role="status">
        This console is desktop-first and unsupported below 1280px [OD-7]. Layout may clip.
      </div>

      <header className="topbar">
        <Link to={meta?.home || '/overview'} className="brand" style={{ color: 'inherit', textDecoration: 'none' }}>
          <span className="brand-mark" aria-hidden="true">IT</span>
          <span className="brand-name">Motiveminds <span className="muted">ITR</span></span>
        </Link>

        {/* Non-dismissable emulation honesty chip [F-121, P-5] */}
        <span className="tenant-chip" title="Every source in this console is a high-fidelity emulator. No live tenant is connected.">
          <span aria-hidden="true">⌬</span>
          {TENANT}
          <span className="sep" aria-hidden="true">·</span>
          Synthetic data
        </span>

        <div className="grow" />

        {config.flags.CR_02_global_search && (
          <button className="search-trigger" onClick={() => setSearchOpen(true)}>
            <span aria-hidden="true">⌕</span>
            <span className="grow">Search cases, analysts, articles</span>
            <span className="kbd">⌘K</span>
          </button>
        )}

        {config.flags.CR_03_notifications && (
          <span className="bell">
            <Button variant="ghost" onClick={() => setNotifOpen(true)}
                    aria-label={`Notifications, ${unread} unread`}>🔔</Button>
            {unread > 0 && <span className="bell-badge" aria-hidden="true">{unread > 9 ? '9+' : unread}</span>}
          </span>
        )}

        <span className="user-menu-wrap">
          <Button variant="ghost" onClick={() => setMenuOpen((v) => !v)} aria-expanded={menuOpen} aria-haspopup="menu">
            {meta?.stubUser} <span className="dim">· {meta?.name}</span>
          </Button>
          {menuOpen && (
            <div className="user-menu" role="menu">
              <div className="caption" style={{ padding: 'var(--sp-2) var(--sp-3)' }}>
                Signed in as <strong>{meta?.stubFull}</strong><br />
                Stub authentication — POC. Audit rows attribute to this user.
              </div>
              <div className="hr" />
              <div className="caption" style={{ padding: '0 var(--sp-3) var(--sp-2)' }}>
                Timezone: {config.tenant_timezone} (tenant default) [OD-6]
              </div>
              <button className="menu-item" role="menuitem" onClick={() => { setMenuOpen(false); nav('/login?switch=1') }}>
                Switch role
              </button>
              <button className="menu-item" role="menuitem" onClick={() => { setMenuOpen(false); setHelpOpen(true) }}>
                Keyboard shortcuts <span className="kbd">?</span>
              </button>
              <button className="menu-item" role="menuitem" onClick={() => { signOut(); nav('/login') }}>
                Sign out
              </button>
              {/* No tenant switcher exists anywhere [§1.4]. */}
            </div>
          )}
        </span>
      </header>

      <div className="shell-body">
        <nav className={`nav ${rail ? '' : ''}`} aria-label="Primary">
          <div className="nav-section">Console</div>
          {navItems.map((n) => (
            <NavLink key={n.key} to={n.path} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <span className="nav-glyph" aria-hidden="true">{NAV_GLYPH[n.key]}</span>
              <span>
                {n.label}
                <span className="nav-hint">{n.hint}</span>
              </span>
            </NavLink>
          ))}

          {/* The demo lane is visually fenced and role-gated (§6.1, §11.6). */}
          {demoItems.length > 0 && (
            <>
              <div className="nav-demo-head">▨ DEMO — not part of the product</div>
              {demoItems.map((n) => (
                <NavLink key={n.key} to={n.path} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
                  <span className="nav-glyph" aria-hidden="true">{NAV_GLYPH.demo}</span>
                  <span>{n.label}<span className="nav-hint">{n.hint}</span></span>
                </NavLink>
              ))}
            </>
          )}

          <div className="hr" />
          <div className="caption" style={{ padding: '0 var(--sp-3)' }}>
            Nav is RBAC-conditional [F-094]. Surfaces your role cannot use are hidden here, not greyed out.
          </div>
        </nav>

        <div className="main">
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.length === 0 && <span className="current">Console</span>}
            {crumbs.map((c, i) => (
              <React.Fragment key={`${c.label}-${i}`}>
                {i > 0 && <span aria-hidden="true">›</span>}
                {c.to && i < crumbs.length - 1
                  ? <Link to={c.to}>{c.label}</Link>
                  : <span className="current" aria-current="page">{c.label}</span>}
              </React.Fragment>
            ))}
            <span className="right meta">
              {loc.pathname}{loc.search}
            </span>
          </nav>

          <main className="scroller" id="main-content" tabIndex={-1}>
            {children}
          </main>
        </div>
      </div>

      {searchOpen && <SearchModal onClose={() => setSearchOpen(false)} />}
      {notifOpen && <NotificationPanel onClose={() => setNotifOpen(false)} items={notifs} onRead={markRead} />}
      {helpOpen && <ShortcutOverlay onClose={() => setHelpOpen(false)} />}
    </div>
  )
}
