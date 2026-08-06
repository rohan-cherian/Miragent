import { useState, useEffect } from 'react'
import {
  Headphones, Loader2, Copy, CheckCheck, AlertTriangle, ShieldAlert,
  Bug, Receipt, KeyRound, Lightbulb, User, Shield, Database, HelpCircle,
  Building2, Clock, ClipboardList,
} from 'lucide-react'
import { api } from '../api/client'
import type { TriageResult, TicketSummary, AccountContext } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function priorityColors(label: string | null) {
  switch (label) {
    case 'P1-Critical': return { badge: 'bg-red-100 text-red-800 border-red-200', bar: 'bg-red-500', dot: 'bg-red-500' }
    case 'P2-High':     return { badge: 'bg-orange-100 text-orange-800 border-orange-200', bar: 'bg-orange-400', dot: 'bg-orange-400' }
    case 'P3-Medium':   return { badge: 'bg-yellow-100 text-yellow-800 border-yellow-200', bar: 'bg-yellow-400', dot: 'bg-yellow-400' }
    case 'P4-Low':      return { badge: 'bg-emerald-100 text-emerald-800 border-emerald-200', bar: 'bg-emerald-400', dot: 'bg-emerald-400' }
    default:            return { badge: 'bg-gray-100 text-gray-700 border-gray-200', bar: 'bg-gray-300', dot: 'bg-gray-400' }
  }
}

function categoryIcon(cat: string | null) {
  const cls = 'flex-shrink-0'
  switch (cat) {
    case 'portal_access':    return <KeyRound size={14} className={cls} />
    case 'billing_dispute':  return <Receipt size={14} className={cls} />
    case 'technical_bug':    return <Bug size={14} className={cls} />
    case 'feature_request':  return <Lightbulb size={14} className={cls} />
    case 'account_mgmt':     return <User size={14} className={cls} />
    case 'security_concern': return <Shield size={14} className={cls} />
    case 'data_question':    return <Database size={14} className={cls} />
    default:                 return <HelpCircle size={14} className={cls} />
  }
}

function categoryBadgeColor(cat: string | null) {
  switch (cat) {
    case 'portal_access':    return 'bg-blue-100 text-blue-700'
    case 'billing_dispute':  return 'bg-purple-100 text-purple-700'
    case 'technical_bug':    return 'bg-red-100 text-red-700'
    case 'feature_request':  return 'bg-amber-100 text-amber-700'
    case 'account_mgmt':     return 'bg-cyan-100 text-cyan-700'
    case 'security_concern': return 'bg-rose-100 text-rose-800'
    case 'data_question':    return 'bg-indigo-100 text-indigo-700'
    default:                 return 'bg-gray-100 text-gray-600'
  }
}

function tierBadge(tier: string) {
  switch (tier) {
    case 'enterprise': return 'bg-violet-100 text-violet-800'
    case 'growth':     return 'bg-blue-100 text-blue-700'
    case 'starter':    return 'bg-gray-100 text-gray-600'
    default:           return 'bg-gray-100 text-gray-600'
  }
}

function healthColor(score: number) {
  if (score >= 80) return 'text-emerald-600'
  if (score >= 60) return 'text-yellow-600'
  return 'text-red-600'
}

function formatArr(arr: number): string {
  if (arr >= 1_000_000) return `$${(arr / 1_000_000).toFixed(1)}M`
  if (arr >= 1_000) return `$${(arr / 1_000).toFixed(0)}k`
  return `$${arr.toFixed(0)}`
}

// ── Account Context panel ─────────────────────────────────────────────────────

