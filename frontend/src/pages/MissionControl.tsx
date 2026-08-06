import { useState, useEffect } from 'react'
import {
  LayoutDashboard,
  Zap,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Activity,
  Pause,
  Play,
  X,
  Circle,
  ArrowRight,
  Settings,
  RefreshCw,
} from 'lucide-react'
import { api } from '../api/client'
import type {
  MissionControlSummary,
  ProcessBlueprint,
  AgentDeployment,
  ConnectorStatus,
  AuditEntry,
} from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Category config ────────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  customer_support: { label: 'Customer Support', color: 'text-blue-700', bg: 'bg-blue-100' },
  sales:            { label: 'Sales',            color: 'text-emerald-700', bg: 'bg-emerald-100' },
  hr:               { label: 'HR',               color: 'text-purple-700', bg: 'bg-purple-100' },
  vendor:           { label: 'Vendor',           color: 'text-orange-700', bg: 'bg-orange-100' },
  finance:          { label: 'Finance',          color: 'text-teal-700', bg: 'bg-teal-100' },
  general:          { label: 'General',          color: 'text-gray-700', bg: 'bg-gray-100' },
}

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  discovered:  { label: 'Discovered',  color: 'text-gray-700', bg: 'bg-gray-100' },
  reviewed:    { label: 'Reviewed',    color: 'text-blue-700', bg: 'bg-blue-100' },
  configured:  { label: 'Configured', color: 'text-purple-700', bg: 'bg-purple-100' },
  active:      { label: 'Active',      color: 'text-emerald-700', bg: 'bg-emerald-100' },
}

// ── Helper components ──────────────────────────────────────────────────────────

