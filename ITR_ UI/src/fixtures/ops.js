/* Connections (S-02), KB review (S-10) and notification fixtures. */

import { NOW, SYSTEMS, CASES } from './corpus.js'
import { ConnectionHealth } from '../contracts/state.js'

const MIN = 60000, HOUR = 3600000, DAY = 24 * HOUR

/* ---------- S-02 Systems tab ---------- */
export const CONNECTIONS = [
  {
    system: 'zendesk', health: ConnectionHealth.RATE_LIMITED,
    last_sync: new Date(NOW - 22 * MIN).toISOString(),
    connector_run_id: 'run-2026-0810-0612-zd',
    completeness: 1.0,
    note: 'Rate-limited, retrying — resumed from checkpoint, 0 loss.',
    objects: [
      { object: 'tickets',        source: 6000, ingested: 6000, checksum: 'pass' },
      { object: 'comments',       source: 21440, ingested: 21440, checksum: 'pass' },
      { object: 'users',          source: 660,  ingested: 660,  checksum: 'pass' },
      { object: 'organizations',  source: 118,  ingested: 118,  checksum: 'pass' },
      { object: 'ticket_audits',  source: 18922, ingested: 18922, checksum: 'pass' },
      { object: 'guide_articles', source: 900,  ingested: 900,  checksum: 'pass' },
      { object: 'satisfaction_ratings', source: 3810, ingested: 3810, checksum: 'pass' },
      { object: 'assets (custom)', source: 412, ingested: 412, checksum: 'pass' },
    ],
    run_log: [
      { ts: new Date(NOW - 3.9 * HOUR).toISOString(), text: 'Incremental export started from cursor 2026-08-10T02:12Z.' },
      { ts: new Date(NOW - 3.4 * HOUR).toISOString(), text: 'HTTP 429 on /api/v2/incremental/tickets — Retry-After 60s. Temporal checkpoint written.' },
      { ts: new Date(NOW - 2.4 * HOUR).toISOString(), text: 'Resumed from checkpoint. 0 records lost, 0 duplicated (idempotent on external_id).' },
      { ts: new Date(NOW - 22 * MIN).toISOString(), text: 'Run complete. Reconciliation pass: 8 of 8 objects match.' },
    ],
  },
  {
    system: 'salesforce', health: ConnectionHealth.HEALTHY,
    last_sync: new Date(NOW - 48 * MIN).toISOString(),
    connector_run_id: 'run-2026-0810-0555-sf', completeness: 1.0,
    objects: [
      { object: 'accounts',     source: 118, ingested: 118, checksum: 'pass' },
      { object: 'contacts',     source: 640, ingested: 640, checksum: 'pass' },
      { object: 'cases',        source: 1180, ingested: 1180, checksum: 'pass' },
      { object: 'entitlements', source: 214, ingested: 214, checksum: 'pass' },
    ],
    run_log: [{ ts: new Date(NOW - 48 * MIN).toISOString(), text: 'Run complete. 4 of 4 objects match. Daily API budget used: 11%.' }],
  },
  {
    system: 'workday', health: ConnectionHealth.ATTENTION,
    last_sync: new Date(NOW - 66 * MIN).toISOString(),
    connector_run_id: 'run-2026-0810-0540-wd', completeness: 0.9987,
    note: 'Checksum delta on one object — others unaffected.',
    objects: [
      { object: 'workers',   source: 2410, ingested: 2410, checksum: 'pass' },
      { object: 'org_units', source: 186,  ingested: 186,  checksum: 'pass' },
      { object: 'schedules', source: 2410, ingested: 2396, checksum: 'fail', delta: -14,
        detail: 'Sampled field checksum mismatch on `schedules`: 14 rows differ on `effective_to`. Sample listed in the run log.' },
      { object: 'job_profiles', source: 92, ingested: 92, checksum: 'pass' },
    ],
    run_log: [
      { ts: new Date(NOW - 66 * MIN).toISOString(), text: 'Reconciliation: schedules Δ-14 on `effective_to`. Object marked attention; other objects unaffected.' },
      { ts: new Date(NOW - 65 * MIN).toISOString(), text: 'Sample of mismatched rows written for review. Re-run reconciliation is available to Admin.' },
    ],
  },
  {
    system: 'jira', health: ConnectionHealth.HEALTHY,
    last_sync: new Date(NOW - 31 * MIN).toISOString(),
    connector_run_id: 'run-2026-0810-0620-jr', completeness: 1.0,
    objects: [
      { object: 'issues',       source: 1840, ingested: 1840, checksum: 'pass' },
      { object: 'issue_links',  source: 620,  ingested: 620,  checksum: 'pass' },
      { object: 'projects',     source: 24,   ingested: 24,   checksum: 'pass' },
    ],
    run_log: [{ ts: new Date(NOW - 31 * MIN).toISOString(), text: 'Run complete. Read-context only — no write adapter exists for Jira [F-119].' }],
  },
  {
    system: 'entra', health: ConnectionHealth.SYNCING,
    last_sync: new Date(NOW - 4 * MIN).toISOString(),
    connector_run_id: 'run-2026-0810-0708-en', completeness: 0.94,
    note: 'Incremental sync in progress — sign-in logs for the last 24h.',
    objects: [
      { object: 'users',    source: 2410, ingested: 2410, checksum: 'pass' },
      { object: 'groups',   source: 318,  ingested: 318,  checksum: 'pass' },
      { object: 'devices',  source: 3120, ingested: 3120, checksum: 'pass' },
      { object: 'sign_ins', source: 48200, ingested: 45300, checksum: 'running' },
    ],
    run_log: [{ ts: new Date(NOW - 4 * MIN).toISOString(), text: 'Incremental sign-in ingestion at 94%.' }],
  },
  {
    system: 'slack', health: ConnectionHealth.HEALTHY,
    last_sync: new Date(NOW - 12 * MIN).toISOString(),
    connector_run_id: 'run-2026-0810-0702-sl', completeness: 1.0,
    objects: [
      { object: 'channels', source: 240,  ingested: 240,  checksum: 'pass' },
      { object: 'messages', source: 9140, ingested: 9140, checksum: 'pass' },
      { object: 'users',    source: 2380, ingested: 2380, checksum: 'pass' },
    ],
    run_log: [{ ts: new Date(NOW - 12 * MIN).toISOString(), text: 'Run complete. 3 of 3 objects match.' }],
  },
]

