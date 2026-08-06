export interface Finding {
  title: string
  detail: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  data: Record<string, unknown>
  recommended_action?: string
}

export interface WorkerResult {
  worker: string
  findings: Finding[]
  summary_stats: Record<string, unknown>
  error?: string
}

export interface InsightsMemo {
  tenant_id: string
  ai_generated: boolean
  narrative: string
  structured: {
    workers: WorkerResult[]
    total_critical: number
    total_high: number
  }
}

export interface ScanJob {
  scan_id: string
  tenant_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  result?: {
    persons_merged: number
    vendors_merged: number
    accounts_merged: number
    opportunities_merged?: number
  }
}

export interface ApiError {
  detail: string
}

// ── Auth ──────────────────────────────────────────────────

export interface AuthUser {
  id: string
  email: string
  full_name?: string
  role: string
  tenant_id: string
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  token_type: string
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at?: string
  is_active: boolean
}

export interface ApiKeyCreateResponse {
  id: string
  name: string
  prefix: string
  raw_key: string   // shown once on creation
  created_at: string
}

// ── Vendor Benchmarks ─────────────────────────────────────

export interface VendorBenchmarkPoint {
  name: string
  fullName: string
  actualSpend: number
  benchmarkSpend: number
  variancePct: number
  category?: string
  potentialSavings: number
  discountPct: number
}

export interface NegotiationWindow {
  vendor: string
  spend: number
  daysToRenewal: number
  potentialSavings: number
  leverage: string[]
}

export interface VendorBenchmarkSummary {
  total_vendors_analyzed: number
  vendors_enriched: number
  vendors_overpaying: number
  total_potential_savings: number
  vendors_in_negotiation_window: number
  total_spend_benchmarked: number
}

// ── Approvals ─────────────────────────────────────────────

export interface ApprovalRequest {
  id: string
  action_id: string
  action_type: string
  risk_tier: 'LOW' | 'MEDIUM' | 'HIGH' | 'BLOCKED'
  rationale: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED'
  proposed_payload: Record<string, unknown>
  expires_at: string | null
  created_at: string
}

// ── Signal / Noise ────────────────────────────────────────

export interface NoiseProfile {
  worker_name: string
  signal_score: number       // 0–1; lower = noisier
  dismissed_rate: number
  acted_rate: number
  total_surfaced: number
  total_acted: number
  total_dismissed: number
  active_action_cap: number
  computed_at: string | null
}

export interface ThresholdProposal {
  id: string
  worker_name: string
  threshold_key: string
  current_value: number
  proposed_value: number
  direction: string
  rationale: string
  confidence: number         // 0–1
  dismissed_count: number
  dismissed_rate: number
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED'
  created_at: string
}

// ── Remediation Actions ───────────────────────────────────

export interface RemediationAction {
  id: string
  finding_hash: string
  worker_name: string
  title: string
  description: string
  action_type: string
  assigned_to_email: string | null
  assigned_to_name: string | null
  effort: string
  timeframe: string
  arr_impact: number | null
  status: 'OPEN' | 'IN_PROGRESS' | 'COMPLETE' | 'DEFERRED' | 'CANCELLED'
  due_date: string | null
  evidence_source: string | null
  evidence_query_type: string | null
  completed_at: string | null
  completion_method: string | null
  created_at: string
}
