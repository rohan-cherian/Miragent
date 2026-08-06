/**
 * Login.tsx — Sprint 74: SSO-aware login page
 *
 * When the user types their email the domain is extracted and checked against
 * the SSO domain registry. If a match is found:
 *   - The password field slides out
 *   - A branded "Sign in with [Provider]" button appears
 *   - A note explains that the organisation uses SSO
 *   - A "Use password instead" escape-hatch lets admins fall back to password
 *
 * SSO click is mocked: 1.5 s spinner → localStorage token → redirect /dashboard
 */

import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Shield, Building2, Globe, Key, Loader2, Eye, EyeOff } from 'lucide-react'
import { api, type SSODomainCheckResult } from '../api/client'

// ── Provider config ───────────────────────────────────────────────────────────

interface ProviderStyle {
  bg: string
  text: string
  Icon: React.ComponentType<{ size?: number; className?: string }>
}

const PROVIDER_STYLES: Record<string, ProviderStyle> = {
  okta:     { bg: '#007DC1', text: '#fff', Icon: Shield as ProviderStyle['Icon'] },
  azure_ad: { bg: '#0078D4', text: '#fff', Icon: Building2 as ProviderStyle['Icon'] },
  google:   { bg: '#fff',    text: '#333', Icon: Globe as ProviderStyle['Icon'] },
  saml:     { bg: '#6B7280', text: '#fff', Icon: Key as ProviderStyle['Icon'] },
}

