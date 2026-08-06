import { useState, useEffect, useCallback } from 'react'
import {
  CreditCard, Search, Loader2, Copy, CheckCheck, AlertTriangle,
  Clock, Mail, AlertCircle, CheckCircle2, Ban,
  Timer, RotateCcw, ShieldAlert, UserCheck,
} from 'lucide-react'
import { api } from '../api/client'
import type { PaymentStatusResult, StuckInvoicesSummary } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusBadge(status: string) {
  switch (status) {
    case 'paid':         return 'bg-green-100 text-green-800 border-green-200'
    case 'scheduled':    return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'approved':     return 'bg-teal-100 text-teal-800 border-teal-200'
    case 'under_review': return 'bg-yellow-100 text-yellow-800 border-yellow-200'
    case 'received':     return 'bg-gray-100 text-gray-700 border-gray-200'
    case 'on_hold':      return 'bg-orange-100 text-orange-800 border-orange-200'
    case 'rejected':     return 'bg-red-100 text-red-800 border-red-200'
    default:             return 'bg-gray-100 text-gray-600 border-gray-200'
  }
}

function statusBar(status: string) {
  switch (status) {
    case 'paid':         return 'bg-green-500'
    case 'scheduled':    return 'bg-blue-500'
    case 'approved':     return 'bg-teal-500'
    case 'under_review': return 'bg-yellow-400'
    case 'received':     return 'bg-gray-400'
    case 'on_hold':      return 'bg-orange-500'
    case 'rejected':     return 'bg-red-500'
    default:             return 'bg-gray-300'
  }
}

function statusIcon(status: string) {
  const cls = 'flex-shrink-0'
  switch (status) {
    case 'paid':         return <CheckCircle2 size={14} className={`${cls} text-green-600`} />
    case 'scheduled':    return <Clock size={14} className={`${cls} text-blue-600`} />
    case 'approved':     return <CheckCheck size={14} className={`${cls} text-teal-600`} />
    case 'under_review': return <Timer size={14} className={`${cls} text-yellow-600`} />
    case 'received':     return <RotateCcw size={14} className={`${cls} text-gray-500`} />
    case 'on_hold':      return <AlertTriangle size={14} className={`${cls} text-orange-600`} />
    case 'rejected':     return <Ban size={14} className={`${cls} text-red-600`} />
    default:             return <AlertCircle size={14} className={`${cls} text-gray-400`} />
  }
}

function statusLabel(status: string) {
  switch (status) {
    case 'paid':         return 'Paid'
    case 'scheduled':    return 'Scheduled'
    case 'approved':     return 'Approved'
    case 'under_review': return 'Under Review'
    case 'received':     return 'Received'
    case 'on_hold':      return 'On Hold'
    case 'rejected':     return 'Rejected'
    default:             return status
  }
}

function approverRoleLabel(role: string | null) {
  switch (role) {
    case 'vendor_management': return 'Vendor Mgmt'
    case 'department_head':   return 'Dept Head'
    case 'cfo':               return 'CFO'
    case 'board_approval':    return 'Board'
    case 'ap_team':           return 'AP Team'
    default:                  return role ?? 'AP Team'
  }
}

function approverRoleColor(role: string | null) {
  switch (role) {
    case 'vendor_management': return 'bg-purple-100 text-purple-800'
    case 'department_head':   return 'bg-blue-100 text-blue-800'
    case 'cfo':               return 'bg-red-100 text-red-800'
    case 'board_approval':    return 'bg-rose-100 text-rose-900'
    case 'ap_team':           return 'bg-gray-100 text-gray-700'
    default:                  return 'bg-gray-100 text-gray-700'
  }
}

function formatAmount(amount: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(amount)
}

function getToken(): string {
  return localStorage.getItem('scout_token') || ''
}

function getTenant(): string {
  return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT
}

// ── Invoice result card ───────────────────────────────────────────────────────

