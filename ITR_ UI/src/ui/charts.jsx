/* §8.13 · Charts — dark, saturated series only; no pastels, no gradients, no 3D.
   Every segment is clickable to its records [P-4], every chart carries a
   "view as table" toggle, and identity is never colour-alone: single-series
   charts are directly labelled and multi-series charts always ship a legend
   plus direct labels (§10.3 accessibility, §7.6). */

import React, { useId, useState } from 'react'
import { num } from '../contracts/format.js'
import { Table } from './data.jsx'

const SERIES = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)',
                'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)']
export const seriesColor = (i) => SERIES[i % SERIES.length]

/* ---------------- Frame: title, actions, table toggle ---------------- */
export function ChartFrame({ title, subtitle, note, data, valueLabel = 'Cases', children, actions }) {
  const [asTable, setAsTable] = useState(false)
  const id = useId()
  return (
    <figure className="chart-frame" style={{ margin: 0 }}>
      <figcaption className="chart-head">
        <div className="grow">
          <div className="chart-title" id={id}>{title}</div>
          {subtitle && <div className="caption">{subtitle}</div>}
        </div>
        {actions}
        <button className="btn btn-ghost btn-sm" onClick={() => setAsTable((v) => !v)}
                aria-pressed={asTable}>
          {asTable ? 'View as chart' : 'View as table'}
        </button>
      </figcaption>
      <div className="chart-body">
        {asTable ? (
          <Table
            ariaLabel={`${title} — data table`}
            columns={[
              { key: 'label', label: 'Series', render: (r) => r.label },
              { key: 'value', label: valueLabel, numeric: true, render: (r) => num(r.value) },
            ]}
            rows={data}
            rowKey={(r) => r.key}
          />
        ) : children}
      </div>
      {note && <div className="chart-note">{note}</div>}
    </figure>
  )
}

/* ---------------- Horizontal bars ----------------
   Magnitude comparison across named categories: horizontal beats vertical
   because the labels are words, not dates. */
/** A segment is openable if it resolves to a filtered list OR to the surface
    holding its records — both satisfy P-4; only "nothing" fails it. */
const openable = (d) => !!(d.drill || d.navTo)

export function BarChart({ data, onSelect, seriesIndex = 0, valueFormat = num, max: maxProp }) {
  const max = maxProp ?? Math.max(...data.map((d) => d.value), 1)
  return (
    <div role="list">
      {data.map((d) => {
        const pct = (d.value / max) * 100
        const hit = onSelect && openable(d)
        const Row = hit ? 'button' : 'div'
        return (
          <Row
            key={d.key}
            className="bar-row"
            role="listitem"
            onClick={hit ? () => onSelect(d) : undefined}
            title={hit ? (d.drillLabel || `Open the ${valueFormat(d.value)} records behind ${d.label}`) : undefined}
          >
            <span className="bar-label" title={d.label}>{d.label}</span>
            <span className="bar-track">
              <span
                className="bar-fill"
                style={{ width: `${Math.max(pct, 0.6)}%`, background: seriesColor(d.seriesIndex ?? seriesIndex) }}
              />
            </span>
            <span className="bar-value">{valueFormat(d.value)}</span>
          </Row>
        )
      })}
    </div>
  )
}

/* ---------------- Line: volume over time ----------------
   One axis only. 2px stroke, 8px markers, crosshair + tooltip on hover. */