function AccountPanel({ ctx }: { ctx: AccountContext }) {
  return (
    <div className="space-y-3">
      <div className="text-xs font-bold text-gray-500 uppercase tracking-wide">Account Context</div>
      <div className="bg-gray-50 rounded-lg p-4 space-y-2.5">
        {/* Company + tier */}
        <div className="flex items-center gap-2">
          <Building2 size={14} className="text-gray-400 flex-shrink-0" />
          <span className="text-sm font-semibold text-gray-800">{ctx.company_name}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${tierBadge(ctx.contract_tier)}`}>
            {ctx.contract_tier.charAt(0).toUpperCase() + ctx.contract_tier.slice(1)}
          </span>
        </div>

        {/* ARR */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">ARR</span>
          <span className="font-semibold text-gray-800">{formatArr(ctx.arr)}</span>
        </div>

        {/* Health score */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">Health Score</span>
          <span className={`font-bold ${healthColor(ctx.health_score)}`}>{ctx.health_score}/100</span>
        </div>

        {/* Account status */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">Status</span>
          <span className={`font-medium ${ctx.account_status === 'at_risk' ? 'text-orange-600' : ctx.account_status === 'churned' ? 'text-red-600' : 'text-emerald-600'}`}>
            {ctx.account_status.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </span>
        </div>

        {/* Prior tickets */}
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500">Tickets (30d)</span>
          <span className={`font-semibold ${ctx.prior_tickets_30d >= 3 ? 'text-orange-600' : 'text-gray-700'}`}>
            {ctx.prior_tickets_30d}
            {ctx.prior_tickets_30d >= 3 && ' ⚠'}
          </span>
        </div>

        {/* CSM */}
        <div className="pt-1 border-t border-gray-200">
          <div className="text-xs text-gray-500 mb-0.5">Customer Success Manager</div>
          <div className="text-sm font-medium text-gray-800">{ctx.csm_name}</div>
          <div className="text-xs text-gray-400">{ctx.csm_email}</div>
        </div>
      </div>
    </div>
  )
}

// ── Result panel ──────────────────────────────────────────────────────────────

function ResultPanel({ result, editedResponse, setEditedResponse }: {
  result: TriageResult
  editedResponse: string
  setEditedResponse: (v: string) => void
}) {
  const [copied, setCopied] = useState(false)
  const pc = priorityColors(result.priority_label)

  function handleCopy() {
    navigator.clipboard.writeText(editedResponse)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      {/* Left: ticket analysis */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className={`h-1.5 ${pc.bar}`} />
        <div className="p-6 space-y-5">
          {/* Priority badge — large and prominent */}
          <div className="flex flex-wrap items-center gap-3">
            <span className={`inline-flex items-center px-4 py-1.5 rounded-full text-sm font-bold border ${pc.badge}`}>
              {result.priority_label}
            </span>
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${categoryBadgeColor(result.category)}`}>
              {categoryIcon(result.category)}
              {result.category_label}
            </span>
          </div>

          {/* Priority score bar */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Priority Score</span>
              <span className="text-sm font-bold text-gray-700">{result.priority_score}/100</span>
            </div>
            <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${pc.bar}`}
                style={{ width: `${result.priority_score}%` }}
              />
            </div>
          </div>

          {/* Assigned queue */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">Assigned Queue</span>
            <span className="text-sm font-bold text-gray-900 ml-auto capitalize">{result.assigned_queue}</span>
          </div>

          {/* Escalation alert */}
          {result.escalation_reason && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              <ShieldAlert size={16} className="text-red-500 mt-0.5 flex-shrink-0" />
              <div>
                <div className="text-xs font-bold text-red-700 uppercase tracking-wide mb-0.5">Escalation Required</div>
                <p className="text-sm text-red-700">{result.escalation_reason}</p>
              </div>
            </div>
          )}

          {/* Routing explanation */}
          <div>
            <div className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-1.5">Routing Explanation</div>
            <p className="text-xs text-gray-500 italic leading-relaxed">{result.routing_explanation}</p>
          </div>

          {/* Account context */}
          <AccountPanel ctx={result.account_context} />
        </div>
      </div>

      {/* Right: drafted response */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-900">Drafted First Response</span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800 transition-colors"
          >
            {copied ? <><CheckCheck size={13} className="text-emerald-500" /> Copied!</> : <><Copy size={13} /> Copy Response</>}
          </button>
        </div>
        <div className="p-6 space-y-4">
          <textarea
            value={editedResponse}
            onChange={e => setEditedResponse(e.target.value)}
            rows={12}
            className="w-full px-4 py-3 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none leading-relaxed font-mono"
          />
          <button
            onClick={handleCopy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-white rounded-lg transition-opacity hover:opacity-90"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {copied ? <><CheckCheck size={15} /> Response Copied!</> : <><Copy size={15} /> Copy Response</>}
          </button>
          <div className="text-xs text-gray-400 leading-relaxed">
            <span className="font-semibold text-gray-500">Next steps for {result.assigned_queue} team:</span>{' '}
            {result.routing_explanation}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Recent tickets table ──────────────────────────────────────────────────────

function TicketsTable({ rows }: { rows: TicketSummary[] }) {
  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center px-6">
        <ClipboardList size={36} className="text-gray-300 mb-3" />
        <p className="text-gray-500 font-medium">No tickets yet.</p>
        <p className="text-gray-400 text-sm mt-1">Submit a ticket above to get started.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Time</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Customer</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Subject</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Category</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Priority</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Queue</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Escalated</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {rows.map(r => {
            const pc = priorityColors(r.priority_label)
            return (
              <tr key={r.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                  {new Date(r.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-gray-700 text-xs font-medium">{r.customer_email}</td>
                <td className="px-4 py-3 text-gray-600 text-xs max-w-[180px] truncate">{r.subject}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${categoryBadgeColor(r.category)}`}>
                    {categoryIcon(r.category)}
                    {r.category?.replace('_', ' ') ?? '—'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {r.priority_label ? (
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border ${pc.badge}`}>
                      {r.priority_label}
                    </span>
                  ) : '—'}
                </td>
                <td className="px-4 py-3 text-gray-600 text-xs capitalize">{r.assigned_queue ?? '—'}</td>
                <td className="px-4 py-3 text-center text-base">
                  {r.escalation_reason ? '⚠️' : <span className="text-gray-300 text-xs">—</span>}
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold
                    ${r.status === 'escalated' ? 'bg-red-100 text-red-700' :
                      r.status === 'draft_ready' ? 'bg-emerald-100 text-emerald-700' :
                      'bg-gray-100 text-gray-600'}`}>
                    {r.status}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SupportTriage() {
  const [form, setForm] = useState({ customerEmail: '', customerName: '', subject: '', body: '' })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TriageResult | null>(null)
  const [tickets, setTickets] = useState<TicketSummary[]>([])
  const [editedResponse, setEditedResponse] = useState('')
  const [error, setError] = useState('')
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT)

  const token = localStorage.getItem('miragent_token') ?? ''

  useEffect(() => {
    const stored = localStorage.getItem(DEFAULT_TENANT_KEY)
    if (stored) setTenantId(stored)
    loadTickets(stored ?? DEFAULT_TENANT)
  }, [])

  async function loadTickets(tid?: string) {
    if (!token) return
    try {
      const rows = await api.listSupportTickets(token, tid ?? tenantId)
      setTickets(rows.slice(0, 15))
    } catch {
      // non-critical
    }
  }

  async function handleSubmit() {
    if (!token) { setError('You must be logged in to submit a ticket.'); return }
    if (!form.customerEmail.trim()) { setError('Customer email is required.'); return }
    if (!form.subject.trim()) { setError('Subject is required.'); return }
    if (!form.body.trim()) { setError('Ticket body is required.'); return }

    setLoading(true)
    setError('')
    setResult(null)
    setEditedResponse('')

    try {
      const res = await api.submitSupportTicket(
        token,
        tenantId,
        form.customerEmail.trim(),
        form.subject.trim(),
        form.body.trim(),
        form.customerName.trim() || undefined,
      )
      setResult(res)
      setEditedResponse(res.drafted_response)
      await loadTickets()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Page header */}
      <div className="mb-2">
        <div className="flex items-center gap-2 mb-1">
          <Headphones size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Support Triage Agent</h1>
        </div>
        <p className="text-gray-500">
          Classify, prioritize, and route incoming support tickets instantly.
        </p>
      </div>

      {/* Submission form */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-4">Submit Ticket for Triage</h2>
        <div className="space-y-4">
          {/* Row: customer email + name */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Customer Email <span className="text-red-400">*</span>
              </label>
              <input
                type="email"
                value={form.customerEmail}
                onChange={e => setForm(f => ({ ...f, customerEmail: e.target.value }))}
                placeholder="customer@example.com"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Customer Name <span className="text-gray-400">(optional)</span>
              </label>
              <input
                type="text"
                value={form.customerName}
                onChange={e => setForm(f => ({ ...f, customerName: e.target.value }))}
                placeholder="Jane Smith"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Subject */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Subject <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={form.subject}
              onChange={e => setForm(f => ({ ...f, subject: e.target.value }))}
              placeholder="e.g. Getting 500 error on dashboard"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Body */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Ticket Body <span className="text-red-400">*</span>
            </label>
            <textarea
              value={form.body}
              onChange={e => setForm(f => ({ ...f, body: e.target.value }))}
              placeholder="Paste the customer's message here..."
              rows={6}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>

          {/* Submit button */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{ backgroundColor: '#1B2A4A' }}
              className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium text-white rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {loading ? (
                <><Loader2 size={16} className="animate-spin" /> Analyzing ticket...</>
              ) : (
                <><Headphones size={16} /> Triage Ticket</>
              )}
            </button>
            {loading && (
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Clock size={14} className="animate-pulse" />
                Classifying and pulling account context…
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

      {/* Result */}
      {result && (
        <ResultPanel
          result={result}
          editedResponse={editedResponse}
          setEditedResponse={setEditedResponse}
        />
      )}

      {/* Recent tickets table */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <span className="text-base font-semibold text-gray-900">Recent Tickets</span>
          <span className="text-xs text-gray-400">{tickets.length} ticket{tickets.length !== 1 ? 's' : ''}</span>
        </div>
        <TicketsTable rows={tickets} />
      </div>
    </div>
  )
}
