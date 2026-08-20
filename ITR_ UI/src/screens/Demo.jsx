/* §12 · Demo Swim Lane — NOT part of the product console.
   Scope Class: POC demo-only (a functional demo against the six emulators —
   not a clickable mock, and not live onboarding).

   Fenced with a striped DEMO header, Demo role only. The catalogue contains
   exactly the six emulated systems; anything else appears only as a
   non-selectable "Concept — not implemented" tile. Nothing here implies live
   tenant integration, and the word "live" is never used of an emulated source. */

import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Chip, DemoChip, EmulatedChip, Meter, ScopeBanner } from '../ui/primitives.jsx'
import { Notice, SkeletonBlock, useToast } from '../ui/feedback.jsx'
import { Table } from '../ui/data.jsx'
import { useSession } from '../shell/session.jsx'
import { DeniedState } from '../ui/feedback.jsx'
import { isHidden } from '../contracts/rbac.js'
import { useAsync } from '../shell/hooks.js'
import * as api from '../mock/api.js'
import { SYSTEMS, systemName } from '../fixtures/corpus.js'
import { ConnectorState, ScopeClass } from '../contracts/state.js'
import { TENANT } from '../contracts/config.js'
import { num } from '../contracts/format.js'

const Fence = ({ children, step }) => (
  <div className="demo-fence">
    <div className="demo-fence-head">
      <span>▨ DEMO SWIM LANE · D-{step} of 4</span>
      <span className="right" style={{ fontWeight: 400, letterSpacing: 0, fontSize: 'var(--fs-caption)' }}>
        Demonstration surface. Not a product feature; nothing here ships in the console.
      </span>
    </div>
    <div style={{ padding: 'var(--sp-5)' }}>{children}</div>
  </div>
)

/* ---------------- D-1 · Catalogue & selection ---------------- */
function D1({ tiles, selected, setSelected, onNext }) {
  return (
    <Fence step={1}>
      <h2>Connect {TENANT}'s systems</h2>
      <p className="caption">
        Six emulated systems are available. The greyed tiles are illustrative only — no adapter exists for
        them in the POC, so they cannot be selected.
      </p>

      <div className="grid grid-4" style={{ marginTop: 'var(--sp-4)' }}>
        {tiles.map((t) => {
          const on = selected.includes(t.id)
          return (
            <button
              key={t.id}
              className="card"
              role="checkbox"
              aria-checked={on}
              aria-disabled={!t.selectable}
              disabled={!t.selectable}
              title={t.selectable ? undefined : 'Illustrative only — no adapter exists in the POC'}
              onClick={() => t.selectable && setSelected((v) => on ? v.filter((x) => x !== t.id) : [...v, t.id])}
              style={{
                textAlign: 'left', cursor: t.selectable ? 'pointer' : 'not-allowed',
                opacity: t.selectable ? 1 : 0.55,
                borderColor: on ? 'var(--primary-700)' : undefined,
                background: on ? 'var(--primary-100)' : undefined,
              }}
            >
              <div className="row gap-2">
                <span className="brand-mark" aria-hidden="true"
                      style={{ background: 'var(--surface-2)', color: 'var(--ink-900)' }}>{t.short}</span>
                <span className="strong grow">{t.name}</span>
              </div>
              <div style={{ marginTop: 'var(--sp-2)' }}>
                {t.kind === 'emulated'
                  ? <EmulatedChip />
                  : <Chip tone="neutral" icon="◌">Concept — not implemented</Chip>}
              </div>
              {t.role && <div className="caption" style={{ marginTop: 6 }}>{t.role}</div>}
            </button>
          )
        })}
      </div>

      <div className="row gap-3" style={{ marginTop: 'var(--sp-5)' }}>
        <div className="card grow" style={{ background: 'var(--surface-1)' }}>
          <div className="row gap-4">
            <div><div className="caption">Selected</div><div className="strong num">{selected.length} of 6</div></div>
            <div><div className="caption">Estimated onboarding envelope</div><div className="strong">~26 h compressed from 2–5 days</div></div>
          </div>
        </div>
        <Button variant="primary" size="lg" disabled={selected.length === 0} onClick={onNext}>
          Initialise adapters
        </Button>
      </div>
    </Fence>
  )
}

