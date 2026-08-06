import { useState, useEffect, useCallback } from 'react'
import {
  TrendingUp, BarChart3, Heart, Users, DollarSign, Code2,
  AlertTriangle, Loader2, RefreshCw,
} from 'lucide-react'
import { api } from '../api/client'
import type { BoardReport, ReportSection, MetricItem } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

function getToken(): string { return localStorage.getItem('scout_token') || '' }
function getTenant(): string { return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT }

const PERIODS = ['April 2026', 'March 2026', 'Q1 2026']

// ── Helpers ────────────────────────────────────────────────────────────────────

function sectionIcon(id: string): React.ReactNode {
  switch (id) {
    case 'revenue':         return <TrendingUp size={18} className="text-emerald-600" />
    case 'pipeline':        return <BarChart3 size={18} className="text-blue-600" />
    case 'customer_success':return <Heart size={18} className="text-rose-500" />
    case 'headcount':       return <Users size={18} className="text-violet-600" />
    case 'financials':      return <DollarSign size={18} className="text-amber-600" />
    case 'engineering':     return <Code2 size={18} className="text-indigo-600" />
    default:                return <BarChart3 size={18} className="text-gray-500" />
  }
}

function doraBadge(tier: string): string {
  switch (tier) {
    case 'Elite':  return 'bg-emerald-100 text-emerald-800 border-emerald-300'
    case 'High':   return 'bg-blue-100 text-blue-800 border-blue-300'
    case 'Medium': return 'bg-yellow-100 text-yellow-800 border-yellow-300'
    default:       return 'bg-red-100 text-red-800 border-red-300'
  }
}

function severityBadge(s: string): string {
  switch (s) {
    case 'HIGH':   return 'bg-red-100 text-red-800 border-red-300'
    case 'MEDIUM': return 'bg-yellow-100 text-yellow-800 border-yellow-300'
    default:       return 'bg-emerald-100 text-emerald-800 border-emerald-300'
  }
}

