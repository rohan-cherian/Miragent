/**
 * Intelligence.tsx — Sprint 51
 *
 * The signal/noise intelligence panel. Shows:
 *   Tab 1 — Worker Signal Scores: which workers are generating actionable
 *            findings vs. noise, how the WIP cap has been auto-adjusted.
 *   Tab 2 — Threshold Proposals: AI-generated suggestions to recalibrate
 *            worker thresholds based on 30-day dismiss patterns. Admin can
 *            accept (applies change immediately) or reject (keeps current).
 *
 * This is the "it learns" page. It makes visible the feedback loop that
 * most AI platforms don't have: when your team dismisses a finding as noise,
 * the system notices and proposes raising the bar — reducing alert fatigue
 * over time without manual configuration.
 *
 * The backend model:
 *   signal_score = acted / (acted + dismissed)   ← 1.0 = pure signal
 *   dismissed_rate > 60% over 30 days → generates a ThresholdProposal
 *   accepted proposals write to WorkerConfig → next scan uses new threshold
 */

import { useEffect, useState } from 'react'
import {
  Brain,
  TrendingUp,
  TrendingDown,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  ArrowRight,
  Zap,
  AlertTriangle,
  Info,
} from 'lucide-react'
import { api } from '../api/client'
import type { NoiseProfile, ThresholdProposal } from '../types'

// ── Helpers ────────────────────────────────────────────────

function workerLabel(name: string) {
  return name.replace(/Worker$/, '').replace(/([A-Z])/g, ' $1').trim()
}

function pct(n: number) {
  return `${Math.round(n * 100)}%`
}

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function signalColor(score: number) {
  if (score >= 0.7) return { bar: '#2ECC71', label: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-200' }
  if (score >= 0.4) return { bar: '#F39C12', label: 'text-yellow-600', bg: 'bg-yellow-50 border-yellow-200' }
  return { bar: '#E74C3C', label: 'text-red-600', bg: 'bg-red-50 border-red-200' }
}

function confidenceBadge(confidence: number) {
  const pctStr = pct(confidence)
  if (confidence >= 0.7) return <span className="text-xs font-medium text-emerald-600">{pctStr} confidence</span>
  if (confidence >= 0.4) return <span className="text-xs font-medium text-yellow-600">{pctStr} confidence</span>
  return <span className="text-xs font-medium text-gray-400">{pctStr} confidence</span>
}

// ── Signal score bar ───────────────────────────────────────

function SignalBar({ score }: { score: number }) {
  const colors = signalColor(score)
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="w-24 h-2 bg-gray-100 rounded-full overflow-hidden flex-shrink-0">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${Math.round(score * 100)}%`, backgroundColor: colors.bar }}
        />
      </div>
      <span className={`text-xs font-semibold ${colors.label}`}>{pct(score)}</span>
    </div>
  )
}

// ── Noise profile row ──────────────────────────────────────

function ProfileRow({ profile }: { profile: NoiseProfile }) {
  const colors = signalColor(profile.signal_score)
  const isEmpty = profile.total_surfaced === 0

  return (
    <tr className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
      <td className="px-4 py-3">
        <div className="text-sm font-medium text-gray-800">{workerLabel(profile.worker_name)}</div>
        <div className="text-xs text-gray-400 mt-0.5 font-mono">{profile.worker_name}</div>
      </td>
      <td className="px-4 py-3">
        {isEmpty
          ? <span className="text-xs text-gray-400">No data yet</span>
          : <SignalBar score={profile.signal_score} />
        }
      </td>
      <td className="px-4 py-3 text-xs text-gray-600 text-right">
        {isEmpty ? '—' : pct(profile.dismissed_rate)}
      </td>
      <td className="px-4 py-3 text-xs text-gray-600 text-right">
        {isEmpty ? '—' : pct(profile.acted_rate)}
      </td>
      <td className="px-4 py-3 text-xs text-gray-500 text-right">
        {isEmpty ? '—' : profile.total_surfaced}
      </td>
      <td className="px-4 py-3 text-right">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${isEmpty ? 'bg-gray-50 text-gray-400 border-gray-200' : colors.bg + ' ' + colors.label}`}>
          {isEmpty ? 'Pending' : `Cap: ${profile.active_action_cap}`}
        </span>
      </td>
    </tr>
  )
}

// ── Proposal card ──────────────────────────────────────────

