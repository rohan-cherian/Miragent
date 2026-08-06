import React, { Suspense } from 'react'
import { Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'

const MissionControl = React.lazy(() => import('./pages/MissionControl'))
const Dashboard = React.lazy(() => import('./pages/Dashboard'))
const Insights = React.lazy(() => import('./pages/Insights'))
const VendorBenchmarks = React.lazy(() => import('./pages/VendorBenchmarks'))
const Scans = React.lazy(() => import('./pages/Scans'))
const Workers = React.lazy(() => import('./pages/Workers'))
const Approvals = React.lazy(() => import('./pages/Approvals'))
const Actions = React.lazy(() => import('./pages/Actions'))
const Intelligence = React.lazy(() => import('./pages/Intelligence'))
const UserManagement = React.lazy(() => import('./pages/UserManagement'))
const Settings = React.lazy(() => import('./pages/Settings'))
const Portfolio = React.lazy(() => import('./pages/Portfolio'))
const DDQ = React.lazy(() => import('./pages/DDQ'))
const PayrollAgent = React.lazy(() => import('./pages/PayrollAgent'))
const PortalAccessAgent = React.lazy(() => import('./pages/PortalAccessAgent'))
const SupportTriage = React.lazy(() => import('./pages/SupportTriage'))
const PaymentStatus = React.lazy(() => import('./pages/PaymentStatus'))
const Benefits = React.lazy(() => import('./pages/Benefits'))
const VendorOnboarding = React.lazy(() => import('./pages/VendorOnboarding'))
const ITAccess = React.lazy(() => import('./pages/ITAccess'))
const ComplianceResponse = React.lazy(() => import('./pages/ComplianceResponse'))
const BoardReport = React.lazy(() => import('./pages/BoardReport'))
const DesignSession = React.lazy(() => import('./pages/DesignSession'))
const Communications = React.lazy(() => import('./pages/Communications'))
const KnowledgeBase = React.lazy(() => import('./pages/KnowledgeBase'))
const NotificationCenter = React.lazy(() => import('./pages/NotificationCenter'))
const HealthScore = React.lazy(() => import('./pages/HealthScore'))
const Copilot = React.lazy(() => import('./pages/Copilot'))
const Login = React.lazy(() => import('./pages/Login'))

function PageSpinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <div
        className="w-8 h-8 border-4 border-t-transparent rounded-full animate-spin"
        style={{ borderColor: '#1B2A4A', borderTopColor: 'transparent' }}
      />
    </div>
  )
}

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="ml-60 flex-1 p-8 min-h-screen bg-gray-50">
        <Suspense fallback={<PageSpinner />}>
          <Routes>
            <Route path="/mission-control" element={<MissionControl />} />
            <Route path="/" element={<Dashboard />} />
            <Route path="/insights" element={<Insights />} />
            <Route path="/vendor-benchmarks" element={<VendorBenchmarks />} />
            <Route path="/scans" element={<Scans />} />
            <Route path="/workers" element={<Workers />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/actions" element={<Actions />} />
            <Route path="/intelligence" element={<Intelligence />} />
            <Route path="/users" element={<UserManagement />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/ddq" element={<DDQ />} />
            <Route path="/payroll-agent" element={<PayrollAgent />} />
            <Route path="/portal-access" element={<PortalAccessAgent />} />
            <Route path="/support-triage" element={<SupportTriage />} />
            <Route path="/payment-status" element={<PaymentStatus />} />
            <Route path="/benefits" element={<Benefits />} />
            <Route path="/vendor-onboarding" element={<VendorOnboarding />} />
            <Route path="/it-access" element={<ITAccess />} />
            <Route path="/compliance-response" element={<ComplianceResponse />} />
            <Route path="/board-report" element={<BoardReport />} />
            <Route path="/design-session" element={<DesignSession />} />
            <Route path="/communications" element={<Communications />} />
            <Route path="/knowledge-base" element={<KnowledgeBase />} />
            <Route path="/notifications" element={<NotificationCenter />} />
            <Route path="/health-score" element={<HealthScore />} />
            <Route path="/copilot" element={<Copilot />} />
            <Route path="/login" element={<Login />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  )
}
