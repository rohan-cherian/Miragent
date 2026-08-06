import { useState, useEffect, useCallback } from 'react'
import {
  Truck, Search, Loader2, AlertCircle, CheckCircle2, AlertTriangle,
  RotateCcw, Plus, Building2, ClipboardList,
  MessageSquare, Clock, User,
} from 'lucide-react'
import { api } from '../api/client'
import type { VendorOnboardingRecord } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function getToken(): string {
  return localStorage.getItem('scout_token') || ''
}

function getTenant(): string {
  return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT
}

type Stage = VendorOnboardingRecord['stage']

const STAGE_LABELS: Record<Stage, string> = {
  initiated:         'Initiated',
  w9_requested:      'W9 Requested',
  w9_received:       'W9 Received',
  banking_requested: 'Banking Requested',
  banking_received:  'Banking Received',
  erp_setup:         'ERP Setup',
  active:            'Active',
  on_hold:           'On Hold',
}

const PIPELINE_STAGES: Stage[] = [
  'initiated',
  'w9_requested',
  'w9_received',
  'banking_requested',
  'banking_received',
  'erp_setup',
  'active',
]

function stageBadgeClass(stage: Stage): string {
  switch (stage) {
    case 'active':            return 'bg-green-100 text-green-800 border-green-200'
    case 'erp_setup':         return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'banking_received':
    case 'banking_requested': return 'bg-teal-100 text-teal-800 border-teal-200'
    case 'w9_received':
    case 'w9_requested':      return 'bg-yellow-100 text-yellow-800 border-yellow-200'
    case 'initiated':         return 'bg-gray-100 text-gray-700 border-gray-200'
    case 'on_hold':           return 'bg-red-100 text-red-800 border-red-200'
  }
}

function stageDotColor(stage: Stage): string {
  switch (stage) {
    case 'active':            return 'bg-green-500'
    case 'erp_setup':         return 'bg-blue-500'
    case 'banking_received':
    case 'banking_requested': return 'bg-teal-500'
    case 'w9_received':
    case 'w9_requested':      return 'bg-yellow-500'
    case 'initiated':         return 'bg-gray-400'
    case 'on_hold':           return 'bg-red-500'
  }
}

const ENTITY_TYPES = [
  'Sole Proprietor',
  'LLC',
  'S-Corp',
  'C-Corp',
  'Corporation',
  'Foreign Entity',
]

// ── Stage Progress Stepper ────────────────────────────────────────────────────

function StageStepper({ currentStage }: { currentStage: Stage }) {
  const pipelineOnly: Stage[] = [
    'initiated', 'w9_requested', 'w9_received',
    'banking_requested', 'banking_received', 'erp_setup', 'active',
  ]
  const currentIdx = pipelineOnly.indexOf(currentStage)

  return (
    <div className="mt-3 mb-1">
      <div className="flex items-center gap-0.5 overflow-x-auto pb-1">
        {pipelineOnly.map((stage, i) => {
          const isActive = stage === currentStage
          const isDone = currentIdx > i && currentStage !== 'on_hold'
          const isOnHold = currentStage === 'on_hold'
          return (
            <div key={stage} className="flex items-center flex-1 min-w-0">
              <div className="flex flex-col items-center flex-1 min-w-0">
                <div
                  className={[
                    'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0',
                    isActive && !isOnHold
                      ? 'bg-indigo-600 text-white ring-2 ring-indigo-300'
                      : isDone
                        ? 'bg-green-500 text-white'
                        : isOnHold && i <= currentIdx
                          ? 'bg-red-500 text-white'
                          : 'bg-gray-100 text-gray-400',
                  ].join(' ')}
                >
                  {isDone ? <CheckCircle2 size={13} /> : i + 1}
                </div>
                <span className={[
                  'text-center mt-0.5 leading-tight',
                  'text-[9px]',
                  isActive ? 'text-indigo-700 font-semibold' : isDone ? 'text-green-600' : 'text-gray-400',
                ].join(' ')}
                  style={{ maxWidth: 48 }}
                >
                  {STAGE_LABELS[stage].split(' ').join('\n')}
                </span>
              </div>
              {i < pipelineOnly.length - 1 && (
                <div className={[
                  'h-0.5 flex-1 mx-0.5 rounded',
                  isDone ? 'bg-green-400' : 'bg-gray-200',
                ].join(' ')} />
              )}
            </div>
          )
        })}
      </div>
      {currentStage === 'on_hold' && (
        <div className="mt-2 text-xs text-red-600 font-medium flex items-center gap-1">
          <AlertTriangle size={12} /> Onboarding is on hold — see below for details
        </div>
      )}
    </div>
  )
}