function ProposalCard({
  proposal,
  token,
  onRefresh,
}: {
  proposal: ThresholdProposal
  token: string | null
  onRefresh: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const isPending = proposal.status === 'PENDING'

  async function handle(action: 'accept' | 'reject') {
    if (!token) return
    setBusy(true)
    setError('')
    try {
      if (action === 'accept') {
        await api.acceptProposal(token, proposal.id)
      } else {
        await api.rejectProposal(token, proposal.id)
      }
      onRefresh()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const changeDir = proposal.proposed_value > proposal.current_value ? 'up' : 'down'
  const changePct = Math.abs((proposal.proposed_value - proposal.current_value) / proposal.current_value * 100).toFixed(1)

  return (
    <div className={`bg-white rounded-xl border shadow-sm overflow-hidden ${
      isPending ? 'border-blue-200' : 'border-gray-100'
    }`}>
      <div className="flex items-start justify-between gap-4 p-4">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="flex-shrink-0 mt-0.5">
            {proposal.status === 'ACCEPTED' && <CheckCircle2 size={16} className="text-emerald-500" />}
            {proposal.status === 'REJECTED' && <XCircle size={16} className="text-red-400" />}
            {isPending && <AlertTriangle size={16} className="text-yellow-500" />}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-sm font-semibold text-gray-800">
                {workerLabel(proposal.worker_name)}
              </p>
              <span className="text-xs font-mono bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                {proposal.threshold_key}
              </span>
              <span className={`text-xs font-medium ${proposal.status === 'ACCEPTED' ? 'text-emerald-600' : proposal.status === 'REJECTED' ? 'text-red-400' : 'text-blue-600'}`}>
                {proposal.status}
              </span>
            </div>

            {/* Current → Proposed */}
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-xs text-gray-500 font-mono">{proposal.current_value}</span>
              <ArrowRight size={12} className="text-gray-400 flex-shrink-0" />
              <span className={`text-xs font-semibold font-mono ${changeDir === 'up' ? 'text-orange-600' : 'text-emerald-600'}`}>
                {proposal.proposed_value}
              </span>
              <span className="text-xs text-gray-400">
                ({changeDir === 'up' ? '+' : '-'}{changePct}% · {pct(proposal.dismissed_rate)} dismissed)
              </span>
              {confidenceBadge(proposal.confidence)}
            </div>
            <p className="text-xs text-gray-400 mt-1">Proposed {fmtDate(proposal.created_at)}</p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          {isPending && (
            <>
              <button
                onClick={() => handle('reject')}
                disabled={busy}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 text-xs font-medium hover:bg-gray-50 disabled:opacity-50 transition-colors"
              >
                <XCircle size={12} />
                Reject
              </button>
              <button
                onClick={() => handle('accept')}
                disabled={busy}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-white text-xs font-medium disabled:opacity-50 transition-colors"
                style={{ backgroundColor: '#2ECC71' }}
              >
                {busy ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                Accept
              </button>
            </>
          )}
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-gray-400 hover:text-gray-600 flex-shrink-0"
          >
            {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        </div>
      </div>

      {error && <p className="px-4 pb-3 text-xs text-red-600">{error}</p>}

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50">
          <p className="text-xs font-medium text-gray-500 mb-2">AI Rationale</p>
          <p className="text-xs text-gray-700 leading-relaxed">{proposal.rationale}</p>
          <p className="text-xs text-gray-400 mt-2 font-mono">ID: {proposal.id}</p>
        </div>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────

type Tab = 'profiles' | 'proposals'

export default function Intelligence() {
  const [tab, setTab] = useState<Tab>('profiles')
  const [profiles, setProfiles] = useState<NoiseProfile[]>([])
  const [proposals, setProposals] = useState<ThresholdProposal[]>([])
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [refreshResult, setRefreshResult] = useState<string | null>(null)
  const token = localStorage.getItem('miragent_token')

  async function loadProfiles() {
    setLoading(true)
    setError('')
    try {
      const data = await api.listNoiseProfiles(token ?? '')
      setProfiles(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function loadProposals() {
    setLoading(true)
    setError('')
    try {
      const data = await api.listProposals(token ?? '')
      setProposals(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  async function runRefresh() {
    if (!token) return
    setRefreshing(true)
    setRefreshResult(null)
    try {
      const res = await api.refreshNoiseProfiles(token)
      const parts: string[] = []
      if (res.profiles_seeded > 0) parts.push(`initialized ${res.profiles_seeded} baseline profile${res.profiles_seeded !== 1 ? 's' : ''}`)
      if (res.profiles_updated > 0) parts.push(`updated ${res.profiles_updated} profile${res.profiles_updated !== 1 ? 's' : ''} from live data`)
      if (res.proposals_created > 0) parts.push(`created ${res.proposals_created} new proposal${res.proposals_created !== 1 ? 's' : ''}`)
      if (parts.length === 0) parts.push('all profiles are current')
      setRefreshResult(parts.join(' · ') + '.')
      await loadProfiles()
      await loadProposals()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    loadProfiles()
    loadProposals()
  }, [])

  const pendingCount = proposals.filter(p => p.status === 'PENDING').length
  const noisyWorkers = profiles.filter(p => p.signal_score < 0.4 && p.total_surfaced > 0).length

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Signal Intelligence</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            How well each worker's findings are being acted on — and how the platform self-calibrates.
            {noisyWorkers > 0 && (
              <span className="ml-2 bg-red-100 text-red-700 border border-red-200 text-xs font-semibold px-2 py-0.5 rounded-full">
                {noisyWorkers} noisy worker{noisyWorkers !== 1 ? 's' : ''}
              </span>
            )}
            {pendingCount > 0 && (
              <span className="ml-2 bg-blue-100 text-blue-700 border border-blue-200 text-xs font-semibold px-2 py-0.5 rounded-full">
                {pendingCount} pending proposal{pendingCount !== 1 ? 's' : ''}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={runRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Run noise scan
        </button>
      </div>

      {/* Refresh result */}
      {refreshResult && (
        <div className="mb-4 p-3 bg-emerald-50 border border-emerald-100 rounded-lg text-sm text-emerald-700 flex items-center gap-2">
          <CheckCircle2 size={15} />
          {refreshResult}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-gray-100 rounded-lg p-1 w-fit">
        <button
          onClick={() => setTab('profiles')}
          className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            tab === 'profiles' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          Worker Scores
        </button>
        <button
          onClick={() => setTab('proposals')}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            tab === 'proposals' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          Threshold Proposals
          {pendingCount > 0 && (
            <span className="bg-blue-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
              {pendingCount}
            </span>
          )}
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 size={24} className="animate-spin" />
        </div>
      )}

      {/* ── Worker Scores tab ──────────────────────────────── */}
      {!loading && tab === 'profiles' && (
        <>
          {profiles.length === 0 ? (
            <div className="text-center py-16">
              <Brain size={40} className="mx-auto text-gray-200 mb-3" />
              <p className="text-sm font-medium text-gray-500">No signal profiles yet</p>
              <p className="text-xs text-gray-400 mt-1 max-w-xs mx-auto">
                Click <span className="font-medium text-gray-600">"Run noise scan"</span> to initialize
                baseline profiles for all 32 workers. Scores will update as findings are acted on or dismissed.
              </p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-left">Worker</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-left">Signal Score</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-right">Dismissed</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-right">Acted</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-right">Surfaced</th>
                    <th className="px-4 py-3 text-xs font-semibold text-gray-500 text-right">WIP Cap</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map(p => <ProfileRow key={p.worker_name} profile={p} />)}
                </tbody>
              </table>
            </div>
          )}

          {/* Legend */}
          <div className="mt-4 flex items-start gap-6 text-xs text-gray-400">
            <span className="flex items-center gap-1.5"><TrendingUp size={12} className="text-emerald-500" /> ≥70% signal — well-calibrated</span>
            <span className="flex items-center gap-1.5"><Zap size={12} className="text-yellow-500" /> 40–70% — monitor</span>
            <span className="flex items-center gap-1.5"><TrendingDown size={12} className="text-red-500" /> &lt;40% — noisy, proposal likely</span>
          </div>
        </>
      )}

      {/* ── Proposals tab ─────────────────────────────────── */}
      {!loading && tab === 'proposals' && (
        <>
          {proposals.length === 0 ? (
            <div className="text-center py-16">
              <Brain size={40} className="mx-auto text-gray-200 mb-3" />
              <p className="text-sm font-medium text-gray-500">No threshold proposals</p>
              <p className="text-xs text-gray-400 mt-1">
                Proposals appear when a worker's dismiss rate exceeds 60% over 30 days.
                Run a noise scan to generate proposals from existing disposition data.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {proposals.map(p => (
                <ProposalCard key={p.id} proposal={p} token={token} onRefresh={() => { loadProposals(); loadProfiles() }} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Explainer */}
      <div className="mt-8 p-4 bg-blue-50 border border-blue-100 rounded-xl">
        <p className="text-xs font-semibold text-blue-700 mb-1 flex items-center gap-1.5">
          <Info size={13} />
          How the signal/noise feedback loop works
        </p>
        <p className="text-xs text-blue-600 leading-relaxed">
          Every time a finding is acted on or dismissed, that signal is recorded.
          Over a rolling 30-day window, Miragent computes a signal score per worker —
          the fraction of decisive interactions that resulted in action vs. dismissal.
          Workers below 40% signal trigger an AI proposal to raise their detection threshold,
          reducing finding volume to match what your team actually considers actionable.
          Accepting a proposal applies the change immediately; the next scan uses the new value.
          Nothing changes without your explicit approval.
        </p>
      </div>
    </div>
  )
}
