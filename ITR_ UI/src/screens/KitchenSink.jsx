/* /kitchen-sink — the living reference for the component library (§8).
   Every component in every state, so drift is visible in one screenshot.
   Not a product surface: it is not in the nav and not in the route registry. */

import React, { useState } from 'react'
import {
  Button, Chip, StatusChip, SlaChip, EmulatedChip, ShadowChip, StretchChip, DemoChip,
  QaFlagChip, ConfidenceBand, Field, Input, Textarea, Select, Meter, ScopeBanner, Drill,
} from '../ui/primitives.jsx'
import {
  EmptyState, ErrorState, DeniedState, NotFoundState, SkeletonRows, SkeletonBlock,
  Notice, LoadingWithBudget, useToast,
} from '../ui/feedback.jsx'
import { Modal, SidePanel } from '../ui/overlays.jsx'
import { Table, EvidenceCard, Timeline, DiffView, KpiTile } from '../ui/data.jsx'
import { ChartFrame, BarChart, LineChart, Donut } from '../ui/charts.jsx'
import { CallPlayer } from '../ui/audio.jsx'
import { callFor } from '../fixtures/details.js'
import { NOW } from '../fixtures/corpus.js'
import { CaseStatus, ScopeClass } from '../contracts/state.js'

const Section = ({ title, note, children }) => (
  <section className="section">
    <div className="section-head">
      <h2 className="section-title">{title}</h2>
      {note && <span className="caption">{note}</span>}
    </div>
    <div className="card">{children}</div>
  </section>
)

const bars = [
  { key: 'a', label: 'Identity & Access', value: 1240, drill: {} },
  { key: 'b', label: 'Order & Fulfilment', value: 980, drill: {} },
  { key: 'c', label: 'Finance & Billing', value: 640, drill: {} },
]
const line = Array.from({ length: 8 }, (_, i) => ({ key: `m${i}`, label: `M${i + 1}`, value: 300 + i * 40 }))
const donut = [
  { key: 'covered', label: 'Covered', value: 21, seriesIndex: 0 },
  { key: 'thin', label: 'Thin', value: 2, seriesIndex: 2 },
  { key: 'gap', label: 'Gap', value: 1, seriesIndex: 4 },
]

const evidence = {
  n: 1, source_system: 'zendesk', source_type: 'resolution', object_id: 'RR-8871',
  excerpt: 'Prior resolution: clearing the cached SAML session resolves the loop for ⟨NAME⟩.',
  source_ts: new Date(NOW - 86400000).toISOString(), relevance: 0.94,
  access_status: 'ok', learned: true, redacted: true,
}
const restricted = { ...evidence, n: 2, learned: false, redacted: false, access_status: 'restricted', excerpt: null }