function changeChip(item: MetricItem): React.ReactNode {
  if (item.change_pct === null || item.change_pct === undefined) return null

  // Determine if this change is good or bad for display purposes
  const isGoodChange =
    (item.direction === 'up' && item.is_positive) ||
    (item.direction === 'down' && !item.is_positive)

  const arrow = item.direction === 'up' ? '▲' : item.direction === 'down' ? '▼' : '●'
  const colorClass = isGoodChange
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
    : 'bg-red-50 text-red-700 border-red-200'

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border font-medium ${colorClass}`}>
      {arrow} {Math.abs(item.change_pct).toFixed(1)}%
    </span>
  )
}

// ── Metric Card ────────────────────────────────────────────────────────────────

function MetricCard({ item }: { item: MetricItem }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 flex flex-col gap-1">
      <p className="text-xs text-gray-500 font-medium">{item.label}</p>
      <div className="flex items-end gap-2 flex-wrap">
        <span className="text-xl font-bold text-gray-900 leading-none">{item.value}</span>
        {changeChip(item)}
      </div>
      {item.prior_value && (
        <p className="text-xs text-gray-400">Prior: {item.prior_value}</p>
      )}
    </div>
  )
}

// ── Section Card ──────────────────────────────────────────────────────────────

function SectionCard({ section }: { section: ReportSection }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 flex flex-col gap-4">
      <div className="flex items-center gap-2">
        {sectionIcon(section.section_id)}
        <h3 className="font-semibold text-gray-900 text-base">{section.title}</h3>
      </div>
      <p className="text-sm text-gray-500 italic leading-relaxed">{section.narrative}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {section.metrics.map((m) => (
          <MetricCard key={m.label} item={m} />
        ))}
      </div>
    </div>
  )
}

// ── Strategic Risks Table ─────────────────────────────────────────────────────

function RisksTable({ risks }: { risks: { risk: string; detail: string; severity: string }[] }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <AlertTriangle size={18} className="text-amber-500" />
        <h3 className="font-semibold text-gray-900 text-base">Strategic Risks & Actions</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <th className="text-left pb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide w-40">Risk</th>
              <th className="text-left pb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">Detail</th>
              <th className="text-left pb-2 text-xs font-semibold text-gray-500 uppercase tracking-wide w-24">Severity</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {risks.map((r) => (
              <tr key={r.risk} className="py-3">
                <td className="py-3 pr-4 font-medium text-gray-800 align-top">{r.risk}</td>
                <td className="py-3 pr-4 text-gray-600 leading-relaxed align-top">{r.detail}</td>
                <td className="py-3 align-top">
                  <span className={`text-xs px-2 py-1 rounded-full border font-semibold ${severityBadge(r.severity)}`}>
                    {r.severity}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function BoardReportPage() {
  const [report, setReport]         = useState<BoardReport | null>(null)
  const [loading, setLoading]       = useState(false)
  const [toastMsg, setToastMsg]     = useState('')
  const [selectedPeriod, setSelectedPeriod] = useState(PERIODS[0])

  const token  = getToken()
  const tenant = getTenant()

  const loadLatest = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.boardReport.getLatest(tenant, token)
      setReport(r)
    } catch {
      // Silently fail on initial load — user can regenerate
    } finally {
      setLoading(false)
    }
  }, [tenant, token])

  useEffect(() => {
    loadLatest()
  }, [loadLatest])

  const handleRegenerate = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.boardReport.generate(tenant, selectedPeriod, token)
      setReport(r)
    } catch {
      setToastMsg('Failed to generate report. Please try again.')
      setTimeout(() => setToastMsg(''), 3000)
    } finally {
      setLoading(false)
    }
  }, [tenant, selectedPeriod, token])

  const handleExportPdf = useCallback(() => {
    setToastMsg('PDF export coming soon')
    setTimeout(() => setToastMsg(''), 3000)
  }, [])

  const formatTs = (iso: string) => {
    try {
      return new Date(iso).toLocaleString('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    } catch {
      return iso
    }
  }

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <BarChart3 size={24} className="text-indigo-600" />
            <h1 className="text-2xl font-bold text-gray-900">
              Board Report{report ? ` — ${report.period}` : ''}
            </h1>
            {report && (
              <span className={`text-xs px-2.5 py-1 rounded-full border font-semibold ${doraBadge(report.dora_tier)}`}>
                DORA {report.dora_tier}
              </span>
            )}
          </div>
          {report && (
            <p className="text-xs text-gray-400 mt-1 ml-9">
              Generated {formatTs(report.generated_at)}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Period selector */}
          <select
            value={selectedPeriod}
            onChange={e => setSelectedPeriod(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"
          >
            {PERIODS.map(p => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          {/* Regenerate */}
          <button
            onClick={handleRegenerate}
            disabled={loading}
            className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            {loading ? 'Generating…' : 'Regenerate'}
          </button>

          {/* Export PDF */}
          <button
            onClick={handleExportPdf}
            className="flex items-center gap-2 border border-gray-300 hover:border-gray-400 text-gray-700 rounded-lg px-4 py-2 text-sm font-medium bg-white"
          >
            Export PDF
          </button>
        </div>
      </div>

      {/* ── Toast ───────────────────────────────────────────────────────────── */}
      {toastMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-gray-800 text-white text-sm px-4 py-3 rounded-lg shadow-lg">
          {toastMsg}
        </div>
      )}

      {/* ── Loading skeleton ─────────────────────────────────────────────────── */}
      {loading && !report && (
        <div className="flex items-center justify-center py-32 text-gray-400">
          <Loader2 size={32} className="animate-spin mr-3" />
          <span className="text-sm">Generating board report…</span>
        </div>
      )}

      {/* ── Report body ──────────────────────────────────────────────────────── */}
      {report && (
        <div className="space-y-6">

          {/* Executive Summary */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-6">
            <h2 className="text-sm font-semibold text-blue-700 uppercase tracking-wide mb-2">
              Executive Summary
            </h2>
            <p className="text-gray-800 text-sm leading-relaxed">{report.executive_summary}</p>
          </div>

          {/* Section grid — 2 columns */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {report.sections.map((s) => (
              <SectionCard key={s.section_id} section={s} />
            ))}
          </div>

          {/* Strategic Risks — full width */}
          <RisksTable risks={report.strategic_risks} />
        </div>
      )}
    </div>
  )
}