/* Completeness is measured over RECONCILED objects. An object whose sync is
   still running has not been reconciled yet, so counting it as a shortfall
   would report a false gap — the in-progress count is surfaced separately
   instead of being folded into the headline. */
export const overallCompleteness = () => {
  const rows = CONNECTIONS.flatMap((c) => c.objects).filter((o) => o.checksum !== 'running')
  const src = rows.reduce((s, o) => s + o.source, 0)
  const got = rows.reduce((s, o) => s + o.ingested, 0)
  return got / src
}
export const inFlightObjects = () =>
  CONNECTIONS.flatMap((c) => c.objects.filter((o) => o.checksum === 'running')).length
export const lastFullRun = () =>
  CONNECTIONS.map((c) => c.last_sync).sort()[0]

/* ---------- S-10 KB draft review ---------- */
export const KB_DRAFTS = [
  {
    id: 'kbd-1', state: 'generated', kind: 'new',
    title: 'SSO login loop after a credential rotation (Payroll Ops)',
    source_resolution: 'RR-8871', source_case: 'HFG-2088',
    generated_at: new Date(NOW - 20 * HOUR).toISOString(),
    dedupe: { nearest_article: 'KB-3312 · Runbook R-07 — SSO loop after credential change', similarity: 0.88, warn: true },
    body: [
      '**Symptom.** After a scheduled password rotation, members of the PayrollOps-All dynamic group are returned to the login page immediately after entering valid credentials. The sign-in log shows AADSTS50105 on a compliant device.',
      '**Cause.** The conditional-access policy "Require re-consent after credential change" invalidates the cached SAML session, but the cached session is replayed before the consent prompt can render.',
      '**Resolution.** 1. Confirm the user is a member of PayrollOps-All. 2. Sign out of all Halcyon applications. 3. Clear the cached session at portal.halcyonfoods.example/logout. 4. Sign in again and accept the consent prompt. 5. If the loop persists, capture the correlation ID and raise to IAM referencing AUTH-341.',
      '**Applies to.** Entra-federated applications for Payroll Ops. Verified on 3 resolved cases.',
    ],
    proposed_update: null,
  },
  {
    id: 'kbd-2', state: 'generated', kind: 'update',
    title: 'Update: Cost centre mapping refresh for the Ireland payroll interface',
    source_resolution: 'RR-8902', source_case: 'HFG-2402',
    generated_at: new Date(NOW - 9 * HOUR).toISOString(),
    dedupe: { nearest_article: 'KB-2980 · Payroll interface file rejections', similarity: 0.94, warn: true },
    existing_article: 'KB-2980',
    body: null,
    proposed_update: {
      original: 'If the interface file is rejected, raise a ticket with Payroll Systems and include the rejection code.',
      updated: 'If the interface file is rejected with an unrecognised cost centre, check whether the cost centre was created in Workday after the last payroll mapping load (loads run nightly at 02:00 IST). If so, re-submit after the next load window rather than raising a ticket. For any other rejection code, raise a ticket with Payroll Systems and include the code.',
    },
  },
  {
    id: 'kbd-3', state: 'generated', kind: 'new',
    title: 'Cold chain telemetry alert storms — recognising a single incident',
    source_resolution: 'RR-8930', source_case: 'HFG-2519',
    generated_at: new Date(NOW - 3 * HOUR).toISOString(),
    dedupe: { nearest_article: 'KB-3702 · Trailer telemetry probe offline', similarity: 0.51, warn: false },
    body: [
      '**Symptom.** Dozens of telemetry alerts arrive within minutes for trailers on the same route, each raising its own ticket.',
      '**Cause.** A gateway restart on the route controller replays the buffered probe readings, and each replayed reading breaches the threshold independently.',
      '**Resolution.** Confirm the gateway restart in the route controller log, link the tickets to the earliest one, and resolve the linked set once the buffer has drained. Do not reset individual probes.',
    ],
    proposed_update: null,
  },
]

