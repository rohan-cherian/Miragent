/* §8 · 3, 4, 10, 15 — Table, evidence card, timeline, diff view (+ KPI tile).
   The evidence card is the signature component: its body STRUCTURALLY refuses to
   render without a source reference [P-2, F-083]. */

import React, { useRef, useState } from 'react'
import { EmulatedChip, Chip, Drill } from './primitives.jsx'
import { absolute, relative, num, delta as fmtDelta } from '../contracts/format.js'
import { systemName } from '../fixtures/corpus.js'

/* ---------------- Table (§8.3) ----------------
   Sticky header, tabular numerals, aria-sort, J/K row focus, selected-row wash. */
export function Table({
  columns, rows, rowKey = (r) => r.id, onRowClick, selectedKey,
  sort, onSort, footer, emptyState, ariaLabel, focusIndex,
}) {
  const bodyRef = useRef(null)
  if (!rows.length && emptyState) return emptyState

  return (
    <div className="tbl-wrap">
      <div className="tbl-scroll">
        <table className="tbl" aria-label={ariaLabel}>
          <thead>
            <tr>
              {columns.map((c) => {
                const active = sort === c.key
                return (
                  <th
                    key={c.key}
                    style={c.width ? { width: c.width } : undefined}
                    className={c.numeric ? 'num-cell' : ''}
                    aria-sort={c.sortable ? (active ? 'ascending' : 'none') : undefined}
                    onClick={c.sortable && onSort ? () => onSort(c.key) : undefined}
                  >
                    {c.label}{c.sortable && <span aria-hidden="true">{active ? ' ↑' : ' ⇅'}</span>}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody ref={bodyRef}>
            {rows.map((r, i) => {
              const k = rowKey(r)
              return (
                <tr
                  key={k}
                  className={[
                    onRowClick ? 'clickable' : '',
                    selectedKey === k ? 'selected' : '',
                    focusIndex === i ? 'focused' : '',
                  ].filter(Boolean).join(' ')}
                  onClick={onRowClick ? () => onRowClick(r) : undefined}
                  tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(r) } : undefined}
                  aria-selected={selectedKey === k || undefined}
                >
                  {columns.map((c) => (
                    <td key={c.key} className={c.numeric ? 'num-cell' : ''}>{c.render(r, i)}</td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {footer && <div className="tbl-foot">{footer}</div>}
    </div>
  )
}

/* ---------------- Evidence card (§8.4) ---------------- */
export function EvidenceCard({ card, focused, onOpen, expandedByDefault }) {
  const [expanded, setExpanded] = useState(!!expandedByDefault)

  /* Structural rule (P-2): no source reference ⇒ no body. This is the whole
     point of the component — a card that cannot cite renders as unavailable. */
  const hasSource = !!(card.source_system && card.object_id)
  const unavailable = !hasSource || card.access_status !== 'ok' || !card.excerpt

  return (
    <article
      className={`ev-card ${focused ? 'is-focused' : ''} ${unavailable ? 'ev-unavailable' : ''}`}
      id={`ev-card-${card.n}`}
      tabIndex={-1}
      aria-label={`Evidence ${card.n} from ${systemName(card.source_system)}`}
    >
      <div className="ev-head">
        <span className="ev-n">{card.n}</span>
        <strong style={{ fontSize: 'var(--fs-table)' }}>{systemName(card.source_system)}</strong>
        <EmulatedChip compact />
        {card.learned && (
          <Chip tone="primary" icon="↺" title="A prior resolution being cited back — the compounding loop [F-078]">
            learned
          </Chip>
        )}
        {card.runbook && <Chip tone="info" icon="▤">Runbook {card.runbook}</Chip>}
        {card.stale && <Chip tone="warning" icon="⧗" title="Provenance is older than the pack compile time">stale</Chip>}
        {card.redacted && <Chip tone="neutral" icon="▒" title="PII redaction applied before the model saw this">redacted</Chip>}
        {card.relevance != null && (
          <span className="right meta num" title="Relevance produced by retrieval [F-050]">rel {card.relevance.toFixed(2)}</span>
        )}
      </div>

      {unavailable ? (
        <div className="ev-body muted">
          <strong>Evidence unavailable.</strong>{' '}
          {card.access_status === 'restricted'
            ? 'This item exists but the trust filter removed its content for your context. Any draft sentence depending on it is withheld — the system fails safe rather than guessing.'
            : 'No resolvable source reference. The card refuses to render a body without one.'}
        </div>
      ) : (
        <>
          <div className={`ev-body ${expanded ? '' : 'clamped'}`}>
            {renderRedacted(card.excerpt)}
          </div>
          <button className="btn btn-ghost btn-sm" style={{ marginTop: 4 }}
                  onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        </>
      )}

      <div className="ev-prov">
        <span>{card.source_type}</span>
        <span aria-hidden="true">·</span>
        <span className="mono">{card.object_id}</span>
        <span aria-hidden="true">·</span>
        <time dateTime={card.source_ts} title={absolute(card.source_ts)}>{relative(card.source_ts)}</time>
        {onOpen && !unavailable && (
          <button className="drill right" onClick={() => onOpen(card)}>Open source →</button>
        )}
      </div>
    </article>
  )
}

/** PII tokens render as labelled chips and are never reversible client-side. */
function renderRedacted(text) {
  const parts = String(text).split(/(⟨[^⟩]+⟩)/g)
  return parts.map((p, i) =>
    p.startsWith('⟨')
      ? <span key={i} className="redact-chip" title="Redacted personal data" aria-label="redacted personal data">{p}</span>
      : <React.Fragment key={i}>{p}</React.Fragment>
  )
}

/* ---------------- Timeline (§8.10) ----------------
   `immutable` is the audit variant: no hover-edit affordance exists at all. */
export function Timeline({ entries, immutable, renderExtra }) {
  return (
    <div className="timeline">
      {entries.map((e, i) => (
        <article className="tl-entry" key={e.id || i}>
          <span className={`tl-dot t-${e.type}`} aria-hidden="true" />
          <div className="tl-head">
            <span className="tl-type">{e.type}</span>
            {e.author && <span className="strong" style={{ fontSize: 'var(--fs-table)' }}>{e.author}</span>}
            {e.channel && e.channel !== 'system' && <Chip>{e.channel}</Chip>}
            <time className="meta right" dateTime={e.ts} title={absolute(e.ts)}>
              {immutable ? absolute(e.ts) : relative(e.ts)}
            </time>
          </div>
          <div className="tl-text">{e.text}</div>
          {e.meta && <div className="tl-meta mono">{e.meta}</div>}
          {e.links && (
            <div className="row gap-2 wrap" style={{ marginTop: 6 }}>
              {e.links.map((l) => <Chip key={l} icon="→">{l}</Chip>)}
            </div>
          )}
          {renderExtra?.(e)}
        </article>
      ))}
      {immutable && (
        <p className="tl-immutable-note">
          Append-only record. Entries cannot be edited or removed — there is no control here that would.
        </p>
      )}
    </div>
  )
}

/* ---------------- Diff view (§8.15) ---------------- */
export function DiffView({ original, edited, leftLabel = 'Original draft', rightLabel = 'Edited & approved' }) {
  const o = original.split(/(\s+)/), n = edited.split(/(\s+)/)
  const oSet = new Set(o), nSet = new Set(n)
  return (
    <div className="diff">
      <div className="diff-pane">
        <div className="diff-head">{leftLabel}</div>
        <div className="diff-body">
          {o.map((w, i) => nSet.has(w) || !w.trim()
            ? <React.Fragment key={i}>{w}</React.Fragment>
            : <span key={i} className="diff-del">{w}</span>)}
        </div>
      </div>
      <div className="diff-pane">
        <div className="diff-head">{rightLabel}</div>
        <div className="diff-body">
          {n.map((w, i) => oSet.has(w) || !w.trim()
            ? <React.Fragment key={i}>{w}</React.Fragment>
            : <span key={i} className="diff-ins">{w}</span>)}
        </div>
      </div>
    </div>
  )
}

/* ---------------- KPI tile (§10.3) ----------------
   The delta uses an arrow + a word as well as colour (§7.6), and the value
   drills to its records where a drill target exists (P-4). */
export function KpiTile({ label, value, format, delta, deltaUnit, deltaLabel, help, onDrill }) {
  const d = delta == null ? null : fmtDelta(delta, deltaUnit || '')
  const display = format === 'pct' ? `${Math.round(value * 100)}%` : num(value)
  return (
    <div className="card card-1" style={{ padding: 'var(--sp-4)' }}>
      <div className="caption">{label}</div>
      <div className="kpi-value" style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600, margin: '2px 0 4px' }}>
        {onDrill ? <Drill onClick={onDrill} title={`Open the cases behind "${label}"`}>{display}</Drill> : display}
      </div>
      {d && (
        <div className="caption row gap-1">
          <span aria-hidden="true">{d.icon}</span>
          <span>{d.text}</span>
          <span className="dim">{deltaLabel}</span>
        </div>
      )}
      {help && <div className="meta" style={{ marginTop: 6 }}>{help}</div>}
    </div>
  )
}