/* ---------------- D-2 · Adapter init & metadata discovery ---------------- */
function D2({ selected, discovery, onNext }) {
  const [states, setStates] = useState(() =>
    Object.fromEntries(selected.map((s) => [s, { state: ConnectorState.INITIALIZING, found: 0, elapsed: 0 }])))

  useEffect(() => {
    const id = setInterval(() => {
      setStates((prev) => {
        const next = { ...prev }
        selected.forEach((s, i) => {
          const cur = next[s]
          const target = (discovery[s]?.standard || 0) + (discovery[s]?.custom || 0)
          if (cur.state === ConnectorState.INITIALIZING) {
            const el = cur.elapsed + 1
            // One system fails resumably on purpose — a silent reset would be the lie.
            if (s === 'workday' && el > 3) next[s] = { ...cur, state: ConnectorState.FAILED_RESUMABLE, elapsed: el }
            else if (el > 2 + i) next[s] = { ...cur, state: ConnectorState.DISCOVERING, elapsed: el }
            else next[s] = { ...cur, elapsed: el }
          } else if (cur.state === ConnectorState.DISCOVERING) {
            const found = Math.min(target, cur.found + 2)
            next[s] = { ...cur, found, state: found >= target ? 'inventory_ready' : cur.state }
          }
        })
        return next
      })
    }, 700)
    return () => clearInterval(id)
  }, [selected, discovery])

  const resume = (s) => setStates((p) => ({ ...p, [s]: { ...p[s], state: ConnectorState.DISCOVERING } }))
  const ready = selected.every((s) => states[s]?.state === 'inventory_ready')

  return (
    <Fence step={2}>
      <h2>Adapter initialisation & metadata discovery</h2>
      <p className="caption">
        Each adapter reads the emulator's own metadata: standard objects and custom objects, discovered
        rather than configured. This is the anti-consulting-project claim, and it is checkable below.
      </p>

      <div className="stack gap-2" style={{ marginTop: 'var(--sp-4)' }}>
        {selected.map((s) => {
          const st = states[s] || {}
          const inv = discovery[s]
          const total = (inv?.standard || 0) + (inv?.custom || 0)
          return (
            <div className="card" key={s}>
              <div className="row gap-3 wrap">
                <span className="strong" style={{ minWidth: 190 }}>{systemName(s)}</span>
                {st.state === ConnectorState.INITIALIZING && <Chip tone="info" icon="↻">initializing · {st.elapsed}s</Chip>}
                {st.state === ConnectorState.DISCOVERING && <Chip tone="info" icon="⌕">discovering · {st.found} found</Chip>}
                {st.state === ConnectorState.FAILED_RESUMABLE && (
                  <>
                    <Chip tone="danger" icon="✕">failed (resumable) · metadata endpoint timed out</Chip>
                    <Button size="sm" variant="secondary" onClick={() => resume(s)}>Resume</Button>
                  </>
                )}
                {st.state === 'inventory_ready' && <Chip tone="success" icon="✓">inventory ready · {total} objects</Chip>}
                <span className="grow" />
              </div>
              {st.state === 'inventory_ready' && inv && (
                <div className="row gap-4 wrap caption" style={{ marginTop: 'var(--sp-2)' }}>
                  <span><strong>{inv.standard}</strong> standard: {inv.objects.join(', ')}</span>
                  {inv.custom > 0 && <span><strong>{inv.custom}</strong> custom: {inv.customObjects.join(', ')}</span>}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <Notice tone="info" icon="🛈" title="A failure that resumes is not a failure that resets">
        The Workday row fails on purpose. Resuming picks up from the checkpoint — there is no scenario in
        this journey where a failure silently restarts the run.
      </Notice>

      <div className="row" style={{ marginTop: 'var(--sp-4)' }}>
        <Button variant="primary" size="lg" disabled={!ready} onClick={onNext}>Continue to the confirmation gate</Button>
      </div>
    </Fence>
  )
}

/* ---------------- D-3 · Confirmation gate & staged plan ---------------- */
function D3({ selected, plan, onNext, onBack }) {
  return (
    <Fence step={3}>
      <h2>Confirmation gate & staged ingestion plan</h2>
      <div className="grid grid-2" style={{ marginTop: 'var(--sp-4)' }}>
        <div className="card">
          <div className="card-head"><span className="card-title">Scan summary</span></div>
          <dl style={{ margin: 0, fontSize: 'var(--fs-table)' }}>
            <div className="row gap-2"><dt className="caption" style={{ width: 150 }}>Systems</dt><dd style={{ margin: 0 }}>{selected.length}</dd></div>
            <div className="row gap-2"><dt className="caption" style={{ width: 150 }}>Objects discovered</dt><dd style={{ margin: 0 }}>34</dd></div>
            <div className="row gap-2"><dt className="caption" style={{ width: 150 }}>Estimated records</dt><dd style={{ margin: 0 }}>{num(118420)}</dd></div>
            <div className="row gap-2"><dt className="caption" style={{ width: 150 }}>Cases in corpus</dt><dd style={{ margin: 0 }}>{num(6000)}</dd></div>
          </dl>
        </div>

        <div className="card">
          <div className="card-head"><span className="card-title">Staged plan</span></div>
          <Table
            ariaLabel="Staged ingestion plan"
            rows={plan}
            rowKey={(r) => r.stage}
            columns={[
              { key: 'stage', label: 'Stage', render: (r) => <span className="strong">{r.stage}</span> },
              { key: 'est', label: 'Estimate', render: (r) => (
                <span className="row gap-2">
                  {r.estimate}
                  {r.assumption && <Chip tone="warning" icon="◇">[ASSUMPTION]</Chip>}
                </span>
              ) },
              { key: 'basis', label: 'Basis', render: (r) => <span className="caption" title={r.basis}>{r.basis}</span> },
            ]}
          />
        </div>
      </div>

      <Notice tone="info" icon="⏱" title="These durations are derived, not decorative">
        Each stage shows its basis. Where the basis is not in the source workbook the estimate is tagged
        [ASSUMPTION] on screen rather than presented as fact. Real tenant onboarding at enterprise scale runs
        2–5 days; this demo compresses honestly, and the fast-forward control says so as it steps.
      </Notice>

      <div className="row gap-2" style={{ marginTop: 'var(--sp-4)' }}>
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button variant="primary" size="lg" onClick={onNext}>Confirm & begin ingestion</Button>
        <span className="caption right">This is the human gate of the connector state machine — an explicit, logged demo action.</span>
      </div>
    </Fence>
  )
}

/* ---------------- D-4 · Ingestion progress & results ---------------- */
function D4({ selected }) {
  const toast = useToast()
  const nav = useNavigate()
  const [progress, setProgress] = useState(() => Object.fromEntries(selected.map((s) => [s, 0])))
  const [clockHours, setClockHours] = useState(0)
  const [events, setEvents] = useState([])
  const [chaosShown, setChaosShown] = useState(false)

  useEffect(() => {
    const id = setInterval(() => {
      setProgress((p) => {
        const next = { ...p }
        selected.forEach((s) => {
          if (next[s] < 1) next[s] = Math.min(1, next[s] + (s === 'zendesk' ? 0.035 : 0.06))
        })
        return next
      })
    }, 500)
    return () => clearInterval(id)
  }, [selected])

  useEffect(() => {
    if (!chaosShown && progress.zendesk > 0.3) {
      setChaosShown(true)
      setEvents((e) => [{ t: 'chaos', text: 'Zendesk: HTTP 429 rate-limited — resumed from checkpoint, 0 loss.' }, ...e])
    }
  }, [progress, chaosShown])

  const done = selected.every((s) => progress[s] >= 1)

  return (
    <Fence step={4}>
      <h2>Ingestion progress & results</h2>

      <div className="row gap-2 wrap" style={{ margin: 'var(--sp-3) 0' }}>
        <Button variant="secondary" onClick={() => {
          setClockHours((h) => h + 4)
          setEvents((e) => [{ t: 'ff', text: `Fast-forward: advanced to bulk extract, T+${clockHours + 4}h. Timestamps advance with the compressed clock; nothing claims wall-clock completion.` }, ...e])
        }}>
          Fast-forward one stage
        </Button>
        <Button variant="secondary" onClick={() => {
          setEvents((e) => [{ t: 'pull', text: 'Incremental sync job enqueued — a PULL against the emulators. No webhook was fired.' }, ...e])
          toast.push({ tone: 'info', text: 'Incremental pull job enqueued — visible in the Phase 2 tail' })
        }}>
          Run incremental sync now
        </Button>
        <Button variant="secondary" onClick={() => {
          setEvents((e) => [{ t: 'push', text: 'Synthetic source event injected into the Zendesk emulator — the webhook path fires end to end and the item reaches the approval queue.' }, ...e])
          toast.push({ tone: 'success', text: 'Event injected · the item will appear in the approval queue', link: '/queue', linkLabel: 'Open queue' })
        }}>
          Simulate incoming event
        </Button>
        <span className="caption right" style={{ maxWidth: 420 }}>
          These two controls are deliberately distinct: a manual sync is a <strong>pull</strong>; simulating an
          event is a source <strong>push</strong>. They are never conflated.
        </span>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="card-head"><span className="card-title">Phase 1 · Bulk backfill</span>
            <span className="right caption">demo clock T+{clockHours}h</span></div>
          {selected.map((s) => (
            <div key={s} style={{ marginBottom: 'var(--sp-3)' }}>
              <div className="row caption">
                <span className="grow">{systemName(s)}</span>
                <span className="num">{Math.round(progress[s] * 100)}%</span>
              </div>
              <Meter value={progress[s]} tone={progress[s] >= 1 ? 'success' : ''} label={`${systemName(s)} backfill`} />
            </div>
          ))}
        </div>

        <div className="card">
          <div className="card-head"><span className="card-title">Phase 2 · Incremental sync</span></div>
          {events.length === 0 && <p className="caption">No events yet. Use the controls above to drive the tail.</p>}
          <div className="stack gap-2">
            {events.map((e, i) => (
              <div key={i} className="row gap-2" style={{ fontSize: 'var(--fs-table)' }}>
                <Chip tone={e.t === 'chaos' ? 'warning' : e.t === 'push' ? 'primary' : 'neutral'}
                      icon={e.t === 'chaos' ? '⚠' : e.t === 'push' ? '⇢' : e.t === 'pull' ? '⇠' : '⏩'}>
                  {e.t === 'chaos' ? 'chaos' : e.t === 'push' ? 'webhook' : e.t === 'pull' ? 'pull job' : 'clock'}
                </Chip>
                <span>{e.text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {done && (
        <div className="card" style={{ marginTop: 'var(--sp-4)' }}>
          <div className="card-head"><span className="card-title">Emulated ingestion run complete</span>
            <Chip tone="success" icon="✓" className="right">reconciliation passed</Chip></div>
          <div className="row gap-5 wrap">
            {[['Users', 2410], ['Cases', 6000], ['Records', 118420], ['Accounts', 118], ['Articles', 900]].map(([k, v]) => (
              <div key={k}><div className="caption">{k}</div><div style={{ fontSize: 'var(--fs-kpi)', fontWeight: 600 }}>{num(v)}</div></div>
            ))}
          </div>
          <p className="meta">
            "Complete" means an <strong>emulated ingestion run</strong> completed. The word "live" is not used
            of an emulated source anywhere in this lane.
          </p>
          <Button variant="primary" size="lg" onClick={() => nav('/connections')}>Proceed to the console →</Button>
        </div>
      )}
    </Fence>
  )
}

/* ---------------- Router ---------------- */
export default function Demo() {
  const { role, meta } = useSession()
  const { step = '1' } = useParams()
  const nav = useNavigate()
  const { data, loading } = useAsync(() => api.getDemoCatalogue(), [])
  const [selected, setSelected] = useState(SYSTEMS.map((s) => s.id))

  if (isHidden(role, 'demo.lane')) {
    return <div className="page"><DeniedState action="demo.lane" roleName={meta.name} home={meta.home} /></div>
  }
  if (loading) return <div className="page"><SkeletonBlock lines={10} /></div>

  return (
    <div className="page">
      <div className="page-head row gap-3 wrap">
        <div className="grow">
          <h1 className="page-title">Connector journey</h1>
          <div className="page-sub">
            A functional demo against the six emulators — not a clickable mock, and not live onboarding.
          </div>
        </div>
        <DemoChip />
        <ScopeBanner scope={ScopeClass.POC_DEMO_ONLY} demo />
      </div>

      {step === '1' && <D1 tiles={data.tiles} selected={selected} setSelected={setSelected} onNext={() => nav('/demo/connect/2')} />}
      {step === '2' && <D2 selected={selected} discovery={data.discovery} onNext={() => nav('/demo/connect/3')} />}
      {step === '3' && <D3 selected={selected} plan={data.plan} onNext={() => nav('/demo/connect/4')} onBack={() => nav('/demo/connect/2')} />}
      {step === '4' && <D4 selected={selected} />}
    </div>
  )
}
