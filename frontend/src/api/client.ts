import type {
  ScanJob,
  InsightsMemo,
  TokenResponse,
  AuthUser,
  ApiKey,
  ApiKeyCreateResponse,
  ApprovalRequest,
  RemediationAction,
  NoiseProfile,
  ThresholdProposal,
} from '../types'

// ── Company Health Score types (Sprint 77) ───────────────────────────────────

export interface DimensionScore {
  key: string;
  label: string;
  icon: string;
  score: number;
  prior_score: number;
  change: number;
  weight: number;
  band: string;
  signals: { label: string; value: string; positive: boolean }[];
  top_risk: string;
  top_opportunity: string;
}

export interface HealthScoreResponse {
  tenant_id: string;
  overall_score: number;
  prior_overall: number;
  overall_change: number;
  overall_band: string;
  dimensions: DimensionScore[];
  weakest_dimension: string;
  strongest_dimension: string;
  score_narrative: string;
  computed_at: string;
  period: string;
}

export interface HealthScoreHistory {
  month: string;
  score: number;
}

// ── Notification Center types (Sprint 76) ────────────────────────────────────

export interface Notification {
  id: string;
  tenant_id: string;
  category: 'finding' | 'approval' | 'churn_risk' | 'renewal' | 'agent_action' | 'system';
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  title: string;
  body: string;
  source_agent: string;
  action_url: string;
  action_label: string;
  created_at: string;
  is_read: boolean;
  is_dismissed: boolean;
  metadata: Record<string, unknown>;
}

export interface NotificationSummary {
  total_unread: number;
  critical_unread: number;
  by_category: Record<string, number>;
  top_priority: Notification | null;
}

// ── Mission Control types ─────────────────────────────────────────────────────

export interface ProcessBlueprint {
  id: string
  process_name: string
  category: string
  volume_per_week: number
  median_resolution_hours: number
  automation_potential: number
  recommended_agent: string | null
  systems_involved: string[]
  resolution_patterns: Record<string, number>
  status: 'discovered' | 'reviewed' | 'configured' | 'active'
  sop_coverage: boolean
  conformance_gap: string | null
  created_at: string | null
  reviewed_at: string | null
  reviewed_by: string | null
}

export interface AgentDeployment {
  id: string
  agent_name: string
  status: 'active' | 'paused' | 'configuring'
  blueprint_id: string | null
  config: Record<string, unknown>
  requests_handled: number
  requests_today: number
  resolution_rate: number
  last_activity_at: string | null
  deployed_at: string | null
  deployed_by: string | null
}

export interface ConnectorStatus {
  name: string
  status: 'connected' | 'available' | 'error'
  last_sync: string | null
}

// ── Sprint 83: Real connector status ─────────────────────────────────────────

export interface RealConnectorStatus {
  connector_id: string
  display_name: string
  category: string
  is_mock: boolean
  is_connected: boolean
  connected_at: string | null
  last_error: string | null
}

export interface AuditEntry {
  timestamp?: string
  agent?: string
  action?: string
  outcome?: string
  [key: string]: unknown
}

export interface MissionControlSummary {
  last_scan_at: string | null
  active_agents: number
  paused_agents: number
  pending_approvals: number
  blueprints_discovered: number
  blueprints_active: number
  findings_this_week: number
  critical_findings: number
  connectors: ConnectorStatus[]
  agents: AgentDeployment[]
  blueprints: ProcessBlueprint[]
  recent_actions: AuditEntry[]
}

// ── Communication Analysis types (Sprint 73) ─────────────────────────────────

export interface CommMessage {
  id: string
  channel: string
  source: string
  customer: string
  arr: number
  date: string
  subject: string | null
  body_preview: string
  sentiment: string
  topic: string
  signals: string[]
  requires_action: boolean
  action_suggestion: string | null
}

export interface CommAnalysisSummary {
  total_messages: number
  by_sentiment: Record<string, number>
  by_topic: Record<string, number>
  by_channel: Record<string, number>
  churn_risk_arr: number
  expansion_arr: number
  top_customers_at_risk: CommMessage[]
  top_expansion_opportunities: CommMessage[]
  urgent_unresolved: number
  sentiment_trend: string
  analysis_date: string
}

// ── Design Session types (Sprint 72) ─────────────────────────────────────────

export interface DesignBlueprint {
  id: string
  name: string
  description: string
  volume_per_month: number
  automation_potential: number
  sla_gap: string | null
  recommended_agent: string
  estimated_hours_saved_monthly: number
  status: 'pending_review' | 'approved' | 'skipped'
}

export interface DesignSession {
  session_id: string
  tenant_id: string
  current_step: string
  step_number: number
  connected_systems: { name: string; status: string; records: number; icon: string }[]
  scout_summary: {
    total_findings: number
    critical: number
    high: number
    medium: number
    low: number
    workers_run: number
    scan_duration_seconds: number
  }
  blueprints: DesignBlueprint[]
  approved_count: number
  estimated_hours_saved: number
  completed: boolean
  go_live_summary: Record<string, unknown> | null
}

// ── DDQ types (inline — no separate types file) ───────────────────────────────

export interface DDQAnswer {
  question_index: number
  question_text: string
  category: string
  drafted_text: string
  confidence: number
  confidence_label: 'High' | 'Review' | 'Unknown'
  sources: string[]
  needs_human: boolean
}

