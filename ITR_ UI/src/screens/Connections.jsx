/* S-02 · Connections view [F-122, F-121, F-120] — the opening shot.
   Scope Class: POC functional (Identity tab: POC functional per F-044).

   Job: prove six systems are connected, complete and honestly labelled, in one
   glance. Chaos is shown as honest status, never as a silent spinner: a 429
   storm reads "rate-limited, retrying — resumed from checkpoint, 0 loss", and
   the recovery IS the demo point. */

import React, { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Chip, EmulatedChip, Meter, ScopeBanner } from '../ui/primitives.jsx'
import { EmptyState, ErrorState, Notice, SkeletonBlock, useToast } from '../ui/feedback.jsx'
import { Table } from '../ui/data.jsx'
import { useAsync } from '../shell/hooks.js'
import { useSession } from '../shell/session.jsx'
import * as api from '../mock/api.js'
import { CONNECTION_META, ScopeClass, ConnectionHealth } from '../contracts/state.js'
import { canAct, isHidden, DENY_REASON } from '../contracts/rbac.js'
import { DeniedState } from '../ui/feedback.jsx'
import { systemName, SYSTEMS } from '../fixtures/corpus.js'
import { absolute, relative, num, pct } from '../contracts/format.js'

/* ---------------- Systems tab ---------------- */
function SystemCard({ conn, expanded, onToggle, onRunLog }) {
  const meta = CONNECTION_META[conn.health]
  const sys = SYSTEMS.find((s) => s.id === conn.system)
  return (
    <article className="card">
      <div className="row gap-2 wrap">
        <span className="brand-mark" aria-hidden="true"
              style={{ background: 'var(--surface-2)', color: 'var(--ink-900)' }}>{sys.short}</span>
        <div className="grow">
          <div className="row gap-2">
            <span className="card-title">{sys.name}</span>
            <EmulatedChip />
          </div>
          <div className="caption">{sys.role}</div>
        </div>
        <Chip tone={meta.tone} icon={meta.icon}>{meta.label}</Chip>
      </div>

      {conn.note && (
        <p className="caption" style={{ marginTop: 'var(--sp-2)' }}>{conn.note}</p>
      )}

      <div className="row gap-4 wrap" style={{ marginTop: 'var(--sp-3)' }}>
        <div>
          <div className="caption">Last sync</div>
          <div className="strong" title={absolute(conn.last_sync)}>{relative(conn.last_sync)}</div>
        </div>
        <div>
          <div className="caption">Objects</div>
          <div className="strong num">{conn.objects.length}</div>
        </div>
        <div className="grow" style={{ minWidth: 160 }}>
          <div className="row caption">
            <span className="grow">Completeness</span>
            <span className="num">{pct(conn.completeness, 2)}</span>
          </div>
          <Meter value={conn.completeness}
                 tone={conn.completeness >= 1 ? 'success' : 'warning'}
                 label={`completeness ${pct(conn.completeness, 2)}`} />
        </div>
      </div>

      <div className="row gap-2" style={{ marginTop: 'var(--sp-3)' }}>
        <Button variant="secondary" size="sm" onClick={onToggle} aria-expanded={expanded}>
          {expanded ? 'Collapse' : 'Expand object table'}
        </Button>
        <Button variant="ghost" size="sm" onClick={onRunLog}>Run log →</Button>
        <span className="right meta mono">{conn.connector_run_id}</span>
      </div>

      {expanded && (
        <div style={{ marginTop: 'var(--sp-3)' }}>
          <Table
            ariaLabel={`${sys.name} object reconciliation`}
            rows={conn.objects}
            rowKey={(r) => r.object}
            columns={[
              { key: 'object', label: 'Object', render: (r) => <span className="mono">{r.object}</span> },
              { key: 'source', label: 'Source count', numeric: true, render: (r) => num(r.source) },
              { key: 'ingested', label: 'Ingested', numeric: true, render: (r) => num(r.ingested) },
              { key: 'delta', label: 'Δ', numeric: true,
                render: (r) => r.ingested - r.source === 0
                  ? <span className="dim">0</span>
                  : <span className="strong" style={{ color: 'var(--danger-700)' }}>{r.ingested - r.source}</span> },
              { key: 'checksum', label: 'Checksum',
                render: (r) => r.checksum === 'pass'
                  ? <Chip tone="success" icon="✓">pass</Chip>
                  : r.checksum === 'running'
                    ? <Chip tone="info" icon="↻">running</Chip>
                    : <Chip tone="danger" icon="✕">fail</Chip> },
            ]}
          />
          {conn.objects.filter((o) => o.detail).map((o) => (
            <div key={o.object} style={{ marginTop: 'var(--sp-2)' }}>
              <Notice tone="warning" icon="⚠" title={`${o.object} Δ${o.delta}`}>{o.detail}</Notice>
            </div>
          ))}
        </div>
      )}
    </article>
  )
}

