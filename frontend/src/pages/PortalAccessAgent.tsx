import { useState, useEffect } from 'react'
import { KeyRound, Loader2, Copy, CheckCheck, ShieldCheck, ShieldX, Clock, AlertTriangle } from 'lucide-react'
import { api } from '../api/client'
import type { PortalAccessResult, PortalAccessRequestSummary } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function diagnosisLabel(code: string | null): string {
  const map: Record<string, string> = {
    account_locked: 'Account Locked',
    not_provisioned: 'Not Provisioned',
    sso_mismatch: 'SSO Mismatch',
    mfa_reset: 'MFA Reset Required',
    domain_mismatch: 'Domain Mismatch',
    suspended: 'Account Suspended',
    not_found: 'Account Not Found',
    unknown: 'Unknown Issue',
  }
  return code ? (map[code] ?? code) : '—'
}

function statusColors(status: string) {
  switch (status) {
    case 'resolved':
      return { bar: 'bg-emerald-500', badge: 'bg-emerald-100 text-emerald-800', text: 'RESOLVED' }
    case 'escalated':
      return { bar: 'bg-red-500', badge: 'bg-red-100 text-red-800', text: 'ESCALATED' }
    case 'pending_action':
      return { bar: 'bg-amber-400', badge: 'bg-amber-100 text-amber-800', text: 'PENDING ACTION' }
    default:
      return { bar: 'bg-gray-400', badge: 'bg-gray-100 text-gray-700', text: status.toUpperCase() }
  }
}

function severityColors(severity: string) {
  switch (severity) {
    case 'low': return 'bg-emerald-100 text-emerald-700'
    case 'medium': return 'bg-amber-100 text-amber-700'
    case 'high': return 'bg-red-100 text-red-700'
    default: return 'bg-gray-100 text-gray-600'
  }
}

// ── Result card ───────────────────────────────────────────────────────────────