export const KB_DECIDED = [
  { id: 'kbd-0a', title: 'Teams channel missing after the workspace migration', decision: 'approved_for_draft_write', actor: 'P. Nair', at: new Date(NOW - 5 * DAY).toISOString(), article: '4471' },
  { id: 'kbd-0b', title: 'VPN drops on the Dublin plant network', decision: 'rejected', actor: 'R. Bose', at: new Date(NOW - 6 * DAY).toISOString(), reason: 'Duplicates KB-3120 almost exactly; an update would be the right shape, not a new article.' },
]

/* Gap queue — ranked by volume × handling cost [F-073]. */
export const KB_GAPS = [
  { class: 'sso-scim-sync', volume_30d: 18, handling_cost_min: 94, articles: 0,
    note: 'No adequate article exists. Every case in this class was resolved from an analyst\'s own notes.' },
  { class: 'payroll-integrations', volume_30d: 47, handling_cost_min: 71, articles: 3,
    note: 'Three articles exist but none covers the cost-centre timing case that produced most of this month\'s volume.' },
  { class: 'coldchain-telemetry', volume_30d: 39, handling_cost_min: 44, articles: 4,
    note: 'Coverage exists for single-probe faults, not for replay storms.' },
]

/* ---------- Notifications (CR-03, §10.15) ---------- */
export const NOTIFICATIONS = [
  { id: 'n1', class: 'action', kind: 'merge', text: 'Merge proposal on HFG-2214 — similarity 0.93, awaiting your confirmation.',
    ts: new Date(NOW - 80 * MIN).toISOString(), read: false, link: '/queue?type=merge&item=HFG-2214' },
  { id: 'n2', class: 'outcome', kind: 'write_failed', sticky: true,
    text: 'Write failed on HFG-2402 after 3 retries. Your approval is preserved — re-fire execution.',
    ts: new Date(NOW - 91 * MIN).toISOString(), read: false, link: '/audit?row=A-99231' },
  { id: 'n3', class: 'action', kind: 'escalation', text: 'Escalation assigned to you: HFG-2455 · batch record blocked, SLA breached.',
    ts: new Date(NOW - 20 * MIN).toISOString(), read: false, link: '/queue?type=escalation&item=HFG-2455' },
  { id: 'n4', class: 'outcome', kind: 'write_ok', text: 'Approved · written to Zendesk · audit #A-99228.',
    ts: new Date(NOW - 4 * HOUR).toISOString(), read: true, link: '/audit?row=A-99228' },
  { id: 'n5', class: 'digest', kind: 'digest', text: 'Week 32 intelligence digest is ready.',
    ts: new Date(NOW - 26 * HOUR).toISOString(), read: false, link: '/intelligence?week=32' },
  { id: 'n6', class: 'action', kind: 'identity', text: '2 unresolved identities are waiting in the identity queue.',
    ts: new Date(NOW - 4 * HOUR).toISOString(), read: false, link: '/connections/identity', admin_only: true },
]

