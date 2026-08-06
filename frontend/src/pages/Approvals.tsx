/**
 * Approvals.tsx — Sprint 48
 *
 * The agent's approval inbox. When the execution runner determines that
 * an action requires human sign-off (risk tier HIGH, or conditions not met),
 * it creates an ApprovalRequest. This page surfaces those requests and lets
 * admins approve or reject them with one click.
 *
 * This is the UI that makes "agentic with guardrails" visible and real.
 * Without this page, the story is "we have an approval gate" — with it,
 * you can show a prospect exactly what that means: the agent found something,
 * proposed a specific action (with full payload), and waited for a human.
 */

import { useEffect, useState } from 'react'
import {
  ShieldCheck,
  ShieldX,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { api } from '../api/client'
import type { ApprovalRequest } from '../types'

// ── Helpers ────────────────────────────────────────────────

function riskBadge(tier: ApprovalRequest['risk_tier']) {
  const cfg: Record<string, string> = {
    LOW:     'bg-blue-100 text-blue-700 border border-blue-200',
    MEDIUM:  'bg-yellow-100 text-yellow-700 border border-yellow-200',
    HIGH:    'bg-red-100 text-red-700 border border-red-200',
    BLOCKED: 'bg-gray-200 text-gray-600 border border-gray-300',
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg[tier] ?? cfg.HIGH}`}>
      {tier}
    </span>
  )
}

function statusIcon(status: ApprovalRequest['status']) {
  switch (status) {
    case 'PENDING':  return <Clock size={16} className="text-yellow-500 flex-shrink-0" />
    case 'APPROVED': return <CheckCircle2 size={16} className="text-emerald-500 flex-shrink-0" />
    case 'REJECTED': return <XCircle size={16} className="text-red-500 flex-shrink-0" />
    case 'EXPIRED':  return <AlertTriangle size={16} className="text-gray-400 flex-shrink-0" />
    default:         return null
  }
}

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function actionTypeLabel(at: string) {
  return at.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ── Approval card ──────────────────────────────────────────

function ApprovalCard({
  req,
  token,
  onRefresh,
}: {
  req: ApprovalRequest
  token: string | null
  onRefresh: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handle(action: 'approve' | 'reject') {
    if (!token) return
    setBusy(true)
    setError('')
    try {
      if (action === 'approve') {
        await api.approveRequest(token, req.id)
      } else {
        await api.rejectRequest(token, req.id, 'Rejected via Approvals UI')
      }
      onRefresh()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const isPending = req.status === 'PENDING'

  return (
    <div
      className={`bg-white rounded-xl border shadow-sm overflow-hidden transition-all ${
        isPending ? 'border-yellow-200' : 'border-gray-100'
      }`}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-4 p-4">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {statusIcon(req.status)}
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-semibold text-gray-800">
                {actionTypeLabel(req.action_type)}
              </p>
              {riskBadge(req.risk_tier)}
            </div>
            <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{req.rationale}</p>
            <p className="text-xs text-gray-400 mt-1">
              Created {fmtDate(req.created_at)}
              {req.expires_at && <> · Expires {fmtDate(req.expires_at)}</>}
            </p>
          </div>
        </div>

        {/* Action buttons (only for pending) */}
        {isPending && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => handle('reject')}
              disabled={busy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-red-200 text-red-600 text-xs font-medium hover:bg-red-50 disabled:opacity-50 transition-colors"
            >
              <ShieldX size={13} />
              Reject
            </button>
            <button
              onClick={() => handle('approve')}
              disabled={busy}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-xs font-medium disabled:opacity-50 transition-colors"
              style={{ backgroundColor: '#2ECC71' }}
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />}
              Approve
            </button>
          </div>
        )}

        {/* Expand toggle for payload */}
        <button
          onClick={() => setExpanded(e => !e)}
          className="text-gray-400 hover:text-gray-600 flex-shrink-0 mt-0.5"
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
      </div>

      {/* Error */}
      {error && (
        <p className="px-4 pb-3 text-xs text-red-600">{error}</p>
      )}

      {/* Expanded: proposed payload */}
      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50">
          <p className="text-xs font-medium text-gray-500 mb-2">Proposed Payload</p>
          <pre className="text-xs text-gray-700 bg-white rounded border border-gray-100 p-3 overflow-x-auto">
            {JSON.stringify(req.proposed_payload, null, 2)}
          </pre>
          <p className="text-xs text-gray-400 mt-2">Action ID: {req.action_id}</p>
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────

type Filter = 'ALL' | 'PENDING' | 'APPROVED' | 'REJECTED'

const FILTERS: Filter[] = ['ALL', 'PENDING', 'APPROVED', 'REJECTED']

export default function Approvals() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [filter, setFilter] = useState<Filter>('PENDING')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const token = localStorage.getItem('miragent_token')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const status = filter === 'ALL' ? undefined : filter
      const data = await api.listApprovals(token ?? '', status)
      setApprovals(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filter])

  const pending = approvals.filter(a => a.status === 'PENDING').length

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Agent Approvals</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Actions the agent wants to execute — review, approve, or reject.
            {pending > 0 && (
              <span className="ml-2 bg-yellow-100 text-yellow-700 border border-yellow-200 text-xs font-semibold px-2 py-0.5 rounded-full">
                {pending} pending
              </span>
            )}
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 mb-5 bg-gray-100 rounded-lg p-1 w-fit">
        {FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              filter === f
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {f === 'ALL' ? 'All' : f.charAt(0) + f.slice(1).toLowerCase()}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 size={24} className="animate-spin" />
        </div>
      )}

      {/* Empty */}
      {!loading && !error && approvals.length === 0 && (
        <div className="text-center py-16">
          <ShieldCheck size={40} className="mx-auto text-gray-200 mb-3" />
          <p className="text-sm font-medium text-gray-500">
            {filter === 'PENDING' ? 'No pending approvals' : `No ${filter.toLowerCase()} approvals`}
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Run a scan and generate insights to trigger agent actions.
          </p>
        </div>
      )}

      {/* List */}
      {!loading && approvals.length > 0 && (
        <div className="space-y-3">
          {approvals.map(req => (
            <ApprovalCard key={req.id} req={req} token={token} onRefresh={load} />
          ))}
        </div>
      )}

      {/* Explainer */}
      <div className="mt-8 p-4 bg-blue-50 border border-blue-100 rounded-xl">
        <p className="text-xs font-semibold text-blue-700 mb-1">How the approval gate works</p>
        <p className="text-xs text-blue-600 leading-relaxed">
          When Miragent detects a high-risk finding, it proposes a specific action
          (e.g. reassign 12 accounts from a departed rep). If the action type is
          HIGH risk in your playbook, execution pauses here. Approving triggers the
          executor immediately. Rejecting leaves the action open for manual handling.
          Every decision is logged to the audit trail.
        </p>
      </div>
    </div>
  )
}
