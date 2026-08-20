/* Frozen state contract — Spec §5.3. Every screen imports from here.
   Nobody redeclares an enum locally. Decision and write are SEPARATE machines
   (§5.3.2a vs §5.3.2b): approval recorded !== write succeeded. */

/* ---- 5.3.1 Case lifecycle [OPEN DECISION OD-1 — held in config, not code] ---- */
export const CaseStatus = {
  NEW: 'new', OPEN: 'open', PENDING: 'pending',
  HOLD: 'hold', SOLVED: 'solved', CLOSED: 'closed',
}
export const CASE_TRANSITIONS = {
  new:     ['open'],
  open:    ['pending', 'hold', 'solved'],
  pending: ['open', 'hold', 'solved'],
  hold:    ['open', 'solved'],
  solved:  ['closed', 'open'],   // solved -> open = reopen (feeds reopen_rate)
  closed:  [],
}
export const CASE_STATUS_META = {
  new:     { label: 'New',     tone: 'info',    icon: '●' },
  open:    { label: 'Open',    tone: 'info',    icon: '◐' },
  pending: { label: 'Pending', tone: 'warning', icon: '◑' },
  hold:    { label: 'Hold',    tone: 'warning', icon: '⏸' },
  solved:  { label: 'Solved',  tone: 'success', icon: '✓' },
  closed:  { label: 'Closed',  tone: 'neutral', icon: '○' },
}

/* ---- 5.3.2a RecommendationDecision — the HUMAN decision ---- */
export const DecisionState = {
  DRAFT_PENDING: 'draft_pending',
  IN_REVIEW: 'in_review',
  APPROVED: 'approved',
  EDITED_APPROVED: 'edited_approved',
  REJECTED: 'rejected',
  REDRAFTED: 'redrafted',
  SUPERSEDED: 'superseded',
}

/* ---- 5.3.2b WriteExecution — the EXTERNAL effect. Success renders only here. ---- */
export const WriteState = {
  NOT_STARTED: 'not_started',
  QUEUED: 'queued',
  EXECUTING: 'executing',
  RETRYING: 'retrying',
  SUCCEEDED: 'succeeded',
  FAILED: 'failed',            // terminal-until-refired; keeps the approval
}
export const WRITE_COPY = {
  not_started: 'Not started',
  queued:      'Approved · queued for write',
  executing:   'Approved · writing…',
  retrying:    'Approved · retrying',
  succeeded:   'Written',
  failed:      'Write failed — action required',
}
export const isWritePending = (s) =>
  s === WriteState.QUEUED || s === WriteState.EXECUTING || s === WriteState.RETRYING

/* ---- 5.3.3 Dedup proposal — a merge is an external write ---- */
export const DedupState = {
  LINK_PROPOSED: 'link_proposed',
  MERGE_PROPOSED: 'merge_proposed',
  HUMAN_CONFIRMED: 'human_confirmed',
  DECLINED: 'declined',
  WRITE_PENDING: 'write_pending',
  MERGED: 'merged',
  WRITE_FAILED: 'write_failed',
}

/* ---- 5.3.4 Assignment proposal — POC is SHADOW-ONLY [F-064, OD-2].
   No write-path states exist here on purpose. ---- */
export const AssignmentState = {
  PROPOSED: 'proposed',
  CONFLICT_HELD: 'conflict_held',
  FEEDBACK_ACCEPTED: 'feedback_accepted',
  FEEDBACK_OVERRIDDEN: 'feedback_overridden',
}

/* ---- 5.3.5 KB draft — no state can make content publicly live [F-072] ---- */
export const KbDraftState = {
  GENERATED: 'generated',
  UNDER_REVIEW: 'under_review',
  EDITED: 'edited',
  APPROVED_FOR_DRAFT_WRITE: 'approved_for_draft_write',
  DRAFT_CREATED: 'draft_created',
  DRAFT_UPDATED: 'draft_updated',
  WRITE_FAILED: 'write_failed',
  REJECTED: 'rejected',
}
export const KB_APPROVED_VERB = 'Create/update Zendesk Guide draft (draft=true)'

/* ---- 5.3.6 Identity resolution [F-044] ---- */
export const IdentityState = {
  MATCHED: 'matched',
  AMBIGUOUS: 'ambiguous',
  QUEUED: 'queued',
  HUMAN_RESOLVED: 'human_resolved',
  MARKED_NEW_ACTOR: 'marked_new_actor',
  DISMISSED: 'dismissed',
  PARTIAL: 'partial',
}

/* ---- 5.3.7 Connector run (demo lane §12). "complete" never means "live". ---- */
export const ConnectorState = {
  CONFIGURED: 'configured',
  INITIALIZING: 'initializing',
  DISCOVERING: 'discovering',
  AWAITING_CONFIRMATION: 'awaiting_confirmation',
  INGESTING: 'ingesting',
  RECONCILING: 'reconciling',
  COMPLETE: 'complete',
  FAILED_RESUMABLE: 'failed_resumable',
}

/* ---- Connection card health (§10.2) ---- */
export const ConnectionHealth = {
  HEALTHY: 'healthy',
  SYNCING: 'syncing',
  RATE_LIMITED: 'rate_limited',
  ATTENTION: 'attention',
  FAILED: 'failed',
  AWAITING_FIRST_SYNC: 'awaiting_first_sync',
}
export const CONNECTION_META = {
  healthy:             { label: 'Healthy',                  tone: 'success', icon: '✓' },
  syncing:             { label: 'Syncing',                  tone: 'info',    icon: '↻' },
  rate_limited:        { label: 'Rate-limited — retrying', tone: 'warning', icon: '⚠' },
  attention:           { label: 'Attention',                tone: 'warning', icon: '⚠' },
  failed:              { label: 'Failed',                   tone: 'danger',  icon: '✕' },
  awaiting_first_sync: { label: 'Awaiting first backfill',  tone: 'neutral', icon: '○' },
}

/* ---- Confidence bands (§11.2). Thresholds come from config [A-05]. ---- */
export const Band = { HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low' }

/* ---- Queue item kinds (§10.4 filters) ---- */
export const ItemType = { DRAFT: 'draft', MERGE: 'merge', ESCALATION: 'escalation' }

/* ---- Scope Class — declared on every screen (§1.2) ---- */
export const ScopeClass = {
  POC_FUNCTIONAL: 'POC functional',
  POC_DEMO_ONLY: 'POC demo-only',
  FUTURE_MVP: 'Future/MVP',
  OUT_OF_SCOPE: 'Out of scope',
}
