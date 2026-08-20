/* S-05 · Ticket 360 [F-082, F-045] — with S-06 / S-07 / S-08 as tabs and
   S-12 (call player) as an inline expansion of a voice timeline entry.
   Scope Class: POC functional.

   The honesty rule on this screen: a partial identity match is SHOWN, never
   hidden, and a conflict shows both candidates with their evidence and picks
   neither. Everything here is read-only except navigation. */

import React, { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Timeline } from '../ui/data.jsx'
import {
  Button, Chip, ConfidenceBand, SlaChip, StatusChip, ScopeBanner, Meter, Drill,
} from '../ui/primitives.jsx'
import { EmptyState, ErrorState, Notice, NotFoundState, SkeletonBlock } from '../ui/feedback.jsx'
import { CallPlayer } from '../ui/audio.jsx'
import { useAsync } from '../shell/hooks.js'
import * as api from '../mock/api.js'
import Citations from './panels/Citations.jsx'
import Explainers from './panels/Explainers.jsx'
import Assignment from './panels/Assignment.jsx'
import DrillPanel from './DrillPanel.jsx'
import { callFor } from '../fixtures/details.js'
import { systemName, channelMeta } from '../fixtures/corpus.js'
import { absolute, relative, num, ms } from '../contracts/format.js'
import { ScopeClass, IdentityState, WRITE_COPY, WriteState } from '../contracts/state.js'

const TABS = [
  { key: '360', label: 'Timeline', screen: 'S-05' },
  { key: 'citations', label: 'Citations', screen: 'S-06' },
  { key: 'explainers', label: 'Explainers', screen: 'S-07' },
  { key: 'assignment', label: 'Analyst panel', screen: 'S-08' },
]

