/**
 * Portfolio.tsx — Sprint 78 (rebuilt from Sprint 56)
 *
 * Fund-level view for PE operating partners.
 * Monday-morning dashboard: every portfolio company ranked by risk,
 * with the key metrics and top findings from the most recent intelligence run.
 *
 * Data sources (shown clearly per card):
 *   insight_snapshot — real worker intelligence (full 34-worker analysis)
 *   graph_heuristics — lightweight signals (no /insights run yet)
 *
 * GET /portfolio/summary?tenant_ids=acme-corp,techco,...
 * GET /portfolio/tenants  — auto-populates the tenant list on mount
 */

import { useState, useEffect } from 'react'
import {
  LayoutGrid, AlertTriangle, TrendingUp, Users,
  RefreshCw, Plus, X, ChevronRight, Loader2, AlertCircle,
  CheckCircle2, ShieldAlert, Zap, Clock, Brain, DollarSign,
  BarChart2, Activity, CalendarClock, ChevronDown, Settings2,
} from 'lucide-react'
import { api } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────

type DataSource = 'insight_snapshot' | 'graph_heuristics' | 'none'
type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'HEALTHY'

interface TopFinding {
  worker: string
  severity: string
  title: string
}

interface CompanyCard {
  tenant_id: string
  available: boolean
  data_source: DataSource
  last_insights_run: string | null
  error: string | null
  health_score: number
  severity: Severity
  finding_counts: {
    critical: number
    high: number
    medium: number
    low: number
    total: number
  }
  top_findings: TopFinding[]
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
}

interface Aggregate {
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

// ── Helpers ───────────────────────────────────────────────────────────────

const fmtMoney = (n: number | null) => {
  if (n === null || n === undefined) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
  return `$${n}`
}

const fmtRelTime = (iso: string | null) => {
  if (!iso) return null
  const diff = Date.now() - new Date(iso).getTime()
  const hrs = Math.floor(diff / 3_600_000)
  if (hrs < 1) return 'less than 1h ago'
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

const severityColors: Record<Severity, { bg: string; text: string; border: string; dot: string; badge: string }> = {
  CRITICAL: { bg: 'bg-red-50',     text: 'text-red-700',    border: 'border-red-200',    dot: 'bg-red-500',    badge: 'bg-red-100 text-red-700' },
  HIGH:     { bg: 'bg-orange-50',  text: 'text-orange-700', border: 'border-orange-200', dot: 'bg-orange-500', badge: 'bg-orange-100 text-orange-700' },
  MEDIUM:   { bg: 'bg-yellow-50',  text: 'text-yellow-700', border: 'border-yellow-200', dot: 'bg-yellow-500', badge: 'bg-yellow-100 text-yellow-700' },
  HEALTHY:  { bg: 'bg-emerald-50', text: 'text-emerald-700',border: 'border-emerald-200',dot: 'bg-emerald-500',badge: 'bg-emerald-100 text-emerald-700' },
}

const findingSeverityDot: Record<string, string> = {
  critical: 'bg-red-500',
  high:     'bg-orange-500',
  medium:   'bg-yellow-500',
  low:      'bg-blue-400',
}

// ── Score ring ────────────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const r = 22
  const circ = 2 * Math.PI * r
  const fill = circ * (1 - score / 100)
  const color = score >= 80 ? '#10b981' : score >= 60 ? '#f59e0b' : score >= 40 ? '#f97316' : '#ef4444'
  return (
    <svg width={56} height={56} className="flex-shrink-0">
      <circle cx={28} cy={28} r={r} stroke="#f3f4f6" strokeWidth={5} fill="none" />
      <circle
        cx={28} cy={28} r={r}
        stroke={color} strokeWidth={5} fill="none"
        strokeDasharray={circ}
        strokeDashoffset={fill}
        strokeLinecap="round"
        transform="rotate(-90 28 28)"
      />
      <text x={28} y={33} textAnchor="middle" fontSize={13} fontWeight="700" fill={color}>{score}</text>
    </svg>
  )
}

// ── Intelligence quality badge ────────────────────────────────────────────

function DataSourceBadge({ source }: { source: DataSource }) {
  if (source === 'insight_snapshot') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">
        <Brain size={10} /> Full intelligence
      </span>
    )
  }
  if (source === 'graph_heuristics') {
    return (
      <span className="flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
        <Activity size={10} /> Graph signals only
      </span>
    )
  }
  return (
    <span className="text-xs font-medium text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
      No data
    </span>
  )
}

