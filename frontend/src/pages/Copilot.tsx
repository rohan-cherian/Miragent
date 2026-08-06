/**
 * Copilot.tsx — Sprint 79: Miragent Copilot
 *
 * Natural language Q&A against the digital twin.
 * Ask anything about a portfolio company — pipeline, churn, headcount,
 * vendor spend, revenue — and get a concise AI-synthesised answer backed
 * by live graph data.
 *
 * POST /copilot/ask
 */

import { useState, useRef, useEffect } from 'react'
import {
  Sparkles, Send, Loader2, User, Bot, AlertCircle,
  RefreshCw, ChevronDown, Info, CheckCircle, Zap,
} from 'lucide-react'
import { api } from '../api/client'
import type { SuggestedAction } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  intent?: string
  sources?: string[]
  llm_provider?: string
  error?: boolean
  ts: number
  suggested_actions?: SuggestedAction[]
}

// ── Suggested questions ───────────────────────────────────────────────────

const SUGGESTED: string[] = [
  'How many stalled deals do we have?',
  'Which customers are at risk of churning?',
  'What are our biggest vendor contracts?',
  'How many employees do we have and who are the overloaded managers?',
  'What is our total ARR and win rate?',
  'Where are the biggest vendor savings opportunities?',
]

const INTENT_LABELS: Record<string, string> = {
  pipeline:  '📊 Pipeline',
  churn:     '⚠️ Churn Risk',
  workforce: '👥 Workforce',
  vendors:   '💰 Vendors',
  revenue:   '📈 Revenue',
  snapshot:  '🧠 Intelligence',
  none:      '—',
}

// ── Helpers ───────────────────────────────────────────────────────────────

let _msgId = 0
const nextId = () => String(++_msgId)

function fmtTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// ── Suggested Actions ─────────────────────────────────────────────────────

const RISK_BADGE: Record<string, { label: string; cls: string }> = {
  LOW:    { label: 'LOW',    cls: 'bg-green-100 text-green-700' },
  MEDIUM: { label: 'MEDIUM', cls: 'bg-yellow-100 text-yellow-700' },
  HIGH:   { label: 'HIGH',   cls: 'bg-red-100 text-red-700' },
}

interface ActionCardState {
  status: 'idle' | 'loading' | 'done' | 'error'
  routed?: boolean
  errorMsg?: string
}