/* ---------------- Identity queue tab [F-044] — the fifth human gate ---------------- */
function IdentityTab() {
  const { role, meta } = useSession()
  const toast = useToast()
  const { data, loading, error, reload } = useAsync(() => api.listIdentityQueue(), [])
  const [selected, setSelected] = useState(null)
  const [candidate, setCandidate] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [resolved, setResolved] = useState([])

  if (isHidden(role, 'identity.resolve')) {
    return <DeniedState action="identity.resolve" roleName={meta.name} home={meta.home} />
  }
  if (loading) return <SkeletonBlock lines={8} />
  if (error) return <ErrorState dependency="Identity resolution service" traceId={error.trace_id} onRetry={reload} />

  const rows = (data || []).filter((r) => !resolved.includes(r.id))
  if (!rows.length) {
    return <EmptyState icon="✓" title="No unresolved identities"
                       message="Every requester in the corpus resolved above threshold. Sub-threshold matches queue here rather than being guessed." />
  }

  const item = rows.find((r) => r.id === selected) || rows[0]

  const act = async (action) => {
    setBusy(true)
    try {
      const res = await api.resolveIdentity(item.id, action, { candidate, reason })
      toast.push({
        tone: 'success',
        text: `${action === 'resolve' ? 'Resolved' : action === 'new' ? 'Marked as a new actor' : 'Dismissed'} · audit ${res.audit_id} · ${res.retro_linked} cases retro-linked`,
        link: `/audit?row=${res.audit_id}`,
      })
      setResolved((v) => [...v, item.id])
      setCandidate(null); setReason('')
    } catch (e) {
      toast.push({ tone: 'error', text: e.message })
    } finally { setBusy(false) }
  }

  return (
    <div className="split">
      <div className="split-list">
        <div className="tbl-foot" style={{ borderTop: 0, borderBottom: '1px solid var(--border)' }}>
          <strong>{rows.length}</strong> awaiting resolution
        </div>
        <div className="split-scroll">
          {rows.map((r) => (
            <button key={r.id} className={`q-row ${item.id === r.id ? 'selected' : ''}`} onClick={() => setSelected(r.id)}>
              <div className="strong">{r.incoming.name}</div>
              <div className="caption mono">{r.incoming.email}</div>
              <div className="row gap-2 wrap" style={{ marginTop: 4 }}>
                <Chip>{systemName(r.incoming.source)}</Chip>
                <Chip icon="☰">{r.case_count} case{r.case_count > 1 ? 's' : ''}</Chip>
                <Chip tone="warning" icon="⚠">best {r.best_score.toFixed(2)}</Chip>
                <span className="right meta" title={absolute(r.queued_at)}>{relative(r.queued_at)}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      <div className="stack gap-3">
        <Notice tone="info" icon="🛈" title="Why this queue exists">
          A match below threshold is never guessed. It queues here so a human decides, and without this
          surface the queue would silently accumulate. Resolving writes an audit row and retro-links the
          actor's cases — it mutates the canonical identity link only, never an external system.
        </Notice>

        <div className="grid grid-2">
          <div className="card">
            <div className="card-head"><span className="card-title">Incoming identity</span></div>
            <dl style={{ margin: 0, fontSize: 'var(--fs-table)' }}>
              <div className="row gap-2"><dt className="caption" style={{ width: 90 }}>Name</dt><dd style={{ margin: 0 }}>{item.incoming.name}</dd></div>
              <div className="row gap-2"><dt className="caption" style={{ width: 90 }}>Email</dt><dd className="mono" style={{ margin: 0 }}>{item.incoming.email}</dd></div>
              <div className="row gap-2"><dt className="caption" style={{ width: 90 }}>Source</dt><dd style={{ margin: 0 }}>{systemName(item.incoming.source)}</dd></div>
              <div className="row gap-2"><dt className="caption" style={{ width: 90 }}>First seen</dt><dd style={{ margin: 0 }} title={absolute(item.incoming.first_seen)}>{relative(item.incoming.first_seen)}</dd></div>
            </dl>
          </div>

          <div className="stack gap-2">
            {item.candidates.map((c, i) => (
              <div key={c.id} className="card" style={{ borderColor: candidate === c.id ? 'var(--primary-700)' : undefined }}>
                <label className="row gap-2">
                  <input type="radio" name="cand" checked={candidate === c.id} onChange={() => setCandidate(c.id)} />
                  <span className="grow">
                    <span className="strong">{c.label}</span>
                    <span className="caption" style={{ display: 'block' }}>{systemName(c.system)} · score {c.score.toFixed(2)}</span>
                  </span>
                  <span className="kbd">{i + 1}</span>
                </label>
                <table className="tbl" style={{ marginTop: 'var(--sp-2)' }}>
                  <thead><tr><th>Field</th><th>Incoming</th><th>Candidate</th><th>Verdict</th></tr></thead>
                  <tbody>
                    {c.fields.map((f) => (
                      <tr key={f.field}>
                        <td className="caption">{f.field}</td>
                        <td className="mono">{f.incoming}</td>
                        <td className="mono">{f.candidate}</td>
                        <td className="caption">{f.verdict}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="row gap-2 wrap">
            <Button variant="primary" disabled={!candidate || busy} loading={busy} onClick={() => act('resolve')}>
              Resolve as selected candidate <span className="kbd">⌘Enter</span>
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => act('new')}>Mark as new actor</Button>
            <Button variant="destructive" disabled={busy || reason.trim().length < 10} onClick={() => act('dismiss')}>
              Dismiss (needs data)
            </Button>
          </div>
          <div className="field" style={{ marginTop: 'var(--sp-3)' }}>
            <label className="field-label" htmlFor="dismiss-reason">Dismissal reason (required to dismiss)</label>
            <input id="dismiss-reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)}
                   placeholder="e.g. shared mailbox — no worker record should ever be matched to it" />
          </div>
        </div>
      </div>
    </div>
  )
}

/* ---------------- Screen ---------------- */
export default function Connections({ tab: initialTab = 'systems' }) {
  const { role, meta } = useSession()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const tab = initialTab
  const [expanded, setExpanded] = useState(params.get('system'))
  const [runLog, setRunLog] = useState(null)
  const { data, loading, error, reload } = useAsync(() => api.listConnections(), [])

  const mayRerun = canAct(role, 'reconciliation.rerun')

  return (
    <div className="page">
      <div className="page-head row gap-3 wrap">
        <div className="grow">
          <h1 className="page-title">Connections</h1>
          <div className="page-sub">
            S-02 · six emulated source systems, their ingestion completeness and the identity gate.
            Nothing here is a live tenant, and nothing here says "live".
          </div>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} />
      </div>

      <div className="tabs" role="tablist" aria-label="Connections">
        <button className="tab" role="tab" aria-selected={tab === 'systems'} onClick={() => nav('/connections')}>
          Systems
        </button>
        <button className="tab" role="tab" aria-selected={tab === 'identity'} onClick={() => nav('/connections/identity')}>
          Identity queue <Chip tone="warning">2</Chip>
        </button>
      </div>

      <div style={{ paddingTop: 'var(--sp-4)' }} role="tabpanel">
        {tab === 'identity' ? <IdentityTab /> : (
          <>
            {loading && <SkeletonBlock lines={10} />}
            {error && <ErrorState dependency="Reconciliation job" traceId={error.trace_id} onRetry={reload} />}
            {data && (
              <>
                <div className="section">
                  <div className="card card-1">
                    <div className="row gap-4 wrap">
                      <div style={{ minWidth: 240 }}>
                        <div className="caption">Overall completeness</div>
                        <div className="row gap-2">
                          <span style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>{pct(data.completeness, 2)}</span>
                          {data.completeness >= 1
                            ? <Chip tone="success" icon="✓">all reconciled objects match</Chip>
                            : <Chip tone="warning" icon="⚠">one object short</Chip>}
                        </div>
                        <Meter value={data.completeness} tone={data.completeness >= 1 ? 'success' : 'warning'}
                               label={`overall completeness ${pct(data.completeness, 2)}`} />
                        <div className="meta" style={{ marginTop: 6 }}>
                          Measured over reconciled objects. {data.in_flight > 0
                            ? `${data.in_flight} object is still syncing and is reported separately rather than counted as a gap.`
                            : 'No object is mid-sync.'}
                        </div>
                      </div>
                      <div className="grow">
                        <Notice tone="info" icon="⌬" title="Every source below is emulated">
                          These are high-fidelity replicas seeded from a synthetic corpus. The `Emulated`
                          chip on each card is unconditional and non-dismissable, and the same chip appears
                          on every evidence card the pipeline produces.
                        </Notice>
                      </div>
                      <div>
                        <Button variant="secondary" disabled={!mayRerun}
                                deniedReason={!mayRerun ? DENY_REASON['reconciliation.rerun'] : undefined}
                                onClick={() => toast.push({ tone: 'info', text: 'Reconciliation re-run queued · audit row written' })}>
                          Re-run reconciliation
                        </Button>
                        <div className="meta" style={{ marginTop: 4, maxWidth: 170 }}>Admin only. Audit-logged.</div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="grid grid-3">
                  {data.systems.map((c) => (
                    <SystemCard
                      key={c.system}
                      conn={c}
                      expanded={expanded === c.system}
                      onToggle={() => setExpanded((v) => (v === c.system ? null : c.system))}
                      onRunLog={() => setRunLog(c)}
                    />
                  ))}
                </div>

                {runLog && (
                  <div className="section">
                    <div className="card">
                      <div className="card-head">
                        <span className="card-title">Run log · {systemName(runLog.system)}</span>
                        <Button variant="ghost" size="sm" className="right" onClick={() => setRunLog(null)}>Close</Button>
                      </div>
                      {runLog.run_log.map((l, i) => (
                        <div className="row gap-3" key={i} style={{ padding: '4px 0', fontSize: 'var(--fs-table)' }}>
                          <span className="meta mono" style={{ width: 180 }}>{absolute(l.ts)}</span>
                          <span>{l.text}</span>
                        </div>
                      ))}
                      <p className="meta">
                        Checkpointed and resumable. A rate-limit storm costs time, not data — and the run log
                        is where that claim is checkable rather than asserted.
                      </p>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
