/* Shared screen plumbing: async reads with their three states, and URL-state
   filters (a filter mutation is URL state only — never a server write). */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

/** Every read returns {data, loading, error, reload} so a screen cannot forget
    to render one of the three states (§11.5). */
export function useAsync(fn, deps = [], { immediate = true } = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(immediate)
  const [error, setError] = useState(null)
  const live = useRef(true)

  const run = useCallback(() => {
    setLoading(true); setError(null)
    return Promise.resolve()
      .then(fn)
      .then((d) => { if (live.current) { setData(d); setLoading(false) } })
      .catch((e) => { if (live.current) { setError(e); setLoading(false) } })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    live.current = true
    if (immediate) run()
    return () => { live.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run])

  return { data, loading, error, reload: run }
}

/** Filters live in the URL so every list state is shareable and deep-linkable. */
export function useUrlFilters(keys) {
  const [params, setParams] = useSearchParams()
  const filters = {}
  keys.forEach((k) => { const v = params.get(k); if (v) filters[k] = v })

  const set = useCallback((patch) => {
    const next = new URLSearchParams(params)
    Object.entries(patch).forEach(([k, v]) => {
      if (v == null || v === '') next.delete(k)
      else next.set(k, v)
    })
    setParams(next, { replace: true })
  }, [params, setParams])

  const clear = useCallback(() => {
    const next = new URLSearchParams(params)
    keys.forEach((k) => next.delete(k))
    setParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, setParams])

  return { filters, set, clear, params, setParams }
}

/** J/K list navigation shared by S-04 and S-13 (§10.13 a11y: "consistent"). */
export function useListKeys(count, { onOpen, enabled = true } = {}) {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    if (!enabled) return
    const onKey = (e) => {
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'j' || e.key === 'J') { e.preventDefault(); setIndex((i) => Math.min(count - 1, i + 1)) }
      if (e.key === 'k' || e.key === 'K') { e.preventDefault(); setIndex((i) => Math.max(0, i - 1)) }
      if (e.key === 'Enter' && onOpen) { e.preventDefault(); onOpen(index) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [count, index, onOpen, enabled])
  return [index, setIndex]
}
