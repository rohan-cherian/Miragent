import { useState, useEffect, useRef } from 'react'
import { RefreshCw, AlertCircle, CheckCircle, Loader2, Users, Building2, Landmark, TrendingUp } from 'lucide-react'
import { api } from '../api/client'
import type { ScanJob } from '../types'

function StatusBadge({ status }: { status: ScanJob['status'] }) {
  const config: Record<ScanJob['status'], { label: string; classes: string }> = {
    queued: { label: 'Queued', classes: 'bg-gray-100 text-gray-600 border border-gray-200' },
    running: { label: 'Running', classes: 'bg-blue-100 text-blue-700 border border-blue-200' },
    completed: { label: 'Completed', classes: 'bg-emerald-100 text-emerald-700 border border-emerald-200' },
    failed: { label: 'Failed', classes: 'bg-red-100 text-red-700 border border-red-200' }
  }
  const cfg = config[status]
  return (
    <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${cfg.classes}`}>
      {cfg.label}
    </span>
  )
}

interface ResultStatProps {
  icon: React.ReactNode
  label: string
  value: number | undefined
}

function ResultStat({ icon, label, value }: ResultStatProps) {
  return (
    <div className="bg-gray-50 rounded-lg p-4 flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-white border border-gray-100 flex items-center justify-center flex-shrink-0">
        {icon}
      </div>
      <div>
        <p className="text-xl font-bold text-gray-900">{value ?? '—'}</p>
        <p className="text-xs text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  )
}

export default function Scans() {
  const [tenantId, setTenantId] = useState('acme-corp')
  const [scanning, setScanning] = useState(false)
  const [scanId, setScanId] = useState<string | null>(null)
  const [scanStatus, setScanStatus] = useState<ScanJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function clearPoller() {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }

  useEffect(() => {
    return () => clearPoller()
  }, [])

  async function handleRunScan() {
    if (!tenantId.trim()) return
    setScanning(true)
    setError(null)
    setScanStatus(null)
    setScanId(null)
    clearPoller()

    let createdScanId: string
    try {
      const res = await api.createScan(tenantId.trim())
      createdScanId = res.scan_id
      setScanId(createdScanId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create scan')
      setScanning(false)
      return
    }

    intervalRef.current = setInterval(async () => {
      try {
        const job = await api.getScan(createdScanId)
        setScanStatus(job)
        if (job.status === 'completed' || job.status === 'failed') {
          clearPoller()
          setScanning(false)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to poll scan status')
        clearPoller()
        setScanning(false)
      }
    }, 1000)
  }

  const isCompleted = scanStatus?.status === 'completed'
  const isFailed = scanStatus?.status === 'failed'

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <RefreshCw size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Scans</h1>
        </div>
        <p className="text-gray-500">Run a CRM data ingestion and deduplication scan.</p>
      </div>

      {/* Input Card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 mb-6">
        <h2 className="text-base font-semibold text-gray-800 mb-4">New Scan</h2>
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-500 mb-1">Tenant ID</label>
            <input
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !scanning && handleRunScan()}
              placeholder="e.g. acme-corp"
              disabled={scanning}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-900 focus:border-transparent disabled:bg-gray-50 disabled:text-gray-400"
            />
          </div>
          <div className="pt-5">
            <button
              onClick={handleRunScan}
              disabled={scanning || !tenantId.trim()}
              className="flex items-center gap-2 px-5 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              {scanning && <Loader2 size={15} className="animate-spin" />}
              {scanning ? 'Scanning…' : 'Run Scan'}
            </button>
          </div>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-700">Scan error</p>
            <p className="text-xs text-red-600 mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* Scan in Progress */}
      {scanning && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 mb-6">
          <div className="flex items-center gap-3 mb-4">
            <Loader2 size={20} className="animate-spin text-blue-500" />
            <div>
              <p className="text-sm font-semibold text-gray-800">Scan in progress…</p>
              {scanId && (
                <p className="text-xs text-gray-400 mt-0.5">Scan ID: <code className="bg-gray-100 px-1 rounded">{scanId}</code></p>
              )}
            </div>
          </div>
          {scanStatus && (
            <div className="flex items-center gap-2 mt-2">
              <StatusBadge status={scanStatus.status} />
              <span className="text-xs text-gray-400">Polling every 1s…</span>
            </div>
          )}
        </div>
      )}

      {/* Completed Result */}
      {isCompleted && scanStatus && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <div className="flex items-center gap-2 mb-5">
            <CheckCircle size={18} className="text-emerald-500" />
            <h2 className="text-base font-semibold text-gray-800">Scan Completed</h2>
            <StatusBadge status="completed" />
          </div>
          <p className="text-xs text-gray-400 mb-4">
            Scan ID: <code className="bg-gray-100 px-1 rounded">{scanStatus.scan_id}</code> ·
            Tenant: <strong>{scanStatus.tenant_id}</strong>
          </p>
          <div className="grid grid-cols-2 gap-3">
            <ResultStat
              icon={<Users size={16} className="text-blue-500" />}
              label="Persons Merged"
              value={scanStatus.result?.persons_merged}
            />
            <ResultStat
              icon={<Building2 size={16} className="text-purple-500" />}
              label="Vendors Merged"
              value={scanStatus.result?.vendors_merged}
            />
            <ResultStat
              icon={<Landmark size={16} className="text-emerald-500" />}
              label="Accounts Merged"
              value={scanStatus.result?.accounts_merged}
            />
            <ResultStat
              icon={<TrendingUp size={16} className="text-amber-500" />}
              label="Opportunities Merged"
              value={scanStatus.result?.opportunities_merged}
            />
          </div>
        </div>
      )}

      {/* Failed Result */}
      {isFailed && scanStatus && (
        <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-5">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <div className="flex items-center gap-2 mb-1">
              <p className="text-sm font-semibold text-red-700">Scan Failed</p>
              <StatusBadge status="failed" />
            </div>
            <p className="text-xs text-red-500">
              Scan <code className="bg-red-100 px-1 rounded">{scanStatus.scan_id}</code> did not complete successfully.
              Please check the backend logs and try again.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
