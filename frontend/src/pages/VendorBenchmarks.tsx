/**
 * VendorBenchmarks.tsx — Sprint 19
 *
 * Visualises VendorBenchmarkWorker findings:
 *  - KPI summary cards (total vendors, enriched, potential savings, negotiation windows)
 *  - Bar chart: actual spend vs. market benchmark per vendor
 *  - Negotiation windows table (sorted by urgency — days to renewal)
 *  - Full findings list
 */

import { useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import {
  DollarSign,
  Clock,
  TrendingDown,
  Package,
  AlertCircle,
  Loader2,
  CheckCircle,
  AlertTriangle,
} from 'lucide-react'
import { api } from '../api/client'
import type {
  InsightsMemo,
  WorkerResult,
  Finding,
  VendorBenchmarkPoint,
  NegotiationWindow,
  VendorBenchmarkSummary,
} from '../types'

// ── Helpers ───────────────────────────────────────────────

function fmt(n: number): string {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${Math.round(n / 1_000)}K`
  return `$${Math.round(n)}`
}

function fmtDays(d: number): string {
  if (d <= 14) return `${d}d ⚡`
  if (d <= 45) return `${d}d`
  return `${d}d`
}

/** Pull KPI summary stats from VendorBenchmarkWorker summary_stats field */
function extractSummary(worker: WorkerResult): VendorBenchmarkSummary {
  const s = worker.summary_stats
  return {
    total_vendors_analyzed: Number(s.total_vendors_analyzed ?? 0),
    vendors_enriched: Number(s.vendors_enriched ?? 0),
    vendors_overpaying: Number(s.vendors_overpaying ?? 0),
    total_potential_savings: Number(s.total_potential_savings ?? 0),
    vendors_in_negotiation_window: Number(s.vendors_in_negotiation_window ?? 0),
    total_spend_benchmarked: Number(s.total_spend_benchmarked ?? 0),
  }
}

/** Build recharts data from CRITICAL findings (which have benchmark_spend) */
function extractChartData(worker: WorkerResult): VendorBenchmarkPoint[] {
  return worker.findings
    .filter(
      (f) =>
        f.data.benchmark_spend &&
        f.data.annual_spend &&
        f.data.spend_vs_benchmark_pct !== undefined
    )
    .map((f) => ({
      name: String(f.data.vendor ?? '').split(' ')[0], // short label
      fullName: String(f.data.vendor ?? ''),
      actualSpend: Number(f.data.annual_spend),
      benchmarkSpend: Number(f.data.benchmark_spend),
      variancePct: Number(f.data.spend_vs_benchmark_pct),
      category: f.data.category ? String(f.data.category) : undefined,
      potentialSavings: Number(f.data.potential_savings ?? 0),
      discountPct: Number(f.data.discount_opportunity_pct ?? 0),
    }))
    .sort((a, b) => b.variancePct - a.variancePct)
    .slice(0, 8)
}

/** Build negotiation window rows from HIGH findings with negotiation_window=true */
function extractNegotiationWindows(worker: WorkerResult): NegotiationWindow[] {
  return worker.findings
    .filter((f) => f.data.negotiation_window === true && f.data.days_to_renewal !== undefined)
    .map((f) => ({
      vendor: String(f.data.vendor ?? ''),
      spend: Number(f.data.annual_spend ?? 0),
      daysToRenewal: Number(f.data.days_to_renewal),
      potentialSavings: Number(f.data.potential_savings ?? 0),
      leverage: Array.isArray(f.data.negotiation_leverage)
        ? (f.data.negotiation_leverage as string[])
        : [],
    }))
    .sort((a, b) => a.daysToRenewal - b.daysToRenewal)
}

// ── Sub-components ────────────────────────────────────────

interface KpiCardProps {
  icon: React.ReactNode
  value: string
  label: string
  sub?: string
  accent?: string
}

function KpiCard({ icon, value, label, sub, accent = 'bg-gray-50' }: KpiCardProps) {
  return (
    <div className={`rounded-xl border border-gray-100 shadow-sm p-5 ${accent}`}>
      <div className="flex items-center gap-3 mb-2">
        <div className="w-9 h-9 rounded-lg bg-white border border-gray-100 flex items-center justify-center flex-shrink-0">
          {icon}
        </div>
        <span className="text-2xl font-bold text-gray-900">{value}</span>
      </div>
      <p className="text-sm font-semibold text-gray-700">{label}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

type Severity = Finding['severity']

const sevClasses: Record<Severity, string> = {
  CRITICAL: 'bg-red-100 text-red-700 border border-red-200',
  HIGH: 'bg-orange-100 text-orange-700 border border-orange-200',
  MEDIUM: 'bg-yellow-100 text-yellow-700 border border-yellow-200',
  LOW: 'bg-blue-100 text-blue-700 border border-blue-200',
  INFO: 'bg-gray-100 text-gray-600 border border-gray-200',
}

function SevBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${sevClasses[severity]}`}>
      {severity}
    </span>
  )
}

// ── Custom tooltip for recharts ───────────────────────────

