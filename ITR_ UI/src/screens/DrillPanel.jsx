/* The drill target, as an overlay on whatever screen you drilled FROM.

   §10.13 drill mode: "S-13 opens as a 640px side panel, filter chip applied and
   removable, origin chart still visible behind → open case → Esc twice back to
   chart, position preserved." That only works if the panel is an overlay on the
   origin route rather than a navigation away from it — so the drill lives in the
   origin's URL state (`?drill=1&metric=…&<filters>`) and this component reads it.

   Same component as the S-13 page in every respect that matters: same columns,
   same behaviour, same filter vocabulary. Only the chrome differs. */

import React, { useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { SidePanel } from '../ui/overlays.jsx'
import { Chip, Button } from '../ui/primitives.jsx'
import { TicketsTable } from './Tickets.jsx'
import { emit } from '../contracts/telemetry.js'

const FILTER_KEYS = ['status', 'class', 'category', 'channel', 'tier', 'team', 'assignee',
  'assigned', 'assigneeLevel', 'resolvedFrom', 'risk', 'band', 'from', 'to', 'ids', 'qa']

const LABELS = {
  status: 'Status', class: 'Class', category: 'Category', channel: 'Channel', tier: 'Tier',
  team: 'Team', assignee: 'Assignee', assigned: 'Assigned', assigneeLevel: 'Cohort', resolvedFrom: 'Resolved since',
  risk: 'SLA risk', band: 'Band', from: 'From', to: 'To', ids: 'Cases', qa: 'QA-flagged',
}

/** Build the search-param patch that opens the drill on the CURRENT route. */
export function drillParams(filters, metric) {
  const p = { drill: '1', metric }
  FILTER_KEYS.forEach((k) => { if (filters[k] != null && filters[k] !== '') p[k] = String(filters[k]) })
  return p
}

/** Hook a screen calls to open a drill without leaving itself. */
export function useDrill(originLabel) {
  const [params, setParams] = useSearchParams()
  return useCallback((filters, metric) => {
    emit('number_drilldown', { origin: originLabel, metric })
    const next = new URLSearchParams(params)
    Object.entries(drillParams(filters, metric)).forEach(([k, v]) => next.set(k, v))
    setParams(next)
  }, [params, setParams, originLabel])
}

export default function DrillPanel({ originLabel }) {
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  if (params.get('drill') !== '1') return null

  const metric = params.get('metric') || 'Filtered cases'
  const filters = {}
  FILTER_KEYS.forEach((k) => { const v = params.get(k); if (v) filters[k] = v })

  const close = () => {
    const next = new URLSearchParams(params)
    ;['drill', 'metric', ...FILTER_KEYS].forEach((k) => next.delete(k))
    setParams(next, { replace: true })   // origin route untouched; scroll preserved
  }

  const removeFilter = (k) => {
    const next = new URLSearchParams(params)
    next.delete(k)
    setParams(next, { replace: true })
  }

  const openCase = (row) => nav(`/case/${row.id}?origin=${encodeURIComponent(originLabel)}`)

  const entries = Object.entries(filters)

  return (
    <SidePanel
      wide
      title={metric}
      subtitle={`Drilled from ${originLabel} · Esc returns you to it with your position kept`}
      onClose={close}
      footer={
        <>
          <span className="caption grow">
            This is the same list surface as Tickets — the mode changes the chrome, never the columns.
          </span>
          <Button variant="secondary" onClick={() => {
            const q = new URLSearchParams(filters)
            q.set('origin', originLabel)
            nav(`/tickets?${q}`)
          }}>Open as full page</Button>
        </>
      }
    >
      <div className="stack gap-3">
        <div className="chip-rail">
          {entries.length === 0 && <span className="caption">No filter — the whole corpus.</span>}
          {entries.map(([k, v]) => (
            <Chip key={k} tone="primary" onRemove={() => removeFilter(k)}>
              {LABELS[k]}: {k === 'ids' ? `${v.split(',').length} selected` : v}
            </Chip>
          ))}
        </div>
        <TicketsTable filters={filters} onOpen={openCase} compact />
      </div>
    </SidePanel>
  )
}
