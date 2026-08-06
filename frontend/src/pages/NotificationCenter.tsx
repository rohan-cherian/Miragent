import { useState, useEffect, useCallback } from 'react'
import {
  Bell,
  AlertTriangle,
  ClipboardCheck,
  UserX,
  Calendar,
  Bot,
  Server,
  X,
  ArrowRight,
  CheckCheck,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Notification, NotificationSummary } from '../api/client'

const DEFAULT_TENANT_KEY = 'miragent_default_tenant'
const DEFAULT_TENANT = 'acme-corp'

// ── Config maps ────────────────────────────────────────────────────────────────

const SEVERITY_BAR: Record<string, string> = {
  critical: 'bg-red-500',
  high:     'bg-orange-400',
  medium:   'bg-yellow-400',
  low:      'bg-blue-400',
  info:     'bg-gray-300',
}

const SEVERITY_BORDER: Record<string, string> = {
  critical: 'border-l-red-500',
  high:     'border-l-orange-400',
  medium:   'border-l-yellow-400',
  low:      'border-l-blue-400',
  info:     'border-l-gray-300',
}

const UNREAD_BG: Record<string, string> = {
  critical: 'bg-red-50',
  high:     'bg-orange-50',
  medium:   'bg-yellow-50',
  low:      'bg-blue-50',
  info:     'bg-gray-50',
}

type FilterTab = 'all' | 'unread' | 'critical' | 'approval' | 'churn_risk' | 'agent_action'

const FILTER_TABS: { key: FilterTab; label: string }[] = [
  { key: 'all',          label: 'All' },
  { key: 'unread',       label: 'Unread' },
  { key: 'critical',     label: 'Critical' },
  { key: 'approval',     label: 'Approvals' },
  { key: 'churn_risk',   label: 'Churn Risk' },
  { key: 'agent_action', label: 'Agent Activity' },
]

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatRelative(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    if (hrs < 48) return 'yesterday'
    return `${Math.floor(hrs / 24)}d ago`
  } catch {
    return '—'
  }
}

function CategoryIcon({ category, size = 16 }: { category: string; size?: number }) {
  const cls = `flex-shrink-0`
  switch (category) {
    case 'finding':      return <AlertTriangle size={size} className={`${cls} text-red-500`} />
    case 'approval':     return <ClipboardCheck size={size} className={`${cls} text-orange-500`} />
    case 'churn_risk':   return <UserX size={size} className={`${cls} text-rose-500`} />
    case 'renewal':      return <Calendar size={size} className={`${cls} text-blue-500`} />
    case 'agent_action': return <Bot size={size} className={`${cls} text-emerald-500`} />
    case 'system':       return <Server size={size} className={`${cls} text-gray-500`} />
    default:             return <Bell size={size} className={`${cls} text-gray-400`} />
  }
}

// ── Notification card ──────────────────────────────────────────────────────────

function NotificationCard({
  notification,
  onRead,
  onDismiss,
}: {
  notification: Notification
  onRead: (id: string) => void
  onDismiss: (id: string) => void
}) {
  const navigate = useNavigate()
  const isUnread = !notification.is_read
  const barColor = SEVERITY_BAR[notification.severity] ?? 'bg-gray-300'
  const borderColor = SEVERITY_BORDER[notification.severity] ?? 'border-l-gray-300'
  const bgColor = isUnread ? (UNREAD_BG[notification.severity] ?? 'bg-gray-50') : 'bg-white'

  function handleCardClick() {
    if (isUnread) onRead(notification.id)
  }

  function handleActionClick(e: React.MouseEvent) {
    e.stopPropagation()
    if (isUnread) onRead(notification.id)
    navigate(notification.action_url)
  }

  function handleDismiss(e: React.MouseEvent) {
    e.stopPropagation()
    onDismiss(notification.id)
  }

  return (
    <div
      onClick={handleCardClick}
      className={`relative flex gap-0 rounded-xl border border-gray-200 shadow-sm overflow-hidden cursor-pointer
        hover:shadow-md transition-shadow border-l-4 ${borderColor} ${bgColor}`}
    >
      {/* Left severity bar */}
      <div className={`w-1 flex-shrink-0 ${barColor}`} />

      <div className="flex-1 p-4 min-w-0">
        {/* Header row */}
        <div className="flex items-start gap-3">
          <div className="mt-0.5">
            <CategoryIcon category={notification.category} size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <p className={`text-sm leading-snug ${isUnread ? 'font-semibold text-gray-900' : 'font-medium text-gray-700'}`}>
              {notification.title}
            </p>
            <p className="text-xs text-gray-500 mt-1 line-clamp-2 leading-relaxed">
              {notification.body}
            </p>
          </div>
          {/* Dismiss button */}
          <button
            onClick={handleDismiss}
            className="flex-shrink-0 p-1 rounded hover:bg-gray-200 transition-colors text-gray-400 hover:text-gray-600"
            title="Dismiss"
          >
            <X size={14} />
          </button>
        </div>

        {/* Footer row */}
        <div className="flex items-center justify-between mt-3 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-xs font-medium bg-gray-100 text-gray-600 px-2 py-0.5 rounded-md truncate max-w-[160px]">
              {notification.source_agent}
            </span>
            <span className="text-xs text-gray-400 flex-shrink-0">
              {formatRelative(notification.created_at)}
            </span>
          </div>
          <button
            onClick={handleActionClick}
            className="flex items-center gap-1 flex-shrink-0 text-xs font-semibold text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 px-2.5 py-1 rounded-lg border border-blue-100 transition-colors"
          >
            {notification.action_label}
            <ArrowRight size={11} />
          </button>
        </div>
      </div>

      {/* Unread indicator dot */}
      {isUnread && (
        <div className="absolute top-3 right-10 w-2 h-2 rounded-full bg-blue-500" />
      )}
    </div>
  )
}

