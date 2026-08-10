import { FormEvent, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { login, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from || '/corpus'

  const [email, setEmail] = useState('analyst@miragent.demo')
  const [password, setPassword] = useState('demo')
  const [error, setError] = useState<string | null>(null)

  if (isAuthenticated) {
    return <Navigate to={from} replace />
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!email.trim()) {
      setError('Enter an email to continue.')
      return
    }
    login(email.trim(), password)
    navigate(from, { replace: true })
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-surface">
      <div className="w-full max-w-md rounded-xl border border-line bg-surface-raised shadow-shell p-8">
        <p className="font-display text-3xl text-ink">Miragent</p>
        <p className="text-sm text-ink-muted mt-2 mb-8">
          Console sign-in stub — any credentials work for the demo.
        </p>

        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block">
            <span className="text-xs font-medium text-ink-muted">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              autoComplete="username"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink-muted">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              autoComplete="current-password"
            />
          </label>

          {error ? <p className="text-sm text-danger">{error}</p> : null}

          <button
            type="submit"
            className="w-full rounded-md bg-accent text-white text-sm font-medium py-2.5 hover:opacity-95"
          >
            Continue
          </button>
        </form>
      </div>
    </div>
  )
}