/* ---------------- 360 summary card [F-045] ---------------- */
function SummaryCard({ id, actor, identity }) {
  const [open, setOpen] = useState(false)
  const partial = identity.state === IdentityState.PARTIAL
  const conflict = identity.state === IdentityState.AMBIGUOUS

  return (
    <div className="card card-1">
      <div className="row gap-4 wrap">
        <div style={{ minWidth: 220 }}>
          <div className="page-title">{actor.name}</div>
          <div className="caption">{identity.org_unit} · reports to {identity.manager}</div>
          <div className="caption mono">{actor.email}</div>
        </div>
        <div>
          <div className="caption">Account</div>
          <div className="strong">{identity.account}</div>
          <Chip tone={identity.tier === 'Enterprise' ? 'primary' : 'neutral'}>{identity.tier} tier</Chip>
        </div>
        <div>
          <div className="caption">Entitlements</div>
          <div className="strong num">{identity.entitlements}</div>
        </div>
        <div>
          <div className="caption">Assets</div>
          <div className="strong num">{identity.assets}</div>
        </div>
        <div>
          <div className="caption">Open cases</div>
          <div className="strong num">{identity.open_cases}</div>
        </div>
        <div>
          <div className="caption">CSAT trend</div>
          <div className="row gap-1" style={{ alignItems: 'flex-end', height: 30 }}
               aria-label={`CSAT last 5: ${identity.csat_trend.join(', ')}`}>
            {identity.csat_trend.map((v, i) => (
              <span key={i} title={`${v}/5`} style={{
                display: 'inline-block', width: 8, height: 4 + v * 5,
                background: 'var(--ink-900)', borderRadius: 1,
              }} />
            ))}
          </div>
          <div className="meta">last 5: {identity.csat_trend.join(', ')}</div>
        </div>
        <div className="right caption" style={{ textAlign: 'right' }}>
          <div>refreshed {relative(identity.refreshed_at)}</div>
          <div className="meta" title={absolute(identity.refreshed_at)}>{absolute(identity.refreshed_at)}</div>
        </div>
      </div>

      <div className="hr" />

      <div className="row gap-2 wrap">
        <span className="caption">Identity</span>
        {identity.matched_systems.map((s) => (
          <Chip key={s} tone="success" icon="✓">{systemName(s)}</Chip>
        ))}
        {identity.unmatched_systems.map((s) => (
          <Chip key={s} tone="warning" icon="⚠">{systemName(s)} unmatched</Chip>
        ))}
        <span className="caption">resolved in {ms(identity.resolve_ms)}</span>
        <Button variant="ghost" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? 'Hide match evidence' : 'Show match evidence'}
        </Button>
      </div>

      {partial && (
        <div style={{ marginTop: 'var(--sp-3)' }}>
          <Notice tone="warning" icon="⚠" title={`Partial match — ${identity.matched_systems.length} of 4 systems`}
                  action={<Link className="btn btn-secondary btn-sm" to="/connections/identity">Resolve in Identity queue →</Link>}>
            Unmatched: <strong>{identity.unmatched_systems.map(systemName).join(', ')}</strong>
            {identity.unmatched_reason && <> ({identity.unmatched_reason})</>}.
            This is shown rather than hidden, and it does not block the case — the context pack proceeds with
            a partial-identity annotation.
          </Notice>
        </div>
      )}

      {conflict && (
        <div style={{ marginTop: 'var(--sp-3)' }}>
          <Notice tone="warning" icon="⚠" title="Two candidate identities — neither was picked">
            Both candidates and their field evidence are in the identity queue. The system does not guess an
            identity below its threshold.
          </Notice>
        </div>
      )}

      {open && (
        <div style={{ marginTop: 'var(--sp-3)' }}>
          <table className="tbl">
            <thead>
              <tr><th>System</th><th>Matched on</th><th className="num-cell">Confidence</th><th>Evidence</th></tr>
            </thead>
            <tbody>
              {identity.evidence.map((e) => (
                <tr key={e.system}>
                  <td className="strong">{systemName(e.system)}</td>
                  <td>{e.fields.map((f) => <Chip key={f}>{f}</Chip>)}</td>
                  <td className="num-cell num">{e.confidence.toFixed(2)}</td>
                  <td className="caption">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="meta">Expanding identity evidence is itself logged — sensitive detail access is audited.</p>
        </div>
      )}
    </div>
  )
}

/* ---------------- Timeline tab ---------------- */
function TimelineTab({ caseId, playCallId, onPlay, startAt }) {
  const { data, loading, error, reload } = useAsync(() => api.listTimeline(caseId), [caseId])
  const [filter, setFilter] = useState('all')

  if (loading) return <SkeletonBlock lines={10} />
  if (error) return <ErrorState dependency="Timeline service" traceId={error.trace_id} onRetry={reload} />
  if (!data.length) return <EmptyState icon="◌" title="No activity yet" message="This case has been created but nothing has happened on it." />

  const kinds = ['all', 'comment', 'event', 'decision', 'write']
  const rows = filter === 'all' ? data : data.filter((e) => e.type === filter)

  return (
    <div className="stack gap-3">
      <div className="row gap-2 wrap">
        <span className="caption">Filter</span>
        {kinds.map((k) => (
          <Button key={k} size="sm" variant={filter === k ? 'primary' : 'ghost'} onClick={() => setFilter(k)}>
            {k}
          </Button>
        ))}
        <span className="right meta">Cross-channel: every channel's history is here, in one thread.</span>
      </div>

      <Timeline
        entries={rows}
        renderExtra={(e) => (
          <>
            {e.call_id && (
              <div style={{ marginTop: 'var(--sp-2)' }}>
                {playCallId === e.call_id ? (
                  <CallPlayer call={callFor(e.call_id)} startAt={startAt} onClose={() => onPlay(null)} />
                ) : (
                  <Button variant="secondary" size="sm" onClick={() => onPlay(e.call_id)}>
                    ▶ Play call · avg ASR confidence {e.asr_confidence_avg}
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      />
    </div>
  )
}

/* ---------------- Screen ---------------- */
export default function Case360() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const tab = params.get('tab') || '360'
  const origin = params.get('origin')
  const [playCall, setPlayCall] = useState(params.get('play') || null)
  const focusCard = Number(params.get('card')) || null

  const { data, loading, error, reload } = useAsync(() => api.getTicket360(id), [id])

  const setTab = (t) => {
    const next = new URLSearchParams(params)
    next.set('tab', t)
    setParams(next, { replace: true })
  }

  if (loading) return <div className="page"><SkeletonBlock lines={12} /></div>
  if (error?.kind === 'notfound') return <div className="page"><NotFoundState what="Case" backTo="/tickets" /></div>
  if (error) return <div className="page"><ErrorState dependency="Ticket 360 service" traceId={error.trace_id} onRetry={reload} /></div>

  const { case: c, actor, identity, team_name, assignee, linked_issues, write } = data

  return (
    <div className="page">
      <div className="page-head row gap-3 wrap">
        <div className="grow">
          <div className="row gap-2 wrap">
            <h1 className="page-title mono">{c.id}</h1>
            <StatusChip status={c.status} />
            <SlaChip deadline={c.sla_deadline} paused={c.sla_paused} />
            <ConfidenceBand band={c.band} value={c.confidence} />
            <Chip icon={channelMeta(c.channel).icon}>{channelMeta(c.channel).label}</Chip>
          </div>
          <div className="page-sub">{c.subject}</div>
        </div>
        {origin && <Button variant="ghost" onClick={() => nav(-1)}>← Back to {origin}</Button>}
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} />
      </div>

      {write?.state === WriteState.FAILED && (
        <div className="section">
          <Notice tone="danger" icon="✕" title={WRITE_COPY.failed}>
            An approval exists for this case and its external write did not land. The decision record is
            untouched; only the execution needs re-firing. Approval and write are separate states — this is
            what that looks like from the case side.
          </Notice>
        </div>
      )}

      <section className="section">
        <SummaryCard id={c.id} actor={actor} identity={identity} />
      </section>

      <div className="grid" style={{ gridTemplateColumns: '280px 1fr', gap: 'var(--sp-5)', alignItems: 'start' }}>
        {/* Left rail: case facts */}
        <aside className="card">
          <div className="card-head"><span className="card-title">Case facts</span></div>
          <dl style={{ margin: 0, fontSize: 'var(--fs-table)' }}>
            {[
              ['Status', <StatusChip key="s" status={c.status} />],
              ['Class', <Chip key="c">{c.class}</Chip>],
              ['Category', c.category],
              ['Tier', c.tier],
              ['Team', team_name],
              ['Assignee', assignee ? assignee.name : <span className="dim">unassigned</span>],
              ['Created', <span key="cr" title={absolute(c.created_at)}>{relative(c.created_at)}</span>],
              ['SLA', <SlaChip key="sla" deadline={c.sla_deadline} paused={c.sla_paused} />],
            ].map(([k, v]) => (
              <div className="row gap-2" key={k} style={{ padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                <dt className="caption" style={{ width: 82, flex: 'none' }}>{k}</dt>
                <dd style={{ margin: 0 }}>{v}</dd>
              </div>
            ))}
          </dl>

          {linked_issues.length > 0 && (
            <>
              <div className="card-head" style={{ marginTop: 'var(--sp-4)' }}>
                <span className="card-title">Linked engineering</span>
              </div>
              {linked_issues.map((j) => (
                <div key={j.key} className="card" style={{ background: 'var(--surface-1)', padding: 'var(--sp-3)' }}>
                  <div className="row gap-2">
                    <Chip tone="info">{systemName(j.system)}</Chip>
                    <span className="mono strong">{j.key}</span>
                  </div>
                  <div className="caption" style={{ margin: '6px 0' }}>{j.title}</div>
                  <div className="row gap-2 wrap caption">
                    <Chip>{j.status}</Chip>
                    <span>{j.assignee}</span>
                  </div>
                  <p className="meta" style={{ marginTop: 6, marginBottom: 0 }}>
                    Read-context only. No write control exists for non-Zendesk systems — the console does not
                    pretend to manage Jira.
                  </p>
                </div>
              ))}
            </>
          )}

          <div className="card-head" style={{ marginTop: 'var(--sp-4)' }}>
            <span className="card-title">Go to</span>
          </div>
          <div className="stack gap-2">
            <Link className="btn btn-secondary btn-sm" to={`/queue?item=${c.id}`}>Approval queue item →</Link>
            <Link className="btn btn-secondary btn-sm" to={`/audit?case_id=${c.id}&origin=tickets`}>Audit trail for this case →</Link>
          </div>
        </aside>

        {/* Main: tabbed panels */}
        <div>
          <div className="tabs" role="tablist" aria-label="Ticket context">
            {TABS.map((t) => (
              <button
                key={t.key}
                className="tab"
                role="tab"
                aria-selected={tab === t.key}
                onClick={() => setTab(t.key)}
              >
                {t.label} <span className="meta">{t.screen}</span>
              </button>
            ))}
          </div>

          <div style={{ paddingTop: 'var(--sp-4)' }} role="tabpanel">
            {tab === '360' && (
              <TimelineTab caseId={c.id} playCallId={playCall} onPlay={setPlayCall}
                           startAt={Number(params.get('t')) || 0} />
            )}
            {tab === 'citations' && <Citations caseId={c.id} focusCard={focusCard} />}
            {tab === 'explainers' && <Explainers caseId={c.id} onOpenAssignment={() => setTab('assignment')} />}
            {tab === 'assignment' && <Assignment caseId={c.id} classId={c.class} />}
          </div>
        </div>
      </div>

      <DrillPanel originLabel="tickets" />
    </div>
  )
}