function SuggestedActionsPanel({
  actions,
  tenantId,
  token,
}: {
  actions: SuggestedAction[]
  tenantId: string
  token: string
}) {
  const [cardStates, setCardStates] = useState<ActionCardState[]>(
    () => actions.map(() => ({ status: 'idle' }))
  )

  async function handleCreate(action: SuggestedAction, idx: number) {
    setCardStates(prev => {
      const next = [...prev]
      next[idx] = { status: 'loading' }
      return next
    })
    try {
      const result = await api.copilotCreateAction(token, {
        tenant_id: tenantId,
        title: action.title,
        description: action.description,
        action_type: action.action_type,
        risk_tier: action.risk_tier,
        arr_impact: action.arr_impact ?? undefined,
        worker_name: action.worker_name,
        finding_hash: action.finding_hash,
      })
      setCardStates(prev => {
        const next = [...prev]
        next[idx] = { status: 'done', routed: result.routed_to_approvals }
        return next
      })
    } catch (e: unknown) {
      setCardStates(prev => {
        const next = [...prev]
        next[idx] = {
          status: 'error',
          errorMsg: e instanceof Error ? e.message : 'Failed to create action',
        }
        return next
      })
    }
  }

  if (!actions.length) return null

  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs text-gray-400 font-medium uppercase tracking-wide">Suggested Actions</p>
      {actions.map((action, idx) => {
        const badge = RISK_BADGE[action.risk_tier] ?? RISK_BADGE.MEDIUM
        const state = cardStates[idx]
        const truncDesc = action.description.length > 80
          ? action.description.slice(0, 80) + '…'
          : action.description

        return (
          <div
            key={action.finding_hash || idx}
            className="bg-gray-50 border border-gray-200 rounded-xl px-4 py-3 flex flex-col gap-2"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 leading-snug">{action.title}</p>
                <p className="text-xs text-gray-500 mt-0.5">{truncDesc}</p>
              </div>
              <span className={`flex-shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}>
                {badge.label}
              </span>
            </div>

            {action.arr_impact != null && (
              <p className="text-xs text-gray-500">
                ARR impact: <span className="font-semibold text-gray-700">${action.arr_impact.toLocaleString()}</span>
              </p>
            )}

            <div className="flex items-center gap-2">
              {state.status === 'idle' && (
                <button
                  onClick={() => handleCreate(action, idx)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-opacity"
                  style={{ backgroundColor: '#1B2A4A' }}
                >
                  <Zap size={11} /> Create Action
                </button>
              )}
              {state.status === 'loading' && (
                <span className="flex items-center gap-1.5 text-xs text-gray-400">
                  <Loader2 size={11} className="animate-spin" /> Creating…
                </span>
              )}
              {state.status === 'done' && (
                <span className="flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
                  <CheckCircle size={11} /> Created
                  {state.routed && (
                    <span className="text-amber-600 font-normal ml-1">(routed to Approvals)</span>
                  )}
                </span>
              )}
              {state.status === 'error' && (
                <span className="text-xs text-red-600">{state.errorMsg}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────

function MessageBubble({ msg, tenantId, token }: { msg: Message; tenantId: string; token: string }) {
  const isUser = msg.role === 'user'
  const [showMeta, setShowMeta] = useState(false)

  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-1"
          style={{ backgroundColor: '#1B2A4A' }}>
          <Bot size={14} className="text-white" />
        </div>
      )}

      <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div
          className={`px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'text-white rounded-tr-sm'
              : msg.error
                ? 'bg-red-50 text-red-800 border border-red-200 rounded-tl-sm'
                : 'bg-white border border-gray-100 shadow-sm text-gray-800 rounded-tl-sm'
          }`}
          style={isUser ? { backgroundColor: '#1B2A4A' } : {}}
        >
          {msg.content}
          {!isUser && !msg.error && msg.suggested_actions && msg.suggested_actions.length > 0 && (
            <SuggestedActionsPanel
              actions={msg.suggested_actions}
              tenantId={tenantId}
              token={token}
            />
          )}
        </div>

        {/* Meta row */}
        <div className={`flex items-center gap-2 px-1 ${isUser ? 'justify-end' : 'justify-start'}`}>
          <span className="text-xs text-gray-300">{fmtTime(msg.ts)}</span>

          {!isUser && msg.intent && msg.intent !== 'none' && (
            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
              {INTENT_LABELS[msg.intent] ?? msg.intent}
            </span>
          )}

          {!isUser && (msg.sources?.length ?? 0) > 0 && (
            <button
              onClick={() => setShowMeta(m => !m)}
              className="text-xs text-gray-300 hover:text-gray-500 transition-colors"
            >
              <Info size={11} />
            </button>
          )}
        </div>

        {/* Source detail */}
        {showMeta && msg.sources && (
          <div className="ml-1 text-xs text-gray-400 bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
            Sources: {msg.sources.join(', ')}
            {msg.llm_provider && ` · ${msg.llm_provider}`}
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-1">
          <User size={14} className="text-gray-500" />
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function Copilot() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [tenantId, setTenantId] = useState(
    () => localStorage.getItem('miragent_default_tenant') ?? ''
  )
  const [tenantInput, setTenantInput] = useState(tenantId)
  const [showSuggestions, setShowSuggestions] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const token = localStorage.getItem('miragent_token') ?? ''

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function applyTenant() {
    const t = tenantInput.trim()
    if (!t) return
    setTenantId(t)
    localStorage.setItem('miragent_default_tenant', t)
  }

  async function sendMessage(text?: string) {
    const question = (text ?? input).trim()
    if (!question || loading) return
    if (!tenantId) {
      alert('Set a tenant ID above first.')
      return
    }

    setInput('')
    setShowSuggestions(false)

    const userMsg: Message = {
      id: nextId(),
      role: 'user',
      content: question,
      ts: Date.now(),
    }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const resp = await api.copilotAsk(token, tenantId, question)
      const assistantMsg: Message = {
        id: nextId(),
        role: 'assistant',
        content: resp.answer,
        intent: resp.intent,
        sources: resp.sources,
        llm_provider: resp.llm_provider,
        suggested_actions: resp.suggested_actions,
        ts: Date.now(),
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (e: unknown) {
      const errMsg: Message = {
        id: nextId(),
        role: 'assistant',
        content: e instanceof Error ? e.message : 'Something went wrong. Please try again.',
        error: true,
        ts: Date.now(),
      }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }

  function clearChat() {
    setMessages([])
    setShowSuggestions(true)
  }

  return (
    <div className="flex flex-col h-[calc(100vh-80px)] max-w-3xl mx-auto">

      {/* ── Header ── */}
      <div className="mb-4 flex-shrink-0">
        <div className="flex items-center gap-2 mb-1">
          <Sparkles size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Copilot</h1>
        </div>
        <p className="text-gray-500 text-sm">Ask anything about your portfolio company in plain English.</p>
      </div>

      {/* ── Tenant selector ── */}
      <div className="bg-white border border-gray-100 rounded-xl shadow-sm px-4 py-3 mb-4 flex-shrink-0">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Company</p>
        <div className="flex gap-2">
          <input
            type="text"
            value={tenantInput}
            onChange={e => setTenantInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && applyTenant()}
            placeholder="Tenant ID (e.g. acme-corp)"
            className="flex-1 px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <button
            onClick={applyTenant}
            className="px-3 py-1.5 text-sm font-medium text-white rounded-lg transition-opacity"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            Set
          </button>
          {messages.length > 0 && (
            <button
              onClick={clearChat}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50"
            >
              <RefreshCw size={13} /> Clear
            </button>
          )}
        </div>
        {tenantId && (
          <p className="text-xs text-emerald-600 mt-1.5">
            ✓ Asking about <strong>{tenantId}</strong>
          </p>
        )}
      </div>

      {/* ── Message list ── */}
      <div className="flex-1 overflow-y-auto space-y-4 px-1 pb-2">

        {/* Welcome state */}
        {messages.length === 0 && (
          <div className="text-center py-8">
            <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ backgroundColor: '#1B2A4A' }}>
              <Sparkles size={28} className="text-white" />
            </div>
            <h2 className="text-lg font-semibold text-gray-800 mb-1">Miragent Copilot</h2>
            <p className="text-sm text-gray-400 max-w-sm mx-auto">
              Ask about pipeline health, churn risk, headcount, vendor spend, or any aspect of your portfolio company.
            </p>
          </div>
        )}

        {/* Suggested questions */}
        {showSuggestions && messages.length === 0 && tenantId && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Suggested questions</p>
              <button onClick={() => setShowSuggestions(false)} className="text-gray-300 hover:text-gray-500">
                <ChevronDown size={12} />
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {SUGGESTED.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  disabled={loading}
                  className="text-left px-4 py-2.5 bg-white border border-gray-100 rounded-xl text-sm text-gray-600 hover:border-gray-300 hover:shadow-sm transition-all disabled:opacity-40"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages */}
        {messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} tenantId={tenantId} token={token} />
        ))}

        {/* Typing indicator */}
        {loading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: '#1B2A4A' }}>
              <Bot size={14} className="text-white" />
            </div>
            <div className="bg-white border border-gray-100 shadow-sm rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1 items-center">
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ── */}
      <div className="flex-shrink-0 pt-3 pb-1">
        {!tenantId && (
          <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 mb-3">
            <AlertCircle size={14} className="text-amber-600 flex-shrink-0" />
            <p className="text-xs text-amber-700">Set a tenant ID above to start asking questions.</p>
          </div>
        )}
        <div className="flex gap-2 bg-white border border-gray-200 rounded-2xl shadow-sm px-4 py-2 focus-within:border-gray-300 focus-within:shadow-md transition-all">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && sendMessage()}
            placeholder={tenantId ? 'Ask anything about your portfolio company…' : 'Set a tenant ID first…'}
            disabled={loading || !tenantId}
            className="flex-1 text-sm text-gray-800 placeholder-gray-400 bg-transparent focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={() => sendMessage()}
            disabled={loading || !input.trim() || !tenantId}
            className="flex items-center justify-center w-8 h-8 rounded-xl text-white transition-opacity disabled:opacity-30 flex-shrink-0"
            style={{ backgroundColor: '#1B2A4A' }}
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          </button>
        </div>
        <p className="text-xs text-gray-300 text-center mt-2">
          Answers are synthesised from live graph data and intelligence runs.
        </p>
      </div>
    </div>
  )
}
