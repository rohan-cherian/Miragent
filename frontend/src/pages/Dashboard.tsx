import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  Cpu,
  GitBranch,
  Bot,
  ArrowRight,
  CheckCircle,
  XCircle,
  TrendingDown,
  Key,
  DollarSign,
} from 'lucide-react'
import { api } from '../api/client'

interface StatCard {
  icon: React.ReactNode
  value: string
  label: string
  sub: string
}

const capabilities = [
  { sprint: 'Sprint 4', label: 'Revenue Optimization', done: true },
  { sprint: 'Sprint 5', label: 'EBITDA Optimization', done: true },
  { sprint: 'Sprint 6', label: 'Full Funnel Intelligence', done: true },
  { sprint: 'Sprint 7', label: 'Process Mining', done: true },
  { sprint: 'Sprint 9', label: 'Revenue Agents', done: true },
  { sprint: 'Sprint 10', label: 'Ops Agents', done: true },
  { sprint: 'Sprint 13', label: 'Security & Rate Limiting', done: true },
  { sprint: 'Sprint 15', label: 'Multi-Tenant Auth & Users', done: true },
  { sprint: 'Sprint 16', label: 'LLM Narrative (Claude API)', done: true },
  { sprint: 'Sprint 17', label: 'Rich Mock Data (25+ Systems)', done: true },
  { sprint: 'Sprint 18', label: 'Vendor Benchmark Intelligence', done: true },
  { sprint: 'Sprint 19', label: 'Live Dashboard + Vendor UI + Auth', done: true },
]

const quickLinks = [
  {
    icon: <GitBranch size={16} className="text-blue-500" />,
    title: 'Run a Scan',
    desc: 'Ingest and deduplicate CRM data across all connectors.',
    to: '/scans',
    label: 'Go to Scans',
  },
  {
    icon: <Bot size={16} className="text-purple-500" />,
    title: 'Generate Insights',
    desc: 'Run 32 AI workers and get an executive memo.',
    to: '/insights',
    label: 'Go to Insights',
  },
  {
    icon: <TrendingDown size={16} className="text-emerald-500" />,
    title: 'Vendor Benchmarks',
    desc: 'Surface spend vs. market rates and negotiation windows.',
    to: '/vendor-benchmarks',
    label: 'View Benchmarks',
  },
  {
    icon: <Key size={16} className="text-amber-500" />,
    title: 'User Management',
    desc: 'Register users, login, and manage API keys.',
    to: '/users',
    label: 'Manage Users',
  },
]

export default function Dashboard() {
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>('checking')
  const [environment, setEnvironment] = useState<string>('')

  useEffect(() => {
    api
      .health()
      .then((h) => {
        setApiStatus('online')
        setEnvironment(h.environment ?? '')
      })
      .catch(() => setApiStatus('offline'))
  }, [])

  const statCards: StatCard[] = [
    {
      icon: <Cpu className="text-blue-400" size={22} />,
      value: '32',
      label: 'Intelligence Workers',
      sub: 'Revenue · EBITDA · Funnel · Ops · Vendor',
    },
    {
      icon: <GitBranch className="text-emerald-400" size={22} />,
      value: '25+',
      label: 'Mock Connectors',
      sub: 'SFDC · Workday · NetSuite · Okta · Jira + more',
    },
    {
      icon: <DollarSign className="text-amber-400" size={22} />,
      value: '59',
      label: 'Vendor Catalog Entries',
      sub: 'B2B SaaS market rates + negotiation tips',
    },
    {
      icon: <Activity className="text-purple-400" size={22} />,
      value: environment ? environment.charAt(0).toUpperCase() + environment.slice(1) : 'Live',
      label: 'Environment',
      sub: 'Neo4j knowledge graph + SQLite auth DB',
    },
  ]

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1 text-base">Agentic CIO in a Box — Sprint 19</p>
        </div>
        <div className="flex items-center gap-2 mt-1">
          {apiStatus === 'checking' && (
            <span className="flex items-center gap-1.5 text-sm text-gray-400 bg-gray-100 px-3 py-1.5 rounded-full">
              <span className="w-2 h-2 rounded-full bg-gray-400 animate-pulse" />
              Checking API…
            </span>
          )}
          {apiStatus === 'online' && (
            <span className="flex items-center gap-1.5 text-sm text-emerald-700 bg-emerald-50 px-3 py-1.5 rounded-full border border-emerald-200">
              <CheckCircle size={14} />
              API Connected
            </span>
          )}
          {apiStatus === 'offline' && (
            <span className="flex items-center gap-1.5 text-sm text-red-700 bg-red-50 px-3 py-1.5 rounded-full border border-red-200">
              <XCircle size={14} />
              API Offline — run <code className="mx-1 bg-red-100 px-1 rounded text-xs">poetry run uvicorn scout.api.app:app</code>
            </span>
          )}
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-4 gap-5 mb-8">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="bg-white rounded-xl border border-gray-100 shadow-sm p-5"
          >
            <div className="flex items-center gap-3 mb-3">
              <div className="w-9 h-9 rounded-lg bg-gray-50 flex items-center justify-center">
                {card.icon}
              </div>
              <span className="text-2xl font-bold text-gray-900">{card.value}</span>
            </div>
            <p className="text-sm font-semibold text-gray-700">{card.label}</p>
            <p className="text-xs text-gray-400 mt-0.5">{card.sub}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Quick Links */}
        <div className="col-span-2 bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Quick Start</h2>
          <p className="text-sm text-gray-500 mb-5">
            Four entry points to the Miragent platform.
          </p>
          <div className="grid grid-cols-2 gap-4">
            {quickLinks.map((link) => (
              <div
                key={link.to}
                className="p-4 rounded-xl border border-gray-100 bg-gray-50 hover:bg-gray-100 transition-colors"
              >
                <div className="flex items-center gap-2 mb-2">
                  {link.icon}
                  <p className="text-sm font-semibold text-gray-800">{link.title}</p>
                </div>
                <p className="text-xs text-gray-500 mb-3 leading-relaxed">{link.desc}</p>
                <Link
                  to={link.to}
                  className="inline-flex items-center gap-1 text-xs font-medium hover:underline"
                  style={{ color: '#1B2A4A' }}
                >
                  {link.label} <ArrowRight size={12} />
                </Link>
              </div>
            ))}
          </div>
        </div>

        {/* Sprint Capabilities */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6 overflow-y-auto max-h-[500px]">
          <h2 className="text-lg font-semibold text-gray-900 mb-1">Sprint Capabilities</h2>
          <p className="text-sm text-gray-500 mb-4">All 19 sprints deployed ✓</p>
          <ul className="space-y-2.5">
            {capabilities.map((cap) => (
              <li key={cap.sprint} className="flex items-center gap-2.5">
                <CheckCircle size={15} className="text-emerald-500 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-gray-800">{cap.label}</p>
                  <p className="text-xs text-gray-400">{cap.sprint}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
