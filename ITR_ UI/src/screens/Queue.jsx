/* S-04 · Approval queue [F-081, F-093, F-088] — the workhorse.
   Scope Class: POC functional.

   This is where the recommendation-only stance becomes a working practice.
   Three things are structural, not decorative:
     · Decision and write are separate visible states. Success never renders on
       the approval record alone — it renders on `succeeded`.
     · A Low band suppresses one-click approve. The friction is deliberate.
     · No control on this screen writes externally without producing an approval
       record, because there is no such control to add.

   For the Manager role every decision control is disabled-with-explanation
   rather than hidden: a director should be able to see the work being judged
   without being able to judge it. */

import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Button, Chip, ConfidenceBand, SlaChip, ScopeBanner, Select, Drill, QaFlagChip,
  suppressesFastApprove,
} from '../ui/primitives.jsx'
import { EmptyState, ErrorState, Notice, SkeletonRows, useToast } from '../ui/feedback.jsx'
import { Modal } from '../ui/overlays.jsx'
import { DiffView, EvidenceCard } from '../ui/data.jsx'
import { useAsync, useUrlFilters, useListKeys } from '../shell/hooks.js'
import { useSession } from '../shell/session.jsx'
import * as api from '../mock/api.js'
import { packFor } from '../fixtures/details.js'
import { actorMeta, CLASSES, TEAMS } from '../fixtures/corpus.js'
import { config } from '../contracts/config.js'
import { age, relative, absolute } from '../contracts/format.js'
import {
  ScopeClass, Band, ItemType, DecisionState, WriteState, WRITE_COPY, isWritePending,
} from '../contracts/state.js'
import { canAct, isDisabled, DENY_REASON } from '../contracts/rbac.js'
import { emit } from '../contracts/telemetry.js'

/* ---------------- Write-state pill: the second machine, always visible ---------------- */
function WritePill({ state, attempts }) {
  if (state === WriteState.NOT_STARTED) return null
  const tone = state === WriteState.SUCCEEDED ? 'success'
    : state === WriteState.FAILED ? 'danger'
    : state === WriteState.RETRYING ? 'warning' : 'info'
  const icon = state === WriteState.SUCCEEDED ? '✓'
    : state === WriteState.FAILED ? '✕'
    : state === WriteState.RETRYING ? '↻' : '⋯'
  return (
    <Chip tone={tone} icon={icon}>
      {WRITE_COPY[state]}{state === WriteState.RETRYING ? ` (attempt ${attempts})` : ''}
    </Chip>
  )
}

/* ---------------- Draft pane: anchors, and visible withholding ---------------- */
function DraftPane({ draft, onAnchor, editing, editedText, onEditText }) {
  if (editing) {
    return (
      <div className="stack gap-2">
        <label className="field-label" htmlFor="draft-edit">Editing the draft — citation anchors are preserved</label>
        <textarea id="draft-edit" className="textarea" style={{ minHeight: 260 }}
                  value={editedText} onChange={(e) => onEditText(e.target.value)} autoFocus />
        <span className="field-hint">⌘Enter approves the edited text. The diff is stored on the audit row.</span>
      </div>
    )
  }
  return (
    <div className="stack gap-2">
      {draft.sentences.map((s, i) =>
        s.withheld ? (
          <span className="withheld" key={i}>
            <strong>Sentence withheld — no supporting evidence.</strong>{' '}
            {s.withheld_reason}. You are seeing what the system declined to claim; that is the point of
            showing it rather than dropping it silently.
          </span>
        ) : (
          <p className="draft-sentence" key={i} style={{ margin: 0 }}>
            {s.text}
            {s.cite?.map((n) => (
              <button key={n} className="anchor" onClick={() => onAnchor(n)}
                      title={`Jump to evidence card ${n}`} aria-label={`Citation ${n}`}>
                {n}
              </button>
            ))}
            {s.boilerplate && <span className="meta"> (greeting — no claim, no citation needed)</span>}
          </p>
        )
      )}
    </div>
  )
}