interface TooltipPayload {
  name: string
  value: number
  color: string
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayload[]
  label?: string
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null
  const actual = payload.find((p) => p.name === 'Actual Spend')
  const bench = payload.find((p) => p.name === 'Market Benchmark')
  const variance =
    actual && bench && bench.value > 0
      ? Math.round(((actual.value - bench.value) / bench.value) * 100)
      : null
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs">
      <p className="font-semibold text-gray-800 mb-1.5">{label}</p>
      {actual && (
        <p style={{ color: actual.color }}>
          Actual: {fmt(actual.value)}
        </p>
      )}
      {bench && (
        <p style={{ color: bench.color }}>
          Benchmark: {fmt(bench.value)}
        </p>
      )}
      {variance !== null && (
        <p
          className={`font-bold mt-1 ${
            variance > 0 ? 'text-red-600' : 'text-emerald-600'
          }`}
        >
          {variance > 0 ? `+${variance}% over benchmark` : `${variance}% under benchmark`}
        </p>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────

export default function VendorBenchmarks() {
  const [tenantId, setTenantId] = useState('acme-corp')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [memo, setMemo] = useState<InsightsMemo | null>(null)

  async function handleLoad() {
    if (!tenantId.trim()) return
    setLoading(true)
    setError(null)
    setMemo(null)
    try {
      const result = await api.getInsights(tenantId.trim())
      setMemo(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }

  const benchmarkWorker = memo?.structured.workers.find(
    (w) => w.worker === 'VendorBenchmarkWorker'
  ) ?? null

  const summary = benchmarkWorker ? extractSummary(benchmarkWorker) : null
  const chartData = benchmarkWorker ? extractChartData(benchmarkWorker) : []
  const negotiationWindows = benchmarkWorker ? extractNegotiationWindows(benchmarkWorker) : []
  const allFindings = benchmarkWorker?.findings ?? []

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <TrendingDown size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Vendor Benchmarks</h1>
        </div>
        <p className="text-gray-500">
          Spend vs. market benchmarks, negotiation windows, and savings opportunities.
        </p>
      </div>

      {/* Load Bar */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 mb-6">
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-500 mb-1">Tenant ID</label>
            <input
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleLoad()}
              placeholder="e.g. acme-corp"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
            />
          </div>
          <div className="pt-5">
            <button
              onClick={handleLoad}
              disabled={loading || !tenantId.trim()}
              className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              {loading && <Loader2 size={15} className="animate-spin" />}
              Analyse Vendors
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-700">Failed to load benchmark data</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Loader2 size={32} className="animate-spin mx-auto mb-3 text-gray-400" />
            <p className="text-sm text-gray-500">
              Running 32 workers + vendor benchmark analysis…
            </p>
          </div>
        </div>
      )}

      {/* Results */}
      {summary && !loading && (
        <div className="space-y-6">
          {/* KPI Cards */}
          <div className="grid grid-cols-3 gap-5">
            <KpiCard
              icon={<Package size={16} className="text-blue-500" />}
              value={String(summary.total_vendors_analyzed)}
              label="Vendors Analyzed"
              sub={`${summary.vendors_enriched} matched in catalog`}
            />
            <KpiCard
              icon={<DollarSign size={16} className="text-emerald-500" />}
              value={fmt(summary.total_potential_savings)}
              label="Potential Savings"
              sub="Based on catalog discount data"
              accent="bg-emerald-50"
            />
            <KpiCard
              icon={<Clock size={16} className="text-amber-500" />}
              value={String(summary.vendors_in_negotiation_window)}
              label="Negotiation Windows Open"
              sub="Renewals in next 30–120 days"
              accent={summary.vendors_in_negotiation_window > 0 ? 'bg-amber-50' : 'bg-gray-50'}
            />
          </div>

          <div className="grid grid-cols-3 gap-5">
            <KpiCard
              icon={<AlertTriangle size={16} className="text-red-500" />}
              value={String(summary.vendors_overpaying)}
              label="Overpaying (>20% over benchmark)"
              sub={`of ${summary.vendors_enriched} enriched vendors`}
              accent={summary.vendors_overpaying > 0 ? 'bg-red-50' : 'bg-gray-50'}
            />
            <KpiCard
              icon={<TrendingDown size={16} className="text-purple-500" />}
              value={fmt(summary.total_spend_benchmarked)}
              label="Spend Benchmarked"
              sub="Total annual spend with catalog match"
            />
            <KpiCard
              icon={<CheckCircle size={16} className="text-blue-500" />}
              value={`${Math.round((summary.vendors_enriched / Math.max(summary.total_vendors_analyzed, 1)) * 100)}%`}
              label="Catalog Coverage"
              sub="Vendors matched to intelligence catalog"
            />
          </div>

          {/* Spend vs. Benchmark Chart */}
          {chartData.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
              <h2 className="text-base font-semibold text-gray-900 mb-1">
                Spend vs. Market Benchmark
              </h2>
              <p className="text-xs text-gray-500 mb-5">
                Vendors where actual spend exceeds mid-market benchmark. Sorted by
                overpayment %.
              </p>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 11, fill: '#6b7280' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tickFormatter={(v) => fmt(v)}
                    tick={{ fontSize: 11, fill: '#6b7280' }}
                    axisLine={false}
                    tickLine={false}
                    width={60}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend
                    wrapperStyle={{ fontSize: 12 }}
                    iconType="circle"
                    iconSize={8}
                  />
                  <Bar dataKey="actualSpend" name="Actual Spend" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry) => (
                      <Cell
                        key={entry.fullName}
                        fill={entry.variancePct > 50 ? '#ef4444' : entry.variancePct > 20 ? '#f97316' : '#3b82f6'}
                      />
                    ))}
                  </Bar>
                  <Bar
                    dataKey="benchmarkSpend"
                    name="Market Benchmark"
                    fill="#6b7280"
                    radius={[4, 4, 0, 0]}
                    opacity={0.45}
                  />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex items-center gap-6 mt-3 pt-3 border-t border-gray-50">
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-red-500 inline-block" />
                  <span className="text-xs text-gray-500">&gt;50% over benchmark (CRITICAL)</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-orange-500 inline-block" />
                  <span className="text-xs text-gray-500">20–50% over benchmark (HIGH)</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-full bg-blue-500 inline-block" />
                  <span className="text-xs text-gray-500">Under 20% over benchmark</span>
                </div>
              </div>
            </div>
          )}

          {/* Negotiation Windows */}
          {negotiationWindows.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100 bg-amber-50">
                <div className="flex items-center gap-2">
                  <Clock size={16} className="text-amber-600" />
                  <h2 className="text-base font-semibold text-gray-900">
                    Active Negotiation Windows
                  </h2>
                  <span className="text-xs font-medium text-amber-700 bg-amber-100 px-2 py-0.5 rounded-full border border-amber-200">
                    {negotiationWindows.length} vendor{negotiationWindows.length !== 1 ? 's' : ''}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  Renewals within 30–120 days. Act now for maximum leverage.
                </p>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="px-5 py-2.5 text-xs font-semibold text-gray-500 text-left">
                      Vendor
                    </th>
                    <th className="px-5 py-2.5 text-xs font-semibold text-gray-500 text-right">
                      Annual Spend
                    </th>
                    <th className="px-5 py-2.5 text-xs font-semibold text-gray-500 text-center">
                      Days to Renewal
                    </th>
                    <th className="px-5 py-2.5 text-xs font-semibold text-emerald-600 text-right">
                      Savings Opportunity
                    </th>
                    <th className="px-5 py-2.5 text-xs font-semibold text-gray-500 text-left">
                      Key Leverage
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {negotiationWindows.map((nw, idx) => (
                    <tr
                      key={idx}
                      className="border-b border-gray-50 hover:bg-gray-50 transition-colors"
                    >
                      <td className="px-5 py-3 text-sm font-semibold text-gray-800">
                        {nw.vendor}
                      </td>
                      <td className="px-5 py-3 text-sm text-gray-600 text-right font-mono">
                        {fmt(nw.spend)}
                      </td>
                      <td className="px-5 py-3 text-center">
                        <span
                          className={`text-xs font-bold px-2.5 py-1 rounded-full ${
                            nw.daysToRenewal <= 30
                              ? 'bg-red-100 text-red-700'
                              : nw.daysToRenewal <= 60
                              ? 'bg-amber-100 text-amber-700'
                              : 'bg-blue-100 text-blue-700'
                          }`}
                        >
                          {fmtDays(nw.daysToRenewal)}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-sm font-bold text-emerald-600 text-right font-mono">
                        {fmt(nw.potentialSavings)}
                      </td>
                      <td className="px-5 py-3 text-xs text-gray-500 max-w-xs">
                        {nw.leverage.slice(0, 2).join(' · ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* All Findings */}
          {allFindings.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100">
                <h2 className="text-base font-semibold text-gray-900">
                  All Vendor Findings
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  {allFindings.length} findings across all vendors
                </p>
              </div>
              <div className="divide-y divide-gray-50">
                {allFindings.map((finding, idx) => (
                  <div key={idx} className="px-6 py-4 hover:bg-gray-50 transition-colors">
                    <div className="flex items-start justify-between gap-3 mb-1.5">
                      <p className="text-sm font-semibold text-gray-800">{finding.title}</p>
                      <SevBadge severity={finding.severity} />
                    </div>
                    <p className="text-xs text-gray-500 leading-relaxed mb-2">
                      {finding.detail}
                    </p>
                    {finding.recommended_action && (
                      <div className="p-2.5 bg-blue-50 rounded border border-blue-100">
                        <p className="text-xs text-blue-700">
                          <span className="font-semibold">Action: </span>
                          {finding.recommended_action}
                        </p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!memo && !loading && !error && (
        <div className="text-center py-20 text-gray-400">
          <TrendingDown size={44} className="mx-auto mb-3 opacity-25" />
          <p className="text-sm font-medium mb-1">No benchmark data loaded</p>
          <p className="text-xs">
            Enter a tenant ID and click <strong>Analyse Vendors</strong> to surface spend
            intelligence.
          </p>
        </div>
      )}
    </div>
  )
}