/* ---------- Demo lane (§12) fixtures ---------- */
export const DEMO_CATALOGUE = [
  ...SYSTEMS.map((s) => ({ ...s, kind: 'emulated', selectable: true })),
  { id: 'gmail', name: 'Gmail', short: 'GM', kind: 'concept', selectable: false },
  { id: 'servicenow', name: 'ServiceNow', short: 'SN', kind: 'concept', selectable: false },
  { id: 'sap', name: 'SAP S/4HANA', short: 'SAP', kind: 'concept', selectable: false },
  { id: 'netsuite', name: 'NetSuite', short: 'NS', kind: 'concept', selectable: false },
]

export const DISCOVERY = {
  zendesk:    { standard: 11, custom: 2, objects: ['tickets', 'comments', 'users', 'organizations', 'ticket_audits', 'guide_articles', 'satisfaction_ratings', 'groups', 'macros', 'triggers', 'automations'], customObjects: ['assets', 'plant_sites'] },
  salesforce: { standard: 6, custom: 1, objects: ['Account', 'Contact', 'Case', 'Entitlement', 'ServiceContract', 'User'], customObjects: ['Halcyon_Site__c'] },
  workday:    { standard: 5, custom: 0, objects: ['Worker', 'OrganizationUnit', 'JobProfile', 'Schedule', 'SupervisoryOrg'], customObjects: [] },
  jira:       { standard: 4, custom: 1, objects: ['Issue', 'IssueLink', 'Project', 'Sprint'], customObjects: ['plant_impact'] },
  entra:      { standard: 5, custom: 0, objects: ['User', 'Group', 'Device', 'SignInLog', 'ConditionalAccessPolicy'], customObjects: [] },
  slack:      { standard: 3, custom: 0, objects: ['Channel', 'Message', 'User'], customObjects: [] },
}

export const INGESTION_PLAN = [
  { stage: 'Adapter init', estimate: '~10 min', basis: 'Six adapters initialise in parallel; the slowest observed handshake in rehearsal was 96s.', assumption: false },
  { stage: 'Bulk extract', estimate: '~4 h', basis: 'Zendesk incremental export runs ~10 req/min, cursor-paged at 100 records — the 6,000-ticket corpus plus 21,440 comments paces out at roughly 4 hours [06_Integrations_APIs].', assumption: false },
  { stage: 'Normalisation', estimate: '~1 h', basis: 'Deterministic transform throughput measured on demo hardware.', assumption: true },
  { stage: 'Graph build', estimate: '~20 h', basis: 'Entity-resolution and graph projection across 2,410 workers and 660 requesters.', assumption: true },
  { stage: 'Validation', estimate: '~30 min', basis: 'Reconciliation job: row counts, sampled field checksums, referential integrity across 6 systems [F-120].', assumption: false },
]
