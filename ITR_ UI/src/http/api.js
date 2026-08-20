/* ---------------------------------------------------------------------------
   src/http/api.js — the real HTTP data layer (Slice-1 Task 25).

   Exports the same function names and signatures as src/mock/api.js, so a
   screen cannot tell which one it is talking to. Base URL comes from
   import.meta.env.VITE_API_BASE (default /api/v1, the contract's server url).

   Deliberately thin. This is transport, not translation: responses are handed
   to the screens as the API returned them. If a screen breaks, the API is
   wrong and that is the finding — reshaping it here would hide exactly the
   drift this task exists to detect.

   Contract: openapi/console-api-v1.yaml (frozen at Task 2).
--------------------------------------------------------------------------- */

import { ApiError } from '../mock/api.js'

const BASE = (import.meta.env?.VITE_API_BASE ?? '/api/v1').replace(/\/+$/, '')

/* Every POST in the contract declares these two request headers. If-Match
   carries the optimistic-concurrency token; the console has no version token
   yet, so '*' is sent until one is threaded through. */
const idempotencyKey = () =>
  (globalThis.crypto?.randomUUID?.() ?? `ik-${Date.now()}-${Math.random().toString(16).slice(2)}`)

function query(params = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    q.set(k, Array.isArray(v) ? v.join(',') : String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

async function request(path, { method = 'GET', body, headers = {}, op } = {}) {
  const url = `${BASE}${path}`
  let res
  try {
    res = await fetch(url, {
      method,
      headers: {
        Accept: 'application/json',
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
  } catch (cause) {
    // Network-level failure: the console is up, the API is not.
    throw new ApiError('service', `Console API unreachable (${url})`, op)
  }

  if (res.status === 204) return null

  let payload = null
  const text = await res.text()
  if (text) {
    try { payload = JSON.parse(text) } catch { payload = text }
  }

  if (!res.ok) {
    // The contract defines 409 {error, by, at} and 422 {field, min}. Surface
    // both through the same ApiError the mock throws, so screens that already
    // handle a conflict keep handling it.
    if (res.status === 409) {
      throw new ApiError('conflict', payload?.error ?? 'Already decided', op, payload)
    }
    if (res.status === 422) {
      throw new ApiError('validation', `${payload?.field ?? 'field'} is invalid`, op, payload)
    }
    throw new ApiError('service', `${method} ${path} failed (${res.status})`, op, payload)
  }
  return payload
}

const get = (path, op) => request(path, { op })
const post = (path, body, op) =>
  request(path, {
    method: 'POST',
    body,
    op,
    headers: { 'Idempotency-Key': idempotencyKey(), 'If-Match': '*' },
  })

/* ---------------- connections ---------------- */

export async function listConnections() {
  return get('/connections', 'listConnections')
}

/* ---------------- identity ---------------- */

export async function listIdentityQueue() {
  return get('/identity/queue', 'listIdentityQueue')
}

export async function resolveIdentity(id, action, payload = {}) {
  return post(`/identity/queue/${encodeURIComponent(id)}/resolve`,
    { action, ...payload }, 'resolveIdentity')
}

/* ---------------- cases and queue ---------------- */

export async function listCases(filters = {}, { sort = 'risk', limit = 400 } = {}) {
  return get(`/cases${query({ ...filters, sort, limit })}`, 'listCases')
}

export async function listQueueItems(filters = {}) {
  return get(`/queue${query(filters)}`, 'listQueueItems')
}

export async function getTicket360(caseId) {
  return get(`/cases/${encodeURIComponent(caseId)}/360`, 'getTicket360')
}

export async function listTimeline(caseId) {
  return get(`/cases/${encodeURIComponent(caseId)}/timeline`, 'listTimeline')
}

/* ---------------- recommendation and context ---------------- */

export async function getRecommendation(caseId) {
  return get(`/cases/${encodeURIComponent(caseId)}/recommendation`, 'getRecommendation')
}

export async function getContextPack(caseId) {
  return get(`/cases/${encodeURIComponent(caseId)}/context-pack`, 'getContextPack')
}

/* ---------------- the write gate ----------------
   submitDecision records a DECISION. The server, not this module, decides
   whether a write follows — ACTION_MODE gates it (Task 22). Nothing here can
   trigger a send. */

export async function submitDecision(caseId, action, payload = {}) {
  return post(`/cases/${encodeURIComponent(caseId)}/decision`,
    { action, ...payload }, 'submitDecision')
}

export async function getWriteExecution(caseId) {
  return get(`/cases/${encodeURIComponent(caseId)}/write-execution`, 'getWriteExecution')
}

export async function refireExecution(caseId) {
  return post(`/cases/${encodeURIComponent(caseId)}/write-execution/refire`,
    {}, 'refireExecution')
}

/* ---------------- audit ---------------- */

export async function listAuditDecisions(filters = {}) {
  return get(`/audit${query(filters)}`, 'listAuditDecisions')
}

export async function getAuditTimeline(row) {
  // The mock takes the whole row; the contract keys on its id.
  const id = typeof row === 'string' ? row : (row?.id ?? row?.audit_id)
  return get(`/audit/${encodeURIComponent(id)}/timeline`, 'getAuditTimeline')
}

/* Re-exported so the switch module can hand screens one namespace whichever
   implementation is live. */
export { ApiError }