function ResultCard({ result }: { result: PortalAccessResult }) {
  const [copiedMsg, setCopiedMsg] = useState(false)
  const sc = statusColors(result.status)
  const diag = result.diagnosis

  function handleCopyMessage() {
    if (!diag) return
    navigator.clipboard.writeText(diag.customer_message)
    setCopiedMsg(true)
    setTimeout(() => setCopiedMsg(false), 2000)
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      {/* Severity bar */}
      <div className={`h-1.5 ${sc.bar}`} />

      <div className="p-6 space-y-5">
        {/* Header row */}
        <div className="flex flex-wrap items-start gap-3 justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-base font-bold text-gray-900">
              {diagnosisLabel(diag?.diagnosis_code ?? null)}
            </span>
            {diag && (
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${severityColors(diag.severity)}`}>
                {diag.severity.toUpperCase()} SEVERITY
              </span>
            )}
            {result.auto_resolved && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                Auto-Resolved
              </span>
            )}
          </div>
          <span className={`text-xs font-bold px-3 py-1 rounded-full tracking-wide ${sc.badge}`}>
            {sc.text}
          </span>
        </div>

        {/* Diagnosis text */}
        {diag && (
          <p className="text-sm text-gray-600">{diag.diagnosis_text}</p>
        )}

        {/* Error fallback */}
        {result.error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            {result.error}
          </div>
        )}

        {/* Resolution steps */}
        {diag && diag.resolution_steps.length > 0 && (
          <div>
            <div className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-2">
              Resolution Steps
            </div>
            <ol className="space-y-1.5">
              {diag.resolution_steps.map((step, i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm text-gray-700">
                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center mt-0.5">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        )}

        {/* Customer message + support instructions panels */}
        {diag && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Customer message */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <div className="text-xs font-bold text-gray-500 uppercase tracking-wide">
                  Customer Message
                </div>
                <button
                  onClick={handleCopyMessage}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  {copiedMsg
                    ? <><CheckCheck size={12} className="text-emerald-500" /> Copied!</>
                    : <><Copy size={12} /> Copy</>}
                </button>
              </div>
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm text-gray-700 leading-relaxed">
                {diag.customer_message}
              </div>
            </div>

            {/* Support instructions */}
            <div>
              <div className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1.5">
                Support Instructions
              </div>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800 leading-relaxed">
                {diag.support_instructions}
              </div>
            </div>
          </div>
        )}

        {/* Copy customer message button */}
        {diag && (
          <div className="flex justify-end pt-1">
            <button
              onClick={handleCopyMessage}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white rounded-lg transition-opacity hover:opacity-90"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              {copiedMsg
                ? <><CheckCheck size={15} /> Message Copied!</>
                : <><Copy size={15} /> Copy Customer Message</>}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Recent requests table ─────────────────────────────────────────────────────

function RecentRequests({ rows }: { rows: PortalAccessRequestSummary[] }) {
  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center px-6">
        <KeyRound size={36} className="text-gray-300 mb-3" />
        <p className="text-gray-500 font-medium">No requests yet.</p>
        <p className="text-gray-400 text-sm mt-1">
          Submit a portal access request above to get started.
        </p>
      </div>
    )
  }

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="bg-gray-50 border-b border-gray-100">
          <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Time</th>
          <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Customer Email</th>
          <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Diagnosis</th>
          <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Auto-Resolved</th>
          <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-50">
        {rows.map(r => {
          const sc = statusColors(r.status)
          return (
            <tr key={r.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                {new Date(r.created_at).toLocaleString()}
              </td>
              <td className="px-4 py-3 text-gray-800 font-medium text-xs">
                {r.customer_email}
              </td>
              <td className="px-4 py-3 text-gray-600 text-xs">
                {diagnosisLabel(r.diagnosis_code)}
              </td>
              <td className="px-4 py-3">
                {r.auto_resolved ? (
                  <span className="inline-flex items-center gap-1 text-emerald-700 text-xs font-medium">
                    <ShieldCheck size={13} /> Yes
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-gray-400 text-xs">
                    <ShieldX size={13} /> No
                  </span>
                )}
              </td>
              <td className="px-4 py-3">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${sc.badge}`}>
                  {sc.text}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PortalAccessAgent() {
  const [customerEmail, setCustomerEmail] = useState('')
  const [reportedIssue, setReportedIssue] = useState('')
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PortalAccessResult | null>(null)
  const [history, setHistory] = useState<PortalAccessRequestSummary[]>([])
  const [error, setError] = useState('')

  const token = localStorage.getItem('miragent_token') ?? ''

  useEffect(() => {
    const stored = localStorage.getItem(DEFAULT_TENANT_KEY)
    if (stored) setTenantId(stored)
    loadHistory()
  }, [])

  async function loadHistory() {
    if (!token) return
    try {
      const rows = await api.listPortalAccessRequests(token, tenantId || DEFAULT_TENANT)
      setHistory(rows.slice(0, 10))
    } catch {
      // history is non-critical
    }
  }

  async function handleSubmit() {
    if (!token) {
      setError('You must be logged in to submit a portal access request.')
      return
    }
    if (!customerEmail.trim()) {
      setError('Please enter the customer email address.')
      return
    }
    if (!reportedIssue.trim()) {
      setError('Please describe the issue the customer reported.')
      return
    }

    setLoading(true)
    setError('')
    setResult(null)

    try {
      const res = await api.requestPortalAccess(token, tenantId, customerEmail.trim(), reportedIssue.trim())
      setResult(res)
      await loadHistory()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Page header */}
      <div className="mb-2">
        <div className="flex items-center gap-2 mb-1">
          <KeyRound size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Portal Access Agent</h1>
        </div>
        <p className="text-gray-500">
          Diagnose and resolve customer login issues instantly.
        </p>
      </div>

      {/* Request form */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4">New Access Request</h2>

        <div className="space-y-4">
          {/* Customer email */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Customer Email <span className="text-gray-400">(the customer who cannot log in)</span>
            </label>
            <input
              type="email"
              value={customerEmail}
              onChange={e => setCustomerEmail(e.target.value)}
              placeholder="customer@example.com"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Issue description */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Issue Description
            </label>
            <textarea
              value={reportedIssue}
              onChange={e => setReportedIssue(e.target.value)}
              placeholder="Briefly describe what the customer reported — e.g. 'Getting invalid credentials error on portal login'"
              rows={3}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>

          {/* Submit */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{ backgroundColor: '#1B2A4A' }}
              className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Analyzing account…
                </>
              ) : (
                <>
                  <KeyRound size={16} />
                  Diagnose &amp; Resolve
                </>
              )}
            </button>

            {loading && (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Clock size={14} className="animate-pulse" />
                Looking up identity provider data…
              </div>
            )}
          </div>

          {error && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
              <AlertTriangle size={15} className="mt-0.5 flex-shrink-0" />
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Result card */}
      {result && <ResultCard result={result} />}

      {/* Recent requests */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <span className="text-base font-semibold text-gray-900">Recent Requests</span>
          <span className="text-xs text-gray-400">{history.length} request{history.length !== 1 ? 's' : ''}</span>
        </div>
        <RecentRequests rows={history} />
      </div>
    </div>
  )
}
