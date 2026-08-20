/* S-07 · Triage, dedup & assignment explainers [F-084, F-059, F-060, F-062, F-065].
   Scope Class: POC functional.

   Job: understand WHY the system classified, linked and prioritised as it did.
   The deterministic numbers and the model's prose are visually separated
   throughout: the SLA number is computed and not editable, and the sentence
   beside it is labelled "explanation" so nobody mistakes it for the calculation. */

import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Chip, ConfidenceBand, Meter, SlaChip } from '../../ui/primitives.jsx'
import { Notice, SkeletonBlock, EmptyState } from '../../ui/feedback.jsx'
import { Modal } from '../../ui/overlays.jsx'
import { Timeline } from '../../ui/data.jsx'
import { useAsync } from '../../shell/hooks.js'
import * as api from '../../mock/api.js'
import { timelineFor } from '../../fixtures/details.js'
import { caseById } from '../../fixtures/corpus.js'
import { canAct, isDisabled, DENY_REASON } from '../../contracts/rbac.js'
import { useSession } from '../../shell/session.jsx'

function Block({ title, verdict, children, defaultOpen = false, tone }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="card" style={{ padding: 0 }}>
      <button
        className="row gap-3"
        style={{ width: '100%', border: 0, background: 'none', padding: 'var(--sp-3) var(--sp-4)', cursor: 'pointer', textAlign: 'left' }}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="card-title" style={{ minWidth: 120 }}>{title}</span>
        <span className="grow row gap-2 wrap">{verdict}</span>
        <span className="caption" aria-hidden="true">{open ? '▴ collapse' : '▾ expand for reasoning'}</span>
      </button>
      {open && <div style={{ padding: '0 var(--sp-4) var(--sp-4)' }}>{children}</div>}
    </section>
  )
}

/** Side-by-side compare view feeding the merge decision. */
function CompareView({ a, b, onClose, onConfirm, canConfirm, denyReason }) {
  return (
    <Modal
      wide
      title={`Compare ${a} and ${b}`}
      subtitle="A merge is an external write. It enters the same human gate as every other write — and you see both timelines before it does."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Keep as link</Button>
          <Button variant="primary" onClick={onConfirm} disabled={!canConfirm} deniedReason={denyReason}>
            Confirm merge
          </Button>
        </>
      }
    >
      <div className="grid grid-2">
        {[a, b].map((id) => {
          const c = caseById(id)
          return (
            <div key={id}>
              <div className="row gap-2" style={{ marginBottom: 'var(--sp-2)' }}>
                <span className="mono strong">{id}</span>
                <Chip>{c?.channel}</Chip>
                <SlaChip deadline={c?.sla_deadline} paused={c?.sla_paused} />
              </div>
              <p className="caption">{c?.subject}</p>
              <Timeline entries={timelineFor(id).slice(0, 5)} />
            </div>
          )
        })}
      </div>
      <Notice tone="warning" icon="⚠" title="Precision is favoured over recall here">
        A false merge destroys two case histories at once and is the costly error in this class.
        The system proposes; it never merges on its own.
      </Notice>
    </Modal>
  )
}

