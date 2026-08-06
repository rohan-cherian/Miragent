import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Brain, RefreshCw, Cpu, Settings, TrendingDown, Users, ShieldCheck, ListTodo, ActivitySquare, LayoutGrid, FileSearch, Receipt, Gauge, KeyRound, Headphones, CreditCard, HeartPulse, Truck, FileCheck, BarChart3, Wand2, MessageSquare, Database, Bell, Activity, Sparkles } from 'lucide-react'

interface NavItem {
  to: string
  icon: React.ReactNode
  label: string
}

const onboardingNavItems: NavItem[] = [
  { to: '/design-session',   icon: <Wand2 size={18} />,    label: 'Design Session' },
  { to: '/knowledge-base',   icon: <Database size={18} />, label: 'Knowledge Base' },
]

const operationsNavItems: NavItem[] = [
  { to: '/mission-control', icon: <Gauge size={18} />, label: 'Mission Control' },
]

const coreNavItems: NavItem[] = [
  { to: '/', icon: <LayoutDashboard size={18} />, label: 'Dashboard' },
  { to: '/insights', icon: <Brain size={18} />, label: 'Insights' },
  { to: '/vendor-benchmarks', icon: <TrendingDown size={18} />, label: 'Vendor Benchmarks' },
  { to: '/scans', icon: <RefreshCw size={18} />, label: 'Scans' },
  { to: '/workers', icon: <Cpu size={18} />, label: 'Workers' },
  { to: '/approvals', icon: <ShieldCheck size={18} />, label: 'Approvals' },
  { to: '/actions', icon: <ListTodo size={18} />, label: 'Actions' },
  { to: '/intelligence', icon: <ActivitySquare size={18} />, label: 'Intelligence' },
  { to: '/portfolio', icon: <LayoutGrid size={18} />, label: 'Portfolio' },
  { to: '/copilot',   icon: <Sparkles size={18} />, label: 'Copilot' },
  { to: '/users', icon: <Users size={18} />, label: 'User Management' },
  { to: '/settings', icon: <Settings size={18} />, label: 'Settings' },
]

const executiveNavItems: NavItem[] = [
  { to: '/board-report', icon: <BarChart3 size={18} />, label: 'Board Report' },
]

const agentNavItems: NavItem[] = [
  { to: '/ddq', icon: <FileSearch size={18} />, label: 'DDQ Agent v2' },
  { to: '/payroll-agent', icon: <Receipt size={18} />, label: 'Payroll Documents' },
  { to: '/portal-access', icon: <KeyRound size={18} />, label: 'Portal Access' },
  { to: '/support-triage', icon: <Headphones size={18} />, label: 'Support Triage' },
  { to: '/payment-status', icon: <CreditCard size={18} />, label: 'Payment Status' },
  { to: '/benefits', icon: <HeartPulse size={18} />, label: 'Benefits' },
  { to: '/vendor-onboarding', icon: <Truck size={18} />, label: 'Vendor Onboarding' },
  { to: '/it-access', icon: <ShieldCheck size={18} />, label: 'IT Access' },
  { to: '/compliance-response', icon: <FileCheck size={18} />, label: 'Compliance Response' },
]

const intelligenceNavItems: NavItem[] = [
  { to: '/communications', icon: <MessageSquare size={18} />, label: 'Communications' },
]

function NavItemLink({ item }: { item: NavItem }) {
  return (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        [
          'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150',
          isActive
            ? 'bg-white/15 text-white'
            : 'text-gray-300 hover:bg-white/10 hover:text-white',
        ].join(' ')
      }
    >
      <span className="flex-shrink-0">{item.icon}</span>
      <span>{item.label}</span>
    </NavLink>
  )
}

export default function Sidebar() {
  return (
    <div
      className="fixed top-0 left-0 h-screen w-60 flex flex-col z-50"
      style={{ backgroundColor: '#1B2A4A' }}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-6 border-b border-white/10">
        <div className="w-9 h-9 rounded-lg bg-white/15 flex items-center justify-center flex-shrink-0">
          <span className="text-white font-bold text-lg leading-none">M</span>
        </div>
        <div>
          <span className="text-white font-semibold text-base leading-tight tracking-wide">
            Miragent
          </span>
          <p className="text-gray-400 text-xs leading-tight mt-0.5">Scout</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-1">
        {/* Notifications — top-level standalone item */}
        <div className="pb-2">
          <NavLink
            to="/notifications"
            className={({ isActive }) =>
              [
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150',
                isActive
                  ? 'bg-white/15 text-white'
                  : 'text-gray-300 hover:bg-white/10 hover:text-white',
              ].join(' ')
            }
          >
            <span className="flex-shrink-0">
              <Bell size={18} />
            </span>
            <span className="flex-1">Notifications</span>
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-red-500 text-white text-xs font-bold flex-shrink-0">
              8
            </span>
          </NavLink>

          {/* Health Score — standalone top item */}
          <NavLink
            to="/health-score"
            className={({ isActive }) =>
              [
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-150',
                isActive
                  ? 'bg-white/15 text-white'
                  : 'text-gray-300 hover:bg-white/10 hover:text-white',
              ].join(' ')
            }
          >
            <span className="flex-shrink-0">
              <Activity size={18} />
            </span>
            <span>Health Score</span>
          </NavLink>
        </div>

        {/* Onboarding section */}
        <div className="pb-2">
          <p className="px-3 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Onboarding
          </p>
          {onboardingNavItems.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>

        {/* Operations section */}
        <div className="pb-2">
          <p className="px-3 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Operations
          </p>
          {operationsNavItems.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>

        {coreNavItems.map((item) => (
          <NavItemLink key={item.to} item={item} />
        ))}

        {/* Executive section */}
        <div className="pt-4">
          <p className="px-3 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Executive
          </p>
          {executiveNavItems.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>

        {/* Agents section */}
        <div className="pt-4">
          <p className="px-3 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Agents
          </p>
          {agentNavItems.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>

        {/* Intelligence section */}
        <div className="pt-4">
          <p className="px-3 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Intelligence
          </p>
          {intelligenceNavItems.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </div>
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-white/10">
        <p className="text-gray-500 text-xs">v0.83.0 — Sprint 83</p>
      </div>
    </div>
  )
}