export default function KitchenSink() {
  const toast = useToast()
  const [modal, setModal] = useState(false)
  const [panel, setPanel] = useState(false)

  return (
    <div className="page">
      <div className="page-head row gap-3">
        <div className="grow">
          <h1 className="page-title">Kitchen sink</h1>
          <div className="page-sub">Every §8 component in every state. Review surface, not a product screen.</div>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} note="review only" />
      </div>

      <Section title="1 · Button" note="loading locks the width; destructive needs a modal or a typed reason">
        <div className="row gap-2 wrap">
          <Button variant="primary">Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="destructive">Destructive</Button>
          <Button variant="destructive" fill>Destructive fill</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="primary" loading>Loading</Button>
          <Button variant="primary" disabled>Disabled</Button>
          <Button variant="primary" disabled deniedReason="Only the Analyst role decides resolutions.">Disabled w/ reason</Button>
          <Button size="sm">Small</Button>
          <Button size="lg">Large</Button>
        </div>
      </Section>

      <Section title="2 · Form controls">
        <div className="grid grid-3">
          <Field label="Input" id="ks-1"><Input id="ks-1" placeholder="Default" /></Field>
          <Field label="Invalid" id="ks-2" error="A reason of at least 10 characters is required."><Input id="ks-2" invalid /></Field>
          <Select label="Select" id="ks-3" value="" onChange={() => {}} options={[{ value: 'a', label: 'Option A' }]} />
          <Field label="Textarea" id="ks-4"><Textarea id="ks-4" placeholder="Reason…" /></Field>
        </div>
      </Section>

      <Section title="3 · Table">
        <Table
          ariaLabel="Sample"
          rows={[{ id: 'HFG-2214', v: 41 }, { id: 'HFG-2231', v: 27 }]}
          columns={[
            { key: 'id', label: 'Case', sortable: true, render: (r) => <span className="mono">{r.id}</span> },
            { key: 'v', label: 'Handled', numeric: true, render: (r) => r.v },
          ]}
          selectedKey="HFG-2214"
          focusIndex={1}
          onRowClick={() => {}}
          footer={<span>Sticky header · tabular numerals · aria-sort · J/K focus · selected wash</span>}
        />
      </Section>

      <Section title="4 · Evidence card" note="body refuses to render without a source reference [P-2]">
        <EvidenceCard card={evidence} />
        <EvidenceCard card={restricted} />
        <EvidenceCard card={{ ...evidence, n: 3, stale: true, learned: false, redacted: false, excerpt: 'A stale item: provenance older than the pack compile time.' }} focused />
      </Section>

      <Section title="5 · Confidence · 6 · Chips">
        <div className="row gap-2 wrap">
          <ConfidenceBand band="High" value={0.91} />
          <ConfidenceBand band="Medium" value={0.78} />
          <ConfidenceBand band="Low" value={0.41} />
          <ConfidenceBand band="Low" uncalibrated />
        </div>
        <div className="row gap-2 wrap" style={{ marginTop: 'var(--sp-3)' }}>
          {Object.values(CaseStatus).map((s) => <StatusChip key={s} status={s} />)}
          <SlaChip deadline={new Date(NOW + 42 * 60000).toISOString()} />
          <SlaChip deadline={new Date(NOW + 20 * 3600000).toISOString()} />
          <SlaChip deadline={new Date(NOW - 60000).toISOString()} />
          <SlaChip deadline={new Date(NOW + 3600000).toISOString()} paused />
          <EmulatedChip /><ShadowChip /><StretchChip /><DemoChip /><QaFlagChip />
        </div>
      </Section>

      <Section title="7 · Modal · 9 · Side panel · 8 · Toast">
        <div className="row gap-2 wrap">
          <Button onClick={() => setModal(true)}>Open modal</Button>
          <Button onClick={() => setPanel(true)}>Open side panel</Button>
          <Button onClick={() => toast.push({ tone: 'success', text: 'Approved · written to Zendesk · audit #A-99231', link: '/audit' })}>Success toast</Button>
          <Button onClick={() => toast.push({ tone: 'error', text: 'Write failed after 3 retries — approval preserved. trace tr-a91f' })}>Error toast (sticky)</Button>
        </div>
      </Section>

      <Section title="10 · Timeline (product & immutable audit variants)">
        <div className="grid grid-2">
          <Timeline entries={[
            { id: 1, type: 'comment', author: 'Daniel Okafor', channel: 'voice', ts: new Date(NOW - 3600000).toISOString(), text: 'Inbound call, 6:12.' },
            { id: 2, type: 'event', author: 'Triage', channel: 'system', ts: new Date(NOW - 3000000).toISOString(), text: 'Classified auth-sso at 0.91.' },
          ]} />
          <Timeline immutable entries={[
            { id: 3, type: 'decision', author: 'P. Nair', ts: new Date(NOW - 1800000).toISOString(), text: 'Edited-approved.' },
            { id: 4, type: 'retry', author: 'Action Executor', ts: new Date(NOW - 1700000).toISOString(), text: 'Attempt 1 — 429, backoff 2s.' },
            { id: 5, type: 'outcome', author: 'Action Executor', ts: new Date(NOW - 1600000).toISOString(), text: 'Write succeeded.' },
          ]} />
        </div>
      </Section>

      <Section title="11 · Empty / error / denied / not-found">
        <div className="grid grid-2">
          <EmptyState icon="✓" title="No items awaiting approval" message="Nothing needs a decision right now."
                      action={<Button variant="secondary">See Audit</Button>} />
          <ErrorState dependency="Queue service" traceId="tr-9a2c" onRetry={() => {}} />
          <DeniedState action="audit.export" roleName="Manager" />
          <NotFoundState what="Case" />
        </div>
      </Section>

      <Section title="12 · Skeleton & honest-delay">
        <SkeletonRows rows={3} />
        <div style={{ marginTop: 'var(--sp-3)' }}><SkeletonBlock lines={3} /></div>
        <div style={{ marginTop: 'var(--sp-3)' }}>
          <LoadingWithBudget budgetMs={0} label="Compiling the context pack"><SkeletonBlock lines={2} /></LoadingWithBudget>
        </div>
      </Section>

      <Section title="13 · Charts" note="dark series only · every segment clickable · view-as-table on each">
        <div className="grid grid-3">
          <ChartFrame title="Bar" data={bars}><BarChart data={bars} onSelect={() => {}} /></ChartFrame>
          <ChartFrame title="Line" data={line}><LineChart data={line} /></ChartFrame>
          <ChartFrame title="Donut" data={donut} valueLabel="Classes"><Donut data={donut} /></ChartFrame>
        </div>
      </Section>

      <Section title="14 · Audio player">
        <CallPlayer call={callFor('call-2214')} />
      </Section>

      <Section title="15 · Diff view">
        <DiffView
          original="We have queued the mapping refresh; re-submitting the file after the next load window will clear the rejection."
          edited="We have queued the mapping refresh for tonight; re-submitting the file after 02:00 IST will clear the rejection."
        />
      </Section>

      <Section title="KPI tiles · meters · notices · drillable numbers">
        <div className="grid grid-4">
          <KpiTile label="Total cases" value={6000} delta={4.1} deltaUnit="%" deltaLabel="vs prior 30 days" onDrill={() => {}} />
          <KpiTile label="KB coverage" value={0.875} format="pct" delta={-1.2} deltaUnit="pp" deltaLabel="vs prior month" />
          <KpiTile label="Analysts" value={240} delta={0} deltaLabel="roster unchanged" />
          <div className="card card-1">
            <div className="caption">Completeness</div>
            <Meter value={1} tone="success" label="100%" />
            <div className="caption" style={{ marginTop: 8 }}>Drill: <Drill onClick={() => {}}>1,240</Drill></div>
          </div>
        </div>
        <div className="stack gap-2" style={{ marginTop: 'var(--sp-4)' }}>
          <Notice tone="info" title="Info">Informational.</Notice>
          <Notice tone="success" title="Success">Write succeeded.</Notice>
          <Notice tone="warning" title="Warning">Low context — retrieval below threshold.</Notice>
          <Notice tone="danger" title="Danger">Write failed — action required.</Notice>
        </div>
      </Section>

      {modal && (
        <Modal title="Confirm merge" subtitle="A merge is an external write." onClose={() => setModal(false)}
               footer={<><Button variant="ghost" onClick={() => setModal(false)}>Cancel</Button><Button variant="primary">Confirm</Button></>}>
          <p>Modal body. Focus is trapped; Esc closes; modals are never stacked.</p>
        </Modal>
      )}
      {panel && (
        <SidePanel title="Side panel" subtitle="480px right overlay" onClose={() => setPanel(false)}>
          <p>Esc closes. Focus trapped. Origin scroll preserved.</p>
        </SidePanel>
      )}
    </div>
  )
}
