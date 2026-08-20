/* S-09 · Audit viewer [F-085, F-089, F-101, F-094].
   Scope Class: POC functional.

   Job: reconstruct any decision — what was recommended, on what evidence, at what
   confidence, by which model, what the human did, and what happened — with zero
   gaps. This screen is also where the ABSENCE of an ungated write is
   demonstrated: every external effect in the corpus traces back to an approval
   record, and there is no row here that does not.

   The timeline is the immutable variant: no edit affordance exists at all. */

import React, { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Table, Timeline, DiffView } from '../ui/data.jsx'
import {
  Button, Chip, ConfidenceBand, QaFlagChip, ScopeBanner, Select, Meter,
} from '../ui/primitives.jsx'
import { EmptyState, ErrorState, Notice, SkeletonRows } from '../ui/feedback.jsx'
import { SidePanel } from '../ui/overlays.jsx'
import { useAsync, useUrlFilters } from '../shell/hooks.js'
import { useSession } from '../shell/session.jsx'
import * as api from '../mock/api.js'
import { draftFor } from '../fixtures/details.js'
import { absolute, relative, ms, num } from '../contracts/format.js'
import { ScopeClass } from '../contracts/state.js'
import { canAct, DENY_REASON, permission } from '../contracts/rbac.js'

const DECISION_TYPES = [
  { value: 'approved', label: 'Approved' },
  { value: 'edited_approved', label: 'Edited & approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'merge_declined', label: 'Merge declined' },
  { value: 'identity_resolved', label: 'Identity resolved' },
  { value: 'feedback_accepted', label: 'Routing gate — accepted' },
  { value: 'feedback_overridden', label: 'Routing gate — overridden' },
]
const OUTCOMES = [
  { value: 'succeeded', label: 'Write succeeded' },
  { value: 'write_failed', label: 'Write failed' },
  { value: 'no_write', label: 'No write (rejected/declined)' },
]

const TYPE_TONE = {
  approved: 'success', edited_approved: 'info', rejected: 'danger',
  merge_declined: 'neutral', identity_resolved: 'primary',
  feedback_accepted: 'info', feedback_overridden: 'neutral',
}
const OUTCOME_META = {
  succeeded:   { tone: 'success', icon: '✓', label: 'Written' },
  write_failed:{ tone: 'danger',  icon: '✕', label: 'Write failed' },
  no_write:    { tone: 'neutral', icon: '—', label: 'No write' },
}

function AuditDetail({ row, onClose }) {
  const entries = api.getAuditTimeline(row)
  const nav = useNavigate()
  const rejectedDraft = row.decision_type === 'rejected' && row.case_id !== '—'
    ? draftFor(row.case_id)
    : null
  return (
    <SidePanel
      wide
      title={`${row.id} · ${row.case_id}`}
      subtitle="Append-only decision record — recommendation → evidence → confidence → model → decision → write → outcome"
      onClose={onClose}
      footer={
        row.case_id !== '—' && (
          <Button variant="secondary" onClick={() => nav(`/case/${row.case_id}?origin=audit`)}>
            Open Ticket 360 for {row.case_id} →
          </Button>
        )
      }
    >
      <div className="stack gap-4">
        <div className="card">
          <div className="row gap-2 wrap">
            <Chip tone={TYPE_TONE[row.decision_type]}>{row.decision_type.replace('_', ' ')}</Chip>
            <Chip icon="👤">{row.actor}</Chip>
            {row.confidence != null && <ConfidenceBand band={row.confidence >= 0.85 ? 'High' : row.confidence >= 0.6 ? 'Medium' : 'Low'} value={row.confidence} />}
            {row.flagged && <QaFlagChip detail={row.flag_detail?.note} />}
          </div>
          <div className="row gap-4 wrap caption" style={{ marginTop: 'var(--sp-3)' }}>
            <span>model <strong>{row.model}</strong></span>
            <span>version <strong>{row.model_version}</strong></span>
            <span>latency <strong>{ms(row.latency_ms)}</strong></span>
            <span>cost <strong>${row.cost_usd}</strong></span>
            <span title={absolute(row.occurred_at)}>occurred <strong>{absolute(row.occurred_at)}</strong></span>
          </div>
          <p className="meta" style={{ marginTop: 'var(--sp-2)' }}>
            Confidence and model are shown <strong>as recorded at the time</strong>, never recomputed —
            the audit shows what was known then.
          </p>
        </div>

        {row.flag_detail && (
          <Notice tone="warning" icon="⚑" title={`QA/Verifier flag · groundedness ${row.flag_detail.groundedness}`}>
            {row.flag_detail.note}
          </Notice>
        )}

        {row.outcome === 'write_failed' && (
          <Notice tone="danger" icon="✕" title="The write failed and the approval survived it">
            The decision record is intact. The queue item carries “write failed — action required” and offers
            re-fire of execution only; nobody re-approves anything. Approval and write are separate states,
            and this row is what that separation looks like when it matters.
          </Notice>
        )}

        <div>
          <h3 style={{ marginBottom: 'var(--sp-3)' }}>Immutable timeline</h3>
          <Timeline entries={entries} immutable />
        </div>

        {row.diff && (
          <div>
            <h3 style={{ marginBottom: 'var(--sp-3)' }}>What the human changed</h3>
            <DiffView original={row.diff.original} edited={row.diff.edited} />
          </div>
        )}

        {row.reject_reason && (
          <Notice tone="info" icon="✎" title="Reject reason (structured data, not a note)">
            “{row.reject_reason}” — reasons feed the redraft instruction and the QA sample. This is the
            text a manager reads to learn where drafts fail.
          </Notice>
        )}

        {/* §10.9 micro-journey 3: a manager filters to rejections, reads the reasons,
            and clicks through to the DRAFTS. Reading why a draft was refused is not
            much use without seeing what was refused. */}
        {rejectedDraft && (
          <div>
            <h3 style={{ marginBottom: 'var(--sp-2)' }}>The draft that was rejected</h3>
            <p className="caption" style={{ marginTop: 0 }}>
              Shown as it stood at the moment of the decision — {rejectedDraft.model} · {rejectedDraft.version}.
              No external write followed it.
            </p>
            <div className="card" style={{ background: 'var(--surface-1)' }}>
              {rejectedDraft.sentences.map((s, i) =>
                s.withheld ? (
                  <span className="withheld" key={i}>
                    Sentence withheld — {s.withheld_reason}.
                  </span>
                ) : (
                  <p className="draft-sentence" key={i} style={{ margin: '0 0 var(--sp-2)' }}>
                    {s.text}
                    {s.cite?.map((n) => <span key={n} className="anchor" aria-label={`Citation ${n}`}>{n}</span>)}
                  </p>
                )
              )}
            </div>
          </div>
        )}
      </div>
    </SidePanel>
  )
}

export default function Audit() {
  const { role, meta } = useSession()
  const { filters, set, clear } = useUrlFilters(['from', 'to', 'type', 'actor', 'outcome', 'flagged', 'case_id'])
  const [params, setParams] = useSearchParams()
  const [openRow, setOpenRow] = useState(null)

  // Analyst sees only their own decisions (V-own in the §11.6 matrix).
  const scoped = permission(role, 'audit.view') === 'V-own'
    ? { ...filters, own: meta.stubUser }
    : filters

  const { data, loading, error, reload } = useAsync(
    () => api.listAuditDecisions(scoped), [JSON.stringify(scoped)]
  )

  const exportAllowed = canAct(role, 'audit.export')

  return (
    <div className="page">
      <div className="page-head row gap-3">
        <div className="grow">
          <h1 className="page-title">Audit</h1>
          <div className="page-sub">
            S-09 · the product's memory. Every recommendation, every human decision, every external write
            and every retry, as one append-only record per case.
          </div>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} />
      </div>

      {/* F-101 completeness header */}
      {data?.completeness && (
        <div className="section">
          <div className="card card-1">
            <div className="row gap-4 wrap">
              <div style={{ minWidth: 220 }}>
                <div className="caption">Demo-path audit completeness</div>
                <div className="row gap-2" style={{ marginTop: 4 }}>
                  <span style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>
                    {Math.round(data.completeness.pct * 100)}%
                  </span>
                  <Chip tone="success" icon="✓">complete</Chip>
                </div>
                <Meter value={data.completeness.pct} tone="success" label="audit completeness" />
                <div className="meta" style={{ marginTop: 6 }}>
                  {num(data.completeness.with_complete_chain)} of {num(data.completeness.demo_path_actions)} actions
                  carry a full chain · checked {absolute(data.completeness.checked_at)}
                </div>
              </div>
              <div className="grow">
                <Notice tone="success" icon="✓" title="What this screen proves by existing">
                  There is exactly one path to an external write in this product, and it runs through an
                  approval record. Filter to any write below and you will find its approval; there is no
                  row here without one, because there is no control anywhere that could produce one.
                </Notice>
              </div>
              <div>
                <Button
                  variant="secondary"
                  disabled={!exportAllowed}
                  deniedReason={!exportAllowed ? DENY_REASON['audit.export'] : undefined}
                >
                  Export CSV
                </Button>
                <div className="meta" style={{ marginTop: 4, maxWidth: 180 }}>
                  Admin only [A-07]. Your role: {meta?.name}.
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {permission(role, 'audit.view') === 'V-own' && (
        <div className="section">
          <Notice tone="info" icon="🔒">
            As <strong>{meta.name}</strong> you see your own decisions. Manager and Admin roles see every
            actor's. The filter below is applied server-side, not hidden in the UI.
          </Notice>
        </div>
      )}

      <div className="section">
        <div className="filter-bar">
          <Select label="Decision type" id="a-type" value={filters.type} onChange={(v) => set({ type: v })} options={DECISION_TYPES} />
          <Select label="Outcome" id="a-out" value={filters.outcome} onChange={(v) => set({ outcome: v })} options={OUTCOMES} />
          <Select label="Human" id="a-actor" value={filters.actor} onChange={(v) => set({ actor: v })}
                  options={api.auditActors().map((a) => ({ value: a, label: a }))} />
          <div className="field">
            <label className="field-label" htmlFor="a-from">From</label>
            <input id="a-from" className="input" type="date" value={filters.from || ''}
                   onChange={(e) => set({ from: e.target.value })} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="a-to">To</label>
            <input id="a-to" className="input" type="date" value={filters.to || ''}
                   onChange={(e) => set({ to: e.target.value })} />
          </div>
          <label className="row gap-2 caption" style={{ paddingBottom: 6 }}>
            <input type="checkbox" checked={filters.flagged === '1'}
                   onChange={(e) => set({ flagged: e.target.checked ? '1' : null })} />
            QA-flagged only
          </label>
          <Button variant="ghost" onClick={clear}>Clear</Button>
        </div>
        <div className="row gap-2 wrap" style={{ marginTop: 'var(--sp-2)' }}>
          <span className="caption">Manager shortcuts:</span>
          <Button size="sm" variant="secondary" onClick={() => set({ type: 'rejected', outcome: null, flagged: null })}>
            Rejections — read why drafts fail
          </Button>
          <Button size="sm" variant="secondary" onClick={() => set({ outcome: 'write_failed', type: null })}>
            Write failures
          </Button>
          <Button size="sm" variant="secondary" onClick={() => set({ flagged: '1', type: null, outcome: null })}>
            QA-flagged runs
          </Button>
        </div>
      </div>

      <div className="section">
        {loading && <SkeletonRows rows={10} />}
        {error && <ErrorState dependency="Audit service" traceId={error.trace_id} onRetry={reload} />}
        {data && (
          <Table
            ariaLabel="Decision audit"
            rows={data.rows}
            rowKey={(r) => r.id}
            onRowClick={setOpenRow}
            selectedKey={openRow?.id}
            columns={[
              { key: 'id', label: 'Audit', width: 92, render: (r) => <span className="mono">{r.id}</span> },
              { key: 'case', label: 'Case', width: 96, render: (r) => <span className="mono">{r.case_id}</span> },
              { key: 'agent', label: 'Agent', render: (r) => <span className="caption">{r.agent}</span> },
              { key: 'type', label: 'Decision',
                render: (r) => <Chip tone={TYPE_TONE[r.decision_type]}>{r.decision_type.replace('_', ' ')}</Chip> },
              { key: 'actor', label: 'Human', render: (r) => r.actor },
              { key: 'conf', label: 'Confidence',
                render: (r) => r.confidence == null
                  ? <span className="dim caption">deterministic</span>
                  : <ConfidenceBand band={r.confidence >= 0.85 ? 'High' : r.confidence >= 0.6 ? 'Medium' : 'Low'} value={r.confidence} /> },
              { key: 'outcome', label: 'Outcome',
                render: (r) => {
                  const m = OUTCOME_META[r.outcome] || { tone: 'neutral', icon: '•', label: r.outcome }
                  return (
                    <span className="row gap-2">
                      <Chip tone={m.tone} icon={m.icon}>{m.label}</Chip>
                      {r.flagged && <QaFlagChip detail={r.flag_detail?.note} />}
                    </span>
                  )
                } },
              { key: 'when', label: 'When', numeric: true,
                render: (r) => <span title={absolute(r.occurred_at)}>{relative(r.occurred_at)}</span> },
            ]}
            footer={
              <>
                <span>Showing <strong>{num(data.rows.length)}</strong> of <strong>{num(data.total)}</strong> records</span>
                <span className="right meta">Click a row for its immutable timeline. Timestamps in audit are always absolute.</span>
              </>
            }
            emptyState={
              <EmptyState icon="∅" title="No audit records match these filters"
                          message="Try widening the date range, or clear the filters to see the full trail."
                          action={<Button variant="secondary" onClick={clear}>Clear filters</Button>} />
            }
          />
        )}
      </div>

      {openRow && <AuditDetail row={openRow} onClose={() => setOpenRow(null)} />}
    </div>
  )
}
