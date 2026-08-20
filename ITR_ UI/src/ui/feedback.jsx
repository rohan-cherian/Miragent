/* §8 · 11, 12, 8 — Empty / error / denied states, skeletons, toasts.
   Every route and panel ships all three of empty, loading and error (§11.5).
   Generic "something went wrong" copy is prohibited (§11.8): an error names the
   failing dependency, the retry action, and a trace reference. */

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from './primitives.jsx'
import { config } from '../contracts/config.js'
import { requiredRoles } from '../contracts/rbac.js'

/* ---------------- Empty (§8.11): icon + one-line cause + one action ---------------- */
export const EmptyState = ({ icon = '◌', title, message, action }) => (
  <div className="state-block">
    <span className="state-icon" aria-hidden="true">{icon}</span>
    <span className="state-title">{title}</span>
    {message && <span className="state-msg">{message}</span>}
    {action}
  </div>
)

/* ---------------- Error: names the dependency, offers retry, shows trace ---------------- */
export const ErrorState = ({ dependency = 'Console API', message, traceId, onRetry }) => (
  <div className="state-block" role="alert">
    <span className="state-icon" aria-hidden="true">⚠</span>
    <span className="state-title">{dependency} unreachable</span>
    <span className="state-msg">
      {message || `The console could not reach ${dependency}. Your input is preserved.`}
    </span>
    {onRetry && <Button variant="secondary" onClick={onRetry}>Retry</Button>}
    {traceId && <span className="state-trace">trace {traceId} — quote this to support</span>}
  </div>
)

/* ---------------- Permission denied (§11.6): names the required role ---------------- */
export const DeniedState = ({ action, roleName, home = '/overview' }) => {
  const needed = requiredRoles(action)
  return (
    <div className="state-block" role="alert">
      <span className="state-icon" aria-hidden="true">🔒</span>
      <span className="state-title">You do not have access to this surface</span>
      <span className="state-msg">
        The <strong>{roleName}</strong> role cannot open this screen.
        {needed.length > 0 && <> It requires the <strong>{needed.join(' or ')}</strong> role.</>}
        {' '}The auth stub never silently upgrades a role.
      </span>
      <Link className="btn btn-secondary" to={home}>Back to my home screen</Link>
    </div>
  )
}

export const NotFoundState = ({ what = 'Record', backTo = '/overview' }) => (
  <div className="state-block">
    <span className="state-icon" aria-hidden="true">∅</span>
    <span className="state-title">{what} unavailable</span>
    <span className="state-msg">This record is not in the corpus. It may have been merged into another case.</span>
    <Link className="btn btn-secondary" to={backTo}>Back</Link>
  </div>
)

/* ---------------- Skeletons (§8.12) ---------------- */
export const SkeletonRows = ({ rows = 6 }) => (
  <div aria-hidden="true">
    {Array.from({ length: rows }).map((_, i) => <div key={i} className="skel skel-row" />)}
  </div>
)
export const SkeletonBlock = ({ lines = 3, width = '100%' }) => (
  <div aria-hidden="true" style={{ width }}>
    {Array.from({ length: lines }).map((_, i) => (
      <div key={i} className="skel skel-line" style={{ width: i === lines - 1 ? '62%' : '100%' }} />
    ))}
  </div>
)

/** Past the NFR budget, a skeleton degrades to an honest notice — never an
    indefinite spinner (§11.5). */
export function LoadingWithBudget({ budgetMs = config.budgets_ms.honest_delay_notice, label = 'Loading', children }) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const t0 = Date.now()
    const id = setInterval(() => setElapsed(Date.now() - t0), 250)
    return () => clearInterval(id)
  }, [])
  return (
    <div className="stack gap-3">
      {elapsed > budgetMs && (
        <div className="honest-delay" role="status">
          <span aria-hidden="true">⏳</span>
          {label} is slower than usual — {(elapsed / 1000).toFixed(1)}s against a {(budgetMs / 1000).toFixed(0)}s budget.
          Nothing is lost; this is a real wait, not a stuck screen.
        </div>
      )}
      {children}
    </div>
  )
}

/* ---------------- Toast (§8.8) ----------------
   Outcome only. Error toasts persist until dismissed and name the retry state. */
const ToastCtx = createContext({ push: () => {} })
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])

  const push = useCallback((toast) => {
    const id = Math.random().toString(36).slice(2)
    setItems((prev) => [...prev, { id, tone: 'info', ...toast }])
    if (toast.tone !== 'error') {
      setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), toast.duration || 6000)
    }
    return id
  }, [])

  const dismiss = (id) => setItems((prev) => prev.filter((t) => t.id !== id))

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="toast-rail" aria-live="polite" aria-atomic="false">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`} role={t.tone === 'error' ? 'alert' : 'status'}>
            <span aria-hidden="true">
              {t.tone === 'success' ? '✓' : t.tone === 'error' ? '✕' : t.tone === 'warning' ? '⚠' : 'ℹ'}
            </span>
            <div className="grow">
              <div>{t.text}</div>
              {t.link && (
                <div style={{ marginTop: 4 }}>
                  <Link to={t.link} onClick={() => dismiss(t.id)}>{t.linkLabel || 'Open audit row'}</Link>
                </div>
              )}
            </div>
            <button className="chip-x" onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

/* ---------------- Inline notice ---------------- */
export const Notice = ({ tone = 'info', icon, title, children, action }) => (
  <div className={`notice notice-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
    <span aria-hidden="true">{icon || (tone === 'warning' ? '⚠' : tone === 'danger' ? '✕' : tone === 'success' ? '✓' : 'ℹ')}</span>
    <div className="grow">
      {title && <div><strong>{title}</strong></div>}
      <div>{children}</div>
    </div>
    {action}
  </div>
)