// ── Summary sidebar ────────────────────────────────────────────────────────────

function SummarySidebar({
  summary,
  topPriority,
  onReadTopPriority,
  onDismissTopPriority,
}: {
  summary: NotificationSummary | null
  topPriority: Notification | null
  onReadTopPriority: (id: string) => void
  onDismissTopPriority: (id: string) => void
}) {
  const navigate = useNavigate()

  return (
    <div className="w-60 flex-shrink-0 space-y-4">
      {/* Today's Snapshot */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h2 className="text-sm font-bold text-gray-900 mb-3">Today's Snapshot</h2>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-base">🔴</span>
            <span className="text-sm text-gray-700">
              <span className="font-bold text-gray-900">{summary?.critical_unread ?? 0}</span> Critical unread
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-base">🟠</span>
            <span className="text-sm text-gray-700">
              <span className="font-bold text-gray-900">{summary?.by_category['approval'] ?? 0}</span> Approvals pending
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-base">🟡</span>
            <span className="text-sm text-gray-700">
              <span className="font-bold text-gray-900">{summary?.by_category['churn_risk'] ?? 0}</span> Churn signals
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-base">🟢</span>
            <span className="text-sm text-gray-700">
              <span className="font-bold text-gray-900">{summary?.by_category['agent_action'] ?? 0}</span> Agent actions today
            </span>
          </div>
        </div>
      </div>

      {/* Top Priority */}
      {topPriority && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
          <h2 className="text-sm font-bold text-gray-900 mb-3">Top Priority</h2>
          <div
            className={`rounded-lg border border-l-4 p-3 cursor-pointer hover:shadow-sm transition-shadow
              ${SEVERITY_BORDER[topPriority.severity] ?? 'border-l-gray-300'}
              ${!topPriority.is_read ? (UNREAD_BG[topPriority.severity] ?? 'bg-gray-50') : 'bg-white'}`}
            onClick={() => { if (!topPriority.is_read) onReadTopPriority(topPriority.id) }}
          >
            <div className="flex items-start gap-2 mb-2">
              <CategoryIcon category={topPriority.category} size={14} />
              <p className={`text-xs leading-snug ${!topPriority.is_read ? 'font-semibold' : 'font-medium'} text-gray-900`}>
                {topPriority.title}
              </p>
              <button
                onClick={(e) => { e.stopPropagation(); onDismissTopPriority(topPriority.id) }}
                className="flex-shrink-0 p-0.5 rounded hover:bg-gray-200 text-gray-400"
              >
                <X size={12} />
              </button>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation()
                if (!topPriority.is_read) onReadTopPriority(topPriority.id)
                navigate(topPriority.action_url)
              }}
              className="flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700"
            >
              {topPriority.action_label} <ArrowRight size={10} />
            </button>
          </div>
        </div>
      )}

      {/* Quick Links */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h2 className="text-sm font-bold text-gray-900 mb-3">Quick Links</h2>
        <div className="space-y-1.5">
          <button
            onClick={() => navigate('/insights')}
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-100 transition-colors"
          >
            Run Scout Scan <ArrowRight size={11} className="text-gray-400" />
          </button>
          <button
            onClick={() => navigate('/it-access')}
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-100 transition-colors"
          >
            Open Approvals <ArrowRight size={11} className="text-gray-400" />
          </button>
          <button
            onClick={() => navigate('/communications')}
            className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 rounded-lg border border-gray-100 transition-colors"
          >
            View Communications <ArrowRight size={11} className="text-gray-400" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function NotificationCenter() {
  const [tenantId] = useState(
    () => localStorage.getItem(DEFAULT_TENANT_KEY) ?? DEFAULT_TENANT
  )

  const [notifications, setNotifications] = useState<Notification[]>([])
  const [summary, setSummary] = useState<NotificationSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeFilter, setActiveFilter] = useState<FilterTab>('all')
  const [markingAllRead, setMarkingAllRead] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [notifs, sum] = await Promise.all([
        api.notifications.list(tenantId),
        api.notifications.summary(tenantId),
      ])
      setNotifications(notifs)
      setSummary(sum)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load notifications')
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => {
    loadData()
  }, [loadData])

  async function handleMarkRead(id: string) {
    try {
      await api.notifications.markRead(id, tenantId)
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      )
      setSummary((prev) =>
        prev
          ? {
              ...prev,
              total_unread: Math.max(0, prev.total_unread - 1),
            }
          : prev
      )
    } catch (e) {
      console.error('markRead failed', e)
    }
  }

  async function handleDismiss(id: string) {
    try {
      await api.notifications.dismiss(id, tenantId)
      setNotifications((prev) => prev.filter((n) => n.id !== id))
      // Refresh summary to get accurate counts
      const sum = await api.notifications.summary(tenantId)
      setSummary(sum)
    } catch (e) {
      console.error('dismiss failed', e)
    }
  }

  async function handleMarkAllRead() {
    setMarkingAllRead(true)
    try {
      await api.notifications.markAllRead(tenantId)
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })))
      setSummary((prev) =>
        prev ? { ...prev, total_unread: 0, critical_unread: 0, by_category: {} } : prev
      )
    } catch (e) {
      console.error('markAllRead failed', e)
    } finally {
      setMarkingAllRead(false)
    }
  }

  // ── Filtering ──────────────────────────────────────────────────────────────

  const filtered = notifications.filter((n) => {
    switch (activeFilter) {
      case 'unread':       return !n.is_read
      case 'critical':     return n.severity === 'critical'
      case 'approval':     return n.category === 'approval'
      case 'churn_risk':   return n.category === 'churn_risk'
      case 'agent_action': return n.category === 'agent_action'
      default:             return true
    }
  })

  const unreadCount = summary?.total_unread ?? 0
  const topPriority = summary?.top_priority ?? null

  // ── Render ─────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div
          className="w-10 h-10 border-4 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: '#1B2A4A', borderTopColor: 'transparent' }}
        />
        <p className="text-gray-500 text-sm">Loading Notification Center…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-6 py-5">
        <p className="font-semibold">Error loading notifications</p>
        <p className="text-sm mt-1">{error}</p>
        <button
          onClick={loadData}
          className="mt-3 px-4 py-2 text-sm font-medium bg-red-600 text-white rounded-lg hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="-m-8 min-h-screen bg-gray-50">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="px-8 py-6 flex items-center justify-between" style={{ backgroundColor: '#1B2A4A' }}>
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-white/10 flex items-center justify-center">
            <Bell size={22} className="text-white" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-white leading-tight">Notification Center</h1>
              {unreadCount > 0 && (
                <span className="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded-full bg-red-500 text-white text-xs font-bold">
                  {unreadCount}
                </span>
              )}
            </div>
            <p className="text-gray-400 text-sm mt-0.5">Morning briefing — {tenantId}</p>
          </div>
        </div>
        <button
          onClick={handleMarkAllRead}
          disabled={markingAllRead || unreadCount === 0}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <CheckCheck size={15} />
          Mark all read
        </button>
      </div>

      <div className="px-8 py-6 flex gap-6 items-start">
        {/* ── Main feed ────────────────────────────────────────────────────── */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Filter tabs */}
          <div className="flex items-center gap-1 bg-white rounded-xl border border-gray-200 shadow-sm p-1">
            {FILTER_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveFilter(tab.key)}
                className={`flex-1 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                  activeFilter === tab.key
                    ? 'bg-gray-900 text-white'
                    : 'text-gray-600 hover:bg-gray-100'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Feed */}
          {filtered.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm py-16 text-center">
              <Bell size={32} className="text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500 text-sm font-medium">No notifications</p>
              <p className="text-gray-400 text-xs mt-1">
                {activeFilter === 'all' ? "You're all caught up." : 'No items match this filter.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {filtered.map((n) => (
                <NotificationCard
                  key={n.id}
                  notification={n}
                  onRead={handleMarkRead}
                  onDismiss={handleDismiss}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Summary sidebar ───────────────────────────────────────────────── */}
        <SummarySidebar
          summary={summary}
          topPriority={topPriority}
          onReadTopPriority={handleMarkRead}
          onDismissTopPriority={handleDismiss}
        />
      </div>
    </div>
  )
}