export function LineChart({ data, onSelect, height = 200, seriesIndex = 0 }) {
  const [hover, setHover] = useState(null)
  const W = 720, H = height, PAD = { t: 12, r: 16, b: 28, l: 48 }
  const max = Math.max(...data.map((d) => d.value), 1)
  const niceMax = Math.ceil(max / 50) * 50
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b
  const x = (i) => PAD.l + (data.length === 1 ? iw / 2 : (i / (data.length - 1)) * iw)
  const y = (v) => PAD.t + ih - (v / niceMax) * ih
  const path = data.map((d, i) => `${i ? 'L' : 'M'}${x(i)},${y(d.value)}`).join(' ')
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(niceMax * f))

  return (
    <div className="chart-hostage">
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Volume by month, ${data.length} points, peak ${num(max)} cases`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--chart-grid)" strokeWidth="1" />
            <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end">{num(t)}</text>
          </g>
        ))}
        <path d={path} fill="none" stroke={seriesColor(seriesIndex)} strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" />
        {data.map((d, i) => (
          <g key={d.key}>
            {/* Hit target is bigger than the mark. */}
            <circle className="chart-dot" cx={x(i)} cy={y(d.value)} r="12" fill="transparent"
                    onMouseEnter={() => setHover({ i, d })} onMouseLeave={() => setHover(null)}
                    onClick={() => d.drill && onSelect?.(d)} />
            <circle cx={x(i)} cy={y(d.value)} r={hover?.i === i ? 6 : 4}
                    fill={seriesColor(seriesIndex)} stroke="var(--surface-0)" strokeWidth="2" />
            {(i === 0 || i === data.length - 1 || d.value === max) && (
              <text x={x(i)} y={y(d.value) - 12} textAnchor="middle" fontWeight="600" fill="var(--ink-900)">
                {num(d.value)}
              </text>
            )}
            <text x={x(i)} y={H - 8} textAnchor="middle">{i % 2 === 0 ? d.label : ''}</text>
          </g>
        ))}
      </svg>
      {hover && (
        <div className="chart-tip" style={{ left: `${(x(hover.i) / W) * 100}%`, top: `${(y(hover.d.value) / H) * 100}%` }}>
          {hover.d.label}: {num(hover.d.value)} cases
        </div>
      )}
    </div>
  )
}

/* ---------------- Donut: composition of a whole ----------------
   Three slices only. Legend + direct labels + a 2px surface gap between
   segments so the boundary never depends on hue. */
export function Donut({ data, onSelect, size = 168, unitLabel = 'classes' }) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1
  const R = size / 2, r = R * 0.62, C = 2 * Math.PI * ((R + r) / 2)
  const stroke = R - r
  let offset = 0

  return (
    <div className="row gap-5 wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
           aria-label={data.map((d) => `${d.label} ${d.value}`).join(', ')}>
        <g transform={`rotate(-90 ${R} ${R})`}>
          {data.map((d) => {
            const frac = d.value / total
            const len = frac * C
            const el = (
              <circle
                key={d.key}
                cx={R} cy={R} r={(R + r) / 2}
                fill="none"
                stroke={seriesColor(d.seriesIndex ?? 0)}
                strokeWidth={stroke}
                strokeDasharray={`${Math.max(len - 2, 0)} ${C - Math.max(len - 2, 0)}`}
                strokeDashoffset={-offset}
                style={{ cursor: openable(d) ? 'pointer' : 'default' }}
                onClick={() => openable(d) && onSelect?.(d)}
              >
                {openable(d) && <title>{d.drillLabel || `Open ${d.label}`}</title>}
              </circle>
            )
            offset += len
            return el
          })}
        </g>
        <text x={R} y={R - 2} textAnchor="middle" fontSize="22" fontWeight="600" fill="var(--ink-900)">{total}</text>
        <text x={R} y={R + 16} textAnchor="middle">{unitLabel}</text>
      </svg>
      {/* The legend is also the hit target: an arc segment is a small thing to
          ask someone to click, and the label carries the same drill. */}
      <div className="stack gap-2">
        {data.map((d) => {
          const hit = onSelect && openable(d)
          const Row = hit ? 'button' : 'div'
          return (
            <Row
              className="legend-item" key={d.key}
              onClick={hit ? () => onSelect(d) : undefined}
              title={hit ? (d.drillLabel || `Open ${d.label}`) : undefined}
              style={hit ? { background: 'none', border: 0, padding: 0, cursor: 'pointer', font: 'inherit', textAlign: 'left' } : undefined}
            >
              <span className="legend-swatch" style={{ background: seriesColor(d.seriesIndex ?? 0) }} aria-hidden="true" />
              <span className="strong" style={{ color: 'var(--ink-900)', borderBottom: hit ? '1px dashed var(--primary-600)' : 'none' }}>{d.label}</span>
              <span className="num">{d.value}</span>
              <span className="dim">({Math.round((d.value / total) * 100)}%)</span>
            </Row>
          )
        })}
      </div>
    </div>
  )
}

/* ---------------- Legend (multi-series) ---------------- */
export const Legend = ({ items }) => (
  <div className="legend">
    {items.map((it, i) => (
      <span className="legend-item" key={it.key || i}>
        <span className="legend-swatch" style={{ background: seriesColor(it.seriesIndex ?? i) }} aria-hidden="true" />
        {it.label}
      </span>
    ))}
  </div>
)