function InvoiceCard({ result, onReset }: {
  result: PaymentStatusResult
  onReset: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [editedResponse, setEditedResponse] = useState(result.draft_response)

  function handleCopy() {
    navigator.clipboard.writeText(editedResponse)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-4">
      {/* Status card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className={`h-1.5 ${statusBar(result.status)}`} />
        <div className="p-5 space-y-4">
          {/* Header row */}
          <div className="flex flex-wrap items-start gap-3 justify-between">
            <div>
              <div className="text-lg font-bold text-gray-900">{result.invoice_id}</div>
              <div className="text-sm text-gray-500">{result.vendor_name}</div>
            </div>
            <div className="text-right">
              <div className="text-xl font-bold text-gray-900">{formatAmount(result.amount)}</div>
              <div className="text-xs text-gray-400">{result.days_outstanding} days outstanding</div>
            </div>
          </div>

          {/* Status badge */}
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${statusBadge(result.status)}`}>
              {statusIcon(result.status)}
              {statusLabel(result.status)}
            </span>
            {result.is_stuck && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-red-50 text-red-700 border border-red-200">
                <AlertTriangle size={11} />
                Stuck
              </span>
            )}
          </div>

          {/* Key details grid */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-gray-400 text-xs">Submitted</span>
              <div className="font-medium text-gray-800">{result.submitted_date}</div>
            </div>
            {result.payment_date && (
              <div>
                <span className="text-gray-400 text-xs">Payment Date</span>
                <div className="font-medium text-gray-800">{result.payment_date}</div>
              </div>
            )}
            <div>
              <span className="text-gray-400 text-xs">Vendor Email</span>
              <div className="font-medium text-gray-700 truncate">{result.vendor_email || '—'}</div>
            </div>
          </div>

          {/* Hold reason */}
          {result.hold_reason && (
            <div className="flex items-start gap-2.5 bg-orange-50 border border-orange-200 rounded-lg px-4 py-3">
              <AlertTriangle size={15} className="text-orange-500 mt-0.5 flex-shrink-0" />
              <div>
                <div className="text-xs font-bold text-orange-700 uppercase tracking-wide mb-0.5">Hold Reason</div>
                <p className="text-sm text-orange-800">{result.hold_reason}</p>
              </div>
            </div>
          )}

          {/* Stuck reason */}
          {result.stuck_reason && !result.hold_reason && (
            <div className="flex items-start gap-2.5 bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3">
              <Clock size={15} className="text-yellow-600 mt-0.5 flex-shrink-0" />
              <div>
                <div className="text-xs font-bold text-yellow-700 uppercase tracking-wide mb-0.5">Delay Reason</div>
                <p className="text-sm text-yellow-800">{result.stuck_reason}</p>
              </div>
            </div>
          )}

          {/* Approver routing */}
          {result.approver_role && (
            <div className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-3">
              <div className="flex items-center gap-2">
                <UserCheck size={14} className="text-gray-500" />
                <span className="text-sm text-gray-600">Routes to</span>
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${approverRoleColor(result.approver_role)}`}>
                  {approverRoleLabel(result.approver_role)}
                </span>
              </div>
              <span className="text-xs text-gray-400">{result.approver}</span>
            </div>
          )}

          {/* Reset button */}
          <button
            onClick={onReset}
            className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
          >
            Clear and look up another invoice
          </button>
        </div>
      </div>

      {/* Draft response */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <span className="text-sm font-semibold text-gray-900">Draft Vendor Response</span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-800 transition-colors"
          >
            {copied
              ? <><CheckCheck size={13} className="text-emerald-500" /> Copied!</>
              : <><Copy size={13} /> Copy</>}
          </button>
        </div>
        <div className="p-5 space-y-3">
          <textarea
            value={editedResponse}
            onChange={e => setEditedResponse(e.target.value)}
            rows={7}
            className="w-full px-4 py-3 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none leading-relaxed"
          />
          <button
            onClick={handleCopy}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-white rounded-lg hover:opacity-90 transition-opacity"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {copied
              ? <><CheckCheck size={15} /> Copied!</>
              : <><Copy size={15} /> Copy Response</>}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Left panel — lookup ───────────────────────────────────────────────────────

