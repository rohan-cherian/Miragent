/* Route registry wiring — Spec §6.3. Deep links restore exact screen state;
   an unauthenticated deep link goes to S-14 with ?next= and continues after the
   role pick. The stub never silently upgrades a role. */

import React from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { SessionProvider, useSession } from './shell/session.jsx'
import { ToastProvider } from './ui/feedback.jsx'
import Shell from './shell/Shell.jsx'

import Login from './screens/Login.jsx'
import Dashboard from './screens/Dashboard.jsx'
import Queue from './screens/Queue.jsx'
import Tickets from './screens/Tickets.jsx'
import Case360 from './screens/Case360.jsx'
import Audit from './screens/Audit.jsx'
import Knowledge from './screens/Knowledge.jsx'
import Digest from './screens/Digest.jsx'
import Connections from './screens/Connections.jsx'
import Demo from './screens/Demo.jsx'
import KitchenSink from './screens/KitchenSink.jsx'
import { EmptyState } from './ui/feedback.jsx'

function RequireRole({ children }) {
  const { role } = useSession()
  const loc = useLocation()
  if (!role) {
    const next = encodeURIComponent(loc.pathname + loc.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <Shell>{children}</Shell>
}

function Home() {
  const { meta } = useSession()
  return <Navigate to={meta?.home || '/overview'} replace />
}

export default function App() {
  return (
    <SessionProvider>
      <ToastProvider>
        <Routes>
          <Route path="/login" element={<Login />} />

          <Route path="/" element={<RequireRole><Home /></RequireRole>} />
          <Route path="/overview" element={<RequireRole><Dashboard /></RequireRole>} />
          <Route path="/queue" element={<RequireRole><Queue /></RequireRole>} />
          <Route path="/tickets" element={<RequireRole><Tickets /></RequireRole>} />
          <Route path="/case/:id" element={<RequireRole><Case360 /></RequireRole>} />
          <Route path="/audit" element={<RequireRole><Audit /></RequireRole>} />
          <Route path="/knowledge" element={<RequireRole><Knowledge /></RequireRole>} />
          <Route path="/intelligence" element={<RequireRole><Digest /></RequireRole>} />
          <Route path="/connections" element={<RequireRole><Connections tab="systems" /></RequireRole>} />
          <Route path="/connections/identity" element={<RequireRole><Connections tab="identity" /></RequireRole>} />
          <Route path="/demo/connect/:step" element={<RequireRole><Demo /></RequireRole>} />

          {/* Component library reference — reviewable, not a product surface. */}
          <Route path="/kitchen-sink" element={<RequireRole><KitchenSink /></RequireRole>} />

          <Route path="*" element={
            <RequireRole>
              <div className="page">
                <EmptyState icon="∅" title="No such screen"
                            message="This route is not in the registry. Every product surface is reachable from the left nav." />
              </div>
            </RequireRole>
          } />
        </Routes>
      </ToastProvider>
    </SessionProvider>
  )
}
