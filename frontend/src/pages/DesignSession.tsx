import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CheckCircle2,
  Circle,
  AlertTriangle,
  ChevronRight,
  Wand2,
  Zap,
  Clock,
  TrendingUp,
  ArrowRight,
} from 'lucide-react'
import { api } from '../api/client'
import type { DesignSession, DesignBlueprint } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Step definitions ───────────────────────────────────────────────────────────

const WIZARD_STEPS = [
  { key: 'connect', label: 'Connect' },
  { key: 'discover', label: 'Discover' },
  { key: 'review', label: 'Review' },
  { key: 'configure', label: 'Configure' },
  { key: 'golive', label: 'Go Live' },
]

// ── Progress bar ───────────────────────────────────────────────────────────────

function WizardProgressBar({ currentStep }: { currentStep: string }) {
  const currentIndex = WIZARD_STEPS.findIndex((s) => s.key === currentStep)

  return (
    <div className="fixed top-0 left-60 right-0 z-40 bg-white border-b border-gray-200 shadow-sm">
      <div className="max-w-5xl mx-auto px-8 py-4">
        <div className="flex items-center justify-between">
          {WIZARD_STEPS.map((step, i) => {
            const isCompleted = i < currentIndex
            const isCurrent = i === currentIndex
            const isFuture = i > currentIndex

            return (
              <div key={step.key} className="flex items-center flex-1">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold border-2 transition-all ${
                      isCompleted
                        ? 'bg-emerald-500 border-emerald-500 text-white'
                        : isCurrent
                        ? 'border-[#1B2A4A] text-[#1B2A4A] bg-white'
                        : 'border-gray-300 text-gray-400 bg-white'
                    }`}
                  >
                    {isCompleted ? <CheckCircle2 size={16} /> : i + 1}
                  </div>
                  <span
                    className={`mt-1.5 text-xs font-medium whitespace-nowrap ${
                      isCurrent
                        ? 'text-[#1B2A4A]'
                        : isCompleted
                        ? 'text-emerald-600'
                        : isFuture
                        ? 'text-gray-400'
                        : 'text-gray-400'
                    }`}
                  >
                    {step.label}
                  </span>
                </div>
                {i < WIZARD_STEPS.length - 1 && (
                  <div
                    className={`flex-1 h-0.5 mx-3 mt-[-18px] transition-all ${
                      i < currentIndex ? 'bg-emerald-400' : 'bg-gray-200'
                    }`}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Automation potential bar ───────────────────────────────────────────────────

function AutomationBar({ pct }: { pct: number }) {
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-yellow-400' : 'bg-orange-400'
  const textColor = pct >= 80 ? 'text-emerald-700' : pct >= 60 ? 'text-yellow-700' : 'text-orange-700'
  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-500">Automation potential</span>
        <span className={`text-xs font-bold ${textColor}`}>{pct}%</span>
      </div>
      <div className="w-full bg-gray-100 rounded-full h-2">
        <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ── Step 1 — Connect ───────────────────────────────────────────────────────────

function StepConnect({
  session,
  onNext,
}: {
  session: DesignSession
  onNext: () => void
}) {
  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Your Connected Systems</h1>
        <p className="text-gray-500 mt-2">
          Miragent found the following systems in your environment. Connected systems are ready
          for analysis.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-8">
        {session.connected_systems.map((sys) => {
          const isConnected = sys.status === 'connected'
          return (
            <div
              key={sys.name}
              className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 flex items-center gap-4"
            >
              <div
                className={`w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 ${
                  isConnected ? 'bg-emerald-50' : 'bg-gray-50'
                }`}
              >
                <div
                  className={`w-3 h-3 rounded-full ${
                    isConnected ? 'bg-emerald-400' : 'bg-gray-300'
                  }`}
                />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold text-gray-900 text-sm truncate">{sys.name}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${
                      isConnected
                        ? 'bg-emerald-100 text-emerald-700'
                        : 'bg-gray-100 text-gray-600'
                    }`}
                  >
                    {isConnected ? 'Connected' : 'Available'}
                  </span>
                  {isConnected && sys.records > 0 && (
                    <span className="text-xs text-gray-500">
                      {sys.records.toLocaleString()} records
                    </span>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex justify-end">
        <button
          onClick={onNext}
          className="flex items-center gap-2 px-6 py-3 text-sm font-semibold bg-[#1B2A4A] hover:bg-[#243660] text-white rounded-xl transition-colors"
        >
          Continue to Discovery <ArrowRight size={16} />
        </button>
      </div>
    </div>
  )
}

// ── Step 2 — Discover ──────────────────────────────────────────────────────────

function StepDiscover({
  session,
  onNext,
}: {
  session: DesignSession
  onNext: () => void
}) {
  const s = session.scout_summary
  const totalRecords = session.connected_systems
    .filter((c) => c.status === 'connected')
    .reduce((sum, c) => sum + c.records, 0)

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">What Miragent Found</h1>
        <p className="text-gray-500 mt-2">
          Scout ran {s.workers_run} workers and analyzed {totalRecords.toLocaleString()} records
          in {s.scan_duration_seconds} seconds.
        </p>
      </div>

      {/* Metric chips */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: 'Total Findings', value: s.total_findings, accent: 'text-gray-900' },
          { label: 'Critical', value: s.critical, accent: 'text-red-600' },
          { label: 'High', value: s.high, accent: 'text-orange-600' },
          { label: 'Workers Run', value: s.workers_run, accent: 'text-blue-600' },
        ].map((m) => (
          <div
            key={m.label}
            className="bg-white rounded-xl border border-gray-200 shadow-sm px-4 py-3 text-center"
          >
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{m.label}</p>
            <p className={`text-2xl font-bold mt-1 ${m.accent}`}>{m.value}</p>
          </div>
        ))}
      </div>

      {/* Blueprint cards */}
      <div className="space-y-3 mb-8">
        {session.blueprints.map((bp) => (
          <div
            key={bp.id}
            className="bg-white rounded-xl border border-gray-200 shadow-sm p-5"
          >
            <div className="flex items-start justify-between gap-3 mb-3">
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-gray-900">{bp.name}</h3>
                <p className="text-sm text-gray-500 mt-0.5 leading-snug">{bp.description}</p>
              </div>
              <span className="flex-shrink-0 text-xs font-medium text-blue-600 bg-blue-50 px-2 py-1 rounded-md border border-blue-100">
                {bp.recommended_agent}
              </span>
            </div>

            <div className="mb-3">
              <AutomationBar pct={bp.automation_potential} />
            </div>

            <div className="flex items-center gap-4 flex-wrap">
              {bp.sla_gap && (
                <div className="flex items-center gap-1.5 bg-red-50 border border-red-100 rounded-lg px-2.5 py-1.5">
                  <AlertTriangle size={13} className="text-red-500 flex-shrink-0" />
                  <span className="text-xs text-red-700 font-medium">{bp.sla_gap}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5 text-xs text-gray-500">
                <Clock size={13} />
                <span>{bp.estimated_hours_saved_monthly}h saved/month</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-gray-500">
                <TrendingUp size={13} />
                <span>{bp.volume_per_month} requests/month</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex justify-end">
        <button
          onClick={onNext}
          className="flex items-center gap-2 px-6 py-3 text-sm font-semibold bg-[#1B2A4A] hover:bg-[#243660] text-white rounded-xl transition-colors"
        >
          Review Discoveries <ArrowRight size={16} />
        </button>
      </div>
    </div>
  )
}

// ── Step 3 — Review ────────────────────────────────────────────────────────────

function StepReview({
  session,
  onApprove,
  onSkip,
}: {
  session: DesignSession
  onApprove: (id: string) => void
  onSkip: (id: string) => void
}) {
  const blueprints = session.blueprints
  const pendingIndex = blueprints.findIndex((bp) => bp.status === 'pending_review')
  const current: DesignBlueprint | undefined = pendingIndex >= 0 ? blueprints[pendingIndex] : undefined
  const reviewedCount = blueprints.filter((bp) => bp.status !== 'pending_review').length

  const statusIcon = (status: string) => {
    if (status === 'approved') return <CheckCircle2 size={16} className="text-emerald-500 flex-shrink-0" />
    if (status === 'skipped') return <Circle size={16} className="text-gray-400 flex-shrink-0" />
    return <Circle size={16} className="text-gray-200 flex-shrink-0" />
  }

  if (!current) {
    return (
      <div className="max-w-3xl mx-auto text-center py-16">
        <CheckCircle2 size={48} className="text-emerald-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900 mb-2">All Blueprints Reviewed</h2>
        <p className="text-gray-500">
          {session.approved_count} approved, {blueprints.length - session.approved_count} skipped.
          Continue to configure your approved agents.
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Review Discovered Processes</h1>
        <p className="text-gray-500 mt-1">
          Blueprint {reviewedCount + 1} of {blueprints.length}
        </p>
      </div>

      <div className="flex gap-6">
        {/* Main blueprint card */}
        <div className="flex-1">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 mb-4">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h2 className="text-xl font-bold text-gray-900">{current.name}</h2>
                <p className="text-gray-500 mt-1 leading-snug">{current.description}</p>
              </div>
              <span className="flex-shrink-0 text-xs font-medium text-blue-600 bg-blue-50 px-2.5 py-1.5 rounded-md border border-blue-100">
                {current.recommended_agent}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-4">
              <div className="bg-gray-50 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-0.5">Volume / month</p>
                <p className="text-lg font-bold text-gray-900">{current.volume_per_month}</p>
              </div>
              <div className="bg-gray-50 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-0.5">Hours saved / month</p>
                <p className="text-lg font-bold text-emerald-700">{current.estimated_hours_saved_monthly}h</p>
              </div>
            </div>

            <div className="mb-4">
              <AutomationBar pct={current.automation_potential} />
            </div>

            {current.sla_gap && (
              <div className="flex items-start gap-2 bg-red-50 border border-red-100 rounded-lg px-3 py-2.5 mb-4">
                <AlertTriangle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-700 font-medium">{current.sla_gap}</p>
              </div>
            )}
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => onApprove(current.id)}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl transition-colors"
            >
              <CheckCircle2 size={16} /> Approve — Activate this agent
            </button>
            <button
              onClick={() => onSkip(current.id)}
              className="flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-xl transition-colors"
            >
              Skip for now
            </button>
          </div>
        </div>

        {/* Sidebar list */}
        <div className="w-52 flex-shrink-0">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">All Blueprints</p>
          <div className="space-y-2">
            {blueprints.map((bp) => (
              <div
                key={bp.id}
                className={`flex items-center gap-2.5 p-2.5 rounded-lg ${
                  bp.id === current.id ? 'bg-blue-50 border border-blue-100' : 'bg-white border border-gray-100'
                }`}
              >
                {statusIcon(bp.status)}
                <span
                  className={`text-xs font-medium truncate ${
                    bp.status === 'approved'
                      ? 'text-emerald-700'
                      : bp.status === 'skipped'
                      ? 'text-gray-400'
                      : bp.id === current.id
                      ? 'text-blue-700'
                      : 'text-gray-500'
                  }`}
                >
                  {bp.name}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Step 4 — Configure ─────────────────────────────────────────────────────────

const THRESHOLD_OPTIONS = ['Always require approval', '$0', '$1,000', '$5,000', '$10,000']

function StepConfigure({
  session,
  onSave,
}: {
  session: DesignSession
  onSave: (blueprintId: string, config: Record<string, unknown>) => void
}) {
  const approved = session.blueprints.filter((bp) => bp.status === 'approved')

  const [configs, setConfigs] = useState<Record<string, Record<string, unknown>>>(() => {
    const initial: Record<string, Record<string, unknown>> = {}
    approved.forEach((bp) => {
      initial[bp.id] = {
        approval_threshold: 'Always require approval',
        auto_execute_low_risk: false,
        notify_manager: true,
      }
    })
    return initial
  })

  const [saving, setSaving] = useState(false)

  const updateConfig = (bpId: string, key: string, value: unknown) => {
    setConfigs((prev) => ({
      ...prev,
      [bpId]: { ...prev[bpId], [key]: value },
    }))
  }

  const handleSave = async () => {
    setSaving(true)
    // Save configs one at a time; last one advances the step
    for (const bp of approved) {
      await onSave(bp.id, configs[bp.id] ?? {})
    }
    setSaving(false)
  }

  if (approved.length === 0) {
    return (
      <div className="max-w-3xl mx-auto text-center py-16">
        <Zap size={48} className="text-gray-300 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900 mb-2">No Approved Blueprints</h2>
        <p className="text-gray-500">Go back to Review and approve at least one blueprint to configure agents.</p>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Configure Approved Agents</h1>
        <p className="text-gray-500 mt-2">
          Set thresholds and controls for each agent before going live.
        </p>
      </div>

      <div className="space-y-5 mb-8">
        {approved.map((bp) => {
          const cfg = configs[bp.id] ?? {}
          return (
            <div key={bp.id} className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <span className="text-sm font-bold text-gray-900">{bp.name}</span>
                <span className="text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-100 font-medium">
                  {bp.recommended_agent}
                </span>
              </div>

              <div className="space-y-4">
                {/* Approval threshold */}
                <div className="flex items-center justify-between">
                  <label className="text-sm text-gray-700 font-medium">
                    Approval required for actions over
                  </label>
                  <select
                    value={cfg.approval_threshold as string}
                    onChange={(e) => updateConfig(bp.id, 'approval_threshold', e.target.value)}
                    className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 text-gray-800 bg-white focus:outline-none focus:ring-2 focus:ring-blue-300"
                  >
                    {THRESHOLD_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                </div>

                {/* Auto execute toggle */}
                <div className="flex items-center justify-between">
                  <label className="text-sm text-gray-700 font-medium">
                    Auto-execute low-risk actions
                  </label>
                  <button
                    onClick={() =>
                      updateConfig(bp.id, 'auto_execute_low_risk', !cfg.auto_execute_low_risk)
                    }
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      cfg.auto_execute_low_risk ? 'bg-emerald-500' : 'bg-gray-200'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        cfg.auto_execute_low_risk ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>

                {/* Notify manager toggle */}
                <div className="flex items-center justify-between">
                  <label className="text-sm text-gray-700 font-medium">
                    Notify manager on each action
                  </label>
                  <button
                    onClick={() =>
                      updateConfig(bp.id, 'notify_manager', !cfg.notify_manager)
                    }
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      cfg.notify_manager ? 'bg-emerald-500' : 'bg-gray-200'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                        cfg.notify_manager ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-6 py-3 text-sm font-semibold bg-[#1B2A4A] hover:bg-[#243660] text-white rounded-xl transition-colors disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save Configuration'} <ArrowRight size={16} />
        </button>
      </div>
    </div>
  )
}

// ── Step 5 — Go Live ───────────────────────────────────────────────────────────

function StepGoLive({
  session,
  onComplete,
  onStartOver,
}: {
  session: DesignSession
  onComplete: () => void
  onStartOver: () => void
}) {
  const navigate = useNavigate()
  const summary = session.go_live_summary
  const approved = session.blueprints.filter((bp) => bp.status === 'approved')
  const agentNames = approved.map((bp) => bp.recommended_agent).filter(Boolean)
  const bpNames = approved.map((bp) => bp.name)

  return (
    <div className="max-w-2xl mx-auto text-center">
      {/* Animated checkmark */}
      <div className="mb-8">
        <div className="w-20 h-20 rounded-full bg-emerald-100 flex items-center justify-center mx-auto mb-4 animate-[scale-in_0.5s_ease-out]">
          <CheckCircle2 size={44} className="text-emerald-500" />
        </div>
        <h1 className="text-3xl font-bold text-gray-900">Miragent is Ready</h1>
        <p className="text-gray-500 mt-2">Your agents are configured and ready to start working.</p>
      </div>

      {/* Summary card */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-7 mb-6 text-left">
        <div className="grid grid-cols-3 gap-4 mb-5">
          <div className="text-center">
            <p className="text-3xl font-bold text-[#1B2A4A]">
              {summary ? (summary.agents_activated as number) : session.approved_count}
            </p>
            <p className="text-sm text-gray-500 mt-0.5">agents activated</p>
          </div>
          <div className="text-center">
            <p className="text-3xl font-bold text-emerald-600">
              {summary
                ? (summary.estimated_hours_saved_monthly as number)
                : session.estimated_hours_saved}
              h
            </p>
            <p className="text-sm text-gray-500 mt-0.5">hours saved / month</p>
          </div>
          <div className="text-center">
            <p className="text-3xl font-bold text-blue-600">
              {summary ? (summary.processes_automated as number) : session.approved_count}
            </p>
            <p className="text-sm text-gray-500 mt-0.5">processes automated</p>
          </div>
        </div>

        <div className="border-t border-gray-100 pt-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Activated Agents
          </p>
          <div className="flex flex-wrap gap-2">
            {agentNames.map((name) => (
              <span
                key={name}
                className="text-xs font-medium text-blue-700 bg-blue-50 px-2.5 py-1 rounded-lg border border-blue-100"
              >
                {name}
              </span>
            ))}
          </div>
          {bpNames.length > 0 && (
            <p className="text-xs text-gray-500 mt-3">
              Covering: {bpNames.join(', ')}
            </p>
          )}
        </div>
      </div>

      {/* CTAs */}
      <div className="flex flex-col gap-3 mb-6">
        <button
          onClick={() => {
            onComplete()
            navigate('/mission-control')
          }}
          className="flex items-center justify-center gap-2 w-full px-6 py-3.5 text-sm font-semibold bg-[#1B2A4A] hover:bg-[#243660] text-white rounded-xl transition-colors"
        >
          Open Mission Control <ChevronRight size={16} />
        </button>
        <button
          onClick={() => {
            onComplete()
            navigate('/portal-access')
          }}
          className="flex items-center justify-center gap-2 w-full px-6 py-3.5 text-sm font-semibold bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl transition-colors"
        >
          View Active Agents <ChevronRight size={16} />
        </button>
      </div>

      <button
        onClick={onStartOver}
        className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
      >
        Start Over
      </button>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function DesignSessionPage() {
  const [tenantId] = useState(
    () => localStorage.getItem(DEFAULT_TENANT_KEY) ?? DEFAULT_TENANT
  )

  const [session, setSession] = useState<DesignSession | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionLoading, setActionLoading] = useState(false)

  async function loadOrCreate() {
    setLoading(true)
    setError('')
    try {
      const active = await api.designSession.getActive(tenantId)
      if (active) {
        setSession(active)
      } else {
        const created = await api.designSession.start(tenantId)
        setSession(created)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start Design Session')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOrCreate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId])

  // Advance step — called when the operator clicks "Continue"
  async function advanceStep() {
    if (!session) return
    const steps = ['connect', 'discover', 'review', 'configure', 'golive']
    const current = steps.indexOf(session.current_step)
    if (current < 0 || current >= steps.length - 1) return

    const nextStep = steps[current + 1]

    // For review step we don't need to call API — just update local step display
    // The backend advances automatically on blueprint approvals.
    // For connect→discover and discover→review we can just update locally.
    setActionLoading(true)
    try {
      if (nextStep === 'review' || nextStep === 'discover') {
        // Optimistically update to the next step client-side
        setSession((prev) => prev ? { ...prev, current_step: nextStep, step_number: current + 2 } : prev)
      } else {
        const updated = await api.designSession.get(session.session_id, tenantId)
        setSession(updated)
      }
    } catch (e: unknown) {
      console.error('Failed to advance step', e)
    } finally {
      setActionLoading(false)
    }
  }

  async function handleApprove(blueprintId: string) {
    if (!session) return
    setActionLoading(true)
    try {
      const updated = await api.designSession.approveBlueprint(
        session.session_id,
        blueprintId,
        true,
      )
      setSession(updated)
    } catch (e: unknown) {
      console.error('Approve failed', e)
    } finally {
      setActionLoading(false)
    }
  }

  async function handleSkip(blueprintId: string) {
    if (!session) return
    setActionLoading(true)
    try {
      const updated = await api.designSession.approveBlueprint(
        session.session_id,
        blueprintId,
        false,
      )
      setSession(updated)
    } catch (e: unknown) {
      console.error('Skip failed', e)
    } finally {
      setActionLoading(false)
    }
  }

  async function handleConfigure(blueprintId: string, config: Record<string, unknown>) {
    if (!session) return
    try {
      const updated = await api.designSession.configure(
        session.session_id,
        blueprintId,
        config,
      )
      setSession(updated)
    } catch (e: unknown) {
      console.error('Configure failed', e)
    }
  }

  async function handleComplete() {
    if (!session) return
    try {
      const updated = await api.designSession.complete(session.session_id, tenantId)
      setSession(updated)
    } catch (e: unknown) {
      console.error('Complete failed', e)
    }
  }

  async function handleStartOver() {
    setLoading(true)
    try {
      const created = await api.designSession.start(tenantId)
      setSession(created)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to restart session')
    } finally {
      setLoading(false)
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
        <p className="text-gray-500 text-sm">Preparing your Design Session…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-6 py-5 max-w-xl">
        <p className="font-semibold">Could not start Design Session</p>
        <p className="text-sm mt-1">{error}</p>
        <button
          onClick={loadOrCreate}
          className="mt-3 px-4 py-2 text-sm font-medium bg-red-600 text-white rounded-lg hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!session) return null

  return (
    <div className="-m-8 min-h-screen bg-gray-50">
      <WizardProgressBar currentStep={session.current_step} />

      {/* Page content — offset for fixed progress bar */}
      <div className="pt-24 pb-16 px-8">
        {/* Header banner */}
        {session.current_step !== 'golive' && (
          <div
            className="mb-8 px-8 py-5 flex items-center gap-4 rounded-2xl"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center flex-shrink-0">
              <Wand2 size={20} className="text-white" />
            </div>
            <div>
              <h2 className="text-white font-semibold text-base leading-tight">Design Session</h2>
              <p className="text-gray-400 text-sm mt-0.5">
                Guided onboarding — {session.tenant_id}
              </p>
            </div>
            {actionLoading && (
              <div className="ml-auto">
                <div className="w-5 h-5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              </div>
            )}
          </div>
        )}

        {session.current_step === 'connect' && (
          <StepConnect session={session} onNext={advanceStep} />
        )}
        {session.current_step === 'discover' && (
          <StepDiscover session={session} onNext={advanceStep} />
        )}
        {session.current_step === 'review' && (
          <StepReview
            session={session}
            onApprove={handleApprove}
            onSkip={handleSkip}
          />
        )}
        {session.current_step === 'configure' && (
          <StepConfigure session={session} onSave={handleConfigure} />
        )}
        {session.current_step === 'golive' && (
          <StepGoLive
            session={session}
            onComplete={handleComplete}
            onStartOver={handleStartOver}
          />
        )}
      </div>
    </div>
  )
}
