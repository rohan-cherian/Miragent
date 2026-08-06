import { useState, useEffect } from 'react'
import {
  Activity,
  TrendingUp,
  Heart,
  Settings,
  Shield,
  Users,
  DollarSign,
  ChevronDown,
  ChevronUp,
  ArrowRight,
} from 'lucide-react'
import { api } from '../api/client'
import type { HealthScoreResponse, DimensionScore, HealthScoreHistory } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Band config ────────────────────────────────────────────────────────────────

const BAND_CONFIG: Record<string, { border: string; text: string; bg: string; badge: string }> = {
  Excellent:       { border: 'border-green-500',  text: 'text-green-600',  bg: 'bg-green-50',  badge: 'bg-green-100 text-green-800' },
  Good:            { border: 'border-teal-500',   text: 'text-teal-600',   bg: 'bg-teal-50',   badge: 'bg-teal-100 text-teal-800' },
  'Needs Attention': { border: 'border-yellow-500', text: 'text-yellow-600', bg: 'bg-yellow-50', badge: 'bg-yellow-100 text-yellow-800' },
  'At Risk':       { border: 'border-orange-500', text: 'text-orange-600', bg: 'bg-orange-50', badge: 'bg-orange-100 text-orange-800' },
  Critical:        { border: 'border-red-500',    text: 'text-red-600',    bg: 'bg-red-50',    badge: 'bg-red-100 text-red-800' },
}

// ── Dimension icon map ─────────────────────────────────────────────────────────

function DimIcon({ icon, size = 18 }: { icon: string; size?: number }) {
  switch (icon) {
    case 'trending_up': return <TrendingUp size={size} />
    case 'heart':       return <Heart size={size} />
    case 'settings':    return <Settings size={size} />
    case 'shield':      return <Shield size={size} />
    case 'users':       return <Users size={size} />
    case 'dollar':      return <DollarSign size={size} />
    default:            return <Activity size={size} />
  }
}

// ── Score circle ───────────────────────────────────────────────────────────────