/* ---------------- Reject modal: reason is mandatory and structured ---------------- */
function RejectModal({ onClose, onSubmit, busy }) {
  const [reason, setReason] = useState('')
  const [err, setErr] = useState(null)
  const submit = async () => {
    if (reason.trim().length < config.reject_reason_min_chars) {
      setErr(`A reason of at least ${config.reject_reason_min_chars} characters is required. Your text is preserved.`)
      return
    }
    onSubmit(reason)
  }
  return (
    <Modal
      title="Reject this draft"
      subtitle="The reason is structured data: it feeds the redraft instruction and the QA sample, and a manager reads it later to see where drafts fail."
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="destructive" fill loading={busy} onClick={submit}>Reject</Button>
        </>
      }
    >
      <div className="field">
        <label className="field-label" htmlFor="reject-reason">Reason (required)</label>
        <textarea
          id="reject-reason" className={`textarea ${err ? 'textarea-error' : ''}`} autoFocus
          value={reason} onChange={(e) => { setReason(e.target.value); setErr(null) }}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
          placeholder="e.g. Transcript misread the account ID — the draft answers for a different case."
          aria-required="true" aria-invalid={!!err}
        />
        {err
          ? <span className="field-msg" role="alert"><span aria-hidden="true">⚠</span>{err}</span>
          : <span className="field-hint">{reason.trim().length}/{config.reject_reason_min_chars} characters minimum · ⌘Enter to submit</span>}
      </div>
      <Notice tone="info" icon="🛈">
        Rejecting writes an audit row and performs <strong>no external write</strong>. The case returns to
        the queue with the reason attached, and Resolution may redraft once using it as an instruction.
      </Notice>
    </Modal>
  )
}