function getProviderStyle(logo: string | null): ProviderStyle {
  return PROVIDER_STYLES[logo ?? ''] ?? PROVIDER_STYLES['saml']
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function Login() {
  const navigate = useNavigate()

  // Form state
  const [email, setEmail]         = useState('')
  const [password, setPassword]   = useState('')
  const [showPw, setShowPw]       = useState(false)

  // SSO detection state
  const [ssoResult, setSsoResult]     = useState<SSODomainCheckResult | null>(null)
  const [ssoLoading, setSsoLoading]   = useState(false)
  const [bypassSSO, setBypassSSO]     = useState(false)

  // Submit state
  const [submitting, setSubmitting]   = useState(false)
  const [ssoSpinner, setSsoSpinner]   = useState(false)
  const [toast, setToast]             = useState<string | null>(null)
  const [error, setError]             = useState<string | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── SSO domain detection ─────────────────────────────────────────────────

  useEffect(() => {
    const atIdx = email.indexOf('@')
    if (atIdx === -1 || email.indexOf('.', atIdx) === -1) {
      setSsoResult(null)
      return
    }

    const domain = email.slice(atIdx + 1).toLowerCase()
    if (!domain) {
      setSsoResult(null)
      return
    }

    if (debounceRef.current) clearTimeout(debounceRef.current)

    debounceRef.current = setTimeout(async () => {
      setSsoLoading(true)
      try {
        const result = await api.sso.domainCheck(domain)
        setSsoResult(result)
        // Reset bypass flag whenever a new domain resolves
        if (result.sso_enabled) setBypassSSO(false)
      } catch {
        setSsoResult(null)
      } finally {
        setSsoLoading(false)
      }
    }, 600)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [email])

  // Derived: show SSO button?
  const showSSO = !bypassSSO && ssoResult?.sso_enabled === true
  const showPasswordField = !showSSO

  // ── Toast helper ─────────────────────────────────────────────────────────

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 4000)
  }

  // ── SSO sign-in (mock) ───────────────────────────────────────────────────

  async function handleSSOClick() {
    setSsoSpinner(true)
    setError(null)
    await new Promise((r) => setTimeout(r, 1500))
    localStorage.setItem('miragent_token', 'mock-sso-token-sprint74')
    localStorage.setItem('miragent_sso_provider', ssoResult?.provider ?? 'unknown')
    showToast('SSO sign-in simulated — redirecting to dashboard.')
    setSsoSpinner(false)
    setTimeout(() => navigate('/'), 800)
  }

  // ── Password sign-in (mock) ──────────────────────────────────────────────

  async function handlePasswordSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email || !password) {
      setError('Please enter your email and password.')
      return
    }
    setSubmitting(true)
    setError(null)
    // Simulate login
    await new Promise((r) => setTimeout(r, 800))
    localStorage.setItem('miragent_token', 'mock-pw-token-sprint74')
    showToast('Signed in — redirecting.')
    setSubmitting(false)
    setTimeout(() => navigate('/'), 500)
  }

  // ── Provider style ───────────────────────────────────────────────────────

  const providerStyle = getProviderStyle(ssoResult?.logo ?? null)
  const ProviderIcon  = providerStyle.Icon

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-green-600 text-white text-sm px-4 py-3 rounded-lg shadow-lg max-w-xs">
          {toast}
        </div>
      )}

      <div className="w-full max-w-md">
        {/* Card */}
        <div className="bg-white rounded-2xl shadow-lg px-8 py-10">
          {/* Logo + heading */}
          <div className="flex flex-col items-center mb-8">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center mb-4"
              style={{ backgroundColor: '#1B2A4A' }}
            >
              <span className="text-white font-bold text-xl leading-none">M</span>
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Sign in to Miragent</h1>
            <p className="text-gray-500 text-sm mt-1">Scout platform</p>
          </div>

          {error && (
            <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
              {error}
            </div>
          )}

          <form onSubmit={handlePasswordSubmit} noValidate>
            {/* Email field */}
            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="email">
                Work email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@yourcompany.com"
                className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              {ssoLoading && (
                <p className="mt-1 text-xs text-gray-400 flex items-center gap-1">
                  <Loader2 size={11} className="animate-spin" />
                  Checking your organisation…
                </p>
              )}
            </div>

            {/* SSO block — slides in when a recognised domain is detected */}
            {showSSO && ssoResult && (
              <div className="mb-4 space-y-3">
                {/* Provider note */}
                <div className="text-xs text-gray-500 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2.5">
                  Your organisation uses{' '}
                  <span className="font-semibold text-gray-700">{ssoResult.provider_display}</span>{' '}
                  for single sign-on.
                </div>

                {/* SSO button */}
                <button
                  type="button"
                  onClick={handleSSOClick}
                  disabled={ssoSpinner}
                  className="w-full flex items-center justify-center gap-2.5 py-2.5 px-4 rounded-lg text-sm font-semibold transition-opacity disabled:opacity-70"
                  style={{
                    backgroundColor: providerStyle.bg,
                    color: providerStyle.text,
                    border: ssoResult.logo === 'google' ? '1px solid #d1d5db' : 'none',
                  }}
                >
                  {ssoSpinner ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <ProviderIcon size={16} />
                  )}
                  {ssoSpinner ? 'Redirecting…' : (ssoResult.button_label ?? 'Sign in with SSO')}
                </button>

                {/* Bypass link */}
                <button
                  type="button"
                  onClick={() => setBypassSSO(true)}
                  className="w-full text-center text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Use password instead
                </button>
              </div>
            )}

            {/* Password field — hidden when SSO is active */}
            <div
              className="overflow-hidden transition-all duration-300"
              style={{ maxHeight: showPasswordField ? '200px' : '0px', opacity: showPasswordField ? 1 : 0 }}
            >
              <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-1" htmlFor="password">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm pr-10 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    tabIndex={-1}
                    aria-label={showPw ? 'Hide password' : 'Show password'}
                  >
                    {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 rounded-lg text-sm font-semibold text-white transition-opacity disabled:opacity-70"
                style={{ backgroundColor: '#1B2A4A' }}
              >
                {submitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 size={16} className="animate-spin" />
                    Signing in…
                  </span>
                ) : (
                  'Sign in'
                )}
              </button>
            </div>
          </form>
        </div>

        <p className="text-center text-xs text-gray-400 mt-6">
          Miragent Scout · v0.74.0
        </p>
      </div>
    </div>
  )
}
