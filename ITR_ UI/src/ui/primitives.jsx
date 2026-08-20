/* §8 · 1, 2, 5, 6 — Button, form controls, confidence indicator, chips.
   Every status pairs colour + icon + label (§7.6): colour never carries
   meaning alone anywhere in this file. */

import React from 'react'
import { CASE_STATUS_META, Band } from '../contracts/state.js'
import { config } from '../contracts/config.js'
import { slaCountdown } from '../contracts/format.js'

/* ---------------- Button ---------------- */
export function Button({
  variant = 'secondary', size, loading = false, disabled = false,
  fill = false, deniedReason, children, ...rest
}) {
  const cls = [
    'btn', `btn-${variant}`,
    size === 'lg' ? 'btn-lg' : size === 'sm' ? 'btn-sm' : '',
    fill ? 'btn-fill' : '', loading ? 'btn-loading' : '',
  ].filter(Boolean).join(' ')

  const btn = (
    <span className="btn-wrap">
      <button
        className={cls}
        disabled={disabled || loading}
        aria-disabled={disabled || loading}
        title={deniedReason || rest.title}
        {...rest}
      >
        <span className="btn-label">{children}</span>
      </button>
      {loading && <span className="btn-spinner" aria-hidden="true" />}
    </span>
  )
  if (!deniedReason) return btn
  // A disabled control must explain itself — never a mute grey box (§11.6).
  return <span title={deniedReason}>{btn}</span>
}

export const IconButton = ({ label, children, ...rest }) => (
  <button className="btn btn-ghost btn-sm" aria-label={label} title={label} {...rest}>
    <span className="btn-label">{children}</span>
  </button>
)

/* ---------------- Form controls ---------------- */
export function Field({ label, hint, error, id, children }) {
  return (
    <div className="field">
      {label && <label className="field-label" htmlFor={id}>{label}</label>}
      {children}
      {error && (
        <span className="field-msg" role="alert">
          <span aria-hidden="true">⚠</span>{error}
        </span>
      )}
      {!error && hint && <span className="field-hint">{hint}</span>}
    </div>
  )
}

export const Input = ({ invalid, ...p }) =>
  <input className={`input ${invalid ? 'input-error' : ''}`} aria-invalid={!!invalid} {...p} />

export const Textarea = ({ invalid, ...p }) =>
  <textarea className={`textarea ${invalid ? 'textarea-error' : ''}`} aria-invalid={!!invalid} {...p} />

export function Select({ options, value, onChange, label, id, allLabel = 'All', ...rest }) {
  return (
    <Field label={label} id={id}>
      <select className="select" id={id} value={value ?? ''} onChange={(e) => onChange(e.target.value)} {...rest}>
        <option value="">{allLabel}</option>
        {options.map((o) => (
          <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>
        ))}
      </select>
    </Field>
  )
}

/* ---------------- Chips (§8.6) ---------------- */
export const Chip = ({ tone = 'neutral', icon, children, title, onRemove, ...rest }) => (
  <span
    className={`chip ${tone !== 'neutral' ? `chip-${tone}` : ''} ${onRemove ? 'chip-removable' : ''}`}
    title={title} {...rest}
  >
    {icon && <span aria-hidden="true">{icon}</span>}
    {children}
    {onRemove && (
      <button className="chip-x" onClick={onRemove} aria-label={`Remove filter ${children}`}>×</button>
    )}
  </span>
)

export const StatusChip = ({ status }) => {
  const m = CASE_STATUS_META[status] || { label: status, tone: 'neutral', icon: '•' }
  return <Chip tone={m.tone} icon={m.icon}>{m.label}</Chip>
}

/** SLA chip. No clock ⇒ no chip — never a fake "0" (§14C). */
export const SlaChip = ({ deadline, paused }) => {
  const s = slaCountdown(deadline)
  if (!s) return null
  if (paused) return <Chip tone="neutral" icon="⏸" title="Clock paused — awaiting requester">Paused</Chip>
  return <Chip tone={s.tone} icon={s.breached ? '⏰' : s.tone === 'warning' ? '⚠' : '⏱'}>{s.label}</Chip>
}

export const EmulatedChip = ({ compact }) => (
  <Chip tone="emulated" icon="⌬" title="Emulated source — a high-fidelity replica, never a live tenant [F-121]">
    {compact ? 'Emul.' : 'Emulated'}
  </Chip>
)

export const ShadowChip = () => (
  <Chip tone="info" icon="◐" title="Shadow mode — recommendations only; no ticket is reassigned [F-064]">
    Shadow
  </Chip>
)

export const StretchChip = () => (
  <Chip tone="primary" icon="↗" title="Below the strength threshold for this class — development context [F-128]">
    Stretch assignment
  </Chip>
)

export const DemoChip = () => <Chip tone="demo" icon="▨">DEMO</Chip>

export const QaFlagChip = ({ detail }) => (
  <Chip tone="warning" icon="⚑" title={detail || 'Sampled by QA/Verifier'}>QA-flagged</Chip>
)

/* ---------------- Confidence indicator (§8.5) ----------------
   Numeric on hover/focus. The Low band changes behaviour wherever it renders:
   it suppresses one-click approve and expands evidence by default [P-3]. */
export function ConfidenceBand({ band, value, uncalibrated }) {
  const icon = band === Band.HIGH ? '●' : band === Band.MEDIUM ? '◐' : '○'
  // An uncalibrated output hides its numeric and shows the flag only (§11.2).
  const title = uncalibrated
    ? 'Uncalibrated output — the numeric score is withheld; only the band state is shown.'
    : `Score ${value?.toFixed(2)} · High ≥${config.confidence_bands.high} · Medium ≥${config.confidence_bands.medium}`
  return (
    <span className={`band band-${band}`} title={title} tabIndex={0}>
      <span aria-hidden="true">{icon}</span>
      {band}
      {!uncalibrated && value != null && <span className="dim num"> {value.toFixed(2)}</span>}
    </span>
  )
}

/** A one-click approve is suppressed on Low — the caller asks this, not the band. */
export const suppressesFastApprove = (band) => band === Band.LOW

/* ---------------- Scope Class banner (§1.2) ---------------- */
export const ScopeBanner = ({ scope, note, demo }) => (
  <span className={`scope-banner ${demo ? 'scope-demo' : ''}`} title="Scope Class — declared on every screen (§1.2)">
    <span aria-hidden="true">{demo ? '▨' : '◇'}</span>
    <strong>Scope:</strong> {scope}{note ? ` · ${note}` : ''}
  </span>
)

/* ---------------- Meter ---------------- */
export const Meter = ({ value, tone = '', label }) => (
  <div className="meter" role="img" aria-label={label || `${Math.round(value * 100)}%`}>
    <div className={`meter-fill ${tone}`} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
  </div>
)

/* ---------------- Drillable number (P-4) ----------------
   If a number cannot be drilled, it is decoration and does not ship. */
export const Drill = ({ onClick, title, children }) => (
  <button className="drill" onClick={onClick} title={title || 'Open the records behind this number'}>
    {children}
  </button>
)
