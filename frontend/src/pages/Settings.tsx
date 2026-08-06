import { useState, useEffect } from 'react'
import { Settings as SettingsIcon, Edit2, Check, X, ExternalLink, ShieldCheck, ShieldOff, QrCode, Loader2, KeyRound, Plus, Trash2, Cloud } from 'lucide-react'
import { api } from '../api/client'
import type { RealConnectorStatus } from '../api/client'

const DEFAULT_TENANT = 'acme-corp'
const LOCAL_STORAGE_KEY = 'miragent_default_tenant'

interface Sprint {
  number: number
  label: string
  status: 'complete' | 'upcoming'
}

const sprints: Sprint[] = [
  { number: 1,  label: 'Project Setup & Infrastructure', status: 'complete' },
  { number: 2,  label: 'Data Ingestion Pipeline', status: 'complete' },
  { number: 3,  label: 'Graph Schema & Neo4j Integration', status: 'complete' },
  { number: 4,  label: 'Revenue Optimization Workers', status: 'complete' },
  { number: 5,  label: 'EBITDA Optimization Workers', status: 'complete' },
  { number: 6,  label: 'Full Funnel Intelligence', status: 'complete' },
  { number: 7,  label: 'Process Mining', status: 'complete' },
  { number: 8,  label: 'Executive Memo & Narrative AI (Claude API)', status: 'complete' },
  { number: 9,  label: 'Revenue Agents', status: 'complete' },
  { number: 10, label: 'Ops Agents', status: 'complete' },
  { number: 11, label: 'Scout Dashboard Frontend', status: 'complete' },
  { number: 12, label: 'Polish & QA', status: 'complete' },
  { number: 13, label: 'Security, Rate Limiting & Audit Logging', status: 'complete' },
  { number: 14, label: 'Enterprise Connectors (31 Systems)', status: 'complete' },
  { number: 15, label: 'Multi-Tenant User Auth & API Keys', status: 'complete' },
  { number: 16, label: 'LLM Narrative (Claude API, Graceful Fallback)', status: 'complete' },
  { number: 17, label: 'Rich Mock Data & Expanded Sample Records', status: 'complete' },
  { number: 18, label: 'Vendor Benchmark Intelligence (59 Tools)', status: 'complete' },
  { number: 19, label: 'Live Dashboard + Vendor UI + Auth Management', status: 'complete' },
  { number: 20, label: 'Agentic UI — Approvals & Actions Inbox', status: 'complete' },
  { number: 51, label: 'Signal/Noise Intelligence UI', status: 'complete' },
  { number: 52, label: 'Full Stack Deployment (Fly.io + Vercel + Neo4j Aura)', status: 'complete' },
  { number: 53, label: 'Complete Threshold Registry — All 32 Workers', status: 'complete' },
  { number: 54, label: 'Signal/Noise Admin API — Baseline Profile Seeding', status: 'complete' },
  { number: 55, label: 'MFA (TOTP) — Two-Factor Authentication', status: 'complete' },
  { number: 56, label: 'Portfolio Dashboard — Fund-Level Multi-Tenant View', status: 'complete' },
  { number: 57, label: 'DORA Metrics & GitHub Velocity Workers', status: 'complete' },
  { number: 58, label: 'Enterprise SSO — OIDC / Okta / Azure AD', status: 'complete' },
]

function SectionHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}

type MfaStep = 'idle' | 'setup' | 'verify' | 'disable'

interface SSOProvider {
  id: string
  provider_slug: string
  display_name: string
  provider_type: string
  issuer_url: string
  client_id: string
  domains: string[]
  jit_provisioning: boolean
  default_role: string
  is_active: boolean
}

const SSO_TYPE_LABELS: Record<string, string> = {
  oidc: 'Generic OIDC',
  azure_ad: 'Azure AD / Entra ID',
  google: 'Google Workspace',
}

