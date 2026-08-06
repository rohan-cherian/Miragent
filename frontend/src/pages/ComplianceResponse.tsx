import { useState, useCallback } from 'react'
import {
  FileCheck, Loader2, AlertCircle, CheckCircle2, ChevronDown,
  ChevronUp, Flag, RefreshCw, Shield,
} from 'lucide-react'
import { api } from '../api/client'
import type { ComplianceResult, ComplianceAnswer } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

function getToken(): string { return localStorage.getItem('scout_token') || '' }
function getTenant(): string { return localStorage.getItem(DEFAULT_TENANT_KEY) || DEFAULT_TENANT }

// ── Helpers ────────────────────────────────────────────────────────────────────

function confidenceBadge(label: string): string {
  switch (label) {
    case 'High':    return 'bg-green-100 text-green-800 border-green-200'
    case 'Review':  return 'bg-yellow-100 text-yellow-800 border-yellow-200'
    case 'Unknown': return 'bg-red-100 text-red-800 border-red-200'
    default:        return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

function topicChipClass(topic: string | null): string {
  if (!topic) return 'bg-red-100 text-red-700 border-red-200'
  const secCerts = ['soc2', 'penetration_testing', 'vulnerability_management', 'iso27001']
  const techControls = ['encryption', 'network_security', 'logging_monitoring', 'access_control']
  const dataPrivacy = ['gdpr', 'ccpa', 'data_residency']
  const operational = ['incident_response', 'business_continuity']
  if (secCerts.includes(topic))    return 'bg-purple-100 text-purple-800 border-purple-200'
  if (techControls.includes(topic)) return 'bg-blue-100 text-blue-800 border-blue-200'
  if (dataPrivacy.includes(topic)) return 'bg-green-100 text-green-800 border-green-200'
  if (operational.includes(topic)) return 'bg-orange-100 text-orange-800 border-orange-200'
  return 'bg-gray-100 text-gray-700 border-gray-200'
}

function formatTopic(topic: string | null): string {
  if (!topic) return 'Unknown'
  return topic.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function typeBadge(qt: string): string {
  switch (qt) {
    case 'CAIQ':    return 'bg-purple-100 text-purple-800'
    case 'SIG Lite':return 'bg-blue-100 text-blue-800'
    default:        return 'bg-gray-100 text-gray-700'
  }
}

// ── Answer Card ────────────────────────────────────────────────────────────────

function AnswerCard({ answer, flagged, onFlag }: {
  answer: ComplianceAnswer
  flagged: boolean
  onFlag: () => void
}) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={`border rounded-lg p-3 text-sm ${flagged ? 'border-orange-300 bg-orange-50' : 'border-gray-200 bg-white'}`}>
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-500 text-xs">Q{answer.question_number}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${topicChipClass(answer.topic)}`}>
            {formatTopic(answer.topic)}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${confidenceBadge(answer.confidence_label)}`}>
            {answer.confidence_label}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onFlag}
            title="Flag for manual review"
            className={`p-1 rounded ${flagged ? 'text-orange-600' : 'text-gray-400 hover:text-orange-500'}`}
          >
            <Flag size={13} />
          </button>
          <button onClick={() => setExpanded(e => !e)} className="text-gray-400 hover:text-gray-600">
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      <p className="text-gray-700 text-xs mb-1 leading-snug">
        {answer.question_text.length > 90 && !expanded
          ? answer.question_text.slice(0, 90) + '…'
          : answer.question_text}
      </p>

      <div className="text-gray-800 text-xs leading-snug">
        {expanded || answer.answer.length <= 120
          ? answer.answer
          : answer.answer.slice(0, 120) + '…'}
      </div>

      {expanded && answer.evidence && (
        <p className="mt-1.5 text-xs text-gray-400 italic">📎 {answer.evidence}</p>
      )}
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function ComplianceResponse() {
  const [customerName, setCustomerName]   = useState('')
  const [questionText, setQuestionText]   = useState('')
  const [loading, setLoading]             = useState(false)
  const [sampleLoading, setSampleLoading] = useState(false)
  const [error, setError]                 = useState('')
  const [result, setResult]               = useState<ComplianceResult | null>(null)
  const [filter, setFilter]               = useState<'all' | 'review' | 'unknown'>('all')
  const [flagged, setFlagged]             = useState<Set<number>>(new Set())

  const token  = getToken()
  const tenant = getTenant()

  const loadSample = useCallback(async () => {
    setSampleLoading(true)
    try {
      const r = await api.compliance.getSample(token)
      setQuestionText(r.text)
    } catch {
      setError('Could not load sample questionnaire.')
    } finally {
      setSampleLoading(false)
    }
  }, [token])

  const handleProcess = useCallback(async () => {
    if (!customerName.trim() || !questionText.trim()) {
      setError('Please enter a customer name and paste the questionnaire.')
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    setFlagged(new Set())
    try {
      const r = await api.compliance.process(customerName, questionText, tenant, token)
      setResult(r)
    } catch {
      setError('Failed to process questionnaire. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [customerName, questionText, tenant, token])

  const toggleFlag = useCallback((qNum: number) => {
    setFlagged(prev => {
      const next = new Set(prev)
      if (next.has(qNum)) next.delete(qNum)
      else next.add(qNum)
      return next
    })
  }, [])

  const filteredAnswers = result?.answers.filter((a: ComplianceAnswer) => {
    if (filter === 'review')  return a.confidence_label === 'Review'
    if (filter === 'unknown') return a.confidence_label === 'Unknown'
    return true
  }) ?? []

  return (
    <div className="flex h-full gap-4 p-4 overflow-hidden">

      {/* ── Left: Submit ────────────────────────────────────────────────────── */}
      <div className="w-96 flex flex-col gap-3 overflow-y-auto shrink-0">

        {/* Header */}
        <div className="flex items-center gap-2">
          <FileCheck size={20} className="text-indigo-600" />
          <h1 className="text-lg font-bold text-gray-900">Compliance Response</h1>
        </div>
        <p className="text-xs text-gray-500 -mt-2">
          Paste a customer security questionnaire and get AI-drafted answers from your compliance knowledge base.
        </p>

        {/* Customer name */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Customer Name</label>
          <input
            value={customerName}
            onChange={e => setCustomerName(e.target.value)}
            placeholder="e.g. Acme Enterprise Corp"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>

        {/* Questionnaire textarea */}
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium text-gray-700">Questionnaire</label>
            <button
              onClick={loadSample}
              disabled={sampleLoading}
              className="text-xs text-indigo-600 hover:underline flex items-center gap-1"
            >
              {sampleLoading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
              Load Sample
            </button>
          </div>
          <textarea
            value={questionText}
            onChange={e => setQuestionText(e.target.value)}
            placeholder="1. Do you hold SOC 2 Type II certification?&#10;2. Is customer data encrypted at rest and in transit?&#10;..."
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono resize-none focus:outline-none focus:ring-2 focus:ring-indigo-400"
            rows={12}
          />
        </div>

        <button
          onClick={handleProcess}
          disabled={loading}
          className="w-full bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg py-2.5 text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Shield size={16} />}
          {loading ? 'Processing…' : 'Process Questionnaire'}
        </button>

        {error && (
          <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}

        {/* Summary card */}
        {result && (
          <div className="border border-indigo-200 bg-indigo-50 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-gray-900 text-sm">{result.customer_name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${typeBadge(result.questionnaire_type)}`}>
                {result.questionnaire_type}
              </span>
            </div>
            <div className="flex gap-2 flex-wrap">
              <span className="text-xs px-2.5 py-1 rounded-full bg-green-100 text-green-800 font-medium">
                ✓ {result.high_confidence} High Confidence
              </span>
              <span className="text-xs px-2.5 py-1 rounded-full bg-yellow-100 text-yellow-800 font-medium">
                ⚠ {result.needs_review} Needs Review
              </span>
              {result.unknown_count > 0 && (
                <span className="text-xs px-2.5 py-1 rounded-full bg-red-100 text-red-800 font-medium">
                  ✗ {result.unknown_count} Unknown
                </span>
              )}
            </div>
            <p className="text-xs text-gray-600">{result.summary}</p>
            <button
              onClick={() => alert('Export coming soon')}
              className="w-full text-xs bg-white border border-indigo-300 text-indigo-700 rounded-lg py-1.5 hover:bg-indigo-100 font-medium"
            >
              Download Responses
            </button>
          </div>
        )}
      </div>

      {/* ── Right: Answers ──────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2">
            <CheckCircle2 size={16} className="text-green-600" />
            Answer Review
            {result && <span className="text-xs text-gray-500 font-normal">({result.total_questions} questions)</span>}
          </h2>
          {result && (
            <div className="flex gap-1">
              {(['all', 'review', 'unknown'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`text-xs px-3 py-1 rounded-full border font-medium capitalize ${
                    filter === f
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-300'
                  }`}
                >
                  {f === 'all' ? `All (${result.total_questions})` : f === 'review' ? `Review (${result.needs_review})` : `Unknown (${result.unknown_count})`}
                </button>
              ))}
            </div>
          )}
        </div>

        {!result && (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            <div className="text-center space-y-2">
              <FileCheck size={40} className="mx-auto opacity-30" />
              <p>Submit a questionnaire to see AI-drafted answers here.</p>
            </div>
          </div>
        )}

        {result && (
          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {filteredAnswers.length === 0 ? (
              <p className="text-xs text-gray-400 text-center mt-8">No answers match the current filter.</p>
            ) : (
              filteredAnswers.map((a: ComplianceAnswer) => (
                <AnswerCard
                  key={a.question_number}
                  answer={a}
                  flagged={flagged.has(a.question_number)}
                  onFlag={() => toggleFlag(a.question_number)}
                />
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