export interface DDQResult {
  job_id: string
  tenant_id: string
  status: string
  total_questions: number
  answered: number
  needs_review: number
  unanswerable: number
  answers: DDQAnswer[]
  completed_at?: string
  error?: string
}

// ── DDQ Template Fill types (Sprint 71) ──────────────────────────────────────

export interface DDQTemplateQuestion {
  number: number
  question_text: string
  answer: string
  confidence: number
  confidence_label: 'High' | 'Review' | 'Unknown'
}

export interface DDQTemplateResult {
  job_id: string
  tenant_id: string
  source_filename: string
  total_questions: number
  filled_questions: number
  questions: DDQTemplateQuestion[]
  filled_docx_b64: string
  can_download: boolean
  submitted_at: string
  summary: string
}

// ── Payroll Agent types ───────────────────────────────────────────────────────

export interface PayrollResult {
  request_id: string
  status: string
  document_type: string
  period: string
  document: Record<string, unknown> | null
  error?: string
  completed_at: string | null
  created_at: string
}

export interface PayrollRequest {
  id: string
  document_type: string
  period: string
  status: string
  created_at: string
}

// ── Portal Access Agent types ─────────────────────────────────────────────────

export interface PortalAccessDiagnosis {
  diagnosis_code: string
  diagnosis_text: string
  auto_resolvable: boolean
  resolution_steps: string[]
  customer_message: string
  support_instructions: string
  severity: 'low' | 'medium' | 'high'
}

export interface PortalAccessResult {
  request_id: string
  customer_email: string
  reported_issue: string
  diagnosis: PortalAccessDiagnosis | null
  auto_resolved: boolean
  status: 'resolved' | 'escalated' | 'pending_action' | 'analyzing'
  error?: string
  completed_at: string
  created_at: string
}

export interface PortalAccessRequestSummary {
  id: string
  customer_email: string
  reported_issue: string
  diagnosis_code: string | null
  auto_resolved: boolean
  status: string
  created_at: string
}

// ── Support Triage Agent types ────────────────────────────────────────────────

export interface AccountContext {
  customer_email: string
  company_name: string
  arr: number
  health_score: number
  account_status: string
  open_deals: number
  open_deal_value: number
  prior_tickets_30d: number
  csm_name: string
  csm_email: string
  is_enterprise: boolean
  contract_tier: string
  source: string
}

export interface TriageResult {
  ticket_id: string
  customer_email: string
  subject: string
  category: string
  category_label: string
  priority_score: number
  priority_label: string
  assigned_queue: string
  drafted_response: string
  account_context: AccountContext
  escalation_reason: string | null
  routing_explanation: string
  completed_at: string
  created_at: string
  status: string
}

export interface TicketSummary {
  id: string
  customer_email: string
  subject: string
  category: string | null
  priority_label: string | null
  assigned_queue: string | null
  escalation_reason: string | null
  status: string
  created_at: string
}

export interface KBDocument {
  id: string
  tenant_id: string
  filename: string
  doc_type: string
  chunk_count: number
  created_at: string
  created_by?: string
}

// ── Payment Status Agent types ────────────────────────────────────────────────

export interface PaymentStatusResult {
  invoice_id: string
  vendor_name: string
  vendor_email: string
  amount: number
  status: 'received' | 'under_review' | 'approved' | 'scheduled' | 'paid' | 'rejected' | 'on_hold'
  submitted_date: string
  payment_date: string | null
  hold_reason: string | null
  is_stuck: boolean
  stuck_reason: string | null
  approver: string | null
  approver_role: string | null
  draft_response: string
  days_outstanding: number
}

export interface StuckInvoicesSummary {
  total_stuck: number
  on_hold: PaymentStatusResult[]
  overdue_review: PaymentStatusResult[]
  queue_delays: PaymentStatusResult[]
}

// ── Vendor Onboarding Agent types ────────────────────────────────────────────

export interface VendorOnboardingRecord {
  vendor_id: string;
  vendor_name: string;
  vendor_email: string;
  stage: 'initiated' | 'w9_requested' | 'w9_received' | 'banking_requested' | 'banking_received' | 'erp_setup' | 'active' | 'on_hold';
  entity_type: string;
  ein: string | null;
  bank_info: string | null;
  hold_reason: string | null;
  submitted_date: string | null;
  completed_date: string | null;
  days_in_process: number;
  checklist: string[];
  next_step: string;
  internal_contact: string;
  confirmation_message: string;
  is_stalled: boolean;
}

// ── Board Report Agent types ─────────────────────────────────────────────────

export interface MetricItem {
  label: string;
  value: string;
  prior_value: string | null;
  change_pct: number | null;
  direction: 'up' | 'down' | 'flat';
  is_positive: boolean;
}

export interface ReportSection {
  section_id: string;
  title: string;
  narrative: string;
  metrics: MetricItem[];
}

export interface BoardReport {
  report_id: string;
  tenant_id: string;
  period: string;
  generated_at: string;
  sections: ReportSection[];
  strategic_risks: { risk: string; detail: string; severity: string }[];
  executive_summary: string;
  dora_tier: string;
}

// ── Compliance Response Agent types ──────────────────────────────────────────

