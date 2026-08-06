import { useState, useEffect } from 'react'
import {
  MessageSquare, Loader2, AlertTriangle, TrendingUp, Mail, Hash,
  ChevronDown,
} from 'lucide-react'
import { api } from '../api/client'
import type { CommMessage, CommAnalysisSummary } from '../api/client'

const DEFAULT_TENANT = 'acme-corp'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatArr(arr: number): string {
  if (arr >= 1_000_000) return `$${(arr / 1_000_000).toFixed(1)}M`
  if (arr >= 1_000) return `$${(arr / 1_000).toFixed(0)}k`
  return `$${arr.toFixed(0)}`
}

function sentimentBadge(sentiment: string) {
  switch (sentiment) {
    case 'positive':          return 'bg-emerald-100 text-emerald-700'
    case 'negative':          return 'bg-red-100 text-red-700'
    case 'urgent':            return 'bg-red-100 text-red-800 font-bold'
    case 'churn_risk':        return 'bg-orange-100 text-orange-700'
    case 'expansion_signal':  return 'bg-blue-100 text-blue-700'
    default:                  return 'bg-gray-100 text-gray-500'
  }
}

function sentimentLabel(sentiment: string) {
  switch (sentiment) {
    case 'churn_risk':        return 'Churn Risk'
    case 'expansion_signal':  return 'Expansion'
    case 'positive':          return 'Positive'
    case 'negative':          return 'Negative'
    case 'urgent':            return 'Urgent'
    default:                  return 'Neutral'
  }
}

function topicChipColor(topic: string) {
  switch (topic) {
    case 'technical_issue':   return 'bg-red-100 text-red-700'
    case 'billing_question':  return 'bg-yellow-100 text-yellow-700'
    case 'compliance_security': return 'bg-purple-100 text-purple-700'
    case 'expansion_upsell':  return 'bg-blue-100 text-blue-700'
    case 'churn_risk':        return 'bg-orange-100 text-orange-700'
    case 'onboarding':        return 'bg-teal-100 text-teal-700'
    case 'positive_feedback': return 'bg-emerald-100 text-emerald-700'
    case 'feature_request':   return 'bg-gray-100 text-gray-600'
    default:                  return 'bg-gray-100 text-gray-500'
  }
}

