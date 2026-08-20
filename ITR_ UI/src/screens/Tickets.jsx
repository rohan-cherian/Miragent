/* S-13 · Tickets list / search [CR-01, OD-3].
   Scope Class: POC functional as a change request — required by the no-dead-end
   rule (§5.4). This is the single list surface behind EVERY drill in the product:
   S-03 chart segments, S-11 clusters, S-08 evidence numbers and ⌘K all land here.

   Two modes, one component: full page (nav destination) and 640px side panel
   (drill target). Mode changes chrome — never columns, never behaviour. */

import React, { useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Table } from '../ui/data.jsx'
import {
  Button, Chip, StatusChip, SlaChip, ConfidenceBand, Select, ScopeBanner,
} from '../ui/primitives.jsx'
import { EmptyState, ErrorState, SkeletonRows } from '../ui/feedback.jsx'
import { SidePanel } from '../ui/overlays.jsx'
import { useAsync, useUrlFilters, useListKeys } from '../shell/hooks.js'
import * as api from '../mock/api.js'
import { CATEGORIES, CHANNELS, CLASSES, TIERS, TEAMS, actorMeta, analystMeta } from '../fixtures/corpus.js'
import { age, num, absolute } from '../contracts/format.js'
import { ScopeClass, Band, CaseStatus } from '../contracts/state.js'
import { emit } from '../contracts/telemetry.js'

const FILTER_KEYS = ['status', 'class', 'category', 'channel', 'tier', 'team', 'assignee', 'risk', 'band', 'from', 'to', 'ids', 'qa', 'query']

const LABELS = {
  status: 'Status', class: 'Class', category: 'Category', channel: 'Channel', tier: 'Tier',
  team: 'Team', assignee: 'Assignee', risk: 'SLA risk', band: 'Band', from: 'From', to: 'To',
  ids: 'Specific cases', qa: 'QA-flagged', query: 'Search',
}

/* One filter vocabulary, shared with S-04 (§10.13). */
function FilterBar({ filters, set, clear, compact }) {
  return (
    <div className="stack gap-3">
      <div className="filter-bar">
        {/* "Open (any)" is the roll-up of new+open+pending+hold; the individual
            states follow it, so the roll-up is not repeated in the list. */}
        <Select label="Status" id="f-status" value={filters.status} onChange={(v) => set({ status: v })}
                options={[
                  { value: 'open', label: 'Open (any)' },
                  ...Object.values(CaseStatus)
                    .filter((s) => s !== CaseStatus.OPEN)
                    .map((s) => ({ value: s, label: s })),
                ]} />
        <Select label="Class" id="f-class" value={filters.class} onChange={(v) => set({ class: v })}
                options={CLASSES.map((c) => ({ value: c.id, label: c.label }))} />
        {!compact && (
          <Select label="Category" id="f-cat" value={filters.category} onChange={(v) => set({ category: v })}
                  options={CATEGORIES.map((c) => ({ value: c, label: c }))} />
        )}
        <Select label="Channel" id="f-chan" value={filters.channel} onChange={(v) => set({ channel: v })}
                options={CHANNELS.map((c) => ({ value: c.id, label: c.label }))} />
        <Select label="Tier" id="f-tier" value={filters.tier} onChange={(v) => set({ tier: v })}
                options={TIERS.map((t) => ({ value: t, label: t }))} />
        {!compact && (
          <Select label="Team" id="f-team" value={filters.team} onChange={(v) => set({ team: v })}
                  options={TEAMS.map((t) => ({ value: t.id, label: t.name }))} />
        )}
        <Select label="SLA risk" id="f-risk" value={filters.risk} onChange={(v) => set({ risk: v })}
                options={[{ value: 'breached', label: 'Breached' }, { value: 'at-risk', label: 'At risk (<2h)' }, { value: 'ok', label: 'On track' }]} />
        <Select label="Band" id="f-band" value={filters.band} onChange={(v) => set({ band: v })}
                options={Object.values(Band).map((b) => ({ value: b, label: b }))} />
        <Button variant="ghost" onClick={clear}>Clear all</Button>
      </div>
    </div>
  )
}

function FilterChips({ filters, set }) {
  const entries = Object.entries(filters).filter(([, v]) => v)
  if (!entries.length) return null
  return (
    <div className="chip-rail">
      <span className="caption">Applied:</span>
      {entries.map(([k, v]) => (
        <Chip key={k} tone="primary" onRemove={() => set({ [k]: null })}>
          {LABELS[k]}: {k === 'ids' ? `${v.split(',').length} cases` : v}
        </Chip>
      ))}
      <span className="meta">Filters are URL state — this view is shareable as a link.</span>
    </div>
  )
}

