import { useState } from 'react'
import { Brain, ChevronDown, ChevronRight, AlertCircle, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import type { InsightsMemo, WorkerResult, Finding } from '../types'

type Severity = Finding['severity']

const severityConfig: Record<Severity, { label: string; classes: string }> = {
  CRITICAL: { label: 'CRITICAL', classes: 'bg-red-100 text-red-700 border border-red-200' },
  HIGH: { label: 'HIGH', classes: 'bg-orange-100 text-orange-700 border border-orange-200' },
  MEDIUM: { label: 'MEDIUM', classes: 'bg-yellow-100 text-yellow-700 border border-yellow-200' },
  LOW: { label: 'LOW', classes: 'bg-blue-100 text-blue-700 border border-blue-200' },
  INFO: { label: 'INFO', classes: 'bg-gray-100 text-gray-600 border border-gray-200' }
}

const severityOrder: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

function SeverityBadge({ severity }: { severity: Severity }) {
  const cfg = severityConfig[severity]
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg.classes}`}>
      {cfg.label}
    </span>
  )
}

function getHighestSeverity(findings: Finding[]): Severity | null {
  for (const sev of severityOrder) {
    if (findings.some((f) => f.severity?.toUpperCase() === sev)) return sev
  }
  return null
}

function FindingCard({ finding }: { finding: Finding }) {
  const severity = (finding.severity?.toUpperCase() ?? 'INFO') as Severity
  return (
    <div className="bg-gray-50 rounded-lg p-4 border border-gray-100">
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="text-sm font-semibold text-gray-800">{finding.title}</p>
        <SeverityBadge severity={severity} />
      </div>
      <p className="text-xs text-gray-600 leading-relaxed">{finding.detail}</p>
      {finding.recommended_action && (
        <div className="mt-3 p-2.5 bg-blue-50 rounded border border-blue-100">
          <p className="text-xs font-medium text-blue-700 mb-0.5">Recommended Action</p>
          <p className="text-xs text-blue-600">{finding.recommended_action}</p>
        </div>
      )}
    </div>
  )
}

function WorkerCard({ worker, expanded, onToggle }: {
  worker: WorkerResult
  expanded: boolean
  onToggle: () => void
}) {
  const highestSev = getHighestSeverity(worker.findings)

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between p-4 hover:bg-gray-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex-shrink-0">
            {expanded ? (
              <ChevronDown size={16} className="text-gray-400" />
            ) : (
              <ChevronRight size={16} className="text-gray-400" />
            )}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-800 truncate">{worker.worker}</p>
            {worker.error && (
              <p className="text-xs text-red-500 mt-0.5 truncate">{worker.error}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0 ml-3">
          <span className="text-xs text-gray-400">{worker.findings.length} findings</span>
          {highestSev && <SeverityBadge severity={highestSev} />}
          {worker.error && !highestSev && (
            <AlertCircle size={14} className="text-red-400" />
          )}
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-50 pt-3">
          {worker.findings.length === 0 && !worker.error && (
            <p className="text-xs text-gray-400 py-2">No findings for this worker.</p>
          )}
          {worker.findings.map((finding, idx) => (
            <FindingCard key={idx} finding={finding} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function Insights() {
  const [tenantId, setTenantId] = useState('acme-corp')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [memo, setMemo] = useState<InsightsMemo | null>(null)
  const [expandedWorker, setExpandedWorker] = useState<string | null>(null)

  async function handleGenerate() {
    if (!tenantId.trim()) return
    setLoading(true)
    setError(null)
    setMemo(null)
    setExpandedWorker(null)
    try {
      const result = await api.getInsights(tenantId.trim())
      setMemo(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch insights')
    } finally {
      setLoading(false)
    }
  }

  function toggleWorker(workerName: string) {
    setExpandedWorker((prev) => (prev === workerName ? null : workerName))
  }

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Brain size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Insights</h1>
        </div>
        <p className="text-gray-500">Generate AI-powered executive memos from your CRM data.</p>
      </div>

      {/* Input Bar */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 mb-6">
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-500 mb-1">Tenant ID</label>
            <input
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
              placeholder="e.g. acme-corp"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-900 focus:border-transparent"
            />
          </div>
          <div className="pt-5">
            <button
              onClick={handleGenerate}
              disabled={loading || !tenantId.trim()}
              className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              {loading && <Loader2 size={15} className="animate-spin" />}
              Generate Insights
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-700">Failed to generate insights</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Loader2 size={32} className="animate-spin mx-auto mb-3 text-gray-400" />
            <p className="text-sm text-gray-500">Generating insights for <strong>{tenantId}</strong>…</p>
          </div>
        </div>
      )}

      {/* Results */}
      {memo && !loading && (
        <div className="space-y-6">
          {/* Narrative */}
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Executive Memo</h2>
            <pre className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed font-sans">
              {memo.narrative}
            </pre>
          </div>

          {/* Workers */}
          {memo.structured.workers.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900">Worker Findings</h2>
                <span className="text-sm text-gray-400">
                  {memo.structured.workers.length} workers ·{' '}
                  {memo.structured.workers.reduce((sum, w) => sum + w.findings.length, 0)} total findings
                </span>
              </div>
              <div className="grid grid-cols-1 gap-3">
                {memo.structured.workers.map((worker) => (
                  <WorkerCard
                    key={worker.worker}
                    worker={worker}
                    expanded={expandedWorker === worker.worker}
                    onToggle={() => toggleWorker(worker.worker)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