/* ---------------- Detail pane ---------------- */
function Detail({ item, onDecided }) {
  const { role, meta } = useSession()
  const toast = useToast()
  const nav = useNavigate()
  const { data: rec, loading, reload } = useAsync(() => api.getRecommendation(item.case_id), [item.case_id])
  const [editing, setEditing] = useState(false)
  const [editedText, setEditedText] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(null)
  const [lowConfirm, setLowConfirm] = useState(false)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const [, force] = useState(0)

  useEffect(() => api.subscribe(() => force((n) => n + 1)), [])
  useEffect(() => { setEditing(false); setRejecting(false); setConflict(null) }, [item.case_id])

  const pack = packFor(item.case_id)
  const may = canAct(role, 'resolution.decide')
  const denied = isDisabled(role, 'resolution.decide') ? DENY_REASON['resolution.decide'] : undefined
  const write = api.writeFor(item.case_id)
  const decision = api.decisionFor(item.case_id)
  const lowBand = suppressesFastApprove(item.band)
  const locked = busy || isWritePending(write.state)   // mutation-in-progress: controls lock

  const decide = async (action, payload) => {
    setBusy(true)
    try {
      const res = await api.submitDecision(item.case_id, action, { ...payload, actor: meta.stubUser })
      emit('decision_submit', { case: item.case_id, action })
      if (action === 'reject') {
        toast.push({ tone: 'info', text: `Rejected · audit ${res.audit_id} · no external write occurred`, link: `/audit?row=${res.audit_id}` })
      } else {
        // NOT a success toast: the decision is recorded, the write has not landed.
        toast.push({ tone: 'info', text: `Decision recorded · audit ${res.audit_id} · write queued`, link: `/audit?row=${res.audit_id}` })
      }
      setEditing(false); setRejecting(false)
      onDecided?.()
    } catch (e) {
      if (e.kind === 'conflict' && e.decided_by) setConflict(e)
      else if (e.kind === 'validation') toast.push({ tone: 'error', text: e.message })
      else toast.push({ tone: 'error', text: `${e.message} · trace ${e.trace_id}` })
    } finally {
      setBusy(false)
      reload()
    }
  }

  const refire = async () => {
    setBusy(true)
    const res = await api.refireExecution(item.case_id)
    toast.push({ tone: 'success', text: `Written to Zendesk · audit ${res.audit_id}`, link: `/audit?row=${res.audit_id}` })
    setBusy(false)
  }

  /* Exact keyboard map (§10.4). Commit keys are ignored while a mutation flies. */
  useEffect(() => {
    const onKey = (e) => {
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && editing) {
          e.preventDefault(); decide('edit', { edited_text: editedText })
        }
        return
      }
      if (locked || !may) return
      const k = e.key.toLowerCase()
      if (k === 'a' && !lowBand && item.type === ItemType.DRAFT) { e.preventDefault(); decide('approve') }
      if (k === 'a' && lowBand) { e.preventDefault(); setLowConfirm(true) }
      if (k === 'e') { e.preventDefault(); startEdit() }
      if (k === 'r') { e.preventDefault(); setRejecting(true) }
      if (k === 'x') { e.preventDefault(); setEvidenceOpen((v) => !v) }
      if (k === 'o') { e.preventDefault(); nav(`/case/${item.case_id}?origin=queue`) }
      if (k === 'c') { e.preventDefault(); nav(`/case/${item.case_id}?tab=citations&origin=queue`) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const startEdit = () => {
    const text = (rec?.draft?.sentences || []).filter((s) => !s.withheld).map((s) => s.text).join('\n\n')
    setEditedText(text); setEditing(true)
  }

  if (loading || !rec) return <SkeletonRows rows={8} />

  const decided = decision && decision.state !== DecisionState.DRAFT_PENDING
  const requester = actorMeta(item.requester)

  return (
    <div className="stack gap-4">
      {/* Header */}
      <div className="card">
        <div className="row gap-2 wrap">
          <span className="mono strong">{item.case_id}</span>
          <SlaChip deadline={item.sla_deadline} paused={item.sla_paused} />
          <ConfidenceBand band={item.band} value={item.confidence} />
          <Chip>{item.class}</Chip>
          <Chip tone={item.tier === 'Enterprise' ? 'primary' : 'neutral'}>{item.tier}</Chip>
          {item.qa_flagged && <QaFlagChip />}
          <WritePill state={write.state} attempts={write.attempts} />
        </div>
        <div style={{ marginTop: 'var(--sp-2)' }}>{item.subject}</div>
        <div className="caption">
          {requester.name} · {requester.org_unit} · raised <span title={absolute(item.created_at)}>{relative(item.created_at)}</span>
        </div>
      </div>

      {/* --- Concurrency: the conflict path (§11.7a) --- */}
      {conflict && (
        <Notice tone="warning" icon="⚠" title={`Already decided by ${conflict.decided_by}`}>
          Recorded at {absolute(conflict.decided_at)} — outcome: <strong>{conflict.recorded_outcome}</strong>.
          Your submission did not create a second approval. The pane now shows the recorded truth.
        </Notice>
      )}

      {/* --- Write failed: approval preserved, execution re-fired --- */}
      {write.state === WriteState.FAILED && (
        <Notice tone="danger" icon="✕" title={WRITE_COPY.failed}
                action={<Button variant="destructive" loading={busy} onClick={refire}>Re-fire execution</Button>}>
          {write.error} The approval by <strong>{decision?.actor}</strong> is preserved — you are re-firing the
          write, not re-approving the draft. Nobody decides twice.
        </Notice>
      )}

      {isWritePending(write.state) && (
        <Notice tone="info" icon="⋯" title={WRITE_COPY[write.state]}>
          The decision is recorded. The external write has not landed yet, so nothing here says "done".
          Controls are locked until the write settles.
        </Notice>
      )}

      {write.state === WriteState.SUCCEEDED && (
        <Notice tone="success" icon="✓" title="Written to Zendesk">
          Decision and write both complete. The audit row carries the whole chain.
        </Notice>
      )}

      {item.awaiting_context && (
        <Notice tone="warning" icon="⚠" title="Awaiting context">
          Retrieval fell below threshold for this case, so the pipeline paused for enrichment rather than
          answering from too little. One-click approval is suppressed.
        </Notice>
      )}

      {/* --- Escalation variant: replaces the draft; never renders beside one --- */}
      {rec.escalation ? (
        <div className="card">
          <div className="row gap-2">
            <span className="card-title">Escalation</span>
            <Chip tone="warning" icon="↗">no confident resolution</Chip>
          </div>
          <p className="caption">{rec.escalation.reason}</p>
          <p>{rec.escalation.summary}</p>
          <div className="card" style={{ background: 'var(--surface-1)' }}>
            <div className="caption">Suggested owner</div>
            <div className="strong">{rec.escalation.suggested_owner.name}</div>
            <div className="caption">{rec.escalation.suggested_owner.rationale}</div>
          </div>
          <div className="row gap-2 wrap" style={{ marginTop: 'var(--sp-3)' }}>
            {rec.escalation.evidence.map((e) => <Chip key={e.label} icon="◆">{e.label}</Chip>)}
          </div>
          <div className="row gap-2" style={{ marginTop: 'var(--sp-3)' }}>
            <Button variant="primary" disabled={!may || locked} deniedReason={denied}>Accept owner</Button>
            <Button variant="secondary" disabled={!may || locked} deniedReason={denied}>Reassign target</Button>
          </div>
          <p className="meta">
            Every ticket gets a path: a draft or an escalation, never neither — and never both at once.
          </p>
        </div>
      ) : (
        <div className="grid" style={{ gridTemplateColumns: evidenceOpen ? '1fr' : '1.25fr 1fr', gap: 'var(--sp-4)', alignItems: 'start' }}>
          {/* Draft */}
          <div className="card">
            <div className="card-head">
              <span className="card-title">Draft resolution</span>
              <span className="right caption">
                {rec.draft.model} · {rec.draft.version}
                {rec.draft.runbook && <> · grounded in runbook {rec.draft.runbook}</>}
              </span>
            </div>
            <DraftPane
              draft={rec.draft}
              editing={editing}
              editedText={editedText}
              onEditText={setEditedText}
              onAnchor={(n) => nav(`/case/${item.case_id}?tab=citations&card=${n}&origin=queue`)}
            />
          </div>

          {/* Evidence rail */}
          <div className="card">
            <div className="card-head">
              <span className="card-title">Evidence</span>
              <span className="right caption">
                {pack.systems_in_pack} systems · {pack.cards.length} items
              </span>
            </div>
            {pack.cards.slice(0, evidenceOpen ? pack.cards.length : 3).map((card) => (
              <EvidenceCard key={card.n} card={card} expandedByDefault={lowBand} />
            ))}
            <div className="row gap-2" style={{ marginTop: 'var(--sp-3)' }}>
              <Button variant="ghost" size="sm" onClick={() => setEvidenceOpen((v) => !v)}>
                {evidenceOpen ? 'Collapse' : `Expand all (${pack.cards.length})`} <span className="kbd">X</span>
              </Button>
              <Button variant="ghost" size="sm" onClick={() => nav(`/case/${item.case_id}?tab=citations&origin=queue`)}>
                Open full pack <span className="kbd">C</span>
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* --- Merge proposal variant --- */}
      {rec.merge?.candidates?.length > 0 && (
        <div className="card">
          <div className="row gap-2">
            <span className="card-title">Merge proposed</span>
            {rec.merge.candidates.map((c) => (
              <Chip key={c.case_id} tone="warning" icon="⧉">{c.case_id} · {c.similarity.toFixed(2)}</Chip>
            ))}
          </div>
          <p className="caption">
            Dedup proposes; it never merges. Confirming enters the same write gate as any other external
            change, and you see both timelines first.
          </p>
          <Button variant="secondary" onClick={() => nav(`/case/${item.case_id}?tab=explainers&origin=queue`)}>
            Compare side by side <span className="kbd">M</span>
          </Button>
        </div>
      )}

      {/* --- Action bar --- */}
      {!decided && !rec.escalation && (
        <div className="card" style={{ position: 'sticky', bottom: 0, background: 'var(--surface-1)' }}>
          {lowBand && (
            <Notice tone="warning" icon="⚠" title="Low confidence — one-click approval is suppressed">
              Approving this draft requires opening a confirmation. The friction is deliberate: the band is
              calibrated and it changes what the interface lets you do, not just how it looks.
            </Notice>
          )}
          <div className="row gap-2 wrap" style={{ marginTop: lowBand ? 'var(--sp-3)' : 0 }}>
            {editing ? (
              <>
                <Button variant="primary" loading={busy} onClick={() => decide('edit', { edited_text: editedText })}>
                  Approve edited <span className="kbd">⌘Enter</span>
                </Button>
                <Button variant="ghost" onClick={() => setEditing(false)}>Cancel edit</Button>
              </>
            ) : (
              <>
                <Button
                  variant="primary" loading={busy} disabled={!may || locked} deniedReason={denied}
                  onClick={() => (lowBand ? setLowConfirm(true) : decide('approve'))}
                >
                  Approve {!lowBand && <span className="kbd">A</span>}
                </Button>
                <Button variant="secondary" disabled={!may || locked} deniedReason={denied} onClick={startEdit}>
                  Edit <span className="kbd">E</span>
                </Button>
                <Button variant="destructive" disabled={!may || locked} deniedReason={denied} onClick={() => setRejecting(true)}>
                  Reject <span className="kbd">R</span>
                </Button>
              </>
            )}
            <Button variant="ghost" onClick={() => nav(`/case/${item.case_id}?origin=queue`)}>
              Open 360 <span className="kbd">O</span>
            </Button>
            {!may && (
              <span className="right caption" style={{ maxWidth: 380 }}>
                {denied || 'Your role cannot decide resolutions.'} Nothing is hidden from you — the work is
                visible, the commit is not yours.
              </span>
            )}
          </div>
        </div>
      )}

      {decided && (
        <Notice tone="info" icon="✓" title={`Decision: ${decision.state.replace('_', ' ')}`}>
          Recorded by <strong>{decision.actor}</strong> at {absolute(decision.at)}.
          {decision.reason && <> Reason: “{decision.reason}”.</>}
          {' '}The write state is tracked separately and shown above.
        </Notice>
      )}

      {rejecting && (
        <RejectModal busy={busy} onClose={() => setRejecting(false)} onSubmit={(reason) => decide('reject', { reason })} />
      )}

      {lowConfirm && (
        <Modal
          title="Approve a Low-confidence draft?"
          subtitle="Deliberate friction — the calibrated band says the system is not confident in this answer."
          onClose={() => setLowConfirm(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setLowConfirm(false)}>Cancel</Button>
              <Button variant="primary" loading={busy}
                      onClick={() => { setLowConfirm(false); decide('approve') }}>
                I have read the evidence — approve
              </Button>
            </>
          }
        >
          <p>
            Confidence is <strong>{item.confidence.toFixed(2)}</strong>, below the {config.confidence_bands.medium} threshold.
            The evidence pack is expanded by default on this item for exactly this reason.
          </p>
          <Notice tone="info" icon="🛈">
            Approving still produces an approval record and a separate write. Nothing about this path skips a gate.
          </Notice>
        </Modal>
      )}
    </div>
  )
}

/* ---------------- Screen ---------------- */
export default function Queue() {
  const { role, meta } = useSession()
  const { filters, set, clear } = useUrlFilters(['type', 'class', 'band', 'team', 'risk', 'item'])
  const [params, setParams] = useSearchParams()
  const { data: items, loading, error, reload } = useAsync(
    () => api.listQueueItems(filters), [JSON.stringify(filters)]
  )
  const rows = items || []
  const selectedId = params.get('item')
  const selected = rows.find((r) => r.case_id === selectedId) || rows[0]

  const [focus, setFocus] = useListKeys(rows.length, {
    onOpen: (i) => rows[i] && select(rows[i].case_id),
  })

  const select = (id) => {
    const next = new URLSearchParams(params)
    next.set('item', id)
    setParams(next, { replace: true })
    emit('decision_open', { case: id })
  }

  useEffect(() => {
    if (rows[focus] && rows[focus].case_id !== selectedId) select(rows[focus].case_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus])

  return (
    <div className="page">
      <div className="page-head row gap-3 wrap">
        <div className="grow">
          <h1 className="page-title">Approval queue</h1>
          <div className="page-sub">
            S-04 · judge and dispatch each recommendation with the evidence one glance away.
            {canAct(role, 'resolution.decide')
              ? ' Everything here is reachable from the keyboard.'
              : ` You are viewing as ${meta.name} — read-only by role, not by accident.`}
          </div>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} note="decision ≠ write" />
      </div>

      <div className="section">
        <div className="filter-bar">
          <Select label="Type" id="q-type" value={filters.type} onChange={(v) => set({ type: v })}
                  options={Object.values(ItemType).map((t) => ({ value: t, label: t }))} />
          <Select label="Class" id="q-class" value={filters.class} onChange={(v) => set({ class: v })}
                  options={CLASSES.map((c) => ({ value: c.id, label: c.label }))} />
          <Select label="Band" id="q-band" value={filters.band} onChange={(v) => set({ band: v })}
                  options={Object.values(Band).map((b) => ({ value: b, label: b }))} />
          <Select label="Team" id="q-team" value={filters.team} onChange={(v) => set({ team: v })}
                  options={TEAMS.slice(0, 12).map((t) => ({ value: t.id, label: t.name }))} />
          <Select label="SLA risk" id="q-risk" value={filters.risk} onChange={(v) => set({ risk: v })}
                  options={[{ value: 'at-risk', label: 'At risk (<2h)' }]} />
          <Button variant="ghost" onClick={clear}>Clear</Button>
          <span className="caption right">Sorted by SLA risk, then age. There is no bulk approve — approval is per item by principle.</span>
        </div>
      </div>

      <div className="split">
        <div className="split-list">
          <div className="tbl-foot" style={{ borderTop: 0, borderBottom: '1px solid var(--border)' }}>
            <strong>{rows.length}</strong> awaiting decision
            <span className="right meta">J / K to move</span>
          </div>
          <div className="split-scroll">
            {loading && <SkeletonRows rows={8} />}
            {error && <ErrorState dependency="Queue service" traceId={error.trace_id} onRetry={reload} />}
            {!loading && !error && rows.length === 0 && (
              <EmptyState icon="✓" title="No items awaiting approval"
                          message="Nothing needs a decision right now."
                          action={<a className="btn btn-secondary" href="/audit">See today's decisions in Audit</a>} />
            )}
            {rows.map((r, i) => {
              const w = api.writeFor(r.case_id)
              return (
                <button
                  key={r.case_id}
                  className={`q-row ${selected?.case_id === r.case_id ? 'selected' : ''} ${focus === i ? 'focused' : ''}`}
                  onClick={() => { setFocus(i); select(r.case_id) }}
                >
                  <div className="row gap-2 wrap">
                    <span className="mono caption">{r.case_id}</span>
                    <SlaChip deadline={r.sla_deadline} paused={r.sla_paused} />
                    <span className="right caption">{age(r.created_at)}</span>
                  </div>
                  <div className="truncate" style={{ margin: '4px 0', fontSize: 'var(--fs-table)' }}>{r.subject}</div>
                  <div className="row gap-2 wrap">
                    <ConfidenceBand band={r.band} value={r.confidence} />
                    <Chip>{r.class}</Chip>
                    {r.type === ItemType.MERGE && <Chip tone="warning" icon="⧉">merge</Chip>}
                    {r.type === ItemType.ESCALATION && <Chip tone="warning" icon="↗">escalation</Chip>}
                    {r.awaiting_context && <Chip tone="warning" icon="⚠">awaiting context</Chip>}
                    {r.qa_flagged && <QaFlagChip />}
                    {w.state === WriteState.FAILED && <Chip tone="danger" icon="✕">write failed</Chip>}
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div>
          {selected
            ? <Detail item={selected} onDecided={reload} />
            : <EmptyState icon="◌" title="Select an item" message="Pick a row, or press J to start at the top." />}
        </div>
      </div>
    </div>
  )
}