export function TicketsTable({ filters, onOpen, compact }) {
  const { data, loading, error, reload } = useAsync(
    () => api.listCases(filters, { sort: 'risk' }),
    [JSON.stringify(filters)]
  )
  const rows = data?.rows || []
  const [focus] = useListKeys(rows.length, { onOpen: (i) => rows[i] && onOpen(rows[i]) })

  if (loading) return <SkeletonRows rows={10} />
  if (error) return <ErrorState dependency="Case list service" traceId={error.trace_id} onRetry={reload} />

  const columns = [
    { key: 'id', label: 'Case', width: 92, sortable: true,
      render: (r) => <span className="mono" style={{ whiteSpace: 'nowrap' }}>{r.id}</span> },
    { key: 'subject', label: 'Subject',
      render: (r) => <span className="truncate" style={{ display: 'block', maxWidth: compact ? 170 : 420 }}>{r.subject}</span> },
    { key: 'requester', label: 'Requester',
      render: (r) => <span className="truncate" style={{ display: 'block', maxWidth: compact ? 96 : 160 }}>{actorMeta(r.requester).name}</span> },
    ...(compact ? [] : [{ key: 'class', label: 'Class', render: (r) => <Chip>{r.class}</Chip> }]),
    { key: 'status', label: 'Status', render: (r) => <StatusChip status={r.status} /> },
    { key: 'sla', label: 'SLA', render: (r) => <SlaChip deadline={r.sla_deadline} paused={r.sla_paused} /> },
    { key: 'band', label: 'Band', render: (r) => <ConfidenceBand band={r.band} value={r.confidence} /> },
    ...(compact ? [] : [
      { key: 'age', label: 'Age', numeric: true, sortable: true, render: (r) => <span title={absolute(r.created_at)}>{age(r.created_at)}</span> },
      { key: 'assignee', label: 'Assignee', render: (r) =>
          r.assignee ? (analystMeta(r.assignee)?.name || '—') : <span className="dim">unassigned</span> },
    ]),
  ]

  return (
    <Table
      ariaLabel="Cases"
      columns={columns}
      rows={rows}
      focusIndex={focus}
      onRowClick={onOpen}
      footer={
        <>
          <span>Showing <strong>{num(data.showing)}</strong> of <strong>{num(data.total)}</strong> matching cases</span>
          <span className="right meta">
            J / K to move · Enter to open · counts reconcile with the dashboard aggregates [NFR-31]
          </span>
        </>
      }
      emptyState={
        <EmptyState
          icon="∅" title="No cases match these filters"
          message="Every filter here is reversible. Clearing them returns the full corpus."
        />
      }
    />
  )
}

export default function Tickets() {
  const { filters, set, clear } = useUrlFilters(FILTER_KEYS)
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const isPanel = params.get('panel') === '1'
  const origin = params.get('origin')
  const metric = params.get('metric')

  const open = (row) => {
    emit('number_drilldown', { to: row.id })
    const q = new URLSearchParams()
    if (origin) q.set('origin', origin)
    nav(`/case/${row.id}${q.toString() ? `?${q}` : ''}`)
  }

  const closePanel = () => {
    const next = new URLSearchParams(params)
    next.delete('panel')
    // Esc pops the overlay and returns to the origin screen, position preserved.
    if (origin) nav(originPath(origin, params))
    else setParams(next, { replace: true })
  }

  if (isPanel) {
    return (
      <SidePanel
        wide
        title={metric || 'Filtered cases'}
        subtitle={`Drilled from ${origin || 'a metric'} · the origin screen is still behind this panel`}
        onClose={closePanel}
      >
        <div className="stack gap-3">
          <FilterChips filters={filters} set={set} />
          <TicketsTable filters={filters} onOpen={open} compact />
        </div>
      </SidePanel>
    )
  }

  return (
    <div className="page">
      <div className="page-head row gap-3">
        <div className="grow">
          <h1 className="page-title">Tickets</h1>
          <div className="page-sub">
            S-13 · every drill-down in the product terminates here. Find a set of cases by filter, by
            drill-down, or by search — and get to the right Ticket 360 fast.
          </div>
        </div>
        <ScopeBanner scope={ScopeClass.POC_FUNCTIONAL} note="CR-01, pending ratification [OD-3]" />
      </div>

      <div className="stack gap-3">
        <FilterBar filters={filters} set={set} clear={clear} />
        <FilterChips filters={filters} set={set} />
        <TicketsTable filters={filters} onOpen={open} />
      </div>
    </div>
  )
}

export function originPath(origin, params) {
  const back = {
    overview: '/overview', intelligence: '/intelligence', audit: '/audit',
    queue: '/queue', connections: '/connections', tickets: '/tickets',
  }[origin]
  return back || '/overview'
}
