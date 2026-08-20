/* ---------------------------------------------------------------------------
   src/api/index.js — the mock/live switch (Slice-1 Task 25).

   Screens import one namespace and never learn which implementation answered.
   With VITE_LIVE unset, every call goes to the mock exactly as before. With it
   set, only the operations in LIVE_OPS go over HTTP; everything else still
   comes from fixtures, so the two coexist and the console stays clickable
   while the API is only partly built.

   Extending this is the whole migration path: as Sutej lands an endpoint, add
   its name to LIVE_OPS. Nothing else changes, and no screen is touched.

   `export *` republishes the mock's entire surface — subscribe, ApiError,
   getConfig, and the fixture-only helpers screens import by name — and the
   explicit exports below shadow it for the operations that can go live. An
   allow-list rather than a deny-list, so an endpoint that does not exist yet
   can never be reached by accident.
--------------------------------------------------------------------------- */

import * as http from '../http/api.js'
import * as mock from '../mock/api.js'

export * from '../mock/api.js'

export const LIVE_OPS = [
  'listConnections',
  'listIdentityQueue',
  'resolveIdentity',
  'listCases',
  'listQueueItems',
  'getTicket360',
  'listTimeline',
  'getRecommendation',
  'getContextPack',
  'submitDecision',
  'getWriteExecution',
  'refireExecution',
  'listAuditDecisions',
  'getAuditTimeline',
]

const flag = import.meta.env?.VITE_LIVE
export const LIVE = flag === true || flag === '1' || flag === 'true'

/* Live only if allow-listed AND actually implemented over HTTP. A typo in
   LIVE_OPS would otherwise fall through to the mock and look like "the API
   works" when nothing was ever called. */
export const isLive = (name) =>
  LIVE && LIVE_OPS.includes(name) && typeof http[name] === 'function'

/* Late-bound: the choice is made per call, so it is inspectable at runtime
   rather than frozen at module load. */
const pick = (name) => (isLive(name) ? http[name] : mock[name])

export const listConnections = (...a) => pick('listConnections')(...a)
export const listIdentityQueue = (...a) => pick('listIdentityQueue')(...a)
export const resolveIdentity = (...a) => pick('resolveIdentity')(...a)
export const listCases = (...a) => pick('listCases')(...a)
export const listQueueItems = (...a) => pick('listQueueItems')(...a)
export const getTicket360 = (...a) => pick('getTicket360')(...a)
export const listTimeline = (...a) => pick('listTimeline')(...a)
export const getRecommendation = (...a) => pick('getRecommendation')(...a)
export const getContextPack = (...a) => pick('getContextPack')(...a)
export const submitDecision = (...a) => pick('submitDecision')(...a)
export const refireExecution = (...a) => pick('refireExecution')(...a)
export const listAuditDecisions = (...a) => pick('listAuditDecisions')(...a)
export const getAuditTimeline = (...a) => pick('getAuditTimeline')(...a)

/* The doc names getWriteExecution, but the mock has no such function — the
   fixtures expose the same record synchronously as writeFor(caseId). Defined
   here so one operation name works on both sides. */
export const getWriteExecution = (caseId) =>
  isLive('getWriteExecution')
    ? http.getWriteExecution(caseId)
    : Promise.resolve(mock.writeFor(caseId))

if (import.meta.env?.DEV) {
  const live = LIVE ? LIVE_OPS.filter((n) => typeof http[n] === 'function') : []
  console.info(
    `[itr:api] VITE_LIVE=${LIVE ? 'on' : 'off'} · ` +
    `base=${import.meta.env?.VITE_API_BASE ?? '/api/v1'} · ` +
    `live: ${live.length ? live.join(', ') : 'none (all mock)'}`,
  )
}
