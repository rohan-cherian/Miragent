/* S-08 · Analyst recommendation panel [F-128, F-127, F-126, F-063, F-064].
   Scope Class: POC functional — SHADOW-ONLY [F-064, OD-2].

   Two guardrails are structural here, not stylistic:
     · This panel ranks FIT FOR THIS TICKET. There is no overall score, no
       cross-ticket rank, no export, no league table — and employment type is
       neither displayed nor scored [F-127, §1.4].
     · Accept/override records evaluation feedback and an audit row. It performs
       NO external assignment write, and the chip says so in words.

   Every displayed number is click-through to the tickets that produced it — an
   unexplained recommendation is one a team lead will ignore [NFR-42]. */

import React, { useState } from 'react'
import { Button, Chip, Meter, ShadowChip, StretchChip, Drill } from '../../ui/primitives.jsx'
import { EmptyState, Notice, SkeletonBlock } from '../../ui/feedback.jsx'
import { useAsync } from '../../shell/hooks.js'
import * as api from '../../mock/api.js'
import { SCORE_COMPONENTS } from '../../fixtures/details.js'
import { pct, num } from '../../contracts/format.js'
import { canAct, isDisabled, DENY_REASON } from '../../contracts/rbac.js'
import { useSession } from '../../shell/session.jsx'
import { useDrill } from '../DrillPanel.jsx'

function Candidate({ c, expanded, onToggle, onDrillCases, selected, onSelect }) {
  return (
    <article className="card" style={{ padding: 0, marginBottom: 'var(--sp-2)' }}>
      <div className="row gap-3" style={{ padding: 'var(--sp-3)' }}>
        <input
          type="radio" name="shortlist" checked={selected} onChange={onSelect}
          aria-label={`Select ${c.name}`}
        />
        <div style={{ minWidth: 170 }}>
          <div className="strong">{c.name}</div>
          <div className="caption">{c.level}</div>
        </div>
        <div style={{ width: 170 }}>
          <Meter value={c.score} label={`fit score ${c.score}`} />
          <div className="caption num" style={{ marginTop: 2 }}>fit {c.score.toFixed(2)}</div>
        </div>
        <div className="grow">
          <div className="caption">{c.evidence_line}</div>
          <div className="row gap-2 wrap" style={{ marginTop: 4 }}>
            {c.stretch && <StretchChip />}
            <Chip tone={c.availability.within_working_hours ? 'success' : 'neutral'}
                  icon={c.availability.within_working_hours ? '✓' : '○'}>
              {c.availability.within_working_hours ? 'within working hours' : 'outside working hours'}
            </Chip>
            <Chip icon="☰">{c.availability.open_tickets} open</Chip>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onToggle} aria-expanded={expanded}>
          {expanded ? 'Collapse' : 'Why this score'}
        </Button>
      </div>

      {expanded && (
        <div style={{ padding: '0 var(--sp-3) var(--sp-3)', borderTop: '1px solid var(--border)' }}>
          {c.stretch && (
            <Notice tone="info" icon="↗" title="Stretch assignment">{c.stretch_rationale}</Notice>
          )}

          <h4 className="caption" style={{ margin: 'var(--sp-3) 0 var(--sp-2)' }}>
            Score components — deterministic weights, reproducible from case data
          </h4>
          {SCORE_COMPONENTS.map((comp) => (
            <div className="row gap-3" key={comp.key} style={{ marginBottom: 6 }}>
              <span className="caption" style={{ width: 170 }}>{comp.label}</span>
              <span className="caption dim num" style={{ width: 42 }}>×{comp.weight.toFixed(2)}</span>
              <span className="grow"><Meter value={c.components[comp.key]} label={`${comp.label} ${c.components[comp.key]}`} /></span>
              <span className="caption num" style={{ width: 42, textAlign: 'right' }}>{c.components[comp.key].toFixed(2)}</span>
            </div>
          ))}
          <p className="meta">
            This is a weighted fit score, not a probability — no confidence band language is used for it.
            Employment type is not one of the inputs and never will be.
          </p>

          <h4 className="caption" style={{ margin: 'var(--sp-4) 0 var(--sp-2)' }}>Measured history in this class</h4>
          <table className="tbl">
            <tbody>
              <tr>
                <td>Tickets handled</td>
                <td className="strong">
                  <Drill onClick={() => onDrillCases(c)} title="Open the cases behind this number">
                    {c.history.tickets_handled}
                  </Drill>
                </td>
                <td>Avg handle time</td><td className="strong">{c.history.avg_handle_time_min}m</td>
              </tr>
              <tr>
                <td>Reopen rate</td><td className="strong">{pct(c.history.reopen_rate, 1)}</td>
                <td>Escalation rate</td><td className="strong">{pct(c.history.escalation_rate, 1)}</td>
              </tr>
              <tr>
                <td>CSAT average</td><td className="strong">{c.history.csat_avg.toFixed(1)}</td>
                <td>QA score</td><td className="strong">{c.history.qa_score_avg.toFixed(2)}</td>
              </tr>
            </tbody>
          </table>

          <h4 className="caption" style={{ margin: 'var(--sp-4) 0 var(--sp-2)' }}>Skills & provenance</h4>
          <div className="row gap-2 wrap">
            {c.skills.map((s) => (
              <Chip key={s.name} tone={s.provenance === 'certified' ? 'success' : s.provenance === 'manager' ? 'info' : 'neutral'}>
                {s.name} · {s.level}/5 · {s.provenance}
              </Chip>
            ))}
          </div>

          <h4 className="caption" style={{ margin: 'var(--sp-4) 0 var(--sp-2)' }}>Capability signals</h4>
          {c.signals.length === 0 ? (
            <Notice tone="info" icon="∅">
              {c.signals_suppressed || 'No signal is emitted for this analyst in this class.'}
              {' '}A signal below its sample floor is not shown at all — it is not shown greyed out, and it is
              not shown with a caveat. It is absent.
            </Notice>
          ) : (
            c.signals.map((s) => (
              <div className="row gap-3 caption" key={s.type} style={{ marginBottom: 4 }}>
                <Chip>{s.type}</Chip>
                <span className="grow">{s.metric}</span>
                <span>team median {s.team_median}</span>
                <span>n={s.sample_size}</span>
                <span>confidence {s.confidence}</span>
              </div>
            ))
          )}
        </div>
      )}
    </article>
  )
}

