/**
 * Actions.tsx — Sprint 48
 *
 * Remediation actions dashboard. Workers surface findings; findings generate
 * RemediationActions — the concrete, assignable, executable work items that
 * close the loop between "we detected something" and "we fixed it."
 *
 * Three completion paths:
 *   1. Manual complete (human clicks Complete)
 *   2. Deferred  (snooze with a reason)
 *   3. Agent execute (send to the executor — runs reassign, update, approve, etc.)
 *
 * This page is the operational cockpit: everything that needs doing, in one place,
 * with one-click execution or deferral. The audit trail is automatic.
 */

import { useEffect, useState } from 'react'
import {
  ListTodo,
  CheckCircle2,
  Clock,
  XCircle,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  Play,
  CheckCheck,
  Pause,
  DollarSign,
  User,
  Calendar,
  Zap,
} from 'lucide-react'
import { api } from '../api/client'
import type { RemediationAction } from '../types'

// ── Helpers ────────────────────────────────────────────────

function statusBadge(status: RemediationAction['status']) {
  const cfg: Record<string, string> = {
    OPEN:        'bg-blue-100 text-blue-700 border border-blue-200',
    IN_PROGRESS: 'bg-yellow-100 text-yellow-700 border border-yellow-200',
    COMPLETE:    'bg-emerald-100 text-emerald-700 border border-emerald-200',
    DEFERRED:    'bg-gray-100 text-gray-600 border border-gray-300',
    CANCELLED:   'bg-red-50 text-red-400 border border-red-200',
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg[status] ?? cfg.OPEN}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

function statusIcon(status: RemediationAction['status']) {
  switch (status) {
    case 'OPEN':        return <ListTodo size={16} className="text-blue-500 flex-shrink-0" />
    case 'IN_PROGRESS': return <Clock size={16} className="text-yellow-500 flex-shrink-0" />
    case 'COMPLETE':    return <CheckCircle2 size={16} className="text-emerald-500 flex-shrink-0" />
    case 'DEFERRED':    return <Pause size={16} className="text-gray-400 flex-shrink-0" />
    case 'CANCELLED':   return <XCircle size={16} className="text-red-400 flex-shrink-0" />
    default:            return null
  }
}

function effortBadge(effort: string) {
  const cfg: Record<string, string> = {
    LOW:    'text-emerald-600',
    MEDIUM: 'text-yellow-600',
    HIGH:   'text-red-600',
  }
  return (
    <span className={`text-xs font-medium ${cfg[effort.toUpperCase()] ?? 'text-gray-500'}`}>
      {effort} effort
    </span>
  )
}

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function fmtCurrency(n: number | null) {
  if (n === null) return null
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

function workerLabel(name: string) {
  return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/Worker$/, '').trim()
}

// ── Confirm modal ──────────────────────────────────────────

function ConfirmModal({
  title,
  placeholder,
  confirmLabel,
  confirmStyle,
  onConfirm,
  onCancel,
}: {
  title: string
  placeholder: string
  confirmLabel: string
  confirmStyle: string
  onConfirm: (notes: string) => void
  onCancel: () => void
}) {
  const [notes, setNotes] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
        <h3 className="text-sm font-semibold text-gray-800 mb-3">{title}</h3>
        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className="w-full text-sm border border-gray-200 rounded-lg p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-200"
        />
        <div className="flex gap-2 mt-4 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(notes)}
            className={`px-4 py-2 text-sm text-white rounded-lg transition-colors ${confirmStyle}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Action card ────────────────────────────────────────────

function ActionCard({
  action,
  token,
  onRefresh,
}: {
  action: RemediationAction
  token: string | null
  onRefresh: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [modal, setModal] = useState<'complete' | 'defer' | 'execute' | null>(null)

  const isActionable = action.status === 'OPEN' || action.status === 'IN_PROGRESS'

  async function doComplete(notes: string) {
    if (!token) return
    setBusy(true); setError(''); setModal(null)
    try {
      await api.completeAction(token, action.id, notes)
      onRefresh()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function doDefer(reason: string) {
    if (!token) return
    setBusy(true); setError(''); setModal(null)
    try {
      await api.deferAction(token, action.id, reason)
      onRefresh()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function doExecute(dryRun: boolean) {
    if (!token) return
    setBusy(true); setError(''); setModal(null)
    try {
      await api.executeAction(token, action.id, dryRun)
      onRefresh()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const arrDisplay = fmtCurrency(action.arr_impact)

  return (
    <>
      {modal === 'complete' && (
        <ConfirmModal
          title="Mark as Complete"
          placeholder="Optional notes on how this was resolved…"
          confirmLabel="Mark Complete"
          confirmStyle="bg-emerald-600 hover:bg-emerald-700"
          onConfirm={doComplete}
          onCancel={() => setModal(null)}
        />
      )}
      {modal === 'defer' && (
        <ConfirmModal
          title="Defer Action"
          placeholder="Reason for deferring (e.g. 'Waiting on Q3 org review')…"
          confirmLabel="Defer"
          confirmStyle="bg-gray-600 hover:bg-gray-700"
          onConfirm={doDefer}
          onCancel={() => setModal(null)}
        />
      )}
      {modal === 'execute' && (
        <ConfirmModal
          title="Execute via Agent"
          placeholder="Optional notes (leave blank for live run, or type 'dry run' to test)…"
          confirmLabel="Execute"
          confirmStyle="bg-blue-600 hover:bg-blue-700"
          onConfirm={(notes) => doExecute(notes.toLowerCase().includes('dry'))}
          onCancel={() => setModal(null)}
        />
      )}

      <div
        className={`bg-white rounded-xl border shadow-sm overflow-hidden transition-all ${
          action.status === 'OPEN' ? 'border-blue-200' : 'border-gray-100'
        }`}
      >
        {/* Header row */}
        <div className="flex items-start justify-between gap-4 p-4">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            {statusIcon(action.status)}
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-sm font-semibold text-gray-800">{action.title}</p>
                {statusBadge(action.status)}
              </div>
              <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{action.description}</p>

              {/* Meta row */}
              <div className="flex flex-wrap items-center gap-3 mt-1.5">
                <span className="flex items-center gap-1 text-xs text-gray-400">
                  <Zap size={11} />
                  {workerLabel(action.worker_name)}
                </span>
                {effortBadge(action.effort)}
                <span className="text-xs text-gray-400">{action.timeframe}</span>
                {action.assigned_to_name && (
                  <span className="flex items-center gap-1 text-xs text-gray-400">
                    <User size={11} />
                    {action.assigned_to_name}
                  </span>
                )}
                {arrDisplay && (
                  <span className="flex items-center gap-1 text-xs font-medium text-emerald-600">
                    <DollarSign size={11} />
                    {arrDisplay} ARR impact
                  </span>
                )}
                {action.due_date && (
                  <span className="flex items-center gap-1 text-xs text-gray-400">
                    <Calendar size={11} />
                    Due {fmtDate(action.due_date)}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Action buttons */}
          {isActionable && (
            <div className="flex items-center gap-1.5 flex-shrink-0">
              <button
                onClick={() => setModal('defer')}
                disabled={busy}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 text-xs font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
                title="Defer"
              >
                <Pause size={12} />
                Defer
              </button>
              <button
                onClick={() => setModal('complete')}
                disabled={busy}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-emerald-200 text-emerald-700 text-xs font-medium hover:bg-emerald-50 disabled:opacity-50 transition-colors"
                title="Mark as complete"
              >
                <CheckCheck size={12} />
                Complete
              </button>
              <button
                onClick={() => setModal('execute')}
                disabled={busy}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-white text-xs font-medium disabled:opacity-50 transition-colors"
                style={{ backgroundColor: '#1B2A4A' }}
                title="Execute via agent"
              >
                {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                Execute
              </button>
            </div>
          )}

          {/* Expand toggle */}
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

        {/* Expanded: audit details */}
        {expanded && (
          <div className="border-t border-gray-100 px-4 py-3 bg-gray-50 space-y-2">
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
              <div>
                <span className="text-gray-400">Action type</span>
                <p className="text-gray-700 font-medium">
                  {action.action_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                </p>
              </div>
              <div>
                <span className="text-gray-400">Created</span>
                <p className="text-gray-700 font-medium">{fmtDate(action.created_at)}</p>
              </div>
              {action.completed_at && (
                <div>
                  <span className="text-gray-400">Completed</span>
                  <p className="text-gray-700 font-medium">{fmtDate(action.completed_at)}</p>
                </div>
              )}
              {action.completion_method && (
                <div>
                  <span className="text-gray-400">Completion method</span>
                  <p className="text-gray-700 font-medium">{action.completion_method}</p>
                </div>
              )}
              {action.evidence_source && (
                <div>
                  <span className="text-gray-400">Evidence source</span>
                  <p className="text-gray-700 font-medium">{action.evidence_source}</p>
                </div>
              )}
              {action.evidence_query_type && (
                <div>
                  <span className="text-gray-400">Query type</span>
                  <p className="text-gray-700 font-medium">{action.evidence_query_type}</p>
                </div>
              )}
            </div>
            <p className="text-xs text-gray-400 pt-1">
              Finding hash: <span className="font-mono">{action.finding_hash}</span>
            </p>
          </div>
        )}
      </div>
    </>
  )
}

// ── Main page ──────────────────────────────────────────────

type Filter = 'ALL' | 'OPEN' | 'IN_PROGRESS' | 'COMPLETE' | 'DEFERRED'

const FILTERS: Filter[] = ['ALL', 'OPEN', 'IN_PROGRESS', 'COMPLETE', 'DEFERRED']

const FILTER_LABELS: Record<Filter, string> = {
  ALL:         'All',
  OPEN:        'Open',
  IN_PROGRESS: 'In Progress',
  COMPLETE:    'Complete',
  DEFERRED:    'Deferred',
}

export default function Actions() {
  const [actions, setActions] = useState<RemediationAction[]>([])
  const [filter, setFilter] = useState<Filter>('OPEN')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const token = localStorage.getItem('miragent_token')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const status = filter === 'ALL' ? undefined : filter
      const data = await api.listActions(token ?? '', status)
      setActions(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [filter])

  const openCount = actions.filter(a => a.status === 'OPEN').length
  const totalArr = actions.reduce((sum, a) => sum + (a.arr_impact ?? 0), 0)
  const arrDisplay = totalArr > 0 ? fmtCurrency(totalArr) : null

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Remediation Actions</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Work items generated from worker findings — complete, defer, or execute via agent.
            {openCount > 0 && (
              <span className="ml-2 bg-blue-100 text-blue-700 border border-blue-200 text-xs font-semibold px-2 py-0.5 rounded-full">
                {openCount} open
              </span>
            )}
            {arrDisplay && filter !== 'COMPLETE' && (
              <span className="ml-2 bg-emerald-100 text-emerald-700 border border-emerald-200 text-xs font-semibold px-2 py-0.5 rounded-full">
                {arrDisplay} ARR at stake
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
            {FILTER_LABELS[f]}
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
      {!loading && !error && actions.length === 0 && (
        <div className="text-center py-16">
          <ListTodo size={40} className="mx-auto text-gray-200 mb-3" />
          <p className="text-sm font-medium text-gray-500">
            {filter === 'OPEN' ? 'No open actions' : `No ${FILTER_LABELS[filter].toLowerCase()} actions`}
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Run a scan to generate insights and surface remediation actions.
          </p>
        </div>
      )}

      {/* List */}
      {!loading && actions.length > 0 && (
        <div className="space-y-3">
          {actions.map(action => (
            <ActionCard key={action.id} action={action} token={token} onRefresh={load} />
          ))}
        </div>
      )}

      {/* Explainer */}
      <div className="mt-8 p-4 bg-blue-50 border border-blue-100 rounded-xl">
        <p className="text-xs font-semibold text-blue-700 mb-1">How remediation actions work</p>
        <p className="text-xs text-blue-600 leading-relaxed">
          Each worker finding generates one or more actionable work items. You can close them
          manually (Complete), snooze them with a reason (Defer), or send them to the Miragent
          executor (Execute) — which runs the action against Salesforce, Workday, or NetSuite
          directly. All outcomes are written to the audit log. High-risk executions require
          approval first and will appear in the Approvals inbox.
        </p>
      </div>
    </div>
  )
}
