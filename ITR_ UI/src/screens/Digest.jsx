/* S-11 · Weekly intelligence digest [F-087, F-075, F-129, F-074].
   Scope Class: POC functional. Persona: Support Director / Operations Manager.

   Job: read Monday's briefing and leave with three actions, each evidence-backed.
   Written prose-first with charts supporting, because a director acts on a
   sentence and verifies with a number — not the other way round [P-7].

   Two structural guarantees on this screen:
     · patterns below significance are ABSENT — no teaser rows [F-074];
     · development areas are anonymised by employment type, never by name, and
       no per-person management action exists anywhere here [F-129, §1.4]. */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Chip, ScopeBanner, Meter, Drill } from '../ui/primitives.jsx'
import { ErrorState, Notice, SkeletonBlock } from '../ui/feedback.jsx'
import { ChartFrame, BarChart } from '../ui/charts.jsx'
import { Table } from '../ui/data.jsx'
import { useAsync } from '../shell/hooks.js'
import DrillPanel, { useDrill } from './DrillPanel.jsx'
import * as api from '../mock/api.js'
import { num, absolute, relative, delta as fmtDelta } from '../contracts/format.js'
import { ScopeClass } from '../contracts/state.js'

export default function Digest() {
  const nav = useNavigate()
  const { data, loading, error, reload } = useAsync(() => api.getWeeklyDigest(), [])
  const drill = useDrill('intelligence')

  if (loading) {
    return (
      <div className="page density-manager" style={{ maxWidth: 1080 }}>
        <div className="page-head"><h1 className="page-title">Weekly intelligence digest</h1></div>
        <SkeletonBlock lines={6} />
      </div>
    )
  }
  if (error) {
    return (
      <div className="page density-manager">
        <ErrorState dependency="Pattern Miner batch" traceId={error.trace_id} onRetry={reload}
                    message="The weekly batch output could not be read. Last week's archived digest is unaffected." />
      </div>
    )
  }

  const d = data

  return (
    <div className="page density-manager" style={{ maxWidth: 1120 }}>
      <div className="page-head row gap-3">
        <div className="grow">
          <h1 className="page-title">Weekly intelligence digest</h1>
          <div className="page-sub">
            {d.period_label} · published <span title={absolute(d.published_at)}>{relative(d.published_at)}</span>
          </div>
        </div>
        <select className="select" style={{ width: 160 }} defaultValue={d.week}
                aria-label="Digest week" onChange={() => {}}>
          {d.archive.map((w) => <option key={w} value={w}>Week {w}{w === d.week ? ' (current)' : ''}</option>)}
        </select>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} />
      </div>

      {/* ---- Narrative: the briefing, in prose ---- */}
      <section className="section">
        <div className="card card-1">
          <h2 style={{ fontSize: 22, marginBottom: 'var(--sp-3)' }}>{d.narrative.headline}</h2>
          <p style={{ fontSize: 15, lineHeight: 1.6, color: 'var(--ink-900)' }}>{d.narrative.body}</p>
          <div className="row gap-5 wrap" style={{ marginTop: 'var(--sp-4)' }}>
            {d.narrative.figures.map((f) => (
              <div key={f.label}>
                <div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                  {f.drill
                    ? <Drill onClick={() => drill(f.drill, f.drillLabel || f.label)}
                             title={f.drillLabel}>{num(f.value)}</Drill>
                    : num(f.value)}
                </div>
                <div className="caption">{f.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Recurring clusters ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Recurring clusters</h2>
          <span className="caption">
            Week over week. A pattern below the significance floor is not shown at all —
            there are no teaser rows on this screen.
          </span>
        </div>

        <div className="stack gap-3">
          {d.clusters.map((c) => {
            const m = fmtDelta(c.movement)
            return (
              <article className="card" key={c.key}>
                <div className="row gap-3 wrap" style={{ marginBottom: 'var(--sp-2)' }}>
                  <span className="card-title mono">{c.label}</span>
                  <Chip>{c.category}</Chip>
                  <Chip tone={c.movement > 0 ? 'warning' : c.movement < 0 ? 'success' : 'neutral'} icon={m.icon}>
                    {m.text} vs last week
                  </Chip>
                  {c.rootCause && <Chip tone="info" icon="⚙">root cause {c.rootCause}</Chip>}
                  <span className="right">
                    <Drill onClick={() => drill(c.drill, `Cluster: ${c.label}`)}>
                      {num(c.count)} tickets
                    </Drill>
                    <span className="dim caption"> (was {c.prior_count})</span>
                  </span>
                </div>
                <p style={{ fontSize: 'var(--fs-body)', color: 'var(--ink-600)', margin: 0 }}>{c.story}</p>
                <div className="row gap-2 wrap" style={{ marginTop: 'var(--sp-3)' }}>
                  <Button variant="secondary" size="sm" onClick={() => drill(c.drill, `Cluster: ${c.label}`)}>
                    Open the {c.count} cases
                  </Button>
                  {c.exemplar && (
                    <Button variant="ghost" size="sm" onClick={() => nav(`/case/${c.exemplar}?origin=intelligence`)}>
                      {c.exemplar_has_root_cause
                        ? `Open the exemplar and its root cause (${c.exemplar})`
                        : `Open an exemplar (${c.exemplar})`} →
                    </Button>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      </section>

      {/* ---- Deflection candidates ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Deflection candidates</h2>
          <span className="caption">Volume that an article could answer without an analyst.</span>
        </div>
        <div className="grid grid-2">
          {d.deflection.map((x) => (
            <div className="card" key={x.key}>
              <div className="row gap-2">
                <span className="card-title mono">{x.label}</span>
                <span className="right strong num">≈{num(x.estimated_volume)}/week</span>
              </div>
              <p className="caption" style={{ marginTop: 'var(--sp-2)' }}>{x.basis}</p>
              <Button variant="secondary" size="sm" onClick={() => drill(x.drill, `Deflection: ${x.label}`)}>
                Show the cases this estimate is drawn from
              </Button>
            </div>
          ))}
        </div>
      </section>

      {/* ---- KB gaps ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Knowledge gaps</h2>
          <span className="caption">Ranked by volume × median handling cost.</span>
        </div>
        <Table
          ariaLabel="Knowledge gaps"
          rows={d.gaps}
          rowKey={(r) => r.key}
          columns={[
            { key: 'label', label: 'Class', render: (r) => <span className="mono">{r.label}</span> },
            { key: 'cat', label: 'Category', render: (r) => r.category },
            { key: 'vol', label: 'Cases (30d)', numeric: true,
              render: (r) => <Drill onClick={() => drill(r.drill, `KB gap: ${r.label}`)}>{num(r.volume_30d)}</Drill> },
            { key: 'cost', label: 'Median handling', numeric: true, render: (r) => `${r.handling_cost_min}m` },
            { key: 'articles', label: 'Articles', numeric: true,
              render: (r) => r.articles === 0
                ? <Chip tone="danger" icon="✕">none</Chip>
                : <Chip tone="warning" icon="⚠">{r.articles} thin</Chip> },
          ]}
          footer={
            <>
              <span className="grow">A gap is a class the corpus cannot answer from knowledge — it is answered from an analyst's memory instead.</span>
              <Button variant="secondary" size="sm" onClick={() => nav('/knowledge?tab=gaps')}>
                Open the KB gap queue →
              </Button>
            </>
          }
        />
      </section>

      {/* ---- SLA hotspots ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">SLA hotspots</h2>
          <span className="caption">Open cases inside two hours of their deadline, by class.</span>
        </div>
        <ChartFrame
          title="Cases at SLA risk"
          data={d.sla_hotspots.map((h) => ({ key: h.key, label: h.label, value: h.atRisk, drill: h.drill }))}
          valueLabel="At risk"
          note="Click a bar to open the exposed cases. The clock is deterministic; only the written reason on a case is model-generated, and it is labelled as an explanation."
        >
          <BarChart
            data={d.sla_hotspots.map((h) => ({ key: h.key, label: h.label, value: h.atRisk, drill: h.drill }))}
            seriesIndex={4}
            onSelect={(x) => drill(x.drill, `SLA risk: ${x.label}`)}
          />
        </ChartFrame>
      </section>

      {/* ---- Capability map ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Capability map</h2>
          <span className="caption">
            Coverage depth per class — how many analysts carry 80% of the volume. Low depth is a
            continuity risk, not a person's problem.
          </span>
        </div>
        <Table
          ariaLabel="Capability map"
          rows={d.capability.map}
          rowKey={(r) => r.key}
          columns={[
            { key: 'label', label: 'Class', render: (r) => <span className="mono">{r.label}</span> },
            { key: 'cat', label: 'Category', render: (r) => <span className="caption">{r.category}</span> },
            { key: 'vol', label: 'Resolved', numeric: true,
              render: (r) => <Drill onClick={() => drill(r.drill, `Class: ${r.label}`)}>{num(r.volume)}</Drill> },
            { key: 'contrib', label: 'Contributors', numeric: true, render: (r) => num(r.contributors) },
            { key: 'depth', label: 'Depth to 80%', numeric: true,
              render: (r) => (
                <span className="row gap-2" style={{ justifyContent: 'flex-end' }}>
                  <span className="num">{r.depth}</span>
                  {r.thin && <Chip tone="warning" icon="⚠">thin</Chip>}
                </span>
              ) },
          ]}
          footer={<span>A class where two analysts carry 80% of the work is one holiday away from a queue.</span>}
        />
      </section>

      {/* ---- Development areas: anonymised, by rule ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Development areas</h2>
          <span className="caption">Anonymised by employment type. No names appear in this section.</span>
        </div>
        <Notice tone="info" icon="🛈" title="Why there are no names here">
          Capability signals exist to route work and surface support needs — never to rank people.
          This console has no per-analyst leaderboard, no appraisal surface and no management action on a
          person. Employment type is shown here only to keep the anonymisation honest; it is never scored.
        </Notice>
        <div className="grid grid-2" style={{ marginTop: 'var(--sp-3)' }}>
          {d.development.map((x) => (
            <div className="card" key={x.class}>
              <div className="row gap-2">
                <span className="card-title mono">{x.class}</span>
                <span className="right caption">sample floor ≥{x.sample_floor}</span>
              </div>
              <div className="row gap-2 wrap" style={{ margin: 'var(--sp-2) 0' }}>
                {x.below_median.map((b) => (
                  <Chip key={b.type} tone="warning" icon="↗">{b.n} {b.type} below median</Chip>
                ))}
              </div>
              <p className="caption" style={{ margin: 0 }}>{x.note}</p>
            </div>
          ))}
          <div className="card">
            <div className="card-title">Skills claimed without supporting history</div>
            <div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>{d.skills_claimed_without_history}</div>
            <p className="caption" style={{ margin: 0 }}>
              Analysts with a self-rated skill at level 4–5 and no resolved cases in that class.
              A coaching conversation, not a finding.
            </p>
          </div>
        </div>
      </section>

      {/* ---- Adoption: is it earning its keep? ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Adoption</h2>
          <span className="caption">
            The three usefulness targets from the approved metric set, read over the {d.adoption_window}.
            Quality below says whether the system is honest; these say whether it is worth having.
          </span>
        </div>
        <div className="grid grid-3">
          {d.adoption.map((m) => {
            const hit = m.value != null && m.value >= m.target
            // Some rates resolve to a case list, some to the decision records.
            const openIt = () => (m.drill ? drill(m.drill, m.drillLabel) : nav(m.drillTo))
            return (
              <div className="card" key={m.key}>
                <div className="caption">{m.label}</div>
                <div className="row gap-2" style={{ margin: '2px 0 6px' }}>
                  <span style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                    <Drill onClick={openIt} title={m.drillLabel}>
                      {m.value == null ? '—' : `${Math.round(m.value * 100)}%`}
                    </Drill>
                  </span>
                  <Chip tone={hit ? 'success' : 'warning'} icon={hit ? '✓' : '⚠'}>
                    target ≥{Math.round(m.target * 100)}%
                  </Chip>
                </div>
                <Meter value={m.value || 0} tone={hit ? 'success' : 'warning'}
                       label={`${m.label} ${Math.round((m.value || 0) * 100)} percent`} />
                <p className="caption" style={{ marginTop: 'var(--sp-2)', marginBottom: 4 }}>{m.basis}</p>
                <p className="meta" style={{ margin: 0 }}>{m.detail}</p>
              </div>
            )
          })}
        </div>
        <p className="meta" style={{ marginTop: 'var(--sp-2)' }}>
          Each percentage is derived from the decision records, not stated — which is why each one
          opens onto the rows it was computed from.
        </p>
      </section>

      {/* ---- Quality corner ---- */}
      <section className="section">
        <div className="section-head">
          <h2 className="section-title">Quality</h2>
          <span className="caption">QA/Verifier sampling and calibration, week over week.</span>
        </div>
        <div className="grid grid-2">
          <div className="card">
            <div className="row gap-4 wrap">
              <div>
                <div className="caption">Runs sampled</div>
                <div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                  <Drill onClick={() => nav(d.quality.drill_sampled)} title="Open the sampled decision records">
                    {d.quality.sampled_runs}
                  </Drill>
                </div>
              </div>
              <div>
                <div className="caption">Flagged</div>
                <div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                  <Drill onClick={() => nav(d.quality.drill_flagged)} title="Open the QA-flagged runs">
                    {d.quality.flagged}
                  </Drill>
                </div>
              </div>
              <div>
                <div className="caption">Groundedness</div>
                <div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                  <Drill onClick={() => nav(d.quality.drill_sampled)} title="Open the runs this average was computed over">
                    {d.quality.groundedness_avg.toFixed(2)}
                  </Drill>
                </div>
                <div className="caption">was {d.quality.groundedness_prior.toFixed(2)}</div>
              </div>
              <div>
                <div className="caption">Citation coverage</div>
                <div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                  <Drill onClick={() => nav(d.quality.drill_sampled)} title="Open the runs whose packs were inspected">
                    {Math.round(d.quality.citation_coverage * 100)}%
                  </Drill>
                </div>
                <div className="caption">target ≥90%</div>
              </div>
            </div>
            <p className="caption" style={{ marginTop: 'var(--sp-3)' }}>{d.quality.calibration_note}</p>
          </div>

          <div className="card">
            <div className="card-title" style={{ marginBottom: 'var(--sp-3)' }}>Confidence band mix</div>
            {d.quality.band_movement.map((b) => (
              <div key={b.band} style={{ marginBottom: 'var(--sp-3)' }}>
                <div className="row caption">
                  <span className="grow">{b.band}</span>
                  <span className="num">{Math.round(b.share * 100)}%</span>
                  <span className="dim num">{' '}(was {Math.round(b.prior * 100)}%)</span>
                </div>
                <Meter value={b.share}
                       tone={b.band === 'High' ? 'success' : b.band === 'Medium' ? 'warning' : 'danger'}
                       label={`${b.band} band ${Math.round(b.share * 100)} percent`} />
              </div>
            ))}
            <p className="caption" style={{ margin: 0 }}>
              Bands are calibrated, not cosmetic: a Low band suppresses one-click approval in the queue.
            </p>
          </div>
        </div>
      </section>

      <p className="meta">
        Everything on this page resolves to the cases behind it. Nothing is an estimate you cannot open,
        and no number appears here that is not in the approved metric set.
      </p>

      <DrillPanel originLabel="intelligence" />
    </div>
  )
}