export default function Explainers({ caseId, onOpenAssignment }) {
  const { role, stubUser } = useSession()
  const nav = useNavigate()
  const { data: x, loading } = useAsync(() => api.getExplainers(caseId), [caseId])
  const [compare, setCompare] = useState(null)
  const [merged, setMerged] = useState(false)

  if (loading) return <SkeletonBlock lines={10} />
  if (!x) return <EmptyState icon="∅" title="No explainers for this case" />

  const cls = x.classification
  const mayMerge = canAct(role, 'merge.confirm')
  const mergeDenied = isDisabled(role, 'merge.confirm') ? DENY_REASON['merge.confirm'] : undefined

  return (
    <div className="stack gap-3">
      {/* ---- Classification ---- */}
      <Block
        title="Classification"
        defaultOpen
        verdict={
          <>
            <span className="mono strong">{cls.class}</span>
            <ConfidenceBand band={cls.band} value={cls.confidence} />
            <Chip>sentiment {cls.sentiment}</Chip>
            <Chip>lang {cls.language}</Chip>
            <Chip tone={cls.prior.agreed ? 'success' : 'warning'} icon={cls.prior.agreed ? '✓' : '≠'}>
              {cls.prior.source} prior {cls.prior.agreed ? 'agreed' : `disagreed (${cls.prior.value})`}
            </Chip>
            {cls.needs_human_triage && <Chip tone="danger" icon="⚠">needs human triage</Chip>}
          </>
        }
      >
        {cls.needs_human_triage && (
          <Notice tone="warning" icon="⚠" title="Below the calibrated threshold — so it did not guess">
            Confidence is {cls.confidence.toFixed(2)}. Rather than emit a class it is not confident in, the
            classifier escalated once to a stronger model and then flagged the case for a human. The
            alternatives below are shown with their scores so you can see how close the call was.
          </Notice>
        )}
        <h4 className="caption" style={{ margin: 'var(--sp-3) 0 var(--sp-2)' }}>Alternative classes considered</h4>
        {cls.alternatives.map((a) => (
          <div className="row gap-3" key={a.class} style={{ marginBottom: 6 }}>
            <span className="mono caption" style={{ width: 200 }}>{a.class}</span>
            <span className="grow"><Meter value={a.score} label={`${a.class} ${a.score}`} /></span>
            <span className="caption num">{a.score.toFixed(2)}</span>
          </div>
        ))}
      </Block>

      {/* ---- Duplicates ---- */}
      <Block
        title="Duplicates"
        defaultOpen={x.duplicates.length > 0}
        verdict={
          x.duplicates.length === 0
            ? <span className="caption">No candidates above threshold</span>
            : x.duplicates.map((d) => (
                <Chip key={d.case_id} tone={d.proposal === 'merge' ? 'warning' : 'neutral'}
                      icon={d.proposal === 'merge' ? '⧉' : '🔗'}>
                  {d.case_id} · {d.similarity.toFixed(2)} · {d.proposal}
                </Chip>
              ))
        }
      >
        {merged && <Notice tone="success" icon="✓" title="Merged">The merge was performed through the write gate and an audit row was written.</Notice>}
        {x.duplicates.map((d) => (
          <div className="card" key={d.case_id} style={{ marginBottom: 'var(--sp-2)', background: 'var(--surface-1)' }}>
            <div className="row gap-2 wrap">
              <span className="mono strong">{d.case_id}</span>
              <span className="num caption">similarity {d.similarity.toFixed(2)}</span>
              {d.proposal === 'merge'
                ? <Chip tone="warning" icon="⧉">merge proposed</Chip>
                : <Chip tone="neutral" icon="🔗">link only — below the merge threshold</Chip>}
            </div>
            <p className="caption" style={{ margin: 'var(--sp-2) 0' }}>{d.why}</p>
            <div className="row gap-2">
              <Button size="sm" variant="secondary" onClick={() => setCompare(d.case_id)}>
                Compare side by side
              </Button>
              <Button size="sm" variant="ghost" onClick={() => nav(`/case/${d.case_id}`)}>Open {d.case_id} →</Button>
            </div>
          </div>
        ))}
        <p className="meta">
          A mid-score candidate is linked and never proposed for merge — the threshold is the guard, not
          the reviewer's patience.
        </p>
      </Block>

      {/* ---- SLA & priority ---- */}
      {x.sla && (
        <Block
          title="SLA & priority"
          verdict={
            <>
              <SlaChip deadline={caseById(caseId)?.sla_deadline} paused={x.sla.paused} />
              <span className="caption">score {x.sla.score.toFixed(2)} · deterministic</span>
              <Chip>{x.sla.policy}</Chip>
            </>
          }
        >
          <div className="grid grid-2">
            <div>
              <h4 className="caption" style={{ marginBottom: 'var(--sp-2)' }}>
                Deterministic inputs — the number comes from these, and only these
              </h4>
              <table className="tbl">
                <tbody>
                  {x.sla.inputs.map((i) => (
                    <tr key={i.label}>
                      <td style={{ color: 'var(--ink-600)' }}>{i.label}</td>
                      <td className="strong">{i.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="meta" style={{ marginTop: 'var(--sp-2)' }}>
                The priority number is not editable anywhere in this console. It recomputes on every clock event.
              </p>
            </div>
            <div>
              <h4 className="caption" style={{ marginBottom: 'var(--sp-2)' }}>
                <Chip tone="info" icon="✎">explanation</Chip> — written by the model, changes nothing
              </h4>
              <p style={{ fontSize: 'var(--fs-table)', fontStyle: 'italic' }}>{x.sla.explanation}</p>
            </div>
          </div>
        </Block>
      )}

      {/* ---- Assignment summary ---- */}
      <Block
        title="Assignment"
        verdict={
          x.assignment_summary.held
            ? <Chip tone="warning" icon="⏸">held — trigger conflict</Chip>
            : x.assignment_summary.top
              ? <>
                  <span className="strong">{x.assignment_summary.top}</span>
                  <span className="caption num">score {x.assignment_summary.score.toFixed(2)}</span>
                  <Chip tone="info" icon="◐">shadow — no ticket is reassigned</Chip>
                </>
              : <span className="caption">No shortlist above the eligibility floor</span>
        }
      >
        {x.assignment_summary.held && (
          <Notice tone="warning" icon="⏸" title={`Conflicts with tenant trigger “${x.assignment_summary.held_trigger}”`}>
            The proposal is held rather than applied, because the customer's own automation would fire on
            this case. The system respects the tenant's rules instead of racing them.
          </Notice>
        )}
        <Button variant="secondary" size="sm" onClick={onOpenAssignment} style={{ marginTop: 'var(--sp-3)' }}>
          View the full shortlist and its evidence →
        </Button>
      </Block>

      {compare && (
        <CompareView
          a={caseId} b={compare}
          canConfirm={mayMerge}
          denyReason={mergeDenied}
          onClose={() => setCompare(null)}
          onConfirm={async () => {
            await api.confirmMerge(caseId, compare, { actor: stubUser })
            setMerged(true); setCompare(null)
          }}
        />
      )}
    </div>
  )
}
