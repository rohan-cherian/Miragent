/* Shared formatters — Spec §11.9. One implementation, or six lanes format dates
   six ways. Timestamps are ISO-8601 UTC; display is tenant timezone [A-14]. */

import { config } from './config.js'

const TZ = config.tenant_timezone

const dtf = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric',
  hour: '2-digit', minute: '2-digit', hour12: false,
})
const tf = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false,
})
const df = new Intl.DateTimeFormat('en-GB', {
  timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric',
})

/** Absolute timestamp — audit surfaces always use this, never relative alone. */
export const absolute = (iso) =>
  `${dtf.format(new Date(iso))} ${config.tenant_timezone_label}`

export const timeOnly = (iso) => tf.format(new Date(iso))
export const dateOnly = (iso) => df.format(new Date(iso))

/** Relative time. Always paired with `absolute()` in a title attribute (§11.9). */
export function relative(iso, now = Date.now()) {
  const diff = now - new Date(iso).getTime()
  const abs = Math.abs(diff)
  const m = Math.round(abs / 60000)
  const suffix = diff >= 0 ? 'ago' : 'from now'
  if (abs < 45000) return 'just now'
  if (m < 60) return `${m}m ${suffix}`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ${suffix}`
  const d = Math.round(h / 24)
  if (d < 7) return `${d}d ${suffix}`
  const w = Math.round(d / 7)
  if (w < 5) return `${w}w ${suffix}`
  return dateOnly(iso)
}

/** SLA countdown. No clock ⇒ no chip. Never renders "0" as a stand-in (§14C). */
export function slaCountdown(deadlineIso, now = Date.now()) {
  if (!deadlineIso) return null
  const ms = new Date(deadlineIso).getTime() - now
  const breached = ms <= 0
  const mins = Math.round(Math.abs(ms) / 60000)
  const text = mins < 60
    ? `${mins}m`
    : mins < 1440 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${Math.floor(mins / 1440)}d`
  return {
    breached,
    minutes: breached ? -mins : mins,
    // amber inside 2h, per the deterministic prioritisation policy (§10.7)
    tone: breached ? 'danger' : mins <= 120 ? 'warning' : 'success',
    label: breached ? `Breached ${text} ago` : `Breach in ${text}`,
  }
}

/** Age of a case, list-column form. */
export function age(iso, now = Date.now()) {
  const h = (now - new Date(iso).getTime()) / 3600000
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`
  if (h < 48) return `${Math.round(h)}h`
  return `${Math.round(h / 24)}d`
}

export const num = (n) => (n ?? 0).toLocaleString('en-GB')
export const pct = (n, digits = 0) => `${(n * 100).toFixed(digits)}%`
export const score = (n) => (n == null ? '—' : n.toFixed(2))
export const ms = (n) => (n < 1000 ? `${n}ms` : `${(n / 1000).toFixed(1)}s`)

/** Delta with an explicit sign — colour never carries the meaning alone (§7.6). */
export function delta(n, unit = '') {
  if (n === 0 || n == null) return { text: 'no change', dir: 'flat', icon: '→' }
  const up = n > 0
  return {
    text: `${up ? '+' : '−'}${Math.abs(n)}${unit}`,
    dir: up ? 'up' : 'down',
    icon: up ? '↑' : '↓',
  }
}