export default function Assignment({ caseId, classId }) {
  const { role } = useSession()
  const { data, loading } = useAsync(() => api.getShortlist(caseId), [caseId])
  const [expanded, setExpanded] = useState(null)
  const [selected, setSelected] = useState(null)
  const [feedback, setFeedback] = useState(null)
  const [busy, setBusy] = useState(false)
  const drill = useDrill('assignment')

  if (loading) return <SkeletonBlock lines={8} />
  if (!data) return <EmptyState icon="∅" title="No assignment proposal for this case" />

  const may = canAct(role, 'assignment.feedback')
  const denied = isDisabled(role, 'assignment.feedback') ? DENY_REASON['assignment.feedback'] : undefined

  const record = async (kind) => {
    setBusy(true)
    const target = selected || data.candidates[0]?.analyst_id
    const res = await api.submitAssignmentFeedback(caseId, target, kind)
    setFeedback(res)
    setBusy(false)
  }

  const drillCases = (c) => drill({ ids: (c.case_ids || []).join(','), class: classId, assignee: c.analyst_id },
    `${c.name} · ${c.history.tickets_handled} handled in ${classId}`)

  return (
    <div className="stack gap-3">
      <div className="row gap-2 wrap">
        <span className="card-title">Shortlist</span>
        <ShadowChip />
        {data.needed_skills?.map((s) => <Chip key={s} icon="◆">{s}</Chip>)}
      </div>

      <Notice tone="info" icon="◐" title="Shadow mode — recommendations only; no ticket is reassigned">
        Accepting or overriding records evaluation feedback and an audit row. It performs no external
        assignment write. A write-enabled mode would require the architect's sign-off [OD-2]; until then no
        write-path state exists for assignment at all.
      </Notice>

      {data.held && (
        <Notice tone="warning" icon="⏸" title={`Held — conflicts with tenant trigger “${data.held_trigger}”`}>
          The customer's own automation would fire on this case. The proposal is held for a human decision
          rather than racing the tenant's rules.
        </Notice>
      )}

      {data.candidates.length === 0 ? (
        <EmptyState
          icon="↗"
          title="No eligible analyst above the floor"
          message={data.no_eligible_reason}
          action={<Chip tone="warning" icon="↗">Escalation suggested instead of a forced pick</Chip>}
        />
      ) : (
        <>
          {data.candidates.map((c) => (
            <Candidate
              key={c.analyst_id}
              c={c}
              expanded={expanded === c.analyst_id}
              onToggle={() => setExpanded((v) => (v === c.analyst_id ? null : c.analyst_id))}
              onDrillCases={drillCases}
              selected={selected === c.analyst_id}
              onSelect={() => setSelected(c.analyst_id)}
            />
          ))}

          {feedback && (
            <Notice tone="success" icon="✓" title={`Feedback recorded · audit ${feedback.audit_id}`}>
              State is <span className="mono">{feedback.state}</span>. <strong>No external assignment write
              occurred</strong> — the ticket's assignee in Zendesk is unchanged.
            </Notice>
          )}

          <div className="row gap-2">
            <Button variant="primary" loading={busy} disabled={!may} deniedReason={denied}
                    onClick={() => record('accept')}>
              Accept proposal
            </Button>
            <Button variant="secondary" loading={busy} disabled={!may || !selected} deniedReason={denied}
                    onClick={() => record('override')}>
              Choose selected
            </Button>
            <Button variant="ghost" disabled={!may} deniedReason={denied} onClick={() => record('decline')}>
              Decline
            </Button>
            <span className="right meta">
              Ordering is per-ticket fit. There is no overall analyst score anywhere in this product.
            </span>
          </div>
        </>
      )}
    </div>
  )
}
