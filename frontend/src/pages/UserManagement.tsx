/**
 * UserManagement.tsx — Sprint 19
 *
 * Connects the UI to Sprint 15's multi-tenant auth API:
 *  - Register a new user (within an existing tenant)
 *  - Login to get a JWT
 *  - View profile
 *  - Create / revoke API keys
 *  - Create a new tenant
 */

import { useState, useEffect } from 'react'
import {
  Users,
  Key,
  LogIn,
  LogOut,
  Plus,
  Trash2,
  Eye,
  EyeOff,
  Loader2,
  AlertCircle,
  CheckCircle,
  Copy,
  Check,
  Building2,
} from 'lucide-react'
import { api } from '../api/client'
import type { AuthUser, ApiKey, ApiKeyCreateResponse } from '../types'

// ── Local state helpers ───────────────────────────────────

const TOKEN_KEY = 'miragent_jwt'

function loadToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

function saveToken(t: string) {
  sessionStorage.setItem(TOKEN_KEY, t)
}

function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY)
}

// ── Sub-components ────────────────────────────────────────

function SectionHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-5">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}

function ErrorAlert({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
      <AlertCircle size={15} className="text-red-500 flex-shrink-0 mt-0.5" />
      <p className="text-xs text-red-700">{message}</p>
    </div>
  )
}

function SuccessAlert({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 bg-emerald-50 border border-emerald-200 rounded-lg p-3 mb-4">
      <CheckCircle size={15} className="text-emerald-500 flex-shrink-0 mt-0.5" />
      <p className="text-xs text-emerald-700">{message}</p>
    </div>
  )
}

// ── Create Tenant ─────────────────────────────────────────

function CreateTenantCard() {
  const [tenantId, setTenantId] = useState('')
  const [tenantName, setTenantName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  async function handleCreate() {
    if (!tenantId.trim() || !tenantName.trim()) return
    setLoading(true)
    setError(null)
    setSuccess(null)
    try {
      const res = await api.createTenant(tenantId.trim(), tenantName.trim())
      setSuccess(`Tenant "${res.name}" (${res.tenant_id}) created successfully.`)
      setTenantId('')
      setTenantName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create tenant')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <SectionHeading
        title="Create Tenant"
        subtitle="Register a new tenant organisation. Needed before registering users."
      />
      {error && <ErrorAlert message={error} />}
      {success && <SuccessAlert message={success} />}
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">
            Tenant ID <span className="text-gray-400">(slug, e.g. acme-corp)</span>
          </label>
          <input
            type="text"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="acme-corp"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">
            Display Name
          </label>
          <input
            type="text"
            value={tenantName}
            onChange={(e) => setTenantName(e.target.value)}
            placeholder="Acme Corporation"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
          />
        </div>
        <button
          onClick={handleCreate}
          disabled={loading || !tenantId.trim() || !tenantName.trim()}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ backgroundColor: '#1B2A4A' }}
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          <Building2 size={14} />
          Create Tenant
        </button>
      </div>
    </div>
  )
}

// ── Register ──────────────────────────────────────────────

