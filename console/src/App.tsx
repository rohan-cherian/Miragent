import { Navigate, Route, Routes } from 'react-router-dom'
import { RequireAuth } from './auth/RequireAuth'
import { ShellLayout } from './layout/ShellLayout'
import { LoginPage } from './pages/LoginPage'
import {
  ApprovalsPage,
  AuditPage,
  CallPlayerPage,
  ConnectionsPage,
  ContextPage,
  CorpusPage,
  DigestPage,
  ExplainersPage,
  HomePage,
  KbReviewPage,
  RecommendationPage,
  Ticket360Page,
} from './pages/screens'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<RequireAuth />}>
        <Route element={<ShellLayout />}>
          <Route index element={<Navigate to="/corpus" replace />} />
          <Route path="home" element={<HomePage />} />
          <Route path="connections" element={<ConnectionsPage />} />
          <Route path="corpus" element={<CorpusPage />} />
          <Route path="ticket-360" element={<Ticket360Page />} />
          <Route path="context" element={<ContextPage />} />
          <Route path="explainers" element={<ExplainersPage />} />
          <Route path="recommendation" element={<RecommendationPage />} />
          <Route path="call-player" element={<CallPlayerPage />} />
          <Route path="approvals" element={<ApprovalsPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="kb-review" element={<KbReviewPage />} />
          <Route path="digest" element={<DigestPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/corpus" replace />} />
    </Routes>
  )
}