// ── Vendor Status Card ────────────────────────────────────────────────────────

function VendorStatusCard({ record, onReset }: {
  record: VendorOnboardingRecord
  onReset: () => void
}) {
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        {/* Color accent bar */}
        <div className={`h-1.5 ${
          record.stage === 'active' ? 'bg-green-500' :
          record.stage === 'erp_setup' ? 'bg-blue-500' :
          record.stage === 'on_hold' ? 'bg-red-500' :
          record.stage.startsWith('banking') ? 'bg-teal-500' :
          record.stage.startsWith('w9') ? 'bg-yellow-400' :
          'bg-gray-300'
        }`} />

        <div className="p-5 space-y-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-base font-bold text-gray-900">{record.vendor_name}</div>
              <div className="text-xs text-gray-500 mt-0.5">{record.vendor_email}</div>
              {record.entity_type && record.entity_type !== 'unknown' && (
                <span className="inline-block mt-1 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">
                  {record.entity_type}
                </span>
              )}
            </div>
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border flex-shrink-0 ${stageBadgeClass(record.stage)}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${stageDotColor(record.stage)}`} />
              {STAGE_LABELS[record.stage]}
            </span>
          </div>

          {/* Progress stepper */}
          <StageStepper currentStage={record.stage} />

          {/* Hold reason callout */}
          {record.stage === 'on_hold' && record.hold_reason && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              <AlertTriangle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-xs font-semibold text-red-700 mb-0.5">Hold Reason</p>
                <p className="text-xs text-red-700">{record.hold_reason}</p>
              </div>
            </div>
          )}

          {/* Confirmation message */}
          <div className="bg-indigo-50 border border-indigo-100 rounded-lg px-4 py-3">
            <div className="flex items-center gap-1.5 mb-1.5">
              <MessageSquare size={12} className="text-indigo-400" />
              <span className="text-xs font-semibold text-indigo-600 uppercase tracking-wide">Vendor Message</span>
            </div>
            <p className="text-sm text-indigo-900 leading-relaxed">{record.confirmation_message}</p>
          </div>

          {/* Checklist */}
          {record.checklist.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-2">
                <ClipboardList size={13} className="text-gray-400" />
                <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Remaining Steps</span>
              </div>
              <ul className="space-y-1.5">
                {record.checklist.map((item, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <div className="w-4 h-4 mt-0.5 rounded border-2 border-gray-300 flex-shrink-0" />
                    <span className="text-sm text-gray-700">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {record.checklist.length === 0 && record.stage === 'active' && (
            <div className="flex items-center gap-2 text-green-700">
              <CheckCircle2 size={15} className="text-green-500" />
              <span className="text-sm font-medium">Fully onboarded — no outstanding items</span>
            </div>
          )}

          {/* Key facts row */}
          <div className="grid grid-cols-2 gap-3">
            {record.ein && (
              <div className="bg-gray-50 rounded-lg px-3 py-2">
                <div className="text-xs text-gray-400 mb-0.5">EIN</div>
                <div className="text-sm font-semibold text-gray-800">{record.ein}</div>
              </div>
            )}
            {record.bank_info && record.bank_info !== 'pending' && (
              <div className="bg-gray-50 rounded-lg px-3 py-2">
                <div className="text-xs text-gray-400 mb-0.5">Bank</div>
                <div className="text-sm font-semibold text-gray-800">{record.bank_info}</div>
              </div>
            )}
            <div className="bg-gray-50 rounded-lg px-3 py-2">
              <div className="text-xs text-gray-400 mb-0.5">Days in Process</div>
              <div className="text-sm font-semibold text-gray-800">{record.days_in_process}d</div>
            </div>
            {record.submitted_date && (
              <div className="bg-gray-50 rounded-lg px-3 py-2">
                <div className="text-xs text-gray-400 mb-0.5">Submitted</div>
                <div className="text-sm font-semibold text-gray-800">{record.submitted_date}</div>
              </div>
            )}
          </div>

          {/* Internal contact */}
          <div className="flex items-start gap-2 pt-1">
            <User size={13} className="text-gray-400 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-gray-400">
              <span className="font-medium text-gray-500">Internal contact: </span>
              {record.internal_contact}
            </p>
          </div>

          <button
            onClick={onReset}
            className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
          >
            Look up another vendor
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Left Panel — Status Lookup + New Onboarding ───────────────────────────────

function StatusLookupPanel() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<VendorOnboardingRecord | null>(null)

  // New onboarding form
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formEmail, setFormEmail] = useState('')
  const [formEntity, setFormEntity] = useState('')
  const [formLoading, setFormLoading] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  async function handleLookup() {
    if (!email.trim()) { setError('Please enter a vendor email.'); return }
    setError(null); setResult(null); setLoading(true)
    try {
      const token = getToken()
      const tenant = getTenant()
      const r = await api.vendorOnboarding.status(email.trim(), tenant, token)
      setResult(r)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Lookup failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleInitiate() {
    if (!formName.trim()) { setFormError('Vendor name is required.'); return }
    if (!formEmail.trim()) { setFormError('Vendor email is required.'); return }
    if (!formEntity) { setFormError('Entity type is required.'); return }
    setFormError(null); setFormLoading(true)
    try {
      const token = getToken()
      const tenant = getTenant()
      const r = await api.vendorOnboarding.initiate(formName.trim(), formEmail.trim(), formEntity, tenant, token)
      setResult(r)
      setShowForm(false)
      setFormName(''); setFormEmail(''); setFormEntity('')
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Initiation failed')
    } finally {
      setFormLoading(false)
    }
  }

  function handleReset() {
    setResult(null); setError(null); setEmail('')
  }

  return (
    <div className="space-y-5">
      {/* Status lookup */}
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
          Vendor Email
        </label>
        <div className="flex gap-2">
          <input
            type="email"
            value={email}
            onChange={e => { setEmail(e.target.value); setResult(null); setError(null) }}
            onKeyDown={e => e.key === 'Enter' && handleLookup()}
            placeholder="ap@apexfinancial.com"
            className="flex-1 px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <button
            onClick={handleLookup}
            disabled={loading}
            className="flex items-center gap-1.5 px-4 py-2.5 text-sm font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            Check
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Result */}
      {result && <VendorStatusCard record={result} onReset={handleReset} />}

      {/* Empty state + new onboarding toggle */}
      {!result && !loading && !error && (
        <div className="flex flex-col items-center justify-center py-6 text-center px-4">
          <Truck size={36} className="text-gray-300 mb-3" />
          <p className="text-gray-500 font-medium">Look up a vendor's onboarding status</p>
          <p className="text-gray-400 text-sm mt-1">
            Enter the vendor email above to check their current stage.
          </p>
        </div>
      )}

      {/* Divider */}
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-gray-200" />
        </div>
        <div className="relative flex justify-center text-xs">
          <span className="bg-white px-3 text-gray-400">or</span>
        </div>
      </div>

      {/* New onboarding button */}
      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold border border-dashed border-gray-300 text-gray-600 rounded-lg hover:border-indigo-400 hover:text-indigo-600 transition-colors"
        >
          <Plus size={15} />
          Start New Vendor Onboarding
        </button>
      ) : (
        <div className="bg-gray-50 rounded-xl border border-gray-200 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-gray-800">New Vendor Onboarding</span>
            <button
              onClick={() => { setShowForm(false); setFormError(null) }}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Cancel
            </button>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
              Vendor Name
            </label>
            <input
              type="text"
              value={formName}
              onChange={e => setFormName(e.target.value)}
              placeholder="Acme Software Inc."
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
              Vendor Email
            </label>
            <input
              type="email"
              value={formEmail}
              onChange={e => setFormEmail(e.target.value)}
              placeholder="ap@vendor.com"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1 uppercase tracking-wide">
              Entity Type
            </label>
            <select
              value={formEntity}
              onChange={e => setFormEntity(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
            >
              <option value="">Select entity type...</option>
              {ENTITY_TYPES.map(et => (
                <option key={et} value={et}>{et}</option>
              ))}
            </select>
          </div>

          {formError && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <AlertCircle size={13} className="text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-red-700">{formError}</p>
            </div>
          )}

          <button
            onClick={handleInitiate}
            disabled={formLoading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {formLoading
              ? <><Loader2 size={14} className="animate-spin" /> Initiating…</>
              : <><Plus size={14} /> Initiate Onboarding</>}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Right Panel — Pipeline Dashboard ─────────────────────────────────────────

function StageBadge({ stage }: { stage: Stage }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-semibold border ${stageBadgeClass(stage)}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${stageDotColor(stage)}`} />
      {STAGE_LABELS[stage]}
    </span>
  )
}