function Badge({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${bg} ${color}`}>
      {label}
    </span>
  )
}

function StatCard({
  label,
  value,
  accent,
  icon,
}: {
  label: string
  value: number | string
  accent?: 'red' | 'orange' | 'green' | 'blue'
  icon?: React.ReactNode
}) {
  const accentMap = {
    red:    'text-red-600',
    orange: 'text-orange-500',
    green:  'text-emerald-600',
    blue:   'text-blue-600',
  }
  const valueClass = accent ? accentMap[accent] : 'text-gray-900'

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-5 py-4 flex items-center gap-4">
      {icon && (
        <div className="w-10 h-10 rounded-lg bg-gray-50 flex items-center justify-center text-gray-500">
          {icon}
        </div>
      )}
      <div>
        <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{label}</p>
        <p className={`text-2xl font-bold mt-0.5 ${valueClass}`}>{value}</p>
      </div>
    </div>
  )
}

// ── Blueprint card ─────────────────────────────────────────────────────────────

function BlueprintCard({
  blueprint,
  onReview,
}: {
  blueprint: ProcessBlueprint
  onReview: (bp: ProcessBlueprint) => void
}) {
  const cat = CATEGORY_CONFIG[blueprint.category] ?? CATEGORY_CONFIG.general
  const statusCfg = STATUS_CONFIG[blueprint.status] ?? STATUS_CONFIG.discovered

  const patterns = Object.entries(blueprint.resolution_patterns)
  const patternColors = [
    'bg-blue-500', 'bg-emerald-500', 'bg-purple-500', 'bg-orange-400',
    'bg-teal-500', 'bg-pink-400', 'bg-amber-400',
  ]

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 hover:shadow-md transition-shadow">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 text-base leading-tight truncate">
            {blueprint.process_name}
          </h3>
          <div className="flex flex-wrap items-center gap-2 mt-1.5">
            <Badge label={cat.label} color={cat.color} bg={cat.bg} />
            <Badge label={statusCfg.label} color={statusCfg.color} bg={statusCfg.bg} />
            <span className="text-xs text-gray-500">
              {blueprint.volume_per_week.toFixed(0)} tickets/wk
            </span>
          </div>
        </div>
        {blueprint.recommended_agent && (
          <span className="flex-shrink-0 text-xs font-medium text-blue-600 bg-blue-50 px-2 py-1 rounded-md border border-blue-100">
            {blueprint.recommended_agent}
          </span>
        )}
      </div>

      {/* Automation potential bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">Automation potential</span>
          <span className="text-xs font-bold text-emerald-700">{blueprint.automation_potential}%</span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2">
          <div
            className="bg-emerald-500 h-2 rounded-full transition-all"
            style={{ width: `${blueprint.automation_potential}%` }}
          />
        </div>
      </div>

      {/* Resolution pattern stacked bar */}
      {patterns.length > 0 && (
        <div className="mb-3">
          <p className="text-xs text-gray-500 mb-1">Resolution patterns</p>
          <div className="flex w-full h-2.5 rounded-full overflow-hidden gap-px">
            {patterns.map(([key, pct], i) => (
              <div
                key={key}
                className={`${patternColors[i % patternColors.length]} flex-shrink-0`}
                style={{ width: `${(pct * 100).toFixed(0)}%` }}
                title={`${key}: ${(pct * 100).toFixed(0)}%`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5">
            {patterns.slice(0, 4).map(([key, pct], i) => (
              <div key={key} className="flex items-center gap-1">
                <div className={`w-2 h-2 rounded-full ${patternColors[i % patternColors.length]}`} />
                <span className="text-xs text-gray-500 capitalize">
                  {key.replace(/_/g, ' ')} {(pct * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Conformance gap alert */}
      {blueprint.conformance_gap && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2 mb-3">
          <AlertTriangle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-red-700 leading-snug">{blueprint.conformance_gap}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-2">
        <button
          onClick={() => onReview(blueprint)}
          className="flex-1 px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 rounded-lg border border-blue-100 transition-colors"
        >
          Review Blueprint
        </button>
        <button
          disabled={blueprint.status === 'discovered'}
          className={`flex-1 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
            blueprint.status === 'discovered'
              ? 'text-gray-400 bg-gray-50 border-gray-100 cursor-not-allowed'
              : 'text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border-emerald-100'
          }`}
        >
          Configure Agent
        </button>
      </div>
    </div>
  )
}

// ── Agent card ─────────────────────────────────────────────────────────────────

// Static sparkline bars for 7-day activity (mock data)
const MOCK_SPARKLINE = [6, 9, 5, 11, 8, 14, 10]

function AgentCard({
  deployment,
  onPause,
  onResume,
}: {
  deployment: AgentDeployment
  onPause: (id: string) => void
  onResume: (id: string) => void
}) {
  const isActive = deployment.status === 'active'

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <Circle
            size={10}
            className={isActive ? 'text-emerald-500 fill-emerald-500' : 'text-yellow-400 fill-yellow-400'}
          />
          <h3 className="font-semibold text-gray-900 text-sm">{deployment.agent_name}</h3>
        </div>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
          isActive
            ? 'bg-emerald-50 text-emerald-700 border border-emerald-100'
            : 'bg-yellow-50 text-yellow-700 border border-yellow-100'
        }`}>
          {isActive ? 'Active' : 'Paused'}
        </span>
      </div>

      {/* Metric pills */}
      <div className="flex flex-wrap gap-2 mb-3">
        <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded-md font-medium">
          {deployment.requests_today} today
        </span>
        <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded-md font-medium">
          {(deployment.resolution_rate * 100).toFixed(0)}% resolved
        </span>
        {deployment.last_activity_at && (
          <span className="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded-md">
            Active {formatRelative(deployment.last_activity_at)}
          </span>
        )}
      </div>

      {/* Mini sparkline */}
      <div className="flex items-end gap-0.5 h-7 mb-3">
        {MOCK_SPARKLINE.map((v, i) => (
          <div
            key={i}
            className={`flex-1 rounded-sm ${isActive ? 'bg-emerald-400' : 'bg-gray-200'}`}
            style={{ height: `${(v / 14) * 100}%` }}
            title={`Day ${i + 1}: ${v} requests`}
          />
        ))}
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        {isActive ? (
          <button
            onClick={() => onPause(deployment.id)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-yellow-700 bg-yellow-50 hover:bg-yellow-100 rounded-lg border border-yellow-100 transition-colors"
          >
            <Pause size={12} /> Pause
          </button>
        ) : (
          <button
            onClick={() => onResume(deployment.id)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-lg border border-emerald-100 transition-colors"
          >
            <Play size={12} /> Resume
          </button>
        )}
        <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-200 transition-colors">
          <Settings size={12} /> Configure
        </button>
      </div>
    </div>
  )
}

