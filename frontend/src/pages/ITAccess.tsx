import { useState, useEffect, useCallback } from 'react'
import {
  ShieldCheck, Loader2, AlertCircle, CheckCircle2, XCircle,
  RotateCcw, ChevronDown, ChevronUp, Clock, User, Shield,
  BookOpen, DollarSign, Key,
} from 'lucide-react'
import { api } from '../api/client'
import type { ITAccessResult, SystemCatalogEntry } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function getToken(): string {
  return localStorage.getItem('scout_token') || ''
}

function getTenant(): string {
  return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT
}

type ApprovalTier = 'manager' | 'it_admin' | 'ciso'
type StatusType = 'pending_manager' | 'pending_it' | 'pending_ciso' | 'provisioned' | 'rejected' | 'in_progress'

function tierBadgeClass(tier: ApprovalTier | string): string {
  switch (tier) {
    case 'manager':  return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'it_admin': return 'bg-yellow-100 text-yellow-800 border-yellow-200'
    case 'ciso':     return 'bg-red-100 text-red-800 border-red-200'
    default:         return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

function tierLabel(tier: ApprovalTier | string): string {
  switch (tier) {
    case 'manager':  return 'Manager'
    case 'it_admin': return 'IT Admin'
    case 'ciso':     return 'CISO'
    default:         return tier
  }
}

function statusBadgeClass(status: StatusType | string): string {
  switch (status) {
    case 'provisioned':     return 'bg-green-100 text-green-800 border-green-200'
    case 'in_progress':     return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'pending_manager': return 'bg-yellow-100 text-yellow-800 border-yellow-200'
    case 'pending_it':      return 'bg-orange-100 text-orange-800 border-orange-200'
    case 'pending_ciso':    return 'bg-red-100 text-red-800 border-red-200'
    case 'rejected':        return 'bg-gray-100 text-gray-600 border-gray-200'
    default:                return 'bg-gray-100 text-gray-600 border-gray-200'
  }
}

function statusLabel(status: StatusType | string): string {
  switch (status) {
    case 'provisioned':     return 'Provisioned'
    case 'in_progress':     return 'In Progress'
    case 'pending_manager': return 'Pending Manager'
    case 'pending_it':      return 'Pending IT Admin'
    case 'pending_ciso':    return 'Pending CISO'
    case 'rejected':        return 'Rejected'
    default:                return status
  }
}

const SYSTEMS_14 = [
  'salesforce', 'github', 'netsuite', 'workday', 'slack', 'jira', 'aws',
  'hubspot', 'zendesk', 'okta', 'tableau', 'zoom', 'notion', 'figma',
]

// ── Result Card ───────────────────────────────────────────────────────────────

function AccessResultCard({ result, onReset }: {
  result: ITAccessResult
  onReset: () => void
}) {
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        {/* Color bar */}
        <div className={`h-1.5 ${
          result.status === 'provisioned' ? 'bg-green-500' :
          result.status === 'pending_ciso' ? 'bg-red-500' :
          result.status === 'pending_it' ? 'bg-orange-500' :
          result.status === 'pending_manager' ? 'bg-yellow-400' :
          result.status === 'rejected' ? 'bg-gray-400' :
          'bg-blue-500'
        }`} />

        <div className="p-5 space-y-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-base font-bold text-gray-900">{result.system_display_name}</div>
              <div className="text-xs text-gray-500 mt-0.5 font-mono">{result.okta_group}</div>
              <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${tierBadgeClass(result.approval_tier)}`}>
                  <Shield size={10} />
                  {tierLabel(result.approval_tier)}
                </span>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${statusBadgeClass(result.status)}`}>
                  {statusLabel(result.status)}
                </span>
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <div className="text-xs text-gray-400">Request ID</div>
              <div className="text-xs font-mono text-gray-600">{result.request_id}</div>
            </div>
          </div>

          {/* Authority verification */}
          <div className={`flex items-start gap-2.5 rounded-lg px-4 py-3 ${
            result.authority_verified
              ? 'bg-green-50 border border-green-200'
              : 'bg-red-50 border border-red-200'
          }`}>
            {result.authority_verified
              ? <CheckCircle2 size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
              : <XCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
            }
            <div>
              <p className={`text-xs font-semibold mb-0.5 ${result.authority_verified ? 'text-green-700' : 'text-red-700'}`}>
                Authority {result.authority_verified ? 'Verified' : 'Not Verified'}
              </p>
              <p className={`text-xs ${result.authority_verified ? 'text-green-700' : 'text-red-700'}`}>
                {result.authority_note}
              </p>
            </div>
          </div>

          {/* Key facts */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 rounded-lg px-3 py-2">
              <div className="flex items-center gap-1 text-xs text-gray-400 mb-0.5">
                <DollarSign size={10} /> License Cost
              </div>
              <div className="text-sm font-semibold text-gray-800">
                {result.license_cost_monthly === 0 ? 'Free' : `$${result.license_cost_monthly}/mo`}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg px-3 py-2">
              <div className="flex items-center gap-1 text-xs text-gray-400 mb-0.5">
                <Clock size={10} /> SLA
              </div>
              <div className="text-sm font-semibold text-gray-800">
                {result.sla_days === 1 ? '1 business day' : `${result.sla_days} business days`}
              </div>
            </div>
            <div className="bg-gray-50 rounded-lg px-3 py-2">
              <div className="flex items-center gap-1 text-xs text-gray-400 mb-0.5">
                <User size={10} /> Requester
              </div>
              <div className="text-xs font-semibold text-gray-800 truncate">{result.requester_name}</div>
            </div>
            <div className="bg-gray-50 rounded-lg px-3 py-2">
              <div className="flex items-center gap-1 text-xs text-gray-400 mb-0.5">
                <Key size={10} /> Approver
              </div>
              <div className="text-xs font-semibold text-gray-800 truncate">{result.approver_email}</div>
            </div>
          </div>

          {/* Training callout */}
          {result.requires_training && result.training_url && (
            <div className="flex items-start gap-2.5 bg-indigo-50 border border-indigo-100 rounded-lg px-4 py-3">
              <BookOpen size={14} className="text-indigo-400 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-xs font-semibold text-indigo-700 mb-0.5">Training Required</p>
                <a
                  href={result.training_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-indigo-600 hover:text-indigo-800 underline underline-offset-2"
                >
                  {result.training_url}
                </a>
              </div>
            </div>
          )}

          {/* Next steps */}
          {result.next_steps.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Next Steps</p>
              <ol className="space-y-1.5">
                {result.next_steps.map((step, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="w-4 h-4 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                      {i + 1}
                    </span>
                    <span className="text-sm text-gray-700">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          <button
            onClick={onReset}
            className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
          >
            Submit another request
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Submit Panel ──────────────────────────────────────────────────────────────

function SubmitPanel({ catalog }: { catalog: SystemCatalogEntry[] }) {
  const [requesterEmail, setRequesterEmail] = useState('')
  const [targetEmail, setTargetEmail] = useState('')
  const [systemName, setSystemName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ITAccessResult | null>(null)

  async function handleSubmit() {
    if (!requesterEmail.trim()) { setError('Requester email is required.'); return }
    if (!targetEmail.trim()) { setError('User to provision is required.'); return }
    if (!systemName) { setError('Please select a system.'); return }
    setError(null); setResult(null); setLoading(true)
    try {
      const token = getToken()
      const tenant = getTenant()
      const r = await api.itAccess.request(
        requesterEmail.trim(), targetEmail.trim(), systemName, tenant, token
      )
      setResult(r)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setResult(null); setError(null)
    setRequesterEmail(''); setTargetEmail(''); setSystemName('')
  }

  // Build system display map from catalog
  const catalogMap = new Map<string, SystemCatalogEntry>()
  for (const entry of catalog) {
    catalogMap.set(entry.system_key, entry)
  }

  return (
    <div className="space-y-5">
      {result ? (
        <AccessResultCard result={result} onReset={handleReset} />
      ) : (
        <>
          {/* Requester Email */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              Requester Email
            </label>
            <input
              type="email"
              value={requesterEmail}
              onChange={e => { setRequesterEmail(e.target.value); setError(null) }}
              placeholder="james.rodriguez@acme-corp.com"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* Target User */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              User to Provision
            </label>
            <input
              type="email"
              value={targetEmail}
              onChange={e => { setTargetEmail(e.target.value); setError(null) }}
              placeholder="tom.walsh@acme-corp.com (or same email for self-service)"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* System selector */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
              System
            </label>
            <select
              value={systemName}
              onChange={e => { setSystemName(e.target.value); setError(null) }}
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
            >
              <option value="">Select a system...</option>
              {(catalog.length > 0 ? catalog : SYSTEMS_14.map(k => ({
                system_key: k, display_name: k, approval_tier: 'manager',
                license_cost_monthly: 0, requires_training: false, okta_group: '', owner: '',
              }))).map(entry => (
                <option key={entry.system_key} value={entry.system_key}>
                  {entry.display_name} — {tierLabel(entry.approval_tier)} approval
                </option>
              ))}
            </select>

            {/* Show tier badge for selected system */}
            {systemName && catalogMap.has(systemName) && (
              <div className="mt-2 flex items-center gap-2">
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${tierBadgeClass(catalogMap.get(systemName)!.approval_tier)}`}>
                  <Shield size={10} />
                  {tierLabel(catalogMap.get(systemName)!.approval_tier)} approval required
                </span>
                {catalogMap.get(systemName)!.license_cost_monthly > 0 && (
                  <span className="text-xs text-gray-400">
                    ${catalogMap.get(systemName)!.license_cost_monthly}/mo
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {loading
              ? <><Loader2 size={14} className="animate-spin" /> Submitting…</>
              : <><ShieldCheck size={14} /> Submit Access Request</>
            }
          </button>
        </>
      )}
    </div>
  )
}

// ── Queue Card ────────────────────────────────────────────────────────────────

function QueueCard({ item }: { item: ITAccessResult }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-gray-100 last:border-0">
      <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
        <Key size={14} className="text-indigo-400" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-gray-900 truncate">{item.system_display_name}</span>
          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-semibold border ${tierBadgeClass(item.approval_tier)}`}>
            {tierLabel(item.approval_tier)}
          </span>
          <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-semibold border ${statusBadgeClass(item.status)}`}>
            {statusLabel(item.status)}
          </span>
        </div>
        <div className="flex items-center gap-3 mt-0.5 flex-wrap">
          <span className="text-xs text-gray-400 flex items-center gap-1">
            <User size={10} /> {item.requester_name}
          </span>
          <span className="text-xs text-gray-400">→ {item.target_user_email}</span>
        </div>
        <div className="flex items-center gap-1 mt-0.5">
          <Clock size={10} className="text-gray-300" />
          <span className="text-xs text-gray-400">{item.submitted_date}</span>
        </div>
      </div>
    </div>
  )
}

// ── Pending Queue Panel ───────────────────────────────────────────────────────

type QueueTab = 'all' | 'ciso' | 'it_admin' | 'manager'

function PendingQueuePanel() {
  const [queue, setQueue] = useState<ITAccessResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<QueueTab>('all')
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [catalog, setCatalog] = useState<SystemCatalogEntry[]>([])

  const loadQueue = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const token = getToken()
      const tenant = getTenant()
      const [q, cat] = await Promise.all([
        api.itAccess.getPending(tenant, token),
        api.itAccess.getCatalog(token),
      ])
      setQueue(q)
      setCatalog(cat)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load queue')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadQueue() }, [loadQueue])

  const filtered = queue.filter(item => {
    if (activeTab === 'all') return true
    return item.approval_tier === activeTab
  })

  const cisoCount = queue.filter(q => q.approval_tier === 'ciso').length
  const itCount = queue.filter(q => q.approval_tier === 'it_admin').length
  const managerCount = queue.filter(q => q.approval_tier === 'manager').length

  const tabs: { key: QueueTab; label: string; count: number }[] = [
    { key: 'all', label: 'All Pending', count: queue.length },
    { key: 'ciso', label: 'Needs CISO', count: cisoCount },
    { key: 'it_admin', label: 'Needs IT Admin', count: itCount },
    { key: 'manager', label: 'Needs Manager', count: managerCount },
  ]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Pending Requests</span>
          {queue.length > 0 && (
            <span className="px-1.5 py-0.5 text-xs bg-indigo-100 text-indigo-700 rounded-full font-semibold">
              {queue.length}
            </span>
          )}
        </div>
        <button
          onClick={loadQueue}
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          <RotateCcw size={11} /> Refresh
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 flex-wrap">
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={[
              'px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors',
              activeTab === tab.key
                ? 'bg-indigo-600 text-white border-indigo-600'
                : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300 hover:text-indigo-600',
            ].join(' ')}
          >
            {tab.label}
            {tab.count > 0 && (
              <span className={`ml-1.5 ${activeTab === tab.key ? 'text-indigo-200' : 'text-gray-400'}`}>
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-10">
          <Loader2 size={22} className="animate-spin text-gray-300" />
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {!loading && !error && (
        <>
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <CheckCircle2 size={28} className="text-green-300 mb-2" />
              <p className="text-gray-400 text-sm">No pending requests in this queue</p>
            </div>
          ) : (
            <div className="bg-white border border-gray-100 rounded-xl px-4 divide-y divide-gray-50">
              {filtered.map(item => (
                <QueueCard key={item.request_id} item={item} />
              ))}
            </div>
          )}
        </>
      )}

      {/* System catalog collapsible */}
      <div className="border border-gray-200 rounded-xl overflow-hidden">
        <button
          onClick={() => setCatalogOpen(o => !o)}
          className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-semibold text-gray-700"
        >
          <span>View System Catalog ({catalog.length > 0 ? catalog.length : 14} systems)</span>
          {catalogOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {catalogOpen && catalog.length > 0 && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-2 text-left font-semibold text-gray-600">System</th>
                  <th className="px-4 py-2 text-left font-semibold text-gray-600">Approval</th>
                  <th className="px-4 py-2 text-left font-semibold text-gray-600">Cost/mo</th>
                  <th className="px-4 py-2 text-left font-semibold text-gray-600">Okta Group</th>
                  <th className="px-4 py-2 text-left font-semibold text-gray-600">Training</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {catalog.map(entry => (
                  <tr key={entry.system_key} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-medium text-gray-800">{entry.display_name}</td>
                    <td className="px-4 py-2">
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-semibold border ${tierBadgeClass(entry.approval_tier)}`}>
                        {tierLabel(entry.approval_tier)}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {entry.license_cost_monthly === 0 ? 'Free' : `$${entry.license_cost_monthly}`}
                    </td>
                    <td className="px-4 py-2 font-mono text-gray-500">{entry.okta_group}</td>
                    <td className="px-4 py-2 text-gray-500">{entry.requires_training ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ITAccess() {
  const [catalog, setCatalog] = useState<SystemCatalogEntry[]>([])

  useEffect(() => {
    const token = getToken()
    api.itAccess.getCatalog(token).then(setCatalog).catch(() => {})
  }, [])

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
              <ShieldCheck size={18} className="text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">IT Access</h1>
          </div>
          <p className="text-gray-500 text-sm ml-12">
            Request system access, verify authority, route to the correct approver, and track provisioning status.
          </p>
        </div>

        {/* Two-panel layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left panel */}
          <div>
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-5">
                <Key size={15} className="text-gray-400" />
                <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Submit Access Request</span>
              </div>
              <SubmitPanel catalog={catalog} />
            </div>
          </div>

          {/* Right panel */}
          <div>
            <div className="bg-gray-50 rounded-2xl border border-gray-200 p-6">
              <PendingQueuePanel />
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