function VendorRow({ record }: { record: VendorOnboardingRecord }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-gray-100 last:border-0">
      <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Building2 size={14} className="text-gray-500" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-gray-900 truncate">{record.vendor_name}</span>
          <StageBadge stage={record.stage} />
        </div>
        <div className="flex items-center gap-3 mt-0.5 flex-wrap">
          <span className="text-xs text-gray-400 flex items-center gap-1">
            <Clock size={11} />
            {record.days_in_process}d in process
          </span>
          <span className="text-xs text-gray-400 truncate">{record.internal_contact.split(' — ')[0]}</span>
          {record.is_stalled && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-semibold bg-orange-100 text-orange-700 border border-orange-200">
              <AlertTriangle size={10} />
              Stalled
            </span>
          )}
        </div>
        {record.hold_reason && (
          <p className="text-xs text-red-600 mt-1">{record.hold_reason}</p>
        )}
      </div>
    </div>
  )
}

function PipelineDashboard() {
  const [inProgress, setInProgress] = useState<VendorOnboardingRecord[]>([])
  const [blocked, setBlocked] = useState<VendorOnboardingRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const token = getToken()
      const tenant = getTenant()
      const [prog, blk] = await Promise.all([
        api.vendorOnboarding.inProgress(tenant, token),
        api.vendorOnboarding.blocked(tenant, token),
      ])
      setInProgress(prog)
      setBlocked(blk)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load pipeline')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Stage summary counts
  const stageCounts: Partial<Record<Stage, number>> = {}
  for (const v of inProgress) {
    stageCounts[v.stage] = (stageCounts[v.stage] ?? 0) + 1
  }
  // Also count active (not in in-progress list, but for the stat row)
  // blocked vendors that are stalled (not on_hold) are still in in-progress pipeline stage
  const blockedStalled = blocked.filter(b => b.stage !== 'on_hold')

  // Group in-progress by stage for display
  const byStage: Partial<Record<Stage, VendorOnboardingRecord[]>> = {}
  for (const v of inProgress) {
    if (!blockedStalled.find(b => b.vendor_id === v.vendor_id)) {
      // Not stalled, show in "In Progress" section
      if (!byStage[v.stage]) byStage[v.stage] = []
      byStage[v.stage]!.push(v)
    }
  }

  return (
    <div className="space-y-5">
      {/* Summary stat row */}
      <div className="grid grid-cols-5 gap-2">
        {[
          { label: 'Initiated', count: stageCounts['initiated'] ?? 0 },
          { label: 'W9 Stage', count: (stageCounts['w9_requested'] ?? 0) + (stageCounts['w9_received'] ?? 0) },
          { label: 'Banking', count: (stageCounts['banking_requested'] ?? 0) + (stageCounts['banking_received'] ?? 0) },
          { label: 'ERP Setup', count: stageCounts['erp_setup'] ?? 0 },
          { label: 'Blocked', count: blocked.length, isAlert: true },
        ].map(item => (
          <div
            key={item.label}
            className={[
              'rounded-lg px-2 py-2 text-center',
              item.isAlert && item.count > 0
                ? 'bg-red-50 border border-red-200'
                : 'bg-gray-50 border border-gray-100',
            ].join(' ')}
          >
            <div className={`text-lg font-bold ${item.isAlert && item.count > 0 ? 'text-red-700' : 'text-gray-900'}`}>
              {item.count}
            </div>
            <div className={`text-xs ${item.isAlert && item.count > 0 ? 'text-red-500' : 'text-gray-400'}`}>
              {item.label}
            </div>
          </div>
        ))}
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 size={24} className="animate-spin text-gray-300" />
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
          {/* Needs Attention section */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle size={14} className="text-red-500" />
              <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Needs Attention</span>
              {blocked.length > 0 && (
                <span className="px-1.5 py-0.5 text-xs bg-red-100 text-red-700 rounded-full font-semibold">
                  {blocked.length}
                </span>
              )}
            </div>
            {blocked.length === 0 ? (
              <div className="flex items-center gap-2 py-4 text-gray-400">
                <CheckCircle2 size={15} className="text-green-400" />
                <span className="text-sm">No blocked or stalled vendors</span>
              </div>
            ) : (
              <div className="bg-red-50 border border-red-100 rounded-xl px-4 divide-y divide-red-100">
                {blocked.map(record => (
                  <VendorRow key={record.vendor_id} record={record} />
                ))}
              </div>
            )}
          </div>

          {/* In Progress section */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Truck size={14} className="text-indigo-500" />
              <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">In Progress</span>
              <span className="px-1.5 py-0.5 text-xs bg-indigo-100 text-indigo-700 rounded-full font-semibold">
                {inProgress.length}
              </span>
            </div>

            {PIPELINE_STAGES.filter(s => s !== 'active').map(stage => {
              const vendors = byStage[stage]
              if (!vendors || vendors.length === 0) return null
              return (
                <div key={stage} className="mb-3">
                  <div className="flex items-center gap-1.5 mb-1.5 px-1">
                    <StageBadge stage={stage} />
                    <span className="text-xs text-gray-400">({vendors.length})</span>
                  </div>
                  <div className="bg-white border border-gray-100 rounded-xl px-4 divide-y divide-gray-50">
                    {vendors.map(record => (
                      <VendorRow key={record.vendor_id} record={record} />
                    ))}
                  </div>
                </div>
              )
            })}

            {inProgress.length === 0 && (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <Truck size={28} className="text-gray-200 mb-2" />
                <p className="text-gray-400 text-sm">No vendors currently in progress</p>
              </div>
            )}
          </div>
        </>
      )}

      <button
        onClick={load}
        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
      >
        <RotateCcw size={11} />
        Refresh
      </button>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function VendorOnboarding() {
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
              <Truck size={18} className="text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Vendor Onboarding</h1>
          </div>
          <p className="text-gray-500 text-sm ml-12">
            Track W9 collection, banking info, and ERP setup for new payment vendors.
          </p>
        </div>

        {/* Two-panel layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left panel — Status Lookup */}
          <div>
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-5">
                <Search size={15} className="text-gray-400" />
                <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Vendor Status Lookup</span>
              </div>
              <StatusLookupPanel />
            </div>
          </div>

          {/* Right panel — Pipeline Dashboard */}
          <div>
            <div className="bg-gray-50 rounded-2xl border border-gray-200 p-6">
              <div className="flex items-center gap-2 mb-5">
                <Truck size={15} className="text-gray-400" />
                <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Vendor Onboarding Pipeline</span>
              </div>
              <PipelineDashboard />
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
