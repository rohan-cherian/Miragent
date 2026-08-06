import { useState, useEffect, useCallback } from 'react'
import {
  HeartPulse, MessageCircleQuestion, Loader2, AlertCircle, CheckCircle2,
  AlertTriangle, RotateCcw, Umbrella, Heart, PiggyBank, CalendarCheck,
  ChevronRight, Info, TrendingUp,
} from 'lucide-react'
import { api } from '../api/client'
import type { BenefitsResult, BenefitsSummary } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function getToken(): string {
  return localStorage.getItem('scout_token') || ''
}

function getTenant(): string {
  return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT
}

type QuestionCategory =
  | 'pto_balance'
  | 'health_insurance'
  | 'retirement_401k'
  | 'open_enrollment'
  | 'general_benefits'

function categoryBadgeClass(cat: QuestionCategory | string) {
  switch (cat) {
    case 'pto_balance':     return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'health_insurance': return 'bg-green-100 text-green-800 border-green-200'
    case 'retirement_401k': return 'bg-purple-100 text-purple-800 border-purple-200'
    case 'open_enrollment': return 'bg-orange-100 text-orange-800 border-orange-200'
    default:                return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

function categoryLabel(cat: string) {
  switch (cat) {
    case 'pto_balance':     return 'PTO & Time Off'
    case 'health_insurance': return 'Health Insurance'
    case 'retirement_401k': return '401k & Retirement'
    case 'open_enrollment': return 'Open Enrollment'
    default:                return 'General Benefits'
  }
}

function categoryEmoji(cat: string) {
  switch (cat) {
    case 'pto_balance':     return '🏖️'
    case 'health_insurance': return '🏥'
    case 'retirement_401k': return '💰'
    case 'open_enrollment': return '📋'
    default:                return '📄'
  }
}

const EXAMPLE_QUESTIONS = [
  'How many PTO days do I have left?',
  'What\'s my 401k match?',
  'When is open enrollment?',
  'What health plan am I on?',
  'What is my deductible?',
]

// ── Result card ───────────────────────────────────────────────────────────────

function BenefitsResultCard({ result, onReset }: {
  result: BenefitsResult
  onReset: () => void
}) {
  return (
    <div className="space-y-4">
      {/* Answer card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className={`h-1.5 ${
          result.question_category === 'pto_balance' ? 'bg-blue-500' :
          result.question_category === 'health_insurance' ? 'bg-green-500' :
          result.question_category === 'retirement_401k' ? 'bg-purple-500' :
          result.question_category === 'open_enrollment' ? 'bg-orange-500' :
          'bg-gray-400'
        }`} />
        <div className="p-5 space-y-4">
          {/* Header */}
          <div className="flex items-start gap-3 justify-between">
            <div>
              <div className="text-base font-bold text-gray-900">{result.employee_name}</div>
              <span className="inline-block mt-1 px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">
                {result.department}
              </span>
            </div>
            <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${categoryBadgeClass(result.question_category)}`}>
              <span>{categoryEmoji(result.question_category)}</span>
              {categoryLabel(result.question_category)}
            </span>
          </div>

          {/* Answer */}
          <div className="bg-gray-50 rounded-lg px-4 py-3">
            <p className="text-sm text-gray-700 leading-relaxed">{result.answer}</p>
          </div>

          {/* Key facts grid */}
          {Object.keys(result.key_facts).length > 0 && (
            <div className="grid grid-cols-2 gap-3">
              {Object.entries(result.key_facts).map(([key, val]) => (
                <div key={key} className="bg-white border border-gray-100 rounded-lg px-3 py-2">
                  <div className="text-xs text-gray-400 capitalize mb-0.5">
                    {key.replace(/_/g, ' ')}
                  </div>
                  <div className="text-sm font-semibold text-gray-800">
                    {typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Action items */}
          {result.action_items.length > 0 && (
            <div className="space-y-2">
              {result.action_items.map((item, i) => (
                <div key={i} className="flex items-start gap-2.5 bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3">
                  <AlertTriangle size={14} className="text-yellow-600 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-yellow-800 leading-relaxed">{item}</p>
                </div>
              ))}
            </div>
          )}

          {/* Contact */}
          <div className="flex items-start gap-2 pt-1">
            <Info size={13} className="text-gray-400 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-gray-400">
              <span className="font-medium text-gray-500">Contact: </span>
              {result.contact}
            </p>
          </div>

          <button
            onClick={onReset}
            className="text-xs text-gray-400 hover:text-gray-600 underline underline-offset-2 transition-colors"
          >
            Ask another question
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Right panel — Benefits Snapshot ──────────────────────────────────────────

function PtoProgressBar({ remaining, total }: { remaining: number; total: number }) {
  const pct = total > 0 ? Math.round((remaining / total) * 100) : 0
  const barColor = pct <= 20 ? 'bg-red-400' : pct <= 50 ? 'bg-yellow-400' : 'bg-blue-400'
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>{remaining} remaining</span>
        <span>{pct}%</span>
      </div>
      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function SnapshotCard({ icon, label, children, onViewDetails, accentClass }: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
  onViewDetails?: () => void
  accentClass: string
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 ${accentClass}`}>
          {icon}
        </div>
        <span className="text-xs font-bold text-gray-600 uppercase tracking-wide">{label}</span>
      </div>
      <div className="flex-1">{children}</div>
      {onViewDetails && (
        <button
          onClick={onViewDetails}
          className="flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 transition-colors mt-1"
        >
          View full details <ChevronRight size={11} />
        </button>
      )}
    </div>
  )
}

function BenefitsSnapshot({ email, onAskQuestion }: {
  email: string
  onAskQuestion: (q: string) => void
}) {
  const [summary, setSummary] = useState<BenefitsSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!email.trim() || !email.includes('@')) return
    setLoading(true)
    setError(null)
    try {
      const token = getToken()
      const tenant = getTenant()
      const data = await api.benefits.summary(email.trim(), tenant, token)
      setSummary(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load summary')
    } finally {
      setLoading(false)
    }
  }, [email])

  useEffect(() => { load() }, [load])

  if (!email.trim() || !email.includes('@')) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <HeartPulse size={36} className="text-gray-200 mb-3" />
        <p className="text-gray-400 text-sm">Enter your email to load your benefits snapshot.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 size={24} className="animate-spin text-gray-300" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
        <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
        <p className="text-sm text-red-700">{error}</p>
      </div>
    )
  }

  if (!summary || !summary.found) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <AlertCircle size={32} className="text-gray-300 mb-2" />
        <p className="text-gray-500 font-medium">Employee not found</p>
        <p className="text-gray-400 text-sm mt-1">No benefits profile found for {email}</p>
      </div>
    )
  }

  const matchOk = summary.match_captured
  // Days until Dec 31 (rough — for current year)
  const today = new Date()
  const dec31 = new Date(today.getFullYear(), 11, 31)
  const daysToDecember = Math.max(0, Math.ceil((dec31.getTime() - today.getTime()) / 86400000))
  // Days to open enrollment (Nov 1)
  const nov1 = new Date(today.getFullYear(), 10, 1)
  if (nov1 < today) nov1.setFullYear(nov1.getFullYear() + 1)
  const daysToEnrollment = Math.ceil((nov1.getTime() - today.getTime()) / 86400000)

  return (
    <div className="space-y-4">
      {/* Employee header */}
      <div>
        <div className="text-base font-bold text-gray-900">{summary.employee_name}</div>
        <span className="text-xs text-gray-500">{summary.department}</span>
      </div>

      {/* 2x2 mini-card grid */}
      <div className="grid grid-cols-2 gap-3">

        {/* PTO card */}
        <SnapshotCard
          icon={<Umbrella size={14} className="text-blue-600" />}
          label="PTO"
          accentClass="bg-blue-50"
          onViewDetails={() => onAskQuestion('How many PTO days do I have left?')}
        >
          <div className="text-lg font-bold text-gray-900">
            {summary.pto_remaining} <span className="text-sm font-normal text-gray-400">of {summary.pto_total} days</span>
          </div>
          <PtoProgressBar remaining={summary.pto_remaining ?? 0} total={summary.pto_total ?? 20} />
          {(summary.pto_remaining ?? 0) > 15 && (
            <p className="text-xs text-orange-600 mt-1">Only 5 days roll over — use before Dec 31</p>
          )}
          {(summary.pto_remaining ?? 1) === 0 && (
            <p className="text-xs text-red-600 mt-1">No PTO remaining this year</p>
          )}
        </SnapshotCard>

        {/* Health card */}
        <SnapshotCard
          icon={<Heart size={14} className="text-green-600" />}
          label="Health"
          accentClass="bg-green-50"
          onViewDetails={() => onAskQuestion('What health plan am I on?')}
        >
          <div className="text-sm font-semibold text-gray-800 leading-tight">
            {summary.health_plan?.replace(' (', '\n(') ?? 'Unknown'}
          </div>
          <div className="text-xs text-gray-400 mt-1">{summary.monthly_contribution}</div>
        </SnapshotCard>

        {/* 401k card */}
        <SnapshotCard
          icon={<PiggyBank size={14} className="text-purple-600" />}
          label="401k"
          accentClass="bg-purple-50"
          onViewDetails={() => onAskQuestion("What's my 401k match?")}
        >
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-gray-900">{summary.contrib_pct}%</span>
            <span className="text-xs text-gray-400">contribution</span>
          </div>
          <div className="flex items-center gap-1 mt-1">
            {matchOk
              ? <CheckCircle2 size={13} className="text-green-500" />
              : <AlertTriangle size={13} className="text-orange-400" />}
            <span className={`text-xs font-medium ${matchOk ? 'text-green-600' : 'text-orange-500'}`}>
              {matchOk
                ? 'Full match captured'
                : `${summary.match_pct}% of 4% match captured`}
            </span>
          </div>
          {!matchOk && (
            <div className="flex items-center gap-1 mt-1">
              <TrendingUp size={11} className="text-orange-400" />
              <span className="text-xs text-orange-500">Increase to 4% for full match</span>
            </div>
          )}
        </SnapshotCard>

        {/* Open Enrollment card */}
        <SnapshotCard
          icon={<CalendarCheck size={14} className="text-orange-600" />}
          label="Enrollment"
          accentClass="bg-orange-50"
          onViewDetails={() => onAskQuestion('When is open enrollment?')}
        >
          <div className="text-sm font-semibold text-gray-800">
            Next window: {summary.enrollment_window}
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {daysToEnrollment > 0
              ? `${daysToEnrollment} days away`
              : 'Open enrollment is active!'}
          </div>
          <div className="text-xs text-gray-400 mt-0.5">
            {daysToDecember} days until year-end
          </div>
        </SnapshotCard>
      </div>

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

export default function Benefits() {
  const [email, setEmail] = useState('')
  // When snapshot panel clicks "View full details", push question to ask panel
  const [questionOverride, setQuestionOverride] = useState<string | null>(null)

  function handleAskQuestion(q: string) {
    setQuestionOverride(q)
  }

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
              <HeartPulse size={18} className="text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Benefits</h1>
          </div>
          <p className="text-gray-500 text-sm ml-12">
            Ask about your PTO balance, health plan, 401k match, or open enrollment — instantly.
          </p>
        </div>

        {/* Two-panel layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left panel — Ask */}
          <div>
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
              <div className="flex items-center gap-2 mb-5">
                <MessageCircleQuestion size={15} className="text-gray-400" />
                <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Ask About Your Benefits</span>
              </div>
              <AskPanelWithOverride
                emailValue={email}
                onEmailChange={setEmail}
                questionOverride={questionOverride}
                onQuestionOverrideConsumed={() => setQuestionOverride(null)}
              />
            </div>
          </div>

          {/* Right panel — Snapshot */}
          <div>
            <div className="bg-gray-50 rounded-2xl border border-gray-200 p-6">
              <div className="flex items-center gap-2 mb-5">
                <HeartPulse size={15} className="text-gray-400" />
                <span className="text-sm font-bold text-gray-800 uppercase tracking-wide">Benefits Snapshot</span>
              </div>
              <BenefitsSnapshot
                email={email}
                onAskQuestion={handleAskQuestion}
              />
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

// ── AskPanel with question override support ───────────────────────────────────

function AskPanelWithOverride({ emailValue, onEmailChange, questionOverride, onQuestionOverrideConsumed }: {
  emailValue: string
  onEmailChange: (v: string) => void
  questionOverride: string | null
  onQuestionOverrideConsumed: () => void
}) {
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<BenefitsResult | null>(null)

  // When snapshot panel pushes a question, populate and submit
  useEffect(() => {
    if (questionOverride) {
      setQuestion(questionOverride)
      setResult(null)
      setError(null)
      onQuestionOverrideConsumed()
    }
  }, [questionOverride, onQuestionOverrideConsumed])

  async function handleAsk() {
    if (!emailValue.trim()) { setError('Please enter your employee email.'); return }
    if (!question.trim()) { setError('Please enter a question.'); return }
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      const token = getToken()
      const tenant = getTenant()
      const r = await api.benefits.query(emailValue.trim(), question.trim(), tenant, token)
      setResult(r)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Query failed')
    } finally {
      setLoading(false)
    }
  }

  function handleReset() {
    setResult(null)
    setError(null)
    setQuestion('')
  }

  function useExample(q: string) {
    setQuestion(q)
    setResult(null)
    setError(null)
  }

  return (
    <div className="space-y-5">
      {/* Email input */}
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
          Employee Email
        </label>
        <input
          type="email"
          value={emailValue}
          onChange={e => { onEmailChange(e.target.value); setResult(null); setError(null) }}
          placeholder="sarah.chen@acme-corp.com"
          className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Question input */}
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1.5 uppercase tracking-wide">
          Your Question
        </label>
        <textarea
          value={question}
          onChange={e => setQuestion(e.target.value)}
          placeholder="How many PTO days do I have? / What's my 401k match? / When is open enrollment?"
          rows={3}
          className="w-full px-4 py-3 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
      </div>

      {/* Example questions */}
      <div>
        <p className="text-xs text-gray-400 mb-2">Try an example:</p>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLE_QUESTIONS.map(q => (
            <button
              key={q}
              onClick={() => useExample(q)}
              className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-500 hover:text-gray-800 hover:border-gray-300 transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Ask button */}
      <button
        onClick={handleAsk}
        disabled={loading}
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
        style={{ backgroundColor: '#1B2A4A' }}
      >
        {loading
          ? <><Loader2 size={15} className="animate-spin" /> Checking…</>
          : <><MessageCircleQuestion size={15} /> Ask</>}
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={15} className="text-red-500 mt-0.5 flex-shrink-0" />
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Result */}
      {result && <BenefitsResultCard result={result} onReset={handleReset} />}

      {/* Empty state */}
      {!result && !loading && !error && (
        <div className="flex flex-col items-center justify-center py-10 text-center px-6">
          <HeartPulse size={36} className="text-gray-300 mb-3" />
          <p className="text-gray-500 font-medium">Ask about your benefits</p>
          <p className="text-gray-400 text-sm mt-1">
            Enter your email and a question about PTO, health, 401k, or enrollment.
          </p>
        </div>
      )}
    </div>
  )
}
