/* S-03 · Corpus dashboard [F-080].
   Scope Class: POC functional. Persona: Operations Manager (primary).

   The manager's question is "is the operation healthy, and what changed" — so
   every tile answers it in one glance and resolves into cases on click. There is
   no number on this screen that cannot be drilled: a figure that cannot be
   opened is decoration and does not ship [P-4, NFR-42]. */

import React from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { KpiTile } from '../ui/data.jsx'
import { ChartFrame, BarChart, LineChart, Donut } from '../ui/charts.jsx'
import { Button, Chip, ScopeBanner } from '../ui/primitives.jsx'
import { EmptyState, ErrorState, Notice, SkeletonBlock } from '../ui/feedback.jsx'
import { useAsync } from '../shell/hooks.js'
import * as api from '../mock/api.js'
import DrillPanel, { useDrill } from './DrillPanel.jsx'
import { num, absolute } from '../contracts/format.js'
import { ScopeClass } from '../contracts/state.js'
import { TENANT } from '../contracts/config.js'

export default function Dashboard() {
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const period = params.get('period') || '12m'
  const { data, loading, error, reload } = useAsync(
    () => api.getDashboardAggregates(period), [period]
  )

  /* A drill opens the case list as an overlay on THIS screen: the chart stays
     visible behind it, and Esc returns here with scroll position intact (§10.13). */
  const drill = useDrill('overview')

  const setPeriod = (p) => {
    const next = new URLSearchParams(params)
    next.set('period', p)
    setParams(next, { replace: true })
  }

  /* Some figures resolve to a filtered case list; some resolve to the surface
     that holds their records. Both are drills — what P-4 forbids is a number
     that resolves to nothing. */
  const open = (item, label) => {
    if (item.navTo) return nav(item.navTo)
    if (item.drill) return drill(item.drill, item.drillLabel || label)
  }
  const canOpen = (item) => !!(item.navTo || item.drill)

  if (loading) {
    return (
      <div className="page density-manager">
        <div className="page-head"><h1 className="page-title">Overview</h1></div>
        <div className="grid grid-6" style={{ marginBottom: 'var(--sp-5)' }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card card-1"><SkeletonBlock lines={3} /></div>
          ))}
        </div>
        <div className="grid grid-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card"><SkeletonBlock lines={8} /></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page density-manager">
        <ErrorState dependency="Aggregate query service" traceId={error.trace_id} onRetry={reload}
                    message="The dashboard could not run its aggregate queries. No cached numbers are shown — a stale count would be worse than none." />
      </div>
    )
  }

  if (data.empty) {
    return (
      <div className="page density-manager">
        <div className="page-head"><h1 className="page-title">Overview</h1></div>
        <EmptyState
          icon="◌" title="No corpus ingested yet"
          message="The six emulated systems have not completed a first backfill. This screen shows structure, not zeros pretending to be data."
          action={<Button variant="primary" onClick={() => nav('/connections')}>Open Connections</Button>}
        />
      </div>
    )
  }

  const periodLabel = (data.periods.find((p) => p.id === data.period) || {}).label || ''

  return (
    <div className="page density-manager">
      <div className="page-head row gap-3 wrap">
        <div className="grow">
          <h1 className="page-title">Overview</h1>
          <div className="page-sub">
            {TENANT} · corpus health across six emulated systems.
            Every figure below is a live query over the canonical model, and every one of them opens the records behind it.
          </div>
        </div>

        {/* §10.3's success criterion is "what changed this month, in three clicks".
            This is the control that question needs. */}
        <div className="field">
          <label className="field-label" htmlFor="period">Period</label>
          <select id="period" className="select" style={{ width: 170 }}
                  value={data.period} onChange={(e) => setPeriod(e.target.value)}>
            {data.periods.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} />
      </div>

      {/* KPI band */}
      <section className="section">
        <div className="grid grid-6">
          {data.kpis.map(({ key, ...k }) => (
            <KpiTile
              key={key}
              {...k}
              onDrill={canOpen(k) ? () => open(k, k.label) : undefined}
            />
          ))}
        </div>
        <p className="meta" style={{ marginTop: 'var(--sp-2)' }}>
          Counts and deltas cover <strong>{periodLabel.toLowerCase()}</strong>, compared against the
          equivalent window before it. Where the corpus holds no comparable prior window, the delta
          is absent rather than estimated.
        </p>
      </section>

      <section className="section">
        <div className="grid grid-3">
          <ChartFrame
            title="Volume by category"
            subtitle="10 level-1 categories"
            data={data.byCategory}
            note="Click any bar to open its cases. Bars are ordered by volume, and every label is written out — the ordering, not the hue, carries the identity."
          >
            <BarChart data={data.byCategory} seriesIndex={0}
                      onSelect={(d) => drill(d.drill, `Category: ${d.label}`)} />
          </ChartFrame>

          <ChartFrame
            title="Volume by channel"
            subtitle="12 intake channels · voice is a real transcribed artefact"
            data={data.byChannel}
            note="Voice-origin metrics are reported separately elsewhere and never folded into headline numbers [NFR-37]."
          >
            <BarChart data={data.byChannel} seriesIndex={1}
                      onSelect={(d) => drill(d.drill, `Channel: ${d.label}`)} />
          </ChartFrame>

          <ChartFrame
            title="Volume by account tier"
            data={data.byTier}
            note="The enterprise-tier bar is the manager's usual first click: it is where SLA exposure concentrates."
          >
            <BarChart data={data.byTier} seriesIndex={3}
                      onSelect={(d) => drill(d.drill, `Tier: ${d.label}`)} />
          </ChartFrame>
        </div>
      </section>

      <section className="section">
        <div className="grid grid-3">
          <div style={{ gridColumn: 'span 2' }}>
            <ChartFrame
              title="Volume by month"
              subtitle="Trailing 12 months"
              data={data.byMonth}
              note="One measure, one axis. Points are clickable to the month's cases; the first, last and peak values are labelled directly rather than every point."
            >
              <LineChart data={data.byMonth} seriesIndex={0}
                         onSelect={(d) => drill(d.drill, `Month: ${d.label}`)} />
            </ChartFrame>
          </div>

          <ChartFrame
            title="KB coverage by class"
            subtitle="Covered · thin · gap"
            data={data.coverage}
            valueLabel="Classes"
            note="Click the gap segment for the intents with no adequate article, ranked by volume × handling cost."
          >
            <Donut data={data.coverage} unitLabel="classes"
                   onSelect={(d) => open(d, `KB: ${d.label}`)} />
          </ChartFrame>
        </div>
      </section>

      <section className="section">
        <div className="grid grid-2">
          <ChartFrame
            title="Analyst roster by level"
            subtitle="Headcount only"
            data={data.byLevel}
            valueLabel="Analysts"
            note="Click a level to open that cohort's casework — deliberately the cases, not the people. An ordered list of analysts would be the ranking artefact this product does not have [§1.4]."
          >
            <BarChart data={data.byLevel} seriesIndex={5}
                      onSelect={(d) => open(d, d.drillLabel)} />
          </ChartFrame>

          <div className="stack gap-3">
            <Notice tone="info" icon="⌬">
              <strong>Every source on this screen is emulated.</strong> The counts are real queries over a
              synthetic corpus of {num(6000)} cases, 240 analysts and 900 articles — high-fidelity replicas, never a live tenant.
            </Notice>
            <Notice tone="success" icon="✓">
              These aggregates reconcile with the per-system object counts on Connections [NFR-31].
              If a figure here disagrees with the reconciliation table there, one of them is wrong and both are visible.
            </Notice>
            <div className="card">
              <div className="card-head"><span className="card-title">Where the manager usually goes next</span></div>
              <div className="stack gap-2">
                <Button variant="secondary" onClick={() => nav('/intelligence')}>
                  Weekly digest — this week's three recurring clusters →
                </Button>
                <Button variant="secondary" onClick={() => drill({ status: 'open', risk: 'at-risk' }, 'Open · at SLA risk')}>
                  Open cases at SLA risk →
                </Button>
                <Button variant="secondary" onClick={() => nav('/audit?type=rejected')}>
                  Last week's rejections — where drafts fail →
                </Button>
              </div>
            </div>
            <span className="meta">
              Aggregates generated {absolute(data.generated_at)}. Live-changing surfaces carry their own
              refresh stamp and a stale badge past 60s (§11.9).
            </span>
          </div>
        </div>
      </section>

      <DrillPanel originLabel="overview" />
    </div>
  )
}
