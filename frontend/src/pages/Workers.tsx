import { useState } from 'react'
import { Cpu, ChevronDown, ChevronRight, AlertCircle, Loader2, Search } from 'lucide-react'
import { api } from '../api/client'
import type { InsightsMemo, WorkerResult, Finding } from '../types'

type Severity = Finding['severity']

const severityOrder: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

function countBySeverity(findings: Finding[], severity: Severity): number {
  return findings.filter((f) => f.severity === severity).length
}

function getHighestSeverity(findings: Finding[]): Severity | null {
  for (const sev of severityOrder) {
    if (findings.some((f) => f.severity === sev)) return sev
  }
  return null
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const configs: Record<Severity, string> = {
    CRITICAL: 'bg-red-100 text-red-700 border border-red-200',
    HIGH: 'bg-orange-100 text-orange-700 border border-orange-200',
    MEDIUM: 'bg-yellow-100 text-yellow-700 border border-yellow-200',
    LOW: 'bg-blue-100 text-blue-700 border border-blue-200',
    INFO: 'bg-gray-100 text-gray-600 border border-gray-200'
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${configs[severity]}`}>
      {severity}
    </span>
  )
}

function FindingRow({ finding }: { finding: Finding }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 border border-gray-100">
      <div className="flex items-start justify-between gap-3 mb-1">
        <p className="text-xs font-semibold text-gray-800">{finding.title}</p>
        <SeverityBadge severity={finding.severity} />
      </div>
      <p className="text-xs text-gray-500 leading-relaxed">{finding.detail}</p>
      {finding.recommended_action && (
        <p className="text-xs text-blue-600 mt-1.5 italic">→ {finding.recommended_action}</p>
      )}
    </div>
  )
}

function WorkerRow({
  worker,
  expanded,
  onToggle
}: {
  worker: WorkerResult
  expanded: boolean
  onToggle: () => void
}) {
  const critCount = countBySeverity(worker.findings, 'CRITICAL')
  const highCount = countBySeverity(worker.findings, 'HIGH')

  return (
    <>
      <tr
        className="hover:bg-gray-50 cursor-pointer transition-colors border-b border-gray-100"
        onClick={onToggle}
      >
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {expanded ? (
              <ChevronDown size={14} className="text-gray-400 flex-shrink-0" />
            ) : (
              <ChevronRight size={14} className="text-gray-400 flex-shrink-0" />
            )}
            <span className="text-sm font-medium text-gray-800">{worker.worker}</span>
          </div>
        </td>
        <td className="px-4 py-3 text-sm text-gray-500 text-center">
          {worker.findings.length}
        </td>
        <td className="px-4 py-3 text-center">
          {critCount > 0 ? (
            <span className="text-sm font-bold text-red-600">{critCount}</span>
          ) : (
            <span className="text-sm text-gray-300">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-center">
          {highCount > 0 ? (
            <span className="text-sm font-semibold text-orange-500">{highCount}</span>
          ) : (
            <span className="text-sm text-gray-300">—</span>
          )}
        </td>
        <td className="px-4 py-3 text-center">
          {worker.error ? (
            <span className="flex items-center justify-center gap-1 text-xs text-red-500">
              <AlertCircle size={12} />
              Error
            </span>
          ) : (
            <span className="text-xs text-emerald-500">OK</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-gray-50 border-b border-gray-100">
          <td colSpan={5} className="px-6 py-4">
            {worker.error && (
              <div className="mb-3 p-3 bg-red-50 border border-red-100 rounded-lg">
                <p className="text-xs font-medium text-red-700 mb-0.5">Worker Error</p>
                <p className="text-xs text-red-600">{worker.error}</p>
              </div>
            )}
            {worker.findings.length === 0 && !worker.error && (
              <p className="text-xs text-gray-400 py-1">No findings for this worker.</p>
            )}
            <div className="space-y-2">
              {worker.findings.map((finding, idx) => (
                <FindingRow key={idx} finding={finding} />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function Workers() {
  const [tenantId, setTenantId] = useState('acme-corp')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [memo, setMemo] = useState<InsightsMemo | null>(null)
  const [expandedWorker, setExpandedWorker] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  async function handleLoad() {
    if (!tenantId.trim()) return
    setLoading(true)
    setError(null)
    setMemo(null)
    setExpandedWorker(null)
    setSearch('')
    try {
      const result = await api.getInsights(tenantId.trim())
      setMemo(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workers')
    } finally {
      setLoading(false)
    }
  }

  function toggleWorker(workerName: string) {
    setExpandedWorker((prev) => (prev === workerName ? null : workerName))
  }

  const filteredWorkers = memo
    ? memo.structured.workers.filter((w) =>
        w.worker.toLowerCase().includes(search.toLowerCase())
      )
    : []

  const totalFindings = filteredWorkers.reduce((sum, w) => sum + w.findings.length, 0)
  const criticalCount = filteredWorkers.reduce(
    (sum, w) => sum + countBySeverity(w.findings, 'CRITICAL'),
    0
  )

  const allWorkers = memo ? memo.structured.workers : []
  const highestSevOverall = allWorkers.length > 0
    ? getHighestSeverity(allWorkers.flatMap((w) => w.findings))
    : null

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Cpu size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Workers</h1>
        </div>
        <p className="text-gray-500">Browse and explore all intelligence worker findings.</p>
      </div>

      {/* Load Panel */}
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
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-900 focus:border-transparent"
            />
          </div>
          <div className="pt-5">
            <button
              onClick={handleLoad}
              disabled={loading || !tenantId.trim()}
              className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              {loading && <Loader2 size={15} className="animate-spin" />}
              Load Workers
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-700">Failed to load workers</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={28} className="animate-spin text-gray-400" />
        </div>
      )}

      {/* Workers Table */}
      {memo && !loading && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          {/* Summary Bar */}
          <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between bg-gray-50">
            <div className="flex items-center gap-4 text-sm text-gray-600">
              <span>
                <strong>{allWorkers.length}</strong> workers
              </span>
              <span>
                <strong>{totalFindings}</strong> findings
              </span>
              {criticalCount > 0 && (
                <span className="text-red-600 font-semibold">
                  {criticalCount} critical
                </span>
              )}
              {highestSevOverall && (
                <SeverityBadge severity={highestSevOverall} />
              )}
            </div>
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter workers…"
                className="pl-8 pr-3 py-1.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-900"
              />
            </div>
          </div>

          {/* Table */}
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-left">Worker Name</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-center">Findings</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-red-500 text-center">Critical</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-orange-500 text-center">High</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredWorkers.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">
                    No workers match your search.
                  </td>
                </tr>
              )}
              {filteredWorkers.map((worker) => (
                <WorkerRow
                  key={worker.worker}
                  worker={worker}
                  expanded={expandedWorker === worker.worker}
                  onToggle={() => toggleWorker(worker.worker)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Prompt when nothing loaded */}
      {!memo && !loading && !error && (
        <div className="text-center py-16 text-gray-400">
          <Cpu size={40} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Enter a tenant ID above and click <strong>Load Workers</strong> to browse findings.</p>
        </div>
      )}
    </div>
  )
}
