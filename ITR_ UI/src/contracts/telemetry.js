/* Observability stub — Spec §11.11. Telemetry is OPERATIONAL; the decision audit
   (S-09) is the governance trail. The two correlate by trace_id and are never
   conflated — audit is never used as product analytics. */

let counter = 0
const sink = []

export const newTraceId = () => `tr-${(++counter).toString().padStart(5, '0')}`

export const EVENTS = [
  'screen_load', 'decision_open', 'citation_drilldown', 'draft_edit',
  'decision_submit', 'write_outcome', 'merge_confirm', 'identity_resolve',
  'replay_toggle', 'number_drilldown', 'filter_change',
]

export function emit(event, payload = {}) {
  const row = { event, trace_id: payload.trace_id || newTraceId(), ts: new Date().toISOString(), ...payload }
  sink.push(row)
  if (import.meta.env.DEV) console.debug('[itr:event]', event, row)
  return row.trace_id
}

export const eventLog = () => sink.slice()