export interface ComplianceAnswer {
  question_number: number;
  question_text: string;
  topic: string | null;
  answer: string;
  confidence: number;
  confidence_label: 'High' | 'Review' | 'Unknown';
  evidence: string | null;
  needs_review: boolean;
}

export interface ComplianceResult {
  job_id: string;
  tenant_id: string;
  customer_name: string;
  questionnaire_type: string;
  total_questions: number;
  high_confidence: number;
  needs_review: number;
  unknown_count: number;
  answers: ComplianceAnswer[];
  summary: string;
  submitted_at: string;
}

// ── IT Access Agent types ─────────────────────────────────────────────────────

export interface ITAccessResult {
  request_id: string;
  requester_email: string;
  requester_name: string;
  target_user_email: string;
  system_key: string;
  system_display_name: string;
  okta_group: string;
  approval_tier: 'manager' | 'it_admin' | 'ciso';
  approver_email: string;
  status: 'pending_manager' | 'pending_it' | 'pending_ciso' | 'provisioned' | 'rejected' | 'in_progress';
  submitted_date: string;
  completed_date: string | null;
  rejection_reason: string | null;
  license_cost_monthly: number;
  requires_training: boolean;
  training_url: string | null;
  sla_days: number;
  authority_verified: boolean;
  authority_note: string;
  next_steps: string[];
}

export interface SystemCatalogEntry {
  system_key: string;
  display_name: string;
  approval_tier: string;
  license_cost_monthly: number;
  requires_training: boolean;
  okta_group: string;
  owner: string;
}

// ── Benefits Agent types ──────────────────────────────────────────────────────

export interface BenefitsResult {
  employee_email: string
  employee_name: string
  department: string
  question_category: 'pto_balance' | 'health_insurance' | 'retirement_401k' | 'open_enrollment' | 'general_benefits'
  answer: string
  key_facts: Record<string, string | number | boolean>
  action_items: string[]
  contact: string
}

export interface BenefitsSummary {
  found: boolean
  employee_email: string
  employee_name: string | null
  department: string | null
  pto_remaining: number | null
  pto_total: number | null
  ytd_pto_used: number | null
  health_plan: string | null
  monthly_contribution: string | null
  contrib_pct: number | null
  match_pct: number | null
  match_captured: boolean | null
  enrollment_window: string | null
}

// ── Sprint 75: Knowledge Base Manager ────────────────────────────────────────

export interface KBDocumentSummary {
  doc_id: string
  filename: string
  category: string
  description: string
  chunk_count: number
  file_size_bytes: number
  uploaded_at: string
  content_preview: string
}

export interface KBStats {
  total_documents: number
  total_chunks: number
  by_category: Record<string, number>
  agents_powered: string[]
  last_ingested: string | null
}

export interface KBChunkResult {
  doc_id: string
  filename: string
  category: string
  chunk_text: string
  score: number
}

// ── Sprint 74: SSO domain check ───────────────────────────────────────────────

export interface SSODomainCheckResult {
  sso_enabled: boolean
  provider: string | null
  provider_display: string | null
  button_label: string | null
  logo: string | null
}

// ── Copilot Action types (Sprint 82) ─────────────────────────────────────────

export interface SuggestedAction {
  title: string
  description: string
  action_type: string
  risk_tier: 'LOW' | 'MEDIUM' | 'HIGH'
  arr_impact: number | null
  worker_name: string
  finding_hash: string
}

const BASE = '/api'

// ── Low-level helpers ─────────────────────────────────────

export async function apiGet<T>(path: string, token?: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { headers })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  token?: string,
  contentType = 'application/json'
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': contentType }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