function RegisterCard({ onRegistered }: { onRegistered: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [tenantId, setTenantId] = useState('acme-corp')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  async function handleRegister() {
    if (!email.trim() || !password.trim() || !tenantId.trim()) return
    setLoading(true)
    setError(null)
    setSuccess(null)
    try {
      await api.register(email.trim(), password, tenantId.trim(), fullName.trim() || undefined)
      setSuccess(`User ${email} registered. You can now log in.`)
      onRegistered()
      setEmail('')
      setPassword('')
      setFullName('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <SectionHeading
        title="Register User"
        subtitle="Create a new account within an existing tenant."
      />
      {error && <ErrorAlert message={error} />}
      {success && <SuccessAlert message={success} />}
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Full Name (optional)</label>
          <input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Jane Smith"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Password</label>
          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full px-3 py-2 pr-10 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
            />
            <button
              type="button"
              onClick={() => setShowPw((p) => !p)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Tenant ID</label>
          <input
            type="text"
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="acme-corp"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
          />
        </div>
        <button
          onClick={handleRegister}
          disabled={loading || !email.trim() || !password.trim() || !tenantId.trim()}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ backgroundColor: '#1B2A4A' }}
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          <Users size={14} />
          Register
        </button>
      </div>
    </div>
  )
}

// ── Login ─────────────────────────────────────────────────

function LoginCard({ onLogin }: { onLogin: (token: string) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleLogin() {
    if (!email.trim() || !password.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.login(email.trim(), password)
      saveToken(res.access_token)
      onLogin(res.access_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <SectionHeading
        title="Login"
        subtitle="Authenticate to manage your API keys and profile."
      />
      {error && <ErrorAlert message={error} />}
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
            placeholder="you@company.com"
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Password</label>
          <div className="relative">
            <input
              type={showPw ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleLogin()}
              placeholder="••••••••"
              className="w-full px-3 py-2 pr-10 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
            />
            <button
              type="button"
              onClick={() => setShowPw((p) => !p)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
        <button
          onClick={handleLogin}
          disabled={loading || !email.trim() || !password.trim()}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ backgroundColor: '#1B2A4A' }}
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          <LogIn size={14} />
          Login
        </button>
      </div>
    </div>
  )
}

// ── Profile + API Keys ────────────────────────────────────

function ProfileCard({ user, onLogout }: { user: AuthUser; token?: string; onLogout: () => void }) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <div className="flex items-start justify-between mb-4">
        <SectionHeading title="Profile" />
        <button
          onClick={onLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
        >
          <LogOut size={12} />
          Logout
        </button>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {[
          { label: 'Email', value: user.email },
          { label: 'Full Name', value: user.full_name || '—' },
          { label: 'Role', value: user.role },
          { label: 'Tenant', value: user.tenant_id },
          { label: 'Status', value: user.is_active ? 'Active' : 'Inactive' },
          { label: 'User ID', value: user.id.slice(0, 8) + '…' },
        ].map(({ label, value }) => (
          <div key={label}>
            <p className="text-xs text-gray-400 mb-0.5">{label}</p>
            <p className="text-sm font-medium text-gray-800">{value}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function ApiKeysCard({ token }: { token: string }) {
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newKeyName, setNewKeyName] = useState('')
  const [creating, setCreating] = useState(false)
  const [newKey, setNewKey] = useState<ApiKeyCreateResponse | null>(null)
  const [copied, setCopied] = useState(false)
  const [revoking, setRevoking] = useState<string | null>(null)

  useEffect(() => {
    fetchKeys()
  }, [])

  async function fetchKeys() {
    setLoading(true)
    try {
      const ks = await api.listApiKeys(token)
      setKeys(ks)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load API keys')
    } finally {
      setLoading(false)
    }
  }

  async function handleCreate() {
    if (!newKeyName.trim()) return
    setCreating(true)
    setNewKey(null)
    try {
      const key = await api.createApiKey(token, newKeyName.trim())
      setNewKey(key)
      setNewKeyName('')
      await fetchKeys()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create API key')
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke(keyId: string) {
    setRevoking(keyId)
    try {
      await api.revokeApiKey(token, keyId)
      setKeys((ks) => ks.filter((k) => k.id !== keyId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke key')
    } finally {
      setRevoking(null)
    }
  }

  function copyKey(raw: string) {
    navigator.clipboard.writeText(raw)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function formatDate(d: string) {
    return new Date(d).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    })
  }

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
      <SectionHeading
        title="API Keys"
        subtitle="Use API keys to authenticate programmatic access to the Scout API."
      />
      {error && <ErrorAlert message={error} />}

      {/* New key alert */}
      {newKey && (
        <div className="mb-4 p-4 bg-emerald-50 border border-emerald-200 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle size={14} className="text-emerald-600" />
            <p className="text-xs font-semibold text-emerald-700">
              API key created — copy it now. It won't be shown again.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs bg-white px-3 py-2 rounded border border-emerald-200 font-mono text-gray-800 truncate">
              {newKey.raw_key}
            </code>
            <button
              onClick={() => copyKey(newKey.raw_key)}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-emerald-200 bg-white hover:bg-emerald-50 text-emerald-700 transition-colors"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
      )}

      {/* Create new key */}
      <div className="flex items-center gap-2 mb-5">
        <input
          type="text"
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
          placeholder='Key name (e.g. "CI/CD pipeline")'
          className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2"
        />
        <button
          onClick={handleCreate}
          disabled={creating || !newKeyName.trim()}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ backgroundColor: '#1B2A4A' }}
        >
          {creating ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
          Create
        </button>
      </div>

      {/* Keys list */}
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-gray-300" />
        </div>
      ) : keys.length === 0 ? (
        <p className="text-xs text-gray-400 text-center py-6">
          No API keys yet. Create one above.
        </p>
      ) : (
        <div className="rounded-lg border border-gray-100 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-left">Name</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-left">Prefix</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-left">Created</th>
                <th className="px-4 py-2.5 text-xs font-semibold text-gray-500 text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {keys.map((key, idx) => (
                <tr
                  key={key.id}
                  className={`border-b border-gray-50 ${idx === keys.length - 1 ? 'border-b-0' : ''}`}
                >
                  <td className="px-4 py-3 text-sm font-medium text-gray-800">{key.name}</td>
                  <td className="px-4 py-3">
                    <code className="text-xs font-mono bg-gray-100 px-2 py-0.5 rounded text-gray-600">
                      {key.prefix}…
                    </code>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">{formatDate(key.created_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleRevoke(key.id)}
                      disabled={revoking === key.id}
                      className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50 ml-auto"
                    >
                      {revoking === key.id ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Trash2 size={11} />
                      )}
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────

type ActiveTab = 'login' | 'register' | 'tenant'

export default function UserManagement() {
  const [token, setToken] = useState<string | null>(loadToken)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [tab, setTab] = useState<ActiveTab>('login')
  const [loadingUser, setLoadingUser] = useState(!!loadToken())

  // Load user profile on mount if token exists
  useEffect(() => {
    const t = loadToken()
    if (t) {
      api.me(t)
        .then((u) => setUser(u))
        .catch(() => {
          clearToken()
          setToken(null)
        })
        .finally(() => setLoadingUser(false))
    } else {
      setLoadingUser(false)
    }
  }, [])

  function handleLogin(t: string) {
    setToken(t)
    setLoadingUser(true)
    api.me(t)
      .then((u) => setUser(u))
      .catch(() => {
        clearToken()
        setToken(null)
      })
      .finally(() => setLoadingUser(false))
  }

  function handleLogout() {
    clearToken()
    setToken(null)
    setUser(null)
  }

  const TABS: { id: ActiveTab; label: string; icon: React.ReactNode }[] = [
    { id: 'login', label: 'Login', icon: <LogIn size={14} /> },
    { id: 'register', label: 'Register', icon: <Users size={14} /> },
    { id: 'tenant', label: 'Create Tenant', icon: <Building2 size={14} /> },
  ]

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Key size={22} style={{ color: '#1B2A4A' }} />
          <h1 className="text-3xl font-bold text-gray-900">User Management</h1>
        </div>
        <p className="text-gray-500">
          Manage users, API keys, and tenant configuration.
        </p>
      </div>

      {loadingUser ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={24} className="animate-spin text-gray-300" />
        </div>
      ) : token && user ? (
        // Authenticated view
        <div className="space-y-5">
          <ProfileCard user={user} token={token} onLogout={handleLogout} />
          <ApiKeysCard token={token} />
        </div>
      ) : (
        // Unauthenticated view
        <div>
          {/* Tab switcher */}
          <div className="flex gap-1 mb-5 bg-gray-100 p-1 rounded-xl w-fit">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg transition-all ${
                  tab === t.id
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>

          {tab === 'login' && <LoginCard onLogin={handleLogin} />}
          {tab === 'register' && (
            <RegisterCard onRegistered={() => setTab('login')} />
          )}
          {tab === 'tenant' && <CreateTenantCard />}
        </div>
      )}
    </div>
  )
}