export default function Settings() {
  const [tenantId, setTenantId] = useState(DEFAULT_TENANT)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(DEFAULT_TENANT)

  // MFA state
  const [mfaEnabled, setMfaEnabled] = useState(false)
  const [mfaStep, setMfaStep] = useState<MfaStep>('idle')
  const [mfaQr, setMfaQr] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [mfaPassword, setMfaPassword] = useState('')
  const [mfaError, setMfaError] = useState('')
  const [mfaLoading, setMfaLoading] = useState(false)
  const [mfaSuccess, setMfaSuccess] = useState('')

  // SSO state
  const [ssoProviders, setSsoProviders] = useState<SSOProvider[]>([])
  const [ssoLoading, setSsoLoading] = useState(false)
  const [ssoError, setSsoError] = useState('')
  const [showSsoForm, setShowSsoForm] = useState(false)
  const [ssoForm, setSsoForm] = useState({
    provider_slug: '',
    display_name: '',
    provider_type: 'oidc',
    issuer_url: '',
    client_id: '',
    client_secret: '',
    domains: '',        // comma-separated
    jit_provisioning: true,
    default_role: 'viewer',
  })
  const [ssoFormLoading, setSsoFormLoading] = useState(false)
  const [ssoFormError, setSsoFormError] = useState('')

  // Integrations state (Sprint 83)
  const [sfConnector, setSfConnector] = useState<RealConnectorStatus | null>(null)
  const [sfLoading, setSfLoading] = useState(false)
  const [sfTestResult, setSfTestResult] = useState<{ connected: boolean; error?: string } | null>(null)
  const [sfTestLoading, setSfTestLoading] = useState(false)
  const [sfDisconnecting, setSfDisconnecting] = useState(false)

  const token = localStorage.getItem('miragent_token') ?? ''

  useEffect(() => {
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY)
    if (stored) {
      setTenantId(stored)
      setDraft(stored)
    }
    if (token) {
      api.mfaStatus(token).then(r => setMfaEnabled(r.mfa_enabled)).catch(() => {})
      loadSSOProviders()
      loadConnectors()
    }
  }, [])

  async function loadSSOProviders() {
    if (!token) return
    setSsoLoading(true)
    try {
      const providers = await api.listSSOProviders(token)
      setSsoProviders(providers)
    } catch {
      // Not an admin — silently ignore
    } finally {
      setSsoLoading(false)
    }
  }

  async function loadConnectors() {
    if (!token) return
    setSfLoading(true)
    try {
      const list = await api.connectorsList(token)
      const sf = list.find(c => c.connector_id === 'salesforce') ?? null
      setSfConnector(sf)
    } catch {
      // Not admin or API unavailable — silently skip
    } finally {
      setSfLoading(false)
    }
  }

  async function connectSalesforce() {
    try {
      const { auth_url } = await api.connectorsSalesforceAuthUrl(token, tenantId)
      window.open(auth_url, '_blank', 'noopener,noreferrer')
    } catch {
      // fallback: navigate directly
      window.location.href = `/api/connectors/salesforce/auth-start?tenant_id=${encodeURIComponent(tenantId)}`
    }
  }

  async function disconnectSalesforce() {
    setSfDisconnecting(true)
    try {
      await api.connectorsSalesforceDisconnect(token, tenantId)
      await loadConnectors()
      setSfTestResult(null)
    } finally {
      setSfDisconnecting(false)
    }
  }

  async function testSalesforce() {
    setSfTestLoading(true)
    setSfTestResult(null)
    try {
      const result = await api.connectorsSalesforceTest(token, tenantId)
      setSfTestResult(result)
      await loadConnectors()
    } catch (e: unknown) {
      setSfTestResult({ connected: false, error: e instanceof Error ? e.message : 'Test failed' })
    } finally {
      setSfTestLoading(false)
    }
  }

  async function submitSSOProvider() {
    setSsoFormLoading(true)
    setSsoFormError('')
    try {
      const domains = ssoForm.domains
        .split(',')
        .map(d => d.trim().toLowerCase())
        .filter(Boolean)
      await api.createSSOProvider(token, {
        ...ssoForm,
        domains,
      })
      setShowSsoForm(false)
      setSsoForm({
        provider_slug: '', display_name: '', provider_type: 'oidc',
        issuer_url: '', client_id: '', client_secret: '',
        domains: '', jit_provisioning: true, default_role: 'viewer',
      })
      await loadSSOProviders()
    } catch (e: unknown) {
      setSsoFormError(e instanceof Error ? e.message : 'Failed to configure provider')
    } finally {
      setSsoFormLoading(false)
    }
  }

  async function removeSSOProvider(id: string) {
    try {
      await api.deleteSSOProvider(token, id)
      setSsoProviders(prev => prev.filter(p => p.id !== id))
    } catch (e: unknown) {
      setSsoError(e instanceof Error ? e.message : 'Failed to remove provider')
    }
  }

  async function startMfaSetup() {
    setMfaLoading(true)
    setMfaError('')
    setMfaSuccess('')
    try {
      const res = await api.mfaSetup(token)
      setMfaQr(res.qr_image_base64)
      setMfaStep('setup')
    } catch (e: unknown) {
      setMfaError(e instanceof Error ? e.message : 'Setup failed')
    } finally {
      setMfaLoading(false)
    }
  }

  async function verifyMfa() {
    if (!mfaCode.trim()) return
    setMfaLoading(true)
    setMfaError('')
    try {
      await api.mfaVerify(token, mfaCode.trim())
      setMfaEnabled(true)
      setMfaStep('idle')
      setMfaQr(null)
      setMfaCode('')
      setMfaSuccess('Two-factor authentication enabled successfully.')
    } catch (e: unknown) {
      setMfaError(e instanceof Error ? e.message : 'Invalid code — try again')
    } finally {
      setMfaLoading(false)
    }
  }

  async function disableMfa() {
    if (!mfaCode.trim() || !mfaPassword.trim()) return
    setMfaLoading(true)
    setMfaError('')
    try {
      await api.mfaDisable(token, mfaCode.trim(), mfaPassword)
      setMfaEnabled(false)
      setMfaStep('idle')
      setMfaCode('')
      setMfaPassword('')
      setMfaSuccess('Two-factor authentication has been disabled.')
    } catch (e: unknown) {
      setMfaError(e instanceof Error ? e.message : 'Incorrect code or password')
    } finally {
      setMfaLoading(false)
    }
  }

  function startEdit() {
    setDraft(tenantId)
    setEditing(true)
  }

  function saveEdit() {
    const val = draft.trim() || DEFAULT_TENANT
    setTenantId(val)
    localStorage.setItem(LOCAL_STORAGE_KEY, val)
    setEditing(false)
  }

  function cancelEdit() {
    setDraft(tenantId)
    setEditing(false)
  }

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <SettingsIcon size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        </div>
        <p className="text-gray-500">Configure Miragent Scout for your environment.</p>
      </div>

      <div className="space-y-6">
        {/* Tenant Configuration */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <SectionHeading
            title="Tenant Configuration"
            subtitle="The default tenant ID used across Insights and Scans."
          />
          <div className="flex items-center gap-3">
            {editing ? (
              <>
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') saveEdit()
                    if (e.key === 'Escape') cancelEdit()
                  }}
                  autoFocus
                  className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-900"
                />
                <button
                  onClick={saveEdit}
                  className="p-2 rounded-lg bg-emerald-50 hover:bg-emerald-100 text-emerald-600 transition-colors"
                  title="Save"
                >
                  <Check size={16} />
                </button>
                <button
                  onClick={cancelEdit}
                  className="p-2 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-500 transition-colors"
                  title="Cancel"
                >
                  <X size={16} />
                </button>
              </>
            ) : (
              <>
                <div className="flex-1 px-3 py-2 text-sm bg-gray-50 border border-gray-100 rounded-lg text-gray-700 font-mono">
                  {tenantId}
                </div>
                <button
                  onClick={startEdit}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <Edit2 size={13} />
                  Edit
                </button>
              </>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-2">Saved to browser localStorage.</p>
        </div>

        {/* API Configuration */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <SectionHeading
            title="API Configuration"
            subtitle="Backend connection settings for the Scout API."
          />
          <div className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">API Base URL</label>
              <div className="px-3 py-2 text-sm bg-gray-50 border border-gray-100 rounded-lg text-gray-700 font-mono">
                http://localhost:8000
              </div>
            </div>
            <div className="p-3 bg-blue-50 rounded-lg border border-blue-100">
              <p className="text-xs text-blue-700">
                <strong>Note:</strong> Configure the API base URL via the{' '}
                <code className="bg-blue-100 px-1 rounded">VITE_API_BASE</code> environment variable
                in your <code className="bg-blue-100 px-1 rounded">.env</code> file.
                The Vite dev server proxies <code className="bg-blue-100 px-1 rounded">/api/*</code>{' '}
                to the backend automatically.
              </p>
            </div>
          </div>
        </div>

        {/* Sprint Roadmap */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <SectionHeading
            title="Sprint Roadmap"
            subtitle="20-sprint delivery plan for the Miragent platform."
          />
          <div className="rounded-lg border border-gray-100 overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-left w-20">Sprint</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-left">Capability</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-right">Status</th>
                </tr>
              </thead>
              <tbody>
                {sprints.map((sprint, idx) => (
                  <tr
                    key={sprint.number}
                    className={`border-b border-gray-50 ${idx === sprints.length - 1 ? 'border-b-0' : ''}`}
                  >
                    <td className="px-4 py-2.5 text-xs font-mono text-gray-400">
                      S{sprint.number.toString().padStart(2, '0')}
                    </td>
                    <td className="px-4 py-2.5 text-sm text-gray-700">{sprint.label}</td>
                    <td className="px-4 py-2.5 text-right">
                      {sprint.status === 'complete' ? (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-100">
                          Complete
                        </span>
                      ) : (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-400 border border-gray-200">
                          Upcoming
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Two-Factor Authentication */}
        {token && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <SectionHeading
              title="Two-Factor Authentication"
              subtitle="Add a second layer of security using an authenticator app (Google Authenticator, Authy)."
            />

            {mfaSuccess && (
              <div className="mb-4 flex items-center gap-2 p-3 bg-emerald-50 border border-emerald-100 rounded-lg text-sm text-emerald-700">
                <Check size={15} /> {mfaSuccess}
              </div>
            )}

            {/* Status row */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                {mfaEnabled
                  ? <ShieldCheck size={18} className="text-emerald-500" />
                  : <ShieldOff size={18} className="text-gray-400" />
                }
                <span className="text-sm font-medium text-gray-700">
                  {mfaEnabled ? 'Two-factor authentication is ON' : 'Two-factor authentication is OFF'}
                </span>
              </div>
              {mfaStep === 'idle' && (
                mfaEnabled
                  ? (
                    <button
                      onClick={() => { setMfaStep('disable'); setMfaError(''); setMfaCode(''); setMfaPassword('') }}
                      className="text-xs font-medium text-red-600 hover:text-red-700 px-3 py-1.5 rounded-lg border border-red-200 hover:bg-red-50 transition-colors"
                    >
                      Disable MFA
                    </button>
                  ) : (
                    <button
                      onClick={startMfaSetup}
                      disabled={mfaLoading}
                      className="flex items-center gap-1.5 text-xs font-medium text-white px-3 py-1.5 rounded-lg disabled:opacity-50 transition-opacity"
                      style={{ backgroundColor: '#1B2A4A' }}
                    >
                      {mfaLoading ? <Loader2 size={13} className="animate-spin" /> : <QrCode size={13} />}
                      Set up MFA
                    </button>
                  )
              )}
            </div>

            {/* Setup step — show QR code */}
            {mfaStep === 'setup' && mfaQr && (
              <div className="border border-gray-100 rounded-lg p-4 bg-gray-50">
                <p className="text-sm font-semibold text-gray-800 mb-2">Scan with your authenticator app</p>
                <p className="text-xs text-gray-500 mb-4">Open Google Authenticator or Authy, tap the + button, and scan the QR code below.</p>
                <img
                  src={`data:image/png;base64,${mfaQr}`}
                  alt="MFA QR Code"
                  className="w-40 h-40 mx-auto mb-4 rounded border border-gray-200"
                />
                <p className="text-xs text-gray-600 mb-2 font-medium">Enter the 6-digit code from your app to confirm:</p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={mfaCode}
                    onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
                    onKeyDown={e => e.key === 'Enter' && verifyMfa()}
                    placeholder="000000"
                    className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-navy-900"
                  />
                  <button
                    onClick={verifyMfa}
                    disabled={mfaLoading || mfaCode.length !== 6}
                    className="px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50"
                    style={{ backgroundColor: '#1B2A4A' }}
                  >
                    {mfaLoading ? <Loader2 size={14} className="animate-spin" /> : 'Verify'}
                  </button>
                  <button onClick={() => { setMfaStep('idle'); setMfaQr(null); setMfaCode('') }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                </div>
              </div>
            )}

            {/* Disable step — require code + password */}
            {mfaStep === 'disable' && (
              <div className="border border-red-100 rounded-lg p-4 bg-red-50">
                <p className="text-sm font-semibold text-red-700 mb-1">Disable two-factor authentication</p>
                <p className="text-xs text-red-500 mb-3">This reduces your account security. Enter your authenticator code and password to confirm.</p>
                <div className="space-y-2 mb-3">
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    value={mfaCode}
                    onChange={e => setMfaCode(e.target.value.replace(/\D/g, ''))}
                    placeholder="6-digit code from authenticator"
                    className="w-full px-3 py-2 text-sm border border-red-200 rounded-lg font-mono focus:outline-none"
                  />
                  <input
                    type="password"
                    value={mfaPassword}
                    onChange={e => setMfaPassword(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && disableMfa()}
                    placeholder="Your password"
                    className="w-full px-3 py-2 text-sm border border-red-200 rounded-lg focus:outline-none"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={disableMfa}
                    disabled={mfaLoading || mfaCode.length !== 6 || !mfaPassword}
                    className="px-4 py-2 text-sm font-semibold text-white bg-red-600 rounded-lg disabled:opacity-50 hover:bg-red-700"
                  >
                    {mfaLoading ? <Loader2 size={14} className="animate-spin" /> : 'Confirm disable'}
                  </button>
                  <button onClick={() => { setMfaStep('idle'); setMfaCode(''); setMfaPassword('') }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">Cancel</button>
                </div>
              </div>
            )}

            {mfaError && (
              <p className="mt-3 text-xs text-red-600 flex items-center gap-1"><X size={12} /> {mfaError}</p>
            )}
          </div>
        )}

        {/* SSO Configuration */}
        {token && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <div className="flex items-start justify-between mb-4">
              <SectionHeading
                title="Enterprise SSO"
                subtitle="Configure OIDC identity providers (Okta, Azure AD, Google Workspace). Admin only."
              />
              {!showSsoForm && (
                <button
                  onClick={() => { setShowSsoForm(true); setSsoFormError('') }}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg"
                  style={{ backgroundColor: '#1B2A4A' }}
                >
                  <Plus size={13} /> Add Provider
                </button>
              )}
            </div>

            {ssoError && (
              <p className="mb-3 text-xs text-red-600 flex items-center gap-1"><X size={12} /> {ssoError}</p>
            )}

            {/* Existing providers */}
            {ssoLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
                <Loader2 size={14} className="animate-spin" /> Loading providers…
              </div>
            ) : ssoProviders.length === 0 && !showSsoForm ? (
              <div className="py-8 text-center border border-dashed border-gray-200 rounded-lg">
                <KeyRound size={24} className="mx-auto text-gray-300 mb-2" />
                <p className="text-sm text-gray-400">No SSO providers configured</p>
                <p className="text-xs text-gray-300 mt-1">Add an OIDC provider to enable enterprise single sign-on</p>
              </div>
            ) : (
              <div className="space-y-3 mb-4">
                {ssoProviders.map(p => (
                  <div key={p.id} className="flex items-start justify-between p-3 bg-gray-50 border border-gray-100 rounded-lg">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-gray-800">{p.display_name}</span>
                        <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded border border-blue-100 font-mono">
                          {SSO_TYPE_LABELS[p.provider_type] ?? p.provider_type}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 mt-0.5 font-mono">{p.issuer_url}</p>
                      {p.domains.length > 0 && (
                        <p className="text-xs text-gray-500 mt-1">
                          Domains: {p.domains.join(', ')}
                        </p>
                      )}
                      <p className="text-xs text-gray-400 mt-0.5">
                        JIT provisioning: {p.jit_provisioning ? 'enabled' : 'disabled'} · Default role: {p.default_role}
                      </p>
                    </div>
                    <button
                      onClick={() => removeSSOProvider(p.id)}
                      className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                      title="Remove provider"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Add provider form */}
            {showSsoForm && (
              <div className="border border-gray-200 rounded-lg p-4 bg-gray-50 space-y-3">
                <p className="text-sm font-semibold text-gray-800">Configure OIDC Provider</p>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Provider slug *</label>
                    <input
                      type="text"
                      placeholder="e.g. okta"
                      value={ssoForm.provider_slug}
                      onChange={e => setSsoForm(f => ({ ...f, provider_slug: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Display name *</label>
                    <input
                      type="text"
                      placeholder="e.g. Acme Corp Okta"
                      value={ssoForm.display_name}
                      onChange={e => setSsoForm(f => ({ ...f, display_name: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Provider type</label>
                  <select
                    value={ssoForm.provider_type}
                    onChange={e => setSsoForm(f => ({ ...f, provider_type: e.target.value }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none bg-white"
                  >
                    <option value="oidc">Generic OIDC</option>
                    <option value="azure_ad">Azure AD / Entra ID</option>
                    <option value="google">Google Workspace</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Issuer URL *</label>
                  <input
                    type="url"
                    placeholder="https://acme.okta.com/oauth2/default"
                    value={ssoForm.issuer_url}
                    onChange={e => setSsoForm(f => ({ ...f, issuer_url: e.target.value }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 font-mono"
                  />
                  <p className="text-xs text-gray-400 mt-0.5">
                    Miragent will fetch <code className="bg-gray-100 px-0.5 rounded">{'{issuer}/.well-known/openid-configuration'}</code> to validate.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Client ID *</label>
                    <input
                      type="text"
                      value={ssoForm.client_id}
                      onChange={e => setSsoForm(f => ({ ...f, client_id: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-500 mb-1">Client Secret *</label>
                    <input
                      type="password"
                      value={ssoForm.client_secret}
                      onChange={e => setSsoForm(f => ({ ...f, client_secret: e.target.value }))}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Email domains (comma-separated)</label>
                  <input
                    type="text"
                    placeholder="acmecorp.com, acme.io"
                    value={ssoForm.domains}
                    onChange={e => setSsoForm(f => ({ ...f, domains: e.target.value }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={ssoForm.jit_provisioning}
                      onChange={e => setSsoForm(f => ({ ...f, jit_provisioning: e.target.checked }))}
                      className="rounded"
                    />
                    JIT provisioning (auto-create users on first SSO login)
                  </label>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-500 mb-1">Default role for new users</label>
                  <select
                    value={ssoForm.default_role}
                    onChange={e => setSsoForm(f => ({ ...f, default_role: e.target.value }))}
                    className="px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none bg-white"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                {ssoFormError && (
                  <p className="text-xs text-red-600 flex items-center gap-1"><X size={12} /> {ssoFormError}</p>
                )}
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={submitSSOProvider}
                    disabled={ssoFormLoading || !ssoForm.provider_slug || !ssoForm.display_name || !ssoForm.issuer_url || !ssoForm.client_id || !ssoForm.client_secret}
                    className="px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50"
                    style={{ backgroundColor: '#1B2A4A' }}
                  >
                    {ssoFormLoading ? <Loader2 size={14} className="animate-spin inline" /> : 'Save Provider'}
                  </button>
                  <button
                    onClick={() => { setShowSsoForm(false); setSsoFormError('') }}
                    className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
              <p className="text-xs text-blue-700">
                <strong>Callback URL to register with your IdP:</strong>{' '}
                <code className="bg-blue-100 px-1 rounded font-mono">
                  http://localhost:8000/auth/sso/callback
                </code>
                {' '}— update to your production API URL before go-live.
              </p>
            </div>
          </div>
        )}

        {/* Integrations (Sprint 83) */}
        {token && (
          <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
            <SectionHeading
              title="Integrations"
              subtitle="Connect production data sources. Admin only."
            />

            {sfLoading ? (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
                <Loader2 size={14} className="animate-spin" /> Loading connectors…
              </div>
            ) : (
              <div className="border border-gray-100 rounded-lg p-4">
                {/* Salesforce card */}
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center border border-blue-100">
                      <Cloud size={18} className="text-blue-500" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-800">Salesforce CRM</p>
                      <p className="text-xs text-gray-400">OAuth2 Connected App</p>
                      {sfConnector?.connected_at && (
                        <p className="text-xs text-gray-400 mt-0.5">
                          Connected {new Date(sfConnector.connected_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {sfConnector?.is_connected ? (
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 border border-emerald-100">
                        Connected
                      </span>
                    ) : (
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-gray-100 text-gray-400 border border-gray-200">
                        Not connected
                      </span>
                    )}
                  </div>
                </div>

                {/* Last error */}
                {sfConnector?.last_error && (
                  <div className="mt-3 p-2 bg-red-50 border border-red-100 rounded text-xs text-red-600">
                    Last error: {sfConnector.last_error}
                  </div>
                )}

                {/* Test result */}
                {sfTestResult !== null && (
                  <div className={`mt-3 p-2 rounded text-xs border ${sfTestResult.connected ? 'bg-emerald-50 border-emerald-100 text-emerald-700' : 'bg-red-50 border-red-100 text-red-600'}`}>
                    {sfTestResult.connected
                      ? 'Connection test passed — Salesforce API is reachable.'
                      : `Test failed: ${sfTestResult.error ?? 'Unknown error'}`}
                  </div>
                )}

                {/* Actions */}
                <div className="mt-4 flex items-center gap-2 flex-wrap">
                  {sfConnector?.is_connected ? (
                    <>
                      <button
                        onClick={testSalesforce}
                        disabled={sfTestLoading}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
                      >
                        {sfTestLoading ? <Loader2 size={12} className="animate-spin" /> : null}
                        Test Connection
                      </button>
                      <button
                        onClick={disconnectSalesforce}
                        disabled={sfDisconnecting}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
                      >
                        {sfDisconnecting ? <Loader2 size={12} className="animate-spin" /> : null}
                        Disconnect
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={connectSalesforce}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white rounded-lg transition-colors"
                      style={{ backgroundColor: '#1B2A4A' }}
                    >
                      <Cloud size={12} />
                      Connect Salesforce
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* About */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <SectionHeading title="About Miragent" />
          <div className="space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-sm font-semibold text-gray-800">Miragent Scout</p>
                <p className="text-xs text-gray-500 mt-0.5">Agentic CIO in a Box</p>
              </div>
              <span
                className="text-xs font-mono px-2 py-1 rounded-lg text-white"
                style={{ backgroundColor: '#1B2A4A' }}
              >
                v0.58.0
              </span>
            </div>
            <p className="text-sm text-gray-600 leading-relaxed">
              Miragent Scout is an AI-powered operating intelligence platform purpose-built for
              PE-backed companies. It ingests CRM, HRIS, and ERP data, builds a real-time
              knowledge graph, and deploys 34 intelligence workers, 32 connectors, and enterprise SSO to surface revenue,
              EBITDA, and operational insights — then autonomously remediates findings within
              configurable guardrails.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
                <p className="text-xs font-semibold text-gray-700 mb-1">Architecture</p>
                <ul className="text-xs text-gray-500 space-y-0.5">
                  <li>FastAPI backend</li>
                  <li>Neo4j knowledge graph</li>
                  <li>Anthropic Claude API (narrative)</li>
                  <li>React + TypeScript frontend</li>
                </ul>
              </div>
              <div className="p-3 bg-gray-50 rounded-lg border border-gray-100">
                <p className="text-xs font-semibold text-gray-700 mb-1">Intelligence Layers</p>
                <ul className="text-xs text-gray-500 space-y-0.5">
                  <li>Revenue Optimization</li>
                  <li>EBITDA Optimization</li>
                  <li>Full Funnel Intelligence</li>
                  <li>Process Mining</li>
                </ul>
              </div>
            </div>
            <div className="pt-2 border-t border-gray-100">
              <a
                href="http://localhost:8000/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-xs font-medium hover:underline"
                style={{ color: '#1B2A4A' }}
              >
                <ExternalLink size={12} />
                View FastAPI Docs (localhost:8000/docs)
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