export async function apiDelete<T>(path: string, token?: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

export async function apiPostForm<T>(path: string, body: FormData, token?: string): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body })
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`)
  return res.json() as Promise<T>
}

// ── Core API ──────────────────────────────────────────────

export const api = {
  // Health
  health: () => apiGet<{ status: string; environment: string }>('/health'),

  // Scans
  createScan: (tenantId: string) =>
    apiPost<{ scan_id: string; status: string }>('/scans', { tenant_id: tenantId }),
  getScan: (scanId: string) => apiGet<ScanJob>(`/scans/${scanId}`),

  // Insights
  getInsights: (tenantId: string) =>
    apiGet<InsightsMemo>(`/insights?tenant_id=${encodeURIComponent(tenantId)}`),

  // ── Auth ────────────────────────────────────────────────

  createTenant: (tenantId: string, tenantName: string) =>
    apiPost<{ id: string; tenant_id: string; name: string }>('/users/tenants', {
      tenant_id: tenantId,
      name: tenantName,
    }),

  register: (
    email: string,
    password: string,
    tenantId: string,
    fullName?: string
  ) =>
    apiPost<AuthUser>('/users/register', {
      email,
      password,
      tenant_id: tenantId,
      full_name: fullName,
    }),

  login: async (email: string, password: string): Promise<TokenResponse> => {
    // OAuth2 password flow requires form-encoded body
    const body = new URLSearchParams({ username: email, password })
    const res = await fetch(`${BASE}/users/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    })
    if (!res.ok) throw new Error(`Login failed: ${await res.text()}`)
    return res.json() as Promise<TokenResponse>
  },

  me: (token: string) => apiGet<AuthUser>('/users/me', token),

  // ── API Keys ────────────────────────────────────────────

  listApiKeys: (token: string) => apiGet<ApiKey[]>('/users/me/api-keys', token),

  createApiKey: (token: string, name: string) =>
    apiPost<ApiKeyCreateResponse>('/users/me/api-keys', { name }, token),

  revokeApiKey: (token: string, keyId: string) =>
    apiDelete<{ ok: boolean }>(`/users/me/api-keys/${keyId}`, token),

  // ── Approvals ───────────────────────────────────────────

  listApprovals: (token: string, status?: string) =>
    apiGet<ApprovalRequest[]>(
      `/admin/approvals${status ? `?status=${status}` : ''}`,
      token,
    ),

  approveRequest: (token: string, approvalId: string) =>
    apiPost<{ ok: boolean; status: string }>(`/admin/approvals/${approvalId}/approve`, {}, token),

  rejectRequest: (token: string, approvalId: string, reason = '') =>
    apiPost<{ ok: boolean; status: string }>(
      `/admin/approvals/${approvalId}/reject?reason=${encodeURIComponent(reason)}`,
      {},
      token,
    ),

  // ── Remediation Actions ─────────────────────────────────

  listActions: (token: string, status?: string) =>
    apiGet<RemediationAction[]>(
      `/admin/actions${status ? `?status=${status}` : ''}`,
      token,
    ),

  completeAction: (token: string, actionId: string, notes = '') =>
    apiPost<RemediationAction>(
      `/admin/actions/${actionId}/complete?notes=${encodeURIComponent(notes)}`,
      {},
      token,
    ),

  deferAction: (token: string, actionId: string, reason = '') =>
    apiPost<RemediationAction>(
      `/admin/actions/${actionId}/defer?reason=${encodeURIComponent(reason)}`,
      {},
      token,
    ),

  executeAction: (token: string, actionId: string, dryRun = false) =>
    apiPost<{ ok: boolean; outcome: string; detail: string }>(
      `/admin/actions/${actionId}/execute?dry_run=${dryRun}`,
      {},
      token,
    ),

  // ── Signal / Noise ──────────────────────────────────────────────────

  listNoiseProfiles: (token: string) =>
    apiGet<NoiseProfile[]>('/admin/noise-profiles', token),

  refreshNoiseProfiles: (token: string) =>
    apiPost<{ ok: boolean; profiles_updated: number; profiles_seeded: number; proposals_created: number; workers_scanned: string[]; workers_seeded: string[] }>(
      '/admin/noise-profiles/refresh', {}, token,
    ),

  listProposals: (token: string, status?: string) =>
    apiGet<ThresholdProposal[]>(
      `/admin/proposals${status ? `?status=${status}` : ''}`,
      token,
    ),

  acceptProposal: (token: string, proposalId: string) =>
    apiPost<{ ok: boolean; applied_value: number }>(
      `/admin/proposals/${proposalId}/accept`, {}, token,
    ),

  rejectProposal: (token: string, proposalId: string) =>
    apiPost<{ ok: boolean }>(
      `/admin/proposals/${proposalId}/reject`, {}, token,
    ),

  // ── Portfolio ─────────────────────────────────────────────────────────

  portfolioSummary: (token: string, tenantIds: string[]) =>
    apiGet<{
      companies: Array<{
        tenant_id: string
        available: boolean
        data_source: 'insight_snapshot' | 'graph_heuristics' | 'none'
        last_insights_run: string | null
        error: string | null
        health_score: number
        severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'HEALTHY'
        finding_counts: {
          critical: number
          high: number
          medium: number
          low: number
          total: number
        }
        top_findings: Array<{
          worker: string
          severity: string
          title: string
        }>
        company_profile: {
          segment: string | null
          business_model: string | null
          data_confidence: string | null
        }
        metrics: {
          headcount: number
          stalled_deals: number | null
          at_risk_arr: number | null
          saas_annual_spend: number | null
          vendor_savings_opportunity: number | null
          workers_run: number
        }
        narrative_snippet: string | null
        llm_provider: string | null
        llm_model: string | null
        note?: string
      }>
      aggregate: {
        total_companies: number
        companies_with_data: number
        companies_with_full_intelligence: number
        companies_needing_insights_run: number
        critical_count: number
        high_count: number
        healthy_count: number
        avg_health_score: number
        total_critical_findings: number
        total_high_findings: number
      }
    }>(
      `/portfolio/summary?tenant_ids=${tenantIds.map(encodeURIComponent).join(',')}`,
      token,
    ),

  portfolioTenants: (token: string) =>
    apiGet<{
      tenants: Array<{
        tenant_id: string
        last_insights_run: string | null
        has_full_intelligence: boolean
      }>
    }>('/portfolio/tenants', token),

  // ── Insight Scheduling (Sprint 78) ────────────────────────────────────

  scheduleList: (token: string) =>
    apiGet<{
      schedules: Array<{
        id: string
        tenant_id: string
        cadence: 'daily' | 'weekly' | 'manual'
        hour_utc: number
        day_of_week: number | null
        enabled: boolean
        last_triggered_at: string | null
        last_status: string | null
        last_error: string | null
      }>
    }>('/schedule', token),

  scheduleUpsert: (
    token: string,
    body: {
      tenant_id: string
      cadence: 'daily' | 'weekly' | 'manual'
      hour_utc: number
      day_of_week?: number | null
      enabled: boolean
    },
  ) => apiPost<{ schedule: object; created: boolean }>('/schedule', body, token),

  scheduleDelete: (token: string, tenantId: string) =>
    apiDelete<{ ok: boolean }>(`/schedule/${encodeURIComponent(tenantId)}`, token),

  // ── Multi-tenant access (Sprint 80) ──────────────────────────────────────

  accessMyTenants: (token: string) =>
    apiGet<{
      tenants: Array<{
        tenant_id: string
        is_home: boolean
        last_insights_run: string | null
        has_full_intelligence: boolean
      }>
    }>('/access/my-tenants', token),

  accessGrant: (token: string, userId: string, tenantId: string, note?: string) =>
    apiPost<{ ok: boolean; user_id: string; tenant_id: string; created: boolean }>(
      '/access/grant', { user_id: userId, tenant_id: tenantId, note: note ?? null }, token
    ),

  accessRevoke: (token: string, userId: string, tenantId: string) =>
    apiDelete<{ ok: boolean }>(`/access/revoke/${encodeURIComponent(userId)}/${encodeURIComponent(tenantId)}`, token),

  accessUserTenants: (token: string, userId: string) =>
    apiGet<{
      tenants: Array<{
        tenant_id: string
        is_home: boolean
        last_insights_run: string | null
        has_full_intelligence: boolean
      }>
    }>(`/access/users/${encodeURIComponent(userId)}`, token),

  // ── Copilot (Sprint 79 / Sprint 82) ───────────────────────────────────

  copilotAsk: (token: string, tenantId: string, question: string) =>
    apiPost<{
      answer: string
      intent: string
      data: Record<string, unknown>
      sources: string[]
      llm_provider: string
      llm_available: boolean
      suggested_actions?: SuggestedAction[]
    }>('/copilot/ask', { tenant_id: tenantId, question }, token),

  copilotCreateAction: (
    token: string,
    body: {
      tenant_id: string
      title: string
      description: string
      action_type: string
      risk_tier: string
      arr_impact?: number | null
      worker_name?: string
      finding_hash?: string
      assigned_to_email?: string
    },
  ) =>
    apiPost<{ action_id: string; approval_id: string | null; risk_tier: string; routed_to_approvals: boolean }>(
      '/copilot/create-action', body, token,
    ),

  // ── MFA ───────────────────────────────────────────────────────────────
  mfaStatus: (token: string) =>
    apiGet<{ mfa_enabled: boolean }>('/mfa/status', token),

  mfaSetup: (token: string) =>
    apiPost<{ secret: string; qr_uri: string; qr_image_base64: string }>(
      '/mfa/setup', {}, token,
    ),

  mfaVerify: (token: string, code: string) =>
    apiPost<{ ok: boolean; message: string }>(
      '/mfa/verify', { code }, token,
    ),

  mfaDisable: (token: string, code: string, password: string) =>
    apiPost<{ ok: boolean }>(
      '/mfa/disable', { code, password }, token,
    ),

  // ── SSO / OIDC ───────────────────────────────────────────────────────────

  listSSOProviders: (token: string) =>
    apiGet<Array<{
      id: string
      provider_slug: string
      display_name: string
      provider_type: string
      issuer_url: string
      client_id: string
      domains: string[]
      jit_provisioning: boolean
      default_role: string
      is_active: boolean
    }>>('/auth/sso/providers', token),

  createSSOProvider: (token: string, body: {
    provider_slug: string
    display_name: string
    provider_type: string
    issuer_url: string
    client_id: string
    client_secret: string
    domains: string[]
    jit_provisioning: boolean
    default_role: string
  }) =>
    apiPost<{ id: string; provider_slug: string; display_name: string }>(
      '/auth/sso/providers', body, token,
    ),

  deleteSSOProvider: (token: string, providerId: string) =>
    apiDelete<{ ok: boolean }>(`/auth/sso/providers/${providerId}`, token),

  detectSSOProvider: (email: string) =>
    apiGet<{
      provider_found: boolean
      provider_id: string | null
      display_name: string | null
      provider_slug: string | null
    }>(`/auth/sso/detect?email=${encodeURIComponent(email)}`),

  // SSO login URL (redirects to IdP — open in browser, not fetch)
  ssoLoginUrl: (providerId: string) => {
    const redirectUri = `${window.location.origin}/sso-return`
    return `/api/auth/sso/login?provider_id=${providerId}&redirect_uri=${encodeURIComponent(redirectUri)}`
  },

  // ── Sprint 74: domain-check (no auth — called before login) ──────────────
  sso: {
    domainCheck: (domain: string) =>
      apiGet<SSODomainCheckResult>(`/sso/domain-check?domain=${encodeURIComponent(domain)}`),
  },

  // ── DDQ ──────────────────────────────────────────────────────────────────────

  listKBDocuments: (token: string, tenantId: string) =>
    apiGet<KBDocument[]>(`/ddq/documents?tenant_id=${encodeURIComponent(tenantId)}`, token),

  uploadKBDocument: (token: string, tenantId: string, file: File, docType: string): Promise<KBDocument> => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('doc_type', docType)
    formData.append('tenant_id', tenantId)
    return fetch(`${BASE}/ddq/documents`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData,
    }).then(r => {
      if (!r.ok) throw new Error(`Upload failed: ${r.status}`)
      return r.json() as Promise<KBDocument>
    })
  },

  deleteKBDocument: (token: string, docId: string) =>
    apiDelete<{ ok: boolean }>(`/ddq/documents/${docId}`, token),

  analyzeDDQ: (token: string, tenantId: string, questionsText: string) =>
    apiPost<DDQResult>('/ddq/analyze', { tenant_id: tenantId, questions_text: questionsText }, token),

  getDDQJob: (token: string, jobId: string) =>
    apiGet<DDQResult>(`/ddq/jobs/${jobId}`, token),

  fillDDQTemplate: (tenantId: string, text?: string, file?: File, token?: string): Promise<DDQTemplateResult> => {
    const fd = new FormData()
    fd.append('tenant_id', tenantId)
    if (text) fd.append('text', text)
    if (file) fd.append('file', file)
    return apiPostForm<DDQTemplateResult>('/ddq/fill-template', fd, token)
  },

  getDDQSampleTemplate: (token?: string) =>
    apiGet<{ filename: string; text: string }>('/ddq/sample-template', token),

  // ── Mission Control ───────────────────────────────────────────────────────
  missionControlSummary: (token: string, tenantId: string) =>
    apiGet<MissionControlSummary>(`/mission-control/summary?tenant_id=${encodeURIComponent(tenantId)}`, token),

  listBlueprints: (token: string, tenantId: string) =>
    apiGet<ProcessBlueprint[]>(`/mission-control/blueprints?tenant_id=${encodeURIComponent(tenantId)}`, token),

  reviewBlueprint: (token: string, blueprintId: string) =>
    apiPost<{ ok: boolean }>(`/mission-control/blueprints/${blueprintId}/review`, {}, token),

  listAgentDeployments: (token: string, tenantId: string) =>
    apiGet<AgentDeployment[]>(`/mission-control/agents?tenant_id=${encodeURIComponent(tenantId)}`, token),

  pauseAgent: (token: string, deploymentId: string) =>
    apiPost<{ ok: boolean }>(`/mission-control/agents/${deploymentId}/pause`, {}, token),

  resumeAgent: (token: string, deploymentId: string) =>
    apiPost<{ ok: boolean }>(`/mission-control/agents/${deploymentId}/resume`, {}, token),

  // ── Portal Access Agent ───────────────────────────────────────────────────
  requestPortalAccess: (token: string, tenantId: string, customerEmail: string, reportedIssue: string) =>
    apiPost<PortalAccessResult>('/agents/portal-access/request', {
      tenant_id: tenantId,
      customer_email: customerEmail,
      reported_issue: reportedIssue,
    }, token),

  listPortalAccessRequests: (token: string, tenantId: string) =>
    apiGet<PortalAccessRequestSummary[]>(`/agents/portal-access/requests?tenant_id=${encodeURIComponent(tenantId)}`, token),

  getPortalAccessRequest: (token: string, requestId: string) =>
    apiGet<PortalAccessResult>(`/agents/portal-access/requests/${requestId}`, token),

  // ── Support Triage Agent ──────────────────────────────────────────────────
  submitSupportTicket: (
    token: string,
    tenantId: string,
    customerEmail: string,
    subject: string,
    body: string,
    customerName?: string,
  ) =>
    apiPost<TriageResult>(
      '/agents/support-triage/submit',
      {
        tenant_id: tenantId,
        customer_email: customerEmail,
        customer_name: customerName,
        subject,
        body,
      },
      token,
    ),

  listSupportTickets: (token: string, tenantId: string) =>
    apiGet<TicketSummary[]>(
      `/agents/support-triage/tickets?tenant_id=${encodeURIComponent(tenantId)}`,
      token,
    ),

  getSupportTicket: (token: string, ticketId: string) =>
    apiGet<TriageResult>(`/agents/support-triage/tickets/${ticketId}`, token),

  // ── Payroll Agent ──────────────────────────────────────────────────────────
  requestPayrollDocument: (token: string, tenantId: string, documentType: string, period: string) =>
    apiPost<PayrollResult>('/agents/payroll/request', {
      tenant_id: tenantId,
      document_type: documentType,
      period,
    }, token),

  listPayrollRequests: (token: string, tenantId: string) =>
    apiGet<PayrollRequest[]>(`/agents/payroll/requests?tenant_id=${encodeURIComponent(tenantId)}`, token),

  getPayrollRequest: (token: string, requestId: string) =>
    apiGet<PayrollResult>(`/agents/payroll/requests/${requestId}`, token),

  // ── Payment Status Agent ───────────────────────────────────────────────────
  paymentStatusLookup: (token: string, invoiceId: string, tenantId: string) =>
    apiPost<PaymentStatusResult>(
      '/payment-status/lookup',
      { invoice_id: invoiceId, tenant_id: tenantId },
      token,
    ),

  paymentStatusVendorLookup: (token: string, vendorEmail: string, tenantId: string) =>
    apiPost<PaymentStatusResult[]>(
      '/payment-status/vendor-lookup',
      { vendor_email: vendorEmail, tenant_id: tenantId },
      token,
    ),

  paymentStatusGetStuck: (token: string, tenantId: string) =>
    apiGet<StuckInvoicesSummary>(
      `/payment-status/stuck?tenant_id=${encodeURIComponent(tenantId)}`,
      token,
    ),

  // ── Benefits Agent ─────────────────────────────────────────────────────────
  benefits: {
    query: (employeeEmail: string, question: string, tenantId: string, token?: string) =>
      apiPost<BenefitsResult>(
        '/benefits/query',
        { employee_email: employeeEmail, question, tenant_id: tenantId },
        token,
      ),

    summary: (employeeEmail: string, tenantId: string, token?: string) =>
      apiGet<BenefitsSummary>(
        `/benefits/summary?employee_email=${encodeURIComponent(employeeEmail)}&tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),
  },

  // ── IT Access Agent ───────────────────────────────────────────────────────
  itAccess: {
    request: (requesterEmail: string, targetUserEmail: string, systemName: string, tenantId: string, token?: string) =>
      apiPost<ITAccessResult>(
        '/it-access/request',
        { requester_email: requesterEmail, target_user_email: targetUserEmail, system_name: systemName, tenant_id: tenantId },
        token,
      ),

    getRequest: (requestId: string, tenantId: string, token?: string) =>
      apiGet<ITAccessResult>(
        `/it-access/request/${encodeURIComponent(requestId)}?tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),

    getPending: (tenantId: string, token?: string) =>
      apiGet<ITAccessResult[]>(
        `/it-access/pending?tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),

    getCatalog: (token?: string) =>
      apiGet<SystemCatalogEntry[]>('/it-access/catalog', token),
  },

  // ── Vendor Onboarding Agent ────────────────────────────────────────────────
  vendorOnboarding: {
    status: (vendorEmail: string, tenantId: string, token?: string) =>
      apiGet<VendorOnboardingRecord>(
        `/vendor-onboarding/status?vendor_email=${encodeURIComponent(vendorEmail)}&tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),

    initiate: (vendorName: string, vendorEmail: string, entityType: string, tenantId: string, token?: string) =>
      apiPost<VendorOnboardingRecord>(
        '/vendor-onboarding/initiate',
        { vendor_name: vendorName, vendor_email: vendorEmail, entity_type: entityType, tenant_id: tenantId },
        token,
      ),

    inProgress: (tenantId: string, token?: string) =>
      apiGet<VendorOnboardingRecord[]>(
        `/vendor-onboarding/in-progress?tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),

    blocked: (tenantId: string, token?: string) =>
      apiGet<VendorOnboardingRecord[]>(
        `/vendor-onboarding/blocked?tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),
  },

  // ── Compliance Response Agent ──────────────────────────────────────────────
  compliance: {
    process: (customerName: string, questionnaireText: string, tenantId: string, token?: string) =>
      apiPost<ComplianceResult>(
        '/compliance/process',
        { customer_name: customerName, questionnaire_text: questionnaireText, tenant_id: tenantId },
        token,
      ),

    getSample: (token?: string) =>
      apiGet<{ text: string }>('/compliance/sample', token),

    getKbTopics: (token?: string) =>
      apiGet<{ topic: string; keywords: string[] }[]>('/compliance/kb-topics', token),
  },

  // ── Board Report Agent ─────────────────────────────────────────────────────
  boardReport: {
    generate: (tenantId: string, period?: string, token?: string) =>
      apiPost<BoardReport>(
        '/board-report/generate',
        { tenant_id: tenantId, period: period ?? null },
        token,
      ),

    getLatest: (tenantId: string, token?: string) =>
      apiGet<BoardReport>(
        `/board-report/latest?tenant_id=${encodeURIComponent(tenantId)}`,
        token,
      ),
  },

  // ── Design Session (Sprint 72) ─────────────────────────────────────────────
  designSession: {
    start: (tenantId: string) =>
      apiPost<DesignSession>('/design-session/start', { tenant_id: tenantId }),

    get: (sessionId: string, tenantId: string) =>
      apiGet<DesignSession>(
        `/design-session/${encodeURIComponent(sessionId)}?tenant_id=${encodeURIComponent(tenantId)}`,
      ),

    approveBlueprint: (sessionId: string, blueprintId: string, approved: boolean) =>
      apiPost<DesignSession>(
        `/design-session/${encodeURIComponent(sessionId)}/approve-blueprint`,
        { blueprint_id: blueprintId, approved },
      ),

    configure: (sessionId: string, blueprintId: string, config: Record<string, unknown>) =>
      apiPost<DesignSession>(
        `/design-session/${encodeURIComponent(sessionId)}/configure`,
        { blueprint_id: blueprintId, config },
      ),

    complete: (sessionId: string, tenantId: string) =>
      apiPost<DesignSession>(
        `/design-session/${encodeURIComponent(sessionId)}/complete`,
        { tenant_id: tenantId },
      ),

    getActive: (tenantId: string) =>
      apiGet<DesignSession | null>(
        `/design-session/active?tenant_id=${encodeURIComponent(tenantId)}`,
      ),
  },

  // ── Knowledge Base Manager (Sprint 75) ───────────────────────────────────
  knowledgeBase: {
    getDocuments: (tenantId: string, category?: string): Promise<KBDocumentSummary[]> => {
      const params = new URLSearchParams({ tenant_id: tenantId })
      if (category) params.set('category', category)
      return apiGet<KBDocumentSummary[]>(`/knowledge-base/documents?${params.toString()}`)
    },

    upload: (tenantId: string, file: File, category: string, description: string, token?: string): Promise<KBDocumentSummary> => {
      const fd = new FormData()
      fd.append('tenant_id', tenantId)
      fd.append('file', file)
      fd.append('category', category)
      fd.append('description', description)
      return apiPostForm<KBDocumentSummary>('/knowledge-base/upload', fd, token)
    },

    deleteDocument: (docId: string, tenantId: string): Promise<{ success: boolean }> =>
      apiDelete<{ success: boolean }>(`/knowledge-base/documents/${encodeURIComponent(docId)}?tenant_id=${encodeURIComponent(tenantId)}`),

    search: (tenantId: string, query: string, k = 6): Promise<KBChunkResult[]> => {
      const params = new URLSearchParams({ tenant_id: tenantId, q: query, k: String(k) })
      return apiGet<KBChunkResult[]>(`/knowledge-base/search?${params.toString()}`)
    },

    getStats: (tenantId: string): Promise<KBStats> =>
      apiGet<KBStats>(`/knowledge-base/stats?tenant_id=${encodeURIComponent(tenantId)}`),
  },

  // ── Communication Analysis (Sprint 73) ────────────────────────────────────
  communications: {
    summary: (tenantId: string) =>
      apiGet<CommAnalysisSummary>(
        `/communications/summary?tenant_id=${encodeURIComponent(tenantId)}`,
      ),

    messages: (tenantId: string, sentiment?: string, topic?: string) => {
      const params = new URLSearchParams({ tenant_id: tenantId })
      if (sentiment) params.set('sentiment', sentiment)
      if (topic) params.set('topic', topic)
      return apiGet<CommMessage[]>(`/communications/messages?${params.toString()}`)
    },

    atRisk: (tenantId: string) =>
      apiGet<CommMessage[]>(
        `/communications/at-risk?tenant_id=${encodeURIComponent(tenantId)}`,
      ),

    expansion: (tenantId: string) =>
      apiGet<CommMessage[]>(
        `/communications/expansion?tenant_id=${encodeURIComponent(tenantId)}`,
      ),
  },

  // ── Company Health Score (Sprint 77) ─────────────────────────────────────
  healthScore: {
    get: (tenantId: string): Promise<HealthScoreResponse> =>
      apiGet<HealthScoreResponse>(`/health-score?tenant_id=${encodeURIComponent(tenantId)}`),

    history: (tenantId: string, months = 6): Promise<HealthScoreHistory[]> =>
      apiGet<HealthScoreHistory[]>(
        `/health-score/history?tenant_id=${encodeURIComponent(tenantId)}&months=${months}`,
      ),

    dimension: (tenantId: string, key: string): Promise<DimensionScore> =>
      apiGet<DimensionScore>(
        `/health-score/dimension/${encodeURIComponent(key)}?tenant_id=${encodeURIComponent(tenantId)}`,
      ),
  },

  // ── Connectors (Sprint 83) ────────────────────────────────────────────────

  connectorsList: (token: string): Promise<RealConnectorStatus[]> =>
    apiGet<RealConnectorStatus[]>('/connectors', token),

  connectorsSalesforceAuthUrl: (token: string, _tenantId: string): Promise<{ auth_url: string }> =>
    apiGet<{ auth_url: string }>('/connectors/salesforce/auth-start?return_url=true', token),

  connectorsSalesforceDisconnect: (token: string, _tenantId: string): Promise<{ disconnected: boolean }> =>
    apiPost<{ disconnected: boolean }>('/connectors/salesforce/disconnect', {}, token),

  connectorsSalesforceTest: (token: string, _tenantId: string): Promise<{ connected: boolean; error?: string; status?: string }> =>
    apiPost<{ connected: boolean; error?: string; status?: string }>('/connectors/salesforce/test', {}, token),

  // ── Notification Center (Sprint 76) ───────────────────────────────────────
  notifications: {
    list: (tenantId: string, unreadOnly?: boolean, category?: string): Promise<Notification[]> => {
      const params = new URLSearchParams({ tenant_id: tenantId })
      if (unreadOnly) params.set('unread_only', 'true')
      if (category) params.set('category', category)
      return apiGet<Notification[]>(`/notifications?${params.toString()}`)
    },

    markRead: (id: string, tenantId: string): Promise<{ success: boolean }> =>
      apiPost<{ success: boolean }>(
        `/notifications/${encodeURIComponent(id)}/read?tenant_id=${encodeURIComponent(tenantId)}`,
        {},
      ),

    markAllRead: (tenantId: string): Promise<{ marked: number }> =>
      apiPost<{ marked: number }>('/notifications/read-all', { tenant_id: tenantId }),

    dismiss: (id: string, tenantId: string): Promise<{ success: boolean }> =>
      apiPost<{ success: boolean }>(
        `/notifications/${encodeURIComponent(id)}/dismiss?tenant_id=${encodeURIComponent(tenantId)}`,
        {},
      ),

    summary: (tenantId: string): Promise<NotificationSummary> =>
      apiGet<NotificationSummary>(
        `/notifications/summary?tenant_id=${encodeURIComponent(tenantId)}`,
      ),
  },
}
