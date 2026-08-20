/* S-10 · KB draft review [F-086, F-072, F-073].
   Scope Class: POC functional.

   The approved verb is precisely "Create/update Zendesk Guide draft (draft=true)".
   No "Publish live" control exists anywhere on this screen — not disabled, not
   hidden behind a role. It does not exist, and that absence is the guarantee. */

import React, { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Chip, ScopeBanner, Drill } from '../ui/primitives.jsx'
import { EmptyState, ErrorState, Notice, SkeletonBlock, useToast } from '../ui/feedback.jsx'
import { Modal } from '../ui/overlays.jsx'
import { DiffView, Table } from '../ui/data.jsx'
import { useAsync } from '../shell/hooks.js'
import { useSession } from '../shell/session.jsx'
import DrillPanel, { useDrill } from './DrillPanel.jsx'
import * as api from '../mock/api.js'
import { KB_APPROVED_VERB, ScopeClass } from '../contracts/state.js'
import { canAct, isDisabled, DENY_REASON } from '../contracts/rbac.js'
import { config } from '../contracts/config.js'
import { absolute, relative, num } from '../contracts/format.js'

const TABS = [
  { key: 'drafts', label: 'Pending drafts' },
  { key: 'updates', label: 'Updates' },
  { key: 'gaps', label: 'Gaps' },
]

function RejectModal({ onClose, onSubmit, busy }) {
  const [reason, setReason] = useState('')
  const [err, setErr] = useState(null)
  return (
    <Modal
      title="Reject this draft"
      onClose={onClose}
      subtitle="The reason is recorded on the audit row and feeds the Curator's next attempt."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" fill loading={busy}
                  onClick={() => reason.trim().length < config.reject_reason_min_chars
                    ? setErr(`At least ${config.reject_reason_min_chars} characters. Your text is preserved.`)
                    : onSubmit(reason)}>
            Reject
          </Button>
        </>
      }
    >
      <div className="field">
        <label className="field-label" htmlFor="kb-reason">Reason (required)</label>
        <textarea id="kb-reason" className={`textarea ${err ? 'textarea-error' : ''}`} autoFocus
                  value={reason} onChange={(e) => { setReason(e.target.value); setErr(null) }} />
        {err && <span className="field-msg" role="alert"><span aria-hidden="true">⚠</span>{err}</span>}
      </div>
    </Modal>
  )
}