function LookupPanel() {
  const [tab, setTab] = useState<'invoice' | 'vendor'>('invoice')
  const [invoiceId, setInvoiceId] = useState('')
  const [vendorEmail, setVendorEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PaymentStatusResult | null>(null)
  const [vendorResults, setVendorResults] = useState<PaymentStatusResult[] | null>(null)

  async function handleLookup() {
    setError(null)
    setResult(null)
    setVendorResults(null)
    setLoading(true)

    try {
      const token = getToken()
      const tenant = getTenant()

      if (tab === 'invoice') {
        if (!invoiceId.trim()) { setError('Please enter an invoice ID.'); setLoading(false); return }
        const r = await api.paymentStatusLookup(token, invoiceId.trim(), tenant)
        setResult(r)
      } else {
        if (!vendorEmail.trim()) { setError('Please enter a vendor email.'); setLoading(false); return }
        const rs = await api.paymentStatusVendorLookup(token, vendorEmail.trim(), tenant)
        setVendorResults(rs)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Lookup failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setResult(null)
    setVendorResults(null)
    setError(null)
    setInvoiceId('')
    setVendorEmail('')
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleLookup()
  }

  return (
    <div className="space-y-5">
      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-gray-100 rounded-lg">
        {(['invoice', 'vendor'] as const).map(t => (
          <button
            key={t}
            onClick={() => { setTab(t); handleReset() }}
            className={[
              'flex-1 py-2 text-sm font-semibold rounded-md transition-all',
              tab === t
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700',
            ].join(' ')}
          >
            {t === 'invoice' ? 'Invoice ID' : 'Vendor Email'}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex gap-2">
        {tab === 'invoice' ? (
          <input
            type="text"
            value={invoiceId}
            onChange={e => setInvoiceId(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="INV-2024-003"
            className="flex-1 px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        ) : (
          <input
            type="email"
            value={vendorEmail}
            onChange={e => setVendorEmail(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="billing@vendor.com"
            className="flex-1 px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        )}
        <button
          onClick={handleLookup}
          disabled={loading}
          className="flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          style={{ backgroundColor: '#1B2A4A' }}
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
          {loading ? 'Looking up…' : 'Look Up'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Single invoice result */}
      {result && <InvoiceCard result={result} onReset={handleReset} />}

      {/* Vendor results */}
      {vendorResults !== null && (
        <div className="space-y-3">
          {vendorResults.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10 text-center">
              <Mail size={32} className="text-gray-300 mb-2" />
              <p className="text-gray-500 font-medium">No invoices found</p>
              <p className="text-gray-400 text-sm mt-1">No invoices are on file for {vendorEmail}</p>
            </div>
          ) : (
            vendorResults.map(r => (
              <div key={r.invoice_id} className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                <div className={`h-1 ${statusBar(r.status)}`} />
                <div className="p-4 flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-semibold text-gray-900 text-sm">{r.invoice_id}</div>
                    <div className="text-xs text-gray-500">{r.vendor_name}</div>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="font-bold text-gray-900">{formatAmount(r.amount)}</div>
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${statusBadge(r.status)}`}>
                      {statusIcon(r.status)}
                      {statusLabel(r.status)}
                    </span>
                  </div>
                  {r.is_stuck && (
                    <AlertTriangle size={15} className="text-orange-500 flex-shrink-0" />
                  )}
                </div>
              </div>
            ))
          )}
          <button
            onClick={handleReset}
            className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
          >
            Clear results
          </button>
        </div>
      )}

      {/* Empty state (before any search) */}
      {!result && vendorResults === null && !loading && !error && (
        <div className="flex flex-col items-center justify-center py-12 text-center px-6">
          <CreditCard size={36} className="text-gray-300 mb-3" />
          <p className="text-gray-500 font-medium">Look up an invoice</p>
          <p className="text-gray-400 text-sm mt-1">
            Enter an invoice ID (e.g. INV-2024-003) or vendor email to check payment status.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Right panel — stuck invoices dashboard ────────────────────────────────────

function StuckDashboard() {
  const [summary, setSummary] = useState<StuckInvoicesSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const token = getToken()
      const tenant = getTenant()
      const data = await api.paymentStatusGetStuck(token, tenant)
      setSummary(data)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load stuck invoices'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function StuckGroup({ title, items, groupColor }: {
    title: string
    items: PaymentStatusResult[]
    groupColor: string
  }) {
    if (items.length === 0) return null
    return (
      <div>
        <div className={`text-xs font-bold uppercase tracking-wider mb-2 ${groupColor}`}>{title}</div>
        <div className="space-y-2">
          {items.map(inv => (
            <div key={inv.invoice_id} className="bg-white rounded-lg border border-gray-100 shadow-sm p-3.5">
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="min-w-0">
                  <div className="font-semibold text-gray-900 text-sm">{inv.invoice_id}</div>
                  <div className="text-xs text-gray-500 truncate">{inv.vendor_name}</div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="font-bold text-gray-900 text-sm">{formatAmount(inv.amount)}</div>
                  <div className="text-xs text-gray-400">{inv.days_outstanding}d outstanding</div>
                </div>
              </div>

              {inv.stuck_reason && (
                <p className="text-xs text-gray-500 mb-2 leading-relaxed">{inv.stuck_reason}</p>
              )}

              <div className="flex items-center justify-between">
                {inv.approver_role ? (
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${approverRoleColor(inv.approver_role)}`}>
                    {approverRoleLabel(inv.approver_role)}
                  </span>
                ) : (
                  <span />
                )}
                {inv.approver && (
                  <button
                    className="text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors flex items-center gap-1"
                    onClick={() => {
                      const subject = encodeURIComponent(`Action Required: ${inv.invoice_id} — ${inv.vendor_name}`)
                      const body = encodeURIComponent(
                        `Hi,\n\nInvoice ${inv.invoice_id} (${inv.vendor_name}, ${formatAmount(inv.amount)}) requires your attention.\n\nReason: ${inv.stuck_reason}\n\nPlease review and take action.\n\nThanks`
                      )
                      window.open(`mailto:${inv.approver}?subject=${subject}&body=${body}`)
                    }}
                  >
                    <ShieldAlert size={11} />
                    Route to Approver
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle size={16} className="text-orange-500" />
          <span className="text-sm font-bold text-gray-900">Requires Attention</span>
          {summary && summary.total_stuck > 0 && (
            <span className="inline-flex items-center justify-center w-5 h-5 text-xs font-bold text-white bg-red-500 rounded-full">
              {summary.total_stuck}
            </span>
          )}
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="text-xs font-medium text-gray-400 hover:text-gray-700 flex items-center gap-1 transition-colors"
        >
          <RotateCcw size={11} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-gray-300" />
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {summary && !loading && (
        <div className="space-y-5">
          {summary.total_stuck === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CheckCircle2 size={36} className="text-green-400 mb-3" />
              <p className="text-gray-600 font-medium">All clear</p>
              <p className="text-gray-400 text-sm mt-1">No stuck invoices require attention.</p>
            </div>
          ) : (
            <>
              <StuckGroup
                title={`On Hold (${summary.on_hold.length})`}
                items={summary.on_hold}
                groupColor="text-orange-600"
              />
              <StuckGroup
                title={`Overdue Review (${summary.overdue_review.length})`}
                items={summary.overdue_review}
                groupColor="text-yellow-600"
              />
              <StuckGroup
                title={`Queue Delays (${summary.queue_delays.length})`}
                items={summary.queue_delays}
                groupColor="text-gray-500"
              />
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PaymentStatus() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-6 py-8">

        {/* Page header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              <CreditCard size={18} className="text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Payment Status</h1>
          </div>
          <p className="text-gray-500 text-sm ml-12">
            Look up invoice payment status, identify stuck invoices, and generate professional vendor responses.
          </p>
        </div>

        {/* Two-panel layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left panel — Invoice Lookup */}
          <div>
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-5">
                <Search size={15} className="text-gray-400" />
                <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Invoice Lookup</span>
              </div>
              <LookupPanel />
            </div>
          </div>

          {/* Right panel — Stuck Invoices Dashboard */}
          <div>
            <div className="bg-gray-50 rounded-2xl border border-gray-200 p-6">
              <StuckDashboard />
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