function topicLabel(topic: string) {
  return topic.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function trendChip(trend: string) {
  switch (trend) {
    case 'improving': return 'bg-emerald-100 text-emerald-700'
    case 'declining': return 'bg-red-100 text-red-700'
    default:          return 'bg-gray-100 text-gray-600'
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatBar({ summary }: { summary: CommAnalysisSummary }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-6 py-4">
      <div className="flex flex-wrap items-center gap-6 text-sm">
        <div className="flex items-center gap-2">
          <span className="text-gray-500">Total Messages</span>
          <span className="font-bold text-gray-900">{summary.total_messages}</span>
        </div>
        <div className="w-px h-4 bg-gray-200" />
        <div className="flex items-center gap-2">
          <span className="text-gray-500">Urgent</span>
          <span className="font-bold text-red-600">{summary.urgent_unresolved}</span>
        </div>
        <div className="w-px h-4 bg-gray-200" />
        <div className="flex items-center gap-2">
          <span className="text-gray-500">Churn Risk ARR</span>
          <span className="font-bold text-orange-600">{formatArr(summary.churn_risk_arr)}</span>
        </div>
        <div className="w-px h-4 bg-gray-200" />
        <div className="flex items-center gap-2">
          <span className="text-gray-500">Expansion ARR</span>
          <span className="font-bold text-emerald-600">{formatArr(summary.expansion_arr)}</span>
        </div>
        <div className="w-px h-4 bg-gray-200" />
        <div className="flex items-center gap-2">
          <span className="text-gray-500">Sentiment</span>
          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold capitalize ${trendChip(summary.sentiment_trend)}`}>
            {summary.sentiment_trend}
          </span>
        </div>
      </div>
    </div>
  )
}

function MiniMessageCard({ msg, accent }: { msg: CommMessage; accent: string }) {
  return (
    <div className={`p-3 rounded-lg border ${accent} mb-2`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-semibold text-gray-800">{msg.customer}</span>
        <span className="text-xs font-medium text-gray-500">{formatArr(msg.arr)}</span>
      </div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${sentimentBadge(msg.sentiment)}`}>
          {sentimentLabel(msg.sentiment)}
        </span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${topicChipColor(msg.topic)}`}>
          {topicLabel(msg.topic)}
        </span>
      </div>
      {msg.action_suggestion && (
        <p className="text-xs text-gray-600 italic">{msg.action_suggestion}</p>
      )}
    </div>
  )
}

function LeftPanel({
  summary,
  atRisk,
  expansion,
}: {
  summary: CommAnalysisSummary | null
  atRisk: CommMessage[]
  expansion: CommMessage[]
}) {
  if (!summary) return null

  return (
    <div className="space-y-5">
      {/* At Risk */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={15} className="text-orange-500" />
          <span className="text-sm font-semibold text-gray-900">At Risk</span>
          <span className="ml-auto text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full font-semibold">
            {atRisk.length}
          </span>
        </div>
        {atRisk.length === 0 ? (
          <p className="text-xs text-gray-400 italic">No at-risk signals detected.</p>
        ) : (
          atRisk.map(msg => (
            <MiniMessageCard key={msg.id} msg={msg} accent="border-orange-200 bg-orange-50" />
          ))
        )}
      </div>

      {/* Expansion Signals */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp size={15} className="text-blue-500" />
          <span className="text-sm font-semibold text-gray-900">Expansion Signals</span>
          <span className="ml-auto text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-semibold">
            {expansion.length}
          </span>
        </div>
        {expansion.length === 0 ? (
          <p className="text-xs text-gray-400 italic">No expansion signals detected.</p>
        ) : (
          expansion.map(msg => (
            <MiniMessageCard key={msg.id} msg={msg} accent="border-blue-200 bg-blue-50" />
          ))
        )}
      </div>
    </div>
  )
}

function MessageCard({ msg }: { msg: CommMessage }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-2.5">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-gray-900 text-sm">{msg.customer}</span>
        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full font-medium">
          {formatArr(msg.arr)} ARR
        </span>
        <span className="ml-auto text-xs text-gray-400">{msg.date}</span>
        {msg.channel === 'email' ? (
          <span className="flex items-center gap-1 text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full font-medium">
            <Mail size={11} /> Email
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs bg-violet-100 text-violet-600 px-2 py-0.5 rounded-full font-medium">
            <Hash size={11} /> {msg.source}
          </span>
        )}
      </div>

      {/* Subject or channel */}
      {msg.subject ? (
        <p className="text-sm font-medium text-gray-700">{msg.subject}</p>
      ) : (
        <p className="text-xs text-gray-400 italic">{msg.source}</p>
      )}

      {/* Body preview */}
      <p className="text-xs text-gray-500 leading-relaxed">{msg.body_preview}</p>

      {/* Topic + sentiment chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${topicChipColor(msg.topic)}`}>
          {topicLabel(msg.topic)}
        </span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${sentimentBadge(msg.sentiment)}`}>
          {sentimentLabel(msg.sentiment)}
        </span>
        {msg.signals.filter(s => s !== msg.sentiment).map(s => (
          <span key={s} className={`px-2 py-0.5 rounded-full text-xs font-medium ${sentimentBadge(s)}`}>
            {sentimentLabel(s)}
          </span>
        ))}
      </div>

      {/* Action suggestion */}
      {msg.requires_action && msg.action_suggestion && (
        <div className="flex items-start gap-2 bg-yellow-50 border border-yellow-200 rounded-lg px-3 py-2">
          <AlertTriangle size={13} className="text-yellow-600 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-yellow-800">{msg.action_suggestion}</p>
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

const SENTIMENT_FILTERS = [
  { value: '', label: 'All' },
  { value: 'positive', label: 'Positive' },
  { value: 'negative', label: 'Negative' },
  { value: 'urgent', label: 'Urgent' },
  { value: 'churn_risk', label: 'Churn Risk' },
  { value: 'expansion_signal', label: 'Expansion' },
]

const TOPIC_OPTIONS = [
  { value: '', label: 'All Topics' },
  { value: 'technical_issue', label: 'Technical Issue' },
  { value: 'billing_question', label: 'Billing' },
  { value: 'compliance_security', label: 'Compliance / Security' },
  { value: 'expansion_upsell', label: 'Expansion / Upsell' },
  { value: 'churn_risk', label: 'Churn Risk' },
  { value: 'onboarding', label: 'Onboarding' },
  { value: 'positive_feedback', label: 'Positive Feedback' },
  { value: 'feature_request', label: 'Feature Request' },
]

export default function Communications() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState<CommAnalysisSummary | null>(null)
  const [messages, setMessages] = useState<CommMessage[]>([])
  const [atRisk, setAtRisk] = useState<CommMessage[]>([])
  const [expansion, setExpansion] = useState<CommMessage[]>([])
  const [sentimentFilter, setSentimentFilter] = useState('')
  const [topicFilter, setTopicFilter] = useState('')
  const tenantId = DEFAULT_TENANT

  useEffect(() => {
    loadAll()
  }, [])

  useEffect(() => {
    loadMessages()
  }, [sentimentFilter, topicFilter])

  async function loadAll() {
    setLoading(true)
    setError('')
    try {
      const [sum, msgs, risk, exp] = await Promise.all([
        api.communications.summary(tenantId),
        api.communications.messages(tenantId),
        api.communications.atRisk(tenantId),
        api.communications.expansion(tenantId),
      ])
      setSummary(sum)
      setMessages(msgs)
      setAtRisk(risk)
      setExpansion(exp)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load communications data.')
    } finally {
      setLoading(false)
    }
  }

  async function loadMessages() {
    try {
      const msgs = await api.communications.messages(
        tenantId,
        sentimentFilter || undefined,
        topicFilter || undefined,
      )
      setMessages(msgs)
    } catch {
      // non-critical — keep existing messages
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-5">
      {/* Page header */}
      <div className="mb-2">
        <div className="flex items-center gap-2 mb-1">
          <MessageSquare size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Communication Analysis</h1>
        </div>
        <p className="text-gray-500 text-sm">
          Customer-facing communications only — support email queue &amp; shared Slack channels.
          Internal DMs excluded (GDPR-safe).
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          <AlertTriangle size={15} className="mt-0.5 flex-shrink-0" />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-48">
          <Loader2 size={28} className="animate-spin text-gray-400" />
        </div>
      ) : summary ? (
        <>
          {/* Top stat bar */}
          <StatBar summary={summary} />

          {/* Two-column layout */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Left column — At Risk + Expansion */}
            <div className="lg:col-span-1">
              <LeftPanel summary={summary} atRisk={atRisk} expansion={expansion} />
            </div>

            {/* Right column — Message Feed */}
            <div className="lg:col-span-2 space-y-4">
              {/* Filter bar */}
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  {/* Sentiment filter pills */}
                  <div className="flex flex-wrap gap-1.5">
                    {SENTIMENT_FILTERS.map(f => (
                      <button
                        key={f.value}
                        onClick={() => setSentimentFilter(f.value)}
                        className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                          sentimentFilter === f.value
                            ? 'bg-gray-800 text-white'
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        {f.label}
                      </button>
                    ))}
                  </div>

                  {/* Topic dropdown */}
                  <div className="relative ml-auto">
                    <select
                      value={topicFilter}
                      onChange={e => setTopicFilter(e.target.value)}
                      className="appearance-none pl-3 pr-7 py-1.5 text-xs bg-gray-100 border border-gray-200 rounded-lg text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer"
                    >
                      {TOPIC_OPTIONS.map(o => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                    <ChevronDown size={12} className="absolute right-2 top-2 text-gray-400 pointer-events-none" />
                  </div>
                </div>
              </div>

              {/* Messages */}
              {messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <MessageSquare size={36} className="text-gray-300 mb-3" />
                  <p className="text-gray-500 font-medium">No messages match the current filters.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {messages.map(msg => (
                    <MessageCard key={msg.id} msg={msg} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