export default function Knowledge() {
  const { role, meta } = useSession()
  const toast = useToast()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'drafts'
  const { data, loading, error, reload } = useAsync(() => api.listKbDrafts(), [])
  const [selectedId, setSelectedId] = useState(params.get('draft'))
  const [rejecting, setRejecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [decided, setDecided] = useState({})
  const drill = useDrill('knowledge')

  const may = canAct(role, 'kb.draft.decide')
  const denied = isDisabled(role, 'kb.draft.decide') ? DENY_REASON['kb.draft.decide'] : undefined

  const setTab = (t) => {
    const next = new URLSearchParams(params)
    next.set('tab', t)
    setParams(next, { replace: true })
  }

  if (loading) return <div className="page"><SkeletonBlock lines={12} /></div>
  if (error) return <div className="page"><ErrorState dependency="KB Curator" traceId={error.trace_id} onRetry={reload} /></div>

  const pool = tab === 'updates'
    ? data.drafts.filter((d) => d.kind === 'update')
    : data.drafts.filter((d) => d.kind === 'new')
  const selected = pool.find((d) => d.id === selectedId) || pool[0]

  const decide = async (action, reason) => {
    setBusy(true)
    try {
      const res = await api.submitKbDecision(selected.id, action, { reason })
      setDecided((v) => ({ ...v, [selected.id]: res.verb }))
      toast.push({
        tone: action === 'reject' ? 'info' : 'success',
        text: action === 'reject'
          ? `Rejected · audit ${res.audit_id}`
          : `${KB_APPROVED_VERB} · audit ${res.audit_id}`,
        link: `/audit?row=${res.audit_id}`,
      })
      setRejecting(false)
    } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <div className="page-head row gap-3 wrap">
        <div className="grow">
          <h1 className="page-title">Knowledge</h1>
          <div className="page-sub">
            S-10 · turn a good resolution into a good article — or refuse — beside the evidence.
          </div>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} note="draft=true only" />
      </div>

      <div className="tabs" role="tablist" aria-label="Knowledge">
        {TABS.map((t) => (
          <button key={t.key} className="tab" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}>
            {t.label}
            {t.key === 'gaps' && <Chip tone="warning" style={{ marginLeft: 6 }}>{data.gaps.length}</Chip>}
          </button>
        ))}
      </div>

      <div style={{ paddingTop: 'var(--sp-4)' }} role="tabpanel">
        {tab === 'gaps' ? (
          <div className="stack gap-3">
            <Notice tone="info" icon="🛈" title="Ranked by volume × median handling cost">
              A gap is a class the knowledge corpus cannot answer. Requesting a draft queues the Curator; it
              does not create anything by itself.
            </Notice>
            <Table
              ariaLabel="Knowledge gaps"
              rows={data.gaps}
              rowKey={(r) => r.class}
              columns={[
                { key: 'class', label: 'Class', render: (r) => <span className="mono">{r.class}</span> },
                { key: 'vol', label: 'Cases (30d)', numeric: true,
                  render: (r) => <Drill onClick={() => drill({ class: r.class }, `KB gap: ${r.class}`)}>{num(r.volume_30d)}</Drill> },
                { key: 'cost', label: 'Median handling', numeric: true, render: (r) => `${r.handling_cost_min}m` },
                { key: 'articles', label: 'Articles', numeric: true,
                  render: (r) => r.articles === 0
                    ? <Chip tone="danger" icon="✕">none</Chip>
                    : <Chip tone="warning" icon="⚠">{r.articles}</Chip> },
                { key: 'note', label: 'Why it is a gap', render: (r) => <span className="caption">{r.note}</span> },
                { key: 'act', label: '', render: (r) => (
                  <Button size="sm" variant="secondary" disabled={!may} deniedReason={denied}
                          onClick={() => toast.push({ tone: 'info', text: `Draft requested for ${r.class} · the Curator is queued` })}>
                    Request draft
                  </Button>
                ) },
              ]}
            />
          </div>
        ) : !selected ? (
          <EmptyState icon="✓" title="No drafts pending"
                      message="The Curator has nothing waiting. New resolutions produce drafts as they close." />
        ) : (
          <div className="split">
            <div className="split-list">
              <div className="split-scroll">
                {pool.map((d) => (
                  <button key={d.id} className={`q-row ${selected.id === d.id ? 'selected' : ''}`}
                          onClick={() => setSelectedId(d.id)}>
                    <div className="strong" style={{ fontSize: 'var(--fs-table)' }}>{d.title}</div>
                    <div className="row gap-2 wrap" style={{ marginTop: 4 }}>
                      <Chip tone={d.kind === 'update' ? 'info' : 'neutral'}>{d.kind}</Chip>
                      {d.dedupe.warn && <Chip tone="warning" icon="⚠">near-duplicate {d.dedupe.similarity.toFixed(2)}</Chip>}
                      {decided[d.id] && <Chip tone="success" icon="✓">decided</Chip>}
                      <span className="right meta" title={absolute(d.generated_at)}>{relative(d.generated_at)}</span>
                    </div>
                  </button>
                ))}
              </div>
              <div className="tbl-foot">
                <span className="grow">Recent decisions</span>
              </div>
              {data.decided.map((h) => (
                <div key={h.id} style={{ padding: 'var(--sp-2) var(--sp-3)', borderTop: '1px solid var(--border)' }}>
                  <div className="caption truncate">{h.title}</div>
                  <div className="row gap-2">
                    <Chip tone={h.decision === 'rejected' ? 'danger' : 'success'}>
                      {h.decision === 'rejected' ? 'rejected' : 'draft created'}
                    </Chip>
                    <span className="meta">{h.actor}</span>
                    <span className="right meta">{relative(h.at)}</span>
                  </div>
                  {h.reason && <div className="meta">“{h.reason}”</div>}
                </div>
              ))}
            </div>

            <div className="stack gap-3">
              {selected.dedupe.warn && (
                <Notice tone="warning" icon="⚠" title={`Near-duplicate: ${selected.dedupe.similarity.toFixed(2)} similarity`}>
                  Closest existing article: <strong>{selected.dedupe.nearest_article}</strong>.
                  {selected.kind === 'update'
                    ? ' The Curator proposes an update to it rather than a second article — the diff is below.'
                    : ' Consider updating the existing article instead of creating a near-twin.'}
                </Notice>
              )}

              <div className="grid grid-2">
                <div className="card">
                  <div className="card-head"><span className="card-title">{selected.kind === 'update' ? 'Proposed update' : 'Draft article'}</span></div>
                  {selected.body?.map((p, i) => (
                    <p key={i} style={{ fontSize: 'var(--fs-table)' }}
                       dangerouslySetInnerHTML={{ __html: p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>') }} />
                  ))}
                  {selected.proposed_update && (
                    <DiffView original={selected.proposed_update.original} edited={selected.proposed_update.updated}
                              leftLabel={`Current · ${selected.existing_article}`} rightLabel="Proposed" />
                  )}
                </div>

                <div className="card">
                  <div className="card-head"><span className="card-title">Source</span></div>
                  <dl style={{ margin: 0, fontSize: 'var(--fs-table)' }}>
                    <div className="row gap-2"><dt className="caption" style={{ width: 130 }}>ResolutionRecord</dt>
                      <dd className="mono" style={{ margin: 0 }}>{selected.source_resolution}</dd></div>
                    <div className="row gap-2"><dt className="caption" style={{ width: 130 }}>Originating case</dt>
                      <dd style={{ margin: 0 }}>
                        <Button variant="ghost" size="sm" onClick={() => nav(`/case/${selected.source_case}?origin=knowledge`)}>
                          {selected.source_case} →
                        </Button>
                      </dd></div>
                    <div className="row gap-2"><dt className="caption" style={{ width: 130 }}>Generated</dt>
                      <dd style={{ margin: 0 }} title={absolute(selected.generated_at)}>{relative(selected.generated_at)}</dd></div>
                  </dl>
                  <Notice tone="info" icon="🛈" title="What approval actually does">
                    <strong>{KB_APPROVED_VERB}</strong>. Publication beyond draft status is a separate,
                    gated act outside this console. There is no control on this screen that makes content
                    publicly live — not disabled, not role-gated. It does not exist.
                  </Notice>
                </div>
              </div>

              {decided[selected.id] ? (
                <Notice tone="success" icon="✓" title="Decision recorded">{decided[selected.id]}</Notice>
              ) : (
                <div className="card" style={{ background: 'var(--surface-1)' }}>
                  <div className="row gap-2 wrap">
                    <Button variant="primary" loading={busy} disabled={!may} deniedReason={denied}
                            onClick={() => decide('approve')}>
                      {selected.kind === 'update' ? 'Approve update as draft' : 'Approve as draft'}
                    </Button>
                    <Button variant="secondary" disabled={!may} deniedReason={denied}>Edit then approve</Button>
                    <Button variant="destructive" disabled={!may} deniedReason={denied} onClick={() => setRejecting(true)}>
                      Reject
                    </Button>
                    {!may && <span className="right caption" style={{ maxWidth: 340 }}>{denied}</span>}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {rejecting && <RejectModal busy={busy} onClose={() => setRejecting(false)} onSubmit={(r) => decide('reject', r)} />}
      <DrillPanel originLabel="knowledge" />
    </div>
  )
}