// ── Blueprint slide-over panel ─────────────────────────────────────────────────

function BlueprintPanel({
  blueprint,
  onClose,
  onApprove,
}: {
  blueprint: ProcessBlueprint
  onClose: () => void
  onApprove: () => void
}) {
  const cat = CATEGORY_CONFIG[blueprint.category] ?? CATEGORY_CONFIG.general
  const patterns = Object.entries(blueprint.resolution_patterns)

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30" />

      {/* Drawer */}
      <div
        className="relative w-full max-w-lg bg-white shadow-2xl flex flex-col h-full overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-lg font-bold text-gray-900">{blueprint.process_name}</h2>
            <div className="flex items-center gap-2 mt-1">
              <Badge label={cat.label} color={cat.color} bg={cat.bg} />
              <span className="text-sm text-gray-500">
                {blueprint.volume_per_week.toFixed(0)} tickets/week
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <X size={18} className="text-gray-500" />
          </button>
        </div>

        <div className="flex-1 px-6 py-5 space-y-6">
          {/* Automation potential */}
          <div>
            <div className="flex justify-between items-center mb-2">
              <p className="text-sm font-semibold text-gray-900">Automation Potential</p>
              <span className="text-lg font-bold text-emerald-600">{blueprint.automation_potential}%</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-3">
              <div
                className="bg-emerald-500 h-3 rounded-full"
                style={{ width: `${blueprint.automation_potential}%` }}
              />
            </div>
          </div>

          {/* Metrics */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-xs text-gray-500">Median Resolution</p>
              <p className="text-base font-bold text-gray-900 mt-0.5">
                {blueprint.median_resolution_hours >= 24
                  ? `${(blueprint.median_resolution_hours / 24).toFixed(1)} days`
                  : `${blueprint.median_resolution_hours.toFixed(1)}h`}
              </p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-xs text-gray-500">SOP Coverage</p>
              <p className="text-base font-bold mt-0.5">
                {blueprint.sop_coverage
                  ? <span className="text-emerald-700">Documented</span>
                  : <span className="text-red-600">No SOP</span>}
              </p>
            </div>
          </div>

          {/* Resolution patterns */}
          <div>
            <p className="text-sm font-semibold text-gray-900 mb-3">Resolution Patterns</p>
            <div className="space-y-2">
              {patterns.map(([key, pct]) => (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-sm text-gray-600 w-40 truncate capitalize">
                    {key.replace(/_/g, ' ')}
                  </span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full"
                      style={{ width: `${(pct * 100).toFixed(0)}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium text-gray-700 w-9 text-right">
                    {(pct * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Conformance gap */}
          {blueprint.conformance_gap && (
            <div className="bg-red-50 border border-red-100 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <AlertTriangle size={16} className="text-red-500" />
                <p className="text-sm font-semibold text-red-800">Conformance Gap</p>
              </div>
              <p className="text-sm text-red-700">{blueprint.conformance_gap}</p>
            </div>
          )}

          {/* Recommended agent */}
          {blueprint.recommended_agent && (
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
              <p className="text-sm font-semibold text-blue-800 mb-1">
                Recommended Agent: {blueprint.recommended_agent}
              </p>
              <p className="text-sm text-blue-700">
                This agent would handle incoming {blueprint.process_name.toLowerCase()} requests
                automatically, using the resolution patterns above to route and resolve without
                human intervention. Escalation triggers and edge cases would still queue for
                human review.
              </p>
            </div>
          )}

          {/* Systems involved */}
          {blueprint.systems_involved.length > 0 && (
            <div>
              <p className="text-sm font-semibold text-gray-900 mb-2">Systems Involved</p>
              <div className="flex flex-wrap gap-2">
                {blueprint.systems_involved.map((sys) => (
                  <span key={sys} className="text-xs font-medium bg-gray-100 text-gray-700 px-2.5 py-1 rounded-lg">
                    {sys}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer actions */}
        <div className="px-6 py-4 border-t border-gray-100 flex gap-3">
          <button
            onClick={onApprove}
            disabled={blueprint.status === 'active'}
            className="flex-1 px-4 py-2.5 text-sm font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {blueprint.status === 'active' ? 'Already Active' : 'Approve & Configure'}
          </button>
          <button
            onClick={onClose}
            className="px-4 py-2.5 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            Not Now
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Connector health grid ──────────────────────────────────────────────────────

function ConnectorGrid({ connectors }: { connectors: ConnectorStatus[] }) {
  // Show only 8 specific connectors in the dashboard widget
  const FEATURED = ['Salesforce', 'Workday', 'NetSuite', 'HubSpot', 'Okta', 'ADP', 'Zendesk', 'GitHub']
  const featured = connectors.filter((c) => FEATURED.includes(c.name))

  const statusDot = (s: string) => {
    if (s === 'connected') return 'bg-emerald-400'
    if (s === 'error') return 'bg-red-400'
    return 'bg-gray-300'
  }

  return (
    <div className="grid grid-cols-2 gap-2">
      {featured.map((c) => (
        <div key={c.name} className="flex items-center gap-2.5 bg-gray-50 rounded-lg px-3 py-2">
          <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${statusDot(c.status)}`} />
          <div className="min-w-0">
            <p className="text-xs font-medium text-gray-800 truncate">{c.name}</p>
            <p className="text-xs text-gray-500 capitalize">{c.status}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Audit entry row ────────────────────────────────────────────────────────────

function AuditRow({ entry, index }: { entry: AuditEntry; index: number }) {
  const OUTCOMES = ['resolved', 'escalated', 'deferred']
  const mockOutcome = OUTCOMES[index % OUTCOMES.length]
  const outcomeColors: Record<string, string> = {
    resolved:  'bg-emerald-100 text-emerald-700',
    escalated: 'bg-orange-100 text-orange-700',
    deferred:  'bg-gray-100 text-gray-600',
  }

  const ts = entry.timestamp
    ? new Date(entry.timestamp as string).toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'

  const agentLabel = (entry.agent || entry.method || 'System') as string
  const actionLabel = (entry.path || entry.action || 'Action taken') as string

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-gray-50 last:border-0">
      <span className="text-xs text-gray-400 font-mono flex-shrink-0 mt-0.5">{ts}</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-gray-800 truncate">{agentLabel}</p>
        <p className="text-xs text-gray-500 truncate">{actionLabel}</p>
      </div>
      <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${outcomeColors[mockOutcome]}`}>
        {mockOutcome}
      </span>
    </div>
  )
}

// ── Conformance alert row ──────────────────────────────────────────────────────

const CONFORMANCE_ALERTS = [
  { process: 'Vendor Onboarding', stated: '15 business days', actual: '31 days', severity: 'critical' },
  { process: 'Portal Access Resolution', stated: '2 hours', actual: '4.2 hours', severity: 'high' },
  { process: 'DDQ Response Time', stated: '5 business days', actual: '8.3 days', severity: 'high' },
  { process: 'First Response SLA', stated: '30 minutes', actual: '48 minutes', severity: 'medium' },
]

function ConformanceAlertRow({
  process, stated, actual, severity,
}: {
  process: string; stated: string; actual: string; severity: string
}) {
  const severityColors: Record<string, string> = {
    critical: 'bg-red-100 text-red-700',
    high:     'bg-orange-100 text-orange-700',
    medium:   'bg-amber-100 text-amber-700',
  }
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-gray-50 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-gray-800">{process}</p>
        <p className="text-xs text-gray-500">
          Stated: {stated} → Actual: <span className="font-medium text-gray-700">{actual}</span>
        </p>
      </div>
      <span className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 capitalize ${severityColors[severity] ?? 'bg-gray-100 text-gray-600'}`}>
        {severity}
      </span>
    </div>
  )
}

// ── Utilities ──────────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  } catch {
    return '—'
  }
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function MissionControl() {
  const [tenantId] = useState(
    () => localStorage.getItem(DEFAULT_TENANT_KEY) ?? DEFAULT_TENANT
  )
  const token = localStorage.getItem('miragent_token') ?? ''

  const [summary, setSummary] = useState<MissionControlSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedBlueprint, setSelectedBlueprint] = useState<ProcessBlueprint | null>(null)
  const [showBlueprintPanel, setShowBlueprintPanel] = useState(false)
  const [agentLoading, setAgentLoading] = useState<string | null>(null)

  async function loadSummary() {
    setLoading(true)
    setError('')
    try {
      const data = await api.missionControlSummary(token, tenantId)
      setSummary(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load Mission Control data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSummary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  async function handleReviewBlueprint() {
    if (!selectedBlueprint) return
    try {
      await api.reviewBlueprint(token, selectedBlueprint.id)
      setShowBlueprintPanel(false)
      await loadSummary()
    } catch (e: unknown) {
      console.error('Review failed', e)
    }
  }

  async function handlePauseAgent(id: string) {
    setAgentLoading(id)
    try {
      await api.pauseAgent(token, id)
      await loadSummary()
    } finally {
      setAgentLoading(null)
    }
  }

  async function handleResumeAgent(id: string) {
    setAgentLoading(id)
    try {
      await api.resumeAgent(token, id)
      await loadSummary()
    } finally {
      setAgentLoading(null)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div
          className="w-10 h-10 border-4 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: '#1B2A4A', borderTopColor: 'transparent' }}
        />
        <p className="text-gray-500 text-sm">Loading Mission Control…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-6 py-5">
        <p className="font-semibold">Error loading Mission Control</p>
        <p className="text-sm mt-1">{error}</p>
        <button
          onClick={loadSummary}
          className="mt-3 px-4 py-2 text-sm font-medium bg-red-600 text-white rounded-lg hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    )
  }

  const s = summary!

  return (
    <div className="-m-8 min-h-screen bg-gray-50">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="px-8 py-6 flex items-center justify-between" style={{ backgroundColor: '#1B2A4A' }}>
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center">
            <LayoutDashboard size={22} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white leading-tight">Mission Control</h1>
            <p className="text-gray-400 text-sm mt-0.5">Miragent deployment — {tenantId}</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {s.last_scan_at && (
            <div className="flex items-center gap-2 text-gray-400 text-sm">
              <Clock size={14} />
              <span>Last scan: {formatRelative(s.last_scan_at)}</span>
            </div>
          )}
          <button
            onClick={loadSummary}
            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg transition-colors"
          >
            <RefreshCw size={14} />
            Run Scout Now
          </button>
        </div>
      </div>

      <div className="px-8 py-6 space-y-6">
        {/* ── Top stat cards ────────────────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            label="Active Agents"
            value={s.active_agents}
            accent="green"
            icon={<Activity size={18} />}
          />
          <StatCard
            label="Pending Approvals"
            value={s.pending_approvals}
            accent={s.pending_approvals > 0 ? 'orange' : undefined}
            icon={<CheckCircle2 size={18} />}
          />
          <StatCard
            label="Blueprints Discovered"
            value={s.blueprints_discovered}
            accent="blue"
            icon={<Zap size={18} />}
          />
          <StatCard
            label="Critical Findings"
            value={s.critical_findings}
            accent={s.critical_findings > 0 ? 'red' : undefined}
            icon={<AlertTriangle size={18} />}
          />
        </div>

        {/* ── Main 2-column layout ──────────────────────────────────────────── */}
        <div className="flex gap-6 items-start">
          {/* ── Left column (65%) ─────────────────────────────────────────── */}
          <div className="flex-[65] space-y-6 min-w-0">
            {/* Process Blueprints */}
            <section>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-base font-bold text-gray-900">Process Blueprints</h2>
                <span className="text-xs text-gray-500">{s.blueprints.length} processes</span>
              </div>
              <div className="space-y-3">
                {s.blueprints.map((bp) => (
                  <BlueprintCard
                    key={bp.id}
                    blueprint={bp}
                    onReview={(b) => {
                      setSelectedBlueprint(b)
                      setShowBlueprintPanel(true)
                    }}
                  />
                ))}
                {s.blueprints.length === 0 && (
                  <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
                    <p className="text-gray-500 text-sm">No blueprints discovered yet. Run a Scout scan to start.</p>
                  </div>
                )}
              </div>
            </section>

            {/* Active Agents */}
            <section>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-base font-bold text-gray-900">Active Agents</h2>
                <span className="text-xs text-gray-500">{s.agents.length} deployed</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {s.agents.map((dep) => (
                  <AgentCard
                    key={dep.id}
                    deployment={dep}
                    onPause={agentLoading ? () => {} : handlePauseAgent}
                    onResume={agentLoading ? () => {} : handleResumeAgent}
                  />
                ))}
                {s.agents.length === 0 && (
                  <div className="col-span-2 text-center py-10 bg-white rounded-xl border border-gray-200">
                    <p className="text-gray-500 text-sm">No agents deployed yet.</p>
                  </div>
                )}
              </div>
            </section>
          </div>

          {/* ── Right column (35%) ────────────────────────────────────────── */}
          <div className="flex-[35] space-y-4 min-w-0">
            {/* Pending Approvals */}
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-bold text-gray-900">Pending Approvals</h2>
                {s.pending_approvals > 0 && (
                  <span className="text-xs font-bold bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">
                    {s.pending_approvals}
                  </span>
                )}
              </div>
              {s.pending_approvals === 0 ? (
                <p className="text-xs text-gray-500 py-2">No pending approvals — all caught up.</p>
              ) : (
                <div className="space-y-2">
                  {Array.from({ length: Math.min(s.pending_approvals, 3) }).map((_, i) => (
                    <div key={i} className="flex items-center gap-2 p-2 bg-orange-50 rounded-lg border border-orange-100">
                      <AlertTriangle size={13} className="text-orange-500 flex-shrink-0" />
                      <p className="text-xs text-orange-800 flex-1">High-risk action awaiting review</p>
                      <span className="text-xs font-medium text-orange-600 bg-orange-100 px-1.5 py-0.5 rounded">HIGH</span>
                    </div>
                  ))}
                  <a
                    href="/approvals"
                    className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 mt-2"
                  >
                    Review All <ArrowRight size={12} />
                  </a>
                </div>
              )}
            </section>

            {/* Conformance Alerts */}
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <h2 className="text-sm font-bold text-gray-900 mb-3">Conformance Alerts</h2>
              <div>
                {CONFORMANCE_ALERTS.map((alert, i) => (
                  <ConformanceAlertRow key={i} {...alert} />
                ))}
              </div>
            </section>

            {/* Connector Health */}
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-bold text-gray-900">Connector Health</h2>
                <span className="text-xs text-gray-500">
                  {s.connectors.filter((c) => c.status === 'connected').length} connected
                </span>
              </div>
              <ConnectorGrid connectors={s.connectors} />
              <a
                href="/settings"
                className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 mt-3"
              >
                Manage Connectors <ArrowRight size={12} />
              </a>
            </section>

            {/* Recent Agent Activity */}
            <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <h2 className="text-sm font-bold text-gray-900 mb-3">Recent Agent Activity</h2>
              {s.recent_actions.length === 0 ? (
                <p className="text-xs text-gray-500">No recent activity recorded.</p>
              ) : (
                <div>
                  {s.recent_actions.slice(0, 8).map((entry, i) => (
                    <AuditRow key={i} entry={entry} index={i} />
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
      </div>

      {/* ── Blueprint slide-over panel ────────────────────────────────────── */}
      {showBlueprintPanel && selectedBlueprint && (
        <BlueprintPanel
          blueprint={selectedBlueprint}
          onClose={() => setShowBlueprintPanel(false)}
          onApprove={handleReviewBlueprint}
        />
      )}
    </div>
  )
}
