/**
 * API client for the console FastAPI skeleton (W1-API-01).
 * Uses relative /api in dev (Vite proxy) or VITE_API_BASE_URL in compose.
 */

export type ApiErrorBody = {
  error: {
    code: string
    message: string
    details?: unknown
  }
}

export class ApiError extends Error {
  status: number
  code: string
  details?: unknown

  constructor(status: number, body: ApiErrorBody | string) {
    if (typeof body === 'string') {
      super(body)
      this.code = 'http_error'
    } else {
      super(body.error?.message || 'Request failed')
      this.code = body.error?.code || 'http_error'
      this.details = body.error?.details
    }
    this.status = status
    this.name = 'ApiError'
  }
}

function baseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL as string | undefined
  if (raw && raw.trim()) return raw.replace(/\/$/, '')
  return '/api'
}

function authHeader(): Record<string, string> {
  const token = localStorage.getItem('miragent_console_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = `${baseUrl()}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    headers: {
      Accept: 'application/json',
      ...authHeader(),
    },
  })

  if (!res.ok) {
    let payload: ApiErrorBody | string = res.statusText
    try {
      payload = (await res.json()) as ApiErrorBody
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, payload)
  }

  return (await res.json()) as T
}

export type CorpusStats = {
  tickets: number
  accounts: number
  analysts: number
  channels: number
  date_range: { start: string | null; end: string | null }
}

export type HealthResponse = { status: string }

export const api = {
  health: () => apiGet<HealthResponse>('/health'),
  ready: () => apiGet<{ status: string; database?: string }>('/ready'),
  corpusStats: () => apiGet<CorpusStats>('/corpus/stats'),
}