// ── Company health card ───────────────────────────────────────────────────

function CompanyHealthCard({
  company,
  onDrillDown,
  onRunInsights,
}: {
  company: CompanyCard
  onDrillDown: (id: string) => void
  onRunInsights: (id: string) => void
}) {
  const [expanded, setExpanded] = useState(false)

  if (!company.available) {
    return (
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div className="flex items-center justify-between mb-2">
          <p className="text-sm font-bold text-gray-800 truncate">{company.tenant_id}</p>
          <DataSourceBadge source="none" />
        </div>
        <p className="text-xs text-gray-400">
          {company.error ?? 'Could not load data for this company.'}
        </p>
      </div>
    )
  }

  const sev = severityColors[company.severity]
  const m = company.metrics
  const isHeuristic = company.data_source === 'graph_heuristics'
  const relTime = fmtRelTime(company.last_insights_run)

  return (
    <div className={`bg-white rounded-xl border shadow-sm overflow-hidden ${sev.border}`}>

      {/* ── Header ── */}
      <div className={`px-5 py-3 ${sev.bg} border-b ${sev.border}`}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${sev.dot}`} />
            <p className="text-sm font-bold text-gray-900 truncate">{company.tenant_id}</p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${sev.badge}`}>
              {company.severity}
            </span>
            <ScoreRing score={company.health_score} />
          </div>
        </div>

        {/* Intelligence quality + timestamp */}
        <div className="flex items-center justify-between mt-2">
          <DataSourceBadge source={company.data_source} />
          {relTime && (
            <span className="flex items-center gap-1 text-xs text-gray-400">
              <Clock size={10} /> {relTime}
            </span>
          )}
        </div>
      </div>

      {/* ── Company profile strip ── */}
      {(company.company_profile.segment || company.company_profile.business_model) && (
        <div className="px-5 pt-3 flex flex-wrap gap-2">
          {company.company_profile.segment && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full capitalize">
              {company.company_profile.segment.replace('_', ' ')}
            </span>
          )}
          {company.company_profile.business_model && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
              {company.company_profile.business_model}
            </span>
          )}
          {company.company_profile.data_confidence && (
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
              {company.company_profile.data_confidence} confidence
            </span>
          )}
        </div>
      )}

      {/* ── Finding counts ── */}
      <div className="px-5 pt-3 pb-1 flex items-center gap-3">
        {company.finding_counts.critical > 0 && (
          <span className="flex items-center gap-1 text-xs font-semibold text-red-700">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />
            {company.finding_counts.critical} critical
          </span>
        )}
        {company.finding_counts.high > 0 && (
          <span className="flex items-center gap-1 text-xs font-semibold text-orange-700">
            <span className="w-1.5 h-1.5 rounded-full bg-orange-500 inline-block" />
            {company.finding_counts.high} high
          </span>
        )}
        {company.finding_counts.medium > 0 && (
          <span className="flex items-center gap-1 text-xs text-yellow-700">
            <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 inline-block" />
            {company.finding_counts.medium} medium
          </span>
        )}
        {company.finding_counts.total === 0 && (
          <span className="text-xs text-emerald-600 font-medium">No issues found</span>
        )}
      </div>

      {/* ── Key metrics ── */}
      <div className="px-5 py-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
        <div className="flex items-center gap-1.5">
          <Users size={12} className="text-gray-300 flex-shrink-0" />
          <div>
            <p className="text-xs text-gray-400">Headcount</p>
            <p className="text-sm font-bold text-gray-800">{m.headcount > 0 ? m.headcount.toLocaleString() : '—'}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <AlertTriangle size={12} className="text-gray-300 flex-shrink-0" />
          <div>
            <p className="text-xs text-gray-400">At-Risk ARR</p>
            <p className="text-sm font-bold text-gray-800">{fmtMoney(m.at_risk_arr)}</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <TrendingUp size={12} className="text-gray-300 flex-shrink-0" />
          <div>
            <p className="text-xs text-gray-400">Stalled Deals</p>
            <p className="text-sm font-bold text-gray-800">
              {m.stalled_deals !== null ? m.stalled_deals : '—'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          <DollarSign size={12} className="text-gray-300 flex-shrink-0" />
          <div>
            <p className="text-xs text-gray-400">SaaS Spend</p>
            <p className="text-sm font-bold text-gray-800">{fmtMoney(m.saas_annual_spend)}</p>
          </div>
        </div>
        {m.vendor_savings_opportunity !== null && m.vendor_savings_opportunity > 0 && (
          <div className="col-span-2 flex items-center gap-1.5">
            <BarChart2 size={12} className="text-emerald-400 flex-shrink-0" />
            <div>
              <p className="text-xs text-gray-400">Vendor Savings Opportunity</p>
              <p className="text-sm font-bold text-emerald-700">{fmtMoney(m.vendor_savings_opportunity)}</p>
            </div>
          </div>
        )}
      </div>

      {/* ── Narrative snippet ── */}
      {company.narrative_snippet && (
        <div className="mx-5 mb-3 p-3 bg-gray-50 rounded-lg border border-gray-100">
          <p className="text-xs text-gray-500 leading-relaxed line-clamp-3">
            {company.narrative_snippet}
          </p>
        </div>
      )}

      {/* ── Top findings (expandable) ── */}
      {company.top_findings.length > 0 && (
        <div className="px-5 pb-3">
          <button
            onClick={() => setExpanded(e => !e)}
            className="flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-800 mb-2 transition-colors"
          >
            <ChevronRight size={12} className={`transition-transform ${expanded ? 'rotate-90' : ''}`} />
            {company.top_findings.length} top finding{company.top_findings.length > 1 ? 's' : ''}
          </button>
          {expanded && (
            <div className="space-y-1.5">
              {company.top_findings.map((f, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5 ${findingSeverityDot[f.severity] ?? 'bg-gray-300'}`} />
                  <div className="min-w-0">
                    <p className="text-xs text-gray-700 leading-snug">{f.title}</p>
                    <p className="text-xs text-gray-400">{f.worker}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Heuristic notice ── */}
      {isHeuristic && company.note && (
        <div className="mx-5 mb-3 flex items-start gap-2 p-2.5 bg-amber-50 rounded-lg border border-amber-200">
          <Zap size={12} className="text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700">Showing graph signals only. Run full intelligence for real worker findings.</p>
        </div>
      )}

      {/* ── Footer actions ── */}
      <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between">
        {isHeuristic ? (
          <button
            onClick={() => onRunInsights(company.tenant_id)}
            className="flex items-center gap-1 text-xs font-semibold text-white bg-navy-900 px-3 py-1.5 rounded-lg hover:opacity-90 transition-opacity"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            <Brain size={11} /> Run Intelligence
          </button>
        ) : (
          <button
            onClick={() => onDrillDown(company.tenant_id)}
            className="flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-800 transition-colors"
          >
            <ChevronRight size={13} /> Deep dive in Insights
          </button>
        )}
        {m.workers_run > 0 && (
          <span className="text-xs text-gray-300">{m.workers_run} workers</span>
        )}
      </div>
    </div>
  )
}

// ── Aggregate strip ───────────────────────────────────────────────────────

function AggregateStrip({ agg }: { agg: Aggregate }) {
  const stats = [
    {
      label: 'Avg Health Score',
      value: `${agg.avg_health_score}/100`,
      icon: <CheckCircle2 size={15} className="text-emerald-500" />,
    },
    {
      label: 'Critical Issues',
      value: agg.total_critical_findings,
      icon: <ShieldAlert size={15} className="text-red-500" />,
      highlight: agg.total_critical_findings > 0,
    },
    {
      label: 'High Issues',
      value: agg.total_high_findings,
      icon: <AlertTriangle size={15} className="text-orange-500" />,
    },
    {
      label: 'Healthy Companies',
      value: agg.healthy_count,
      icon: <CheckCircle2 size={15} className="text-emerald-400" />,
    },
    {
      label: 'Full Intelligence',
      value: `${agg.companies_with_full_intelligence}/${agg.total_companies}`,
      icon: <Brain size={15} className="text-blue-500" />,
    },
    {
      label: 'Need Insights Run',
      value: agg.companies_needing_insights_run,
      icon: <Zap size={15} className="text-amber-500" />,
      highlight: agg.companies_needing_insights_run > 0,
    },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
      {stats.map(s => (
        <div
          key={s.label}
          className={`bg-white rounded-xl border shadow-sm p-4 ${s.highlight ? 'border-red-200 bg-red-50' : 'border-gray-100'}`}
        >
          <div className="flex items-center gap-2 mb-1">
            {s.icon}
            <p className="text-xs text-gray-400 font-medium leading-tight">{s.label}</p>
          </div>
          <p className={`text-xl font-bold ${s.highlight ? 'text-red-700' : 'text-gray-900'}`}>{s.value}</p>
        </div>
      ))}
    </div>
  )
}

// ── Schedule panel ────────────────────────────────────────────────────────

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function SchedulePanel({ token, tenantId }: { token: string; tenantId: string }) {
  const [open, setOpen] = useState(false)
  const [cadence, setCadence] = useState<'daily' | 'weekly' | 'manual'>('daily')
  const [hourUtc, setHourUtc] = useState(6)
  const [dayOfWeek, setDayOfWeek] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [scheduleInfo, setScheduleInfo] = useState<{
    last_triggered_at: string | null
    last_status: string | null
    enabled: boolean
    cadence: string
    hour_utc: number
  } | null>(null)

  useEffect(() => {
    if (!open) return
    api.scheduleList(token).then(resp => {
      const match = resp.schedules.find(s => s.tenant_id === tenantId)
      if (match) {
        setScheduleInfo(match)
        setCadence(match.cadence)
        setHourUtc(match.hour_utc)
        setDayOfWeek(match.day_of_week ?? 0)
      }
    }).catch(() => {})
  }, [open, token, tenantId])

  async function save() {
    setSaving(true)
    try {
      await api.scheduleUpsert(token, {
        tenant_id: tenantId,
        cadence,
        hour_utc: hourUtc,
        day_of_week: cadence === 'weekly' ? dayOfWeek : null,
        enabled: cadence !== 'manual',
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { /* ignore */ } finally {
      setSaving(false)
    }
  }

  const relTime = scheduleInfo?.last_triggered_at
    ? fmtRelTime(scheduleInfo.last_triggered_at)
    : null

  return (
    <div className="border border-gray-100 rounded-xl bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-3 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <CalendarClock size={15} className="text-gray-400" />
          <span className="text-sm font-medium text-gray-700">Auto-schedule insights</span>
          {scheduleInfo?.enabled && (
            <span className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">
              {scheduleInfo.cadence} · {scheduleInfo.hour_utc.toString().padStart(2,'0')}:00 UTC
            </span>
          )}
          {relTime && (
            <span className="text-xs text-gray-400">· last ran {relTime}</span>
          )}
        </div>
        <ChevronDown size={14} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="px-5 pb-5 pt-1 border-t border-gray-100 space-y-4">
          <p className="text-xs text-gray-400 leading-relaxed">
            Automatically run full intelligence for <strong>{tenantId}</strong> on a schedule, keeping your portfolio card fresh without manual calls.
          </p>

          {/* Cadence */}
          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Cadence</label>
            <div className="flex gap-2">
              {(['daily', 'weekly', 'manual'] as const).map(c => (
                <button
                  key={c}
                  onClick={() => setCadence(c)}
                  className={`px-4 py-1.5 rounded-lg text-xs font-medium border transition-colors capitalize ${
                    cadence === c
                      ? 'bg-navy-900 text-white border-navy-900'
                      : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
                  }`}
                  style={cadence === c ? { backgroundColor: '#1B2A4A' } : {}}
                >
                  {c === 'manual' ? 'Manual only' : c}
                </button>
              ))}
            </div>
          </div>

          {cadence !== 'manual' && (
            <div className="flex gap-4">
              {/* Hour */}
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">UTC Hour</label>
                <select
                  value={hourUtc}
                  onChange={e => setHourUtc(Number(e.target.value))}
                  className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-200"
                >
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>{i.toString().padStart(2, '0')}:00 UTC</option>
                  ))}
                </select>
              </div>

              {/* Day of week (weekly only) */}
              {cadence === 'weekly' && (
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Day</label>
                  <select
                    value={dayOfWeek}
                    onChange={e => setDayOfWeek(Number(e.target.value))}
                    className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-200"
                  >
                    {DAY_NAMES.map((d, i) => (
                      <option key={i} value={i}>{d}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          )}

          {cadence === 'manual' && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              Auto-run disabled. The portfolio card will only update when you manually click Run Intelligence.
            </p>
          )}

          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 transition-opacity"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Settings2 size={13} />}
            {saved ? 'Saved ✓' : 'Save Schedule'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

const DEFAULT_TENANTS: string[] = []

export default function Portfolio() {
  const [tenants, setTenants] = useState<string[]>(DEFAULT_TENANTS)
  const [newTenant, setNewTenant] = useState('')
  const [loading, setLoading] = useState(false)
  const [tenantsLoading, setTenantsLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState<{ companies: CompanyCard[]; aggregate: Aggregate } | null>(null)
  const token = localStorage.getItem('miragent_token') ?? ''

  // Auto-load tenants from /access/my-tenants on mount (Sprint 80: includes granted tenants)
  useEffect(() => {
    async function loadTenants() {
      try {
        const resp = await api.accessMyTenants(token)
        const ids = resp.tenants.map(t => t.tenant_id)
        if (ids.length > 0) setTenants(ids)
      } catch {
        // silently ignore — try portfolioTenants as fallback
        try {
          const resp2 = await api.portfolioTenants(token)
          const ids = resp2.tenants.map(t => t.tenant_id)
          if (ids.length > 0) setTenants(ids)
        } catch { /* ignore */ }
      } finally {
        setTenantsLoading(false)
      }
    }
    loadTenants()
  }, [token])

  async function fetchPortfolio() {
    if (tenants.length === 0) return
    setLoading(true)
    setError('')
    setData(null)
    try {
      const result = await api.portfolioSummary(token, tenants)
      setData(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load portfolio data')
    } finally {
      setLoading(false)
    }
  }

  function addTenant() {
    const t = newTenant.trim()
    if (!t || tenants.includes(t)) return
    setTenants(prev => [...prev, t])
    setNewTenant('')
  }

  function removeTenant(t: string) {
    setTenants(prev => prev.filter(x => x !== t))
  }

  function drillDown(tenantId: string) {
    localStorage.setItem('miragent_default_tenant', tenantId)
    window.location.href = '/insights'
  }

  function runInsights(tenantId: string) {
    localStorage.setItem('miragent_default_tenant', tenantId)
    window.location.href = '/insights'
  }

  const agg = data?.aggregate

  return (
    <div className="max-w-7xl mx-auto">

      {/* ── Page header ── */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <LayoutGrid size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Portfolio</h1>
        </div>
        <p className="text-gray-500">Fund-level health scores across all portfolio companies — ranked by risk.</p>
      </div>

      {/* ── Tenant builder ── */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 mb-6">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Portfolio Companies</p>

        {tenantsLoading ? (
          <div className="flex items-center gap-2 text-xs text-gray-400 mb-3">
            <Loader2 size={12} className="animate-spin" /> Loading your tenants…
          </div>
        ) : (
          <div className="flex flex-wrap gap-2 mb-3">
            {tenants.map(t => (
              <span key={t} className="flex items-center gap-1.5 bg-gray-100 text-gray-700 text-xs font-medium px-3 py-1 rounded-full">
                {t}
                <button onClick={() => removeTenant(t)} className="text-gray-400 hover:text-gray-700">
                  <X size={12} />
                </button>
              </span>
            ))}
            {tenants.length === 0 && (
              <p className="text-xs text-gray-400">Add at least one tenant ID to get started.</p>
            )}
          </div>
        )}

        <div className="flex gap-2">
          <input
            type="text"
            value={newTenant}
            onChange={e => setNewTenant(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addTenant()}
            placeholder="Add tenant ID (e.g. techco-inc)"
            className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <button
            onClick={addTenant}
            disabled={!newTenant.trim()}
            className="px-3 py-2 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50 disabled:opacity-40"
          >
            <Plus size={16} />
          </button>
          <button
            onClick={fetchPortfolio}
            disabled={loading || tenants.length === 0}
            className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 transition-opacity"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            Load Portfolio
          </button>
        </div>
      </div>

      {/* ── Schedule panels (one per tenant) ── */}
      {tenants.length > 0 && (
        <div className="space-y-2 mb-6">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide px-1">
            Insight Schedules
          </p>
          {tenants.map(t => (
            <SchedulePanel key={t} token={token} tenantId={t} />
          ))}
        </div>
      )}

      {/* ── Error ── */}
      {error && (
        <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <Loader2 size={32} className="animate-spin mx-auto mb-3 text-gray-300" />
            <p className="text-sm text-gray-500">
              Loading {tenants.length} portfolio compan{tenants.length === 1 ? 'y' : 'ies'}…
            </p>
          </div>
        </div>
      )}

      {/* ── Aggregate strip ── */}
      {agg && !loading && <AggregateStrip agg={agg} />}

      {/* ── Intelligence quality notice ── */}
      {agg && agg.companies_needing_insights_run > 0 && !loading && (
        <div className="flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6">
          <Zap size={16} className="text-amber-600 flex-shrink-0" />
          <p className="text-sm text-amber-800">
            <span className="font-semibold">{agg.companies_needing_insights_run} compan{agg.companies_needing_insights_run === 1 ? 'y' : 'ies'}</span> showing graph signals only.
            Click <span className="font-semibold">Run Intelligence</span> on those cards to generate full worker findings.
          </p>
        </div>
      )}

      {/* ── Company cards ── */}
      {data && !loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {data.companies.map(company => (
            <CompanyHealthCard
              key={company.tenant_id}
              company={company}
              onDrillDown={drillDown}
              onRunInsights={runInsights}
            />
          ))}
        </div>
      )}

      {/* ── Empty state ── */}
      {!data && !loading && !error && (
        <div className="text-center py-24 text-gray-400">
          <LayoutGrid size={44} className="mx-auto mb-4 text-gray-200" />
          <p className="text-sm font-semibold text-gray-500 mb-1">
            {tenants.length > 0
              ? `${tenants.length} tenant${tenants.length > 1 ? 's' : ''} ready — click Load Portfolio`
              : 'Add portfolio companies above to get started'}
          </p>
          <p className="text-xs text-gray-400">
            Cards sourced from full intelligence runs are ranked worst-first.
          </p>
        </div>
      )}
    </div>
  )
}