function ScoreCircle({ score, band }: { score: number; band: string }) {
  const cfg = BAND_CONFIG[band] ?? BAND_CONFIG['Needs Attention']
  return (
    <div
      className={`w-32 h-32 rounded-full border-8 ${cfg.border} flex flex-col items-center justify-center`}
    >
      <span className={`text-4xl font-extrabold leading-none ${cfg.text}`}>{score}</span>
      <span className="text-xs text-gray-500 mt-1 font-medium">/ 100</span>
    </div>
  )
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ history }: { history: HealthScoreHistory[] }) {
  if (history.length === 0) return null
  const max = Math.max(...history.map((h) => h.score))
  const min = Math.min(...history.map((h) => h.score))
  const range = max - min || 1

  return (
    <div className="flex items-end gap-1.5 h-12">
      {history.map((h, i) => {
        const heightPct = 20 + ((h.score - min) / range) * 80
        const isCurrent = i === history.length - 1
        return (
          <div key={h.month} className="flex flex-col items-center gap-1 flex-1" title={`${h.month}: ${h.score}`}>
            <div
              className={`w-full rounded-sm ${isCurrent ? 'bg-teal-500' : 'bg-gray-200'}`}
              style={{ height: `${heightPct}%` }}
            />
            <span className="text-xs text-gray-400 truncate" style={{ fontSize: '9px' }}>
              {h.month.split(' ')[0]}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Dimension card ─────────────────────────────────────────────────────────────

function DimensionCard({ dim }: { dim: DimensionScore }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = BAND_CONFIG[dim.band] ?? BAND_CONFIG['Needs Attention']
  const changePositive = dim.change >= 0

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-gray-700">
          <DimIcon icon={dim.icon} size={16} />
          <span className="text-sm font-semibold text-gray-900">{dim.label}</span>
        </div>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg.badge}`}>
          {dim.band}
        </span>
      </div>

      {/* Score + change */}
      <div className="flex items-end gap-2">
        <span className={`text-3xl font-extrabold leading-none ${cfg.text}`}>{dim.score}</span>
        <span className="text-sm text-gray-400 mb-0.5">/100</span>
        <span
          className={`ml-auto text-xs font-semibold px-2 py-0.5 rounded-full ${
            changePositive
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              : 'bg-red-50 text-red-700 border border-red-200'
          }`}
        >
          {changePositive ? '▲' : '▼'} {Math.abs(dim.change)} MoM
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-gray-100 rounded-full h-2">
        <div
          className={`h-2 rounded-full transition-all ${cfg.border.replace('border-', 'bg-')}`}
          style={{ width: `${dim.score}%` }}
        />
      </div>

      {/* Signal rows */}
      <div className="space-y-1.5">
        {dim.signals.slice(0, 4).map((sig) => (
          <div key={sig.label} className="flex items-center justify-between text-xs">
            <span className="text-gray-600">{sig.label}</span>
            <div className="flex items-center gap-1.5">
              <span className="font-medium text-gray-800">{sig.value}</span>
              {sig.positive ? (
                <span className="text-emerald-500 font-bold">✓</span>
              ) : (
                <span className="text-red-500 font-bold">✕</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Expand toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 mt-1 transition-colors"
      >
        {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        {expanded ? 'Hide risks & opportunities' : 'Show risks & opportunities'}
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="space-y-2 pt-1">
          <div className="bg-red-50 border border-red-100 rounded-lg p-3">
            <p className="text-xs font-semibold text-red-700 mb-1">Top Risk</p>
            <p className="text-xs text-red-600 leading-relaxed">{dim.top_risk}</p>
          </div>
          <div className="bg-emerald-50 border border-emerald-100 rounded-lg p-3">
            <p className="text-xs font-semibold text-emerald-700 mb-1">Top Opportunity</p>
            <p className="text-xs text-emerald-600 leading-relaxed">{dim.top_opportunity}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Dimension → page URL map ───────────────────────────────────────────────────

const DIMENSION_LINKS: Record<string, string> = {
  security:        '/workers',
  operational:     '/mission-control',
  customer_health: '/communications',
  revenue_growth:  '/board-report',
  team_org:        '/users',
  financial:       '/board-report',
}

const DIMENSION_ACTIONS: Record<string, string> = {
  security:        'Enroll remaining 52% of users in MFA and rotate 3 stale API keys',
  operational:     'Resolve portal access and vendor onboarding SLA breaches',
  customer_health: 'Address ConsultancyCo cancellation risk and Enterprise Client Corp API complaints',
  revenue_growth:  'Reduce pipeline concentration — diversify top-3 deal dependency',
  team_org:        'Prioritise 7 open engineering reqs to protect Q3 feature velocity',
  financial:       'Accelerate burn-rate reduction to strengthen Series B positioning',
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function HealthScore() {
  const tenantId =
    typeof window !== 'undefined'
      ? (localStorage.getItem(DEFAULT_TENANT_KEY) ?? DEFAULT_TENANT)
      : DEFAULT_TENANT

  const [data, setData] = useState<HealthScoreResponse | null>(null)
  const [history, setHistory] = useState<HealthScoreHistory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [scoreData, histData] = await Promise.all([
          api.healthScore.get(tenantId),
          api.healthScore.history(tenantId, 6),
        ])
        setData(scoreData)
        setHistory(histData)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Failed to load health score')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [tenantId])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div
          className="w-10 h-10 border-4 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: '#1B2A4A', borderTopColor: 'transparent' }}
        />
        <p className="text-gray-500 text-sm">Loading health score…</p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-6 py-5">
        <p className="font-semibold">Error loading Health Score</p>
        <p className="text-sm mt-1">{error}</p>
      </div>
    )
  }

  const overallCfg = BAND_CONFIG[data.overall_band] ?? BAND_CONFIG['Needs Attention']
  const changePositive = data.overall_change >= 0

  // Dimensions below 70, sorted ascending by score
  const actionItems = data.dimensions
    .filter((d) => d.score < 70)
    .sort((a, b) => a.score - b.score)

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-8">

      {/* ── Page header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <Activity size={24} className="text-teal-600" />
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Company Health Score</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Operational health across 6 dimensions — {data.period}
          </p>
        </div>
      </div>

      {/* ── Hero score card ───────────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-8">
        <div className="flex flex-col items-center gap-4">
          <ScoreCircle score={data.overall_score} band={data.overall_band} />

          <div className="flex flex-col items-center gap-1">
            <span
              className={`text-lg font-bold ${overallCfg.text}`}
            >
              {data.overall_band}
            </span>
            <span className="text-sm text-gray-500">{data.period}</span>
          </div>

          {/* MoM change chip */}
          <span
            className={`text-sm font-semibold px-3 py-1 rounded-full ${
              changePositive
                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`}
          >
            {changePositive ? '▲' : '▼'} {Math.abs(data.overall_change)} from last month
          </span>

          {/* Narrative */}
          <p className="text-sm text-gray-500 text-center max-w-xl leading-relaxed">
            {data.score_narrative}
          </p>

          {/* 6-month sparkline */}
          {history.length > 0 && (
            <div className="w-72 mt-2">
              <p className="text-xs text-gray-400 text-center mb-2 font-medium">
                6-month trend
              </p>
              <Sparkline history={history} />
            </div>
          )}
        </div>
      </div>

      {/* ── 6 dimension cards — 2×3 grid ──────────────────────────────────────── */}
      <div>
        <h2 className="text-base font-bold text-gray-900 mb-4">Dimension Breakdown</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.dimensions.map((dim) => (
            <DimensionCard key={dim.key} dim={dim} />
          ))}
        </div>
      </div>

      {/* ── Action priorities ──────────────────────────────────────────────────── */}
      {actionItems.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
          <h2 className="text-base font-bold text-gray-900 mb-4">What to Focus On This Month</h2>
          <div className="space-y-3">
            {actionItems.map((dim) => {
              const cfg = BAND_CONFIG[dim.band] ?? BAND_CONFIG['Needs Attention']
              const link = DIMENSION_LINKS[dim.key] ?? '/'
              const action = DIMENSION_ACTIONS[dim.key] ?? dim.top_risk
              return (
                <div
                  key={dim.key}
                  className={`flex items-start gap-4 rounded-lg border p-4 ${cfg.bg} ${cfg.border.replace('border-', 'border-')}`}
                >
                  <div className={`flex-shrink-0 mt-0.5 ${cfg.text}`}>
                    <DimIcon icon={dim.icon} size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold text-gray-900">{dim.label}</span>
                      <span className={`text-xs font-bold ${cfg.text}`}>{dim.score}/100</span>
                    </div>
                    <p className="text-sm text-gray-600 leading-relaxed">{action}</p>
                  </div>
                  <a
                    href={link}
                    className="flex-shrink-0 flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 mt-0.5 whitespace-nowrap"
                  >
                    View Details <ArrowRight size={12} />
                  </a>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
