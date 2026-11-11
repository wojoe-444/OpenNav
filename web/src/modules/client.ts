import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { api, type Health } from '@/lib/api'

export interface Query<T> {
  data: T | undefined
  error: Error | undefined
  /** True for the first load (no data yet). */
  loading: boolean
  /** True while any request is in flight, including refreshes. */
  fetching: boolean
  refresh: () => Promise<void>
  /** Replace the data (e.g. with the result of a POST). */
  set: (data: T) => void
}

/**
 * Load data from the local API (MonoRail's useModuleQuery, over HTTP). Keeps
 * the previous data while refetching so views hold their frame instead of
 * flashing a skeleton. `key` changes trigger a new load.
 */
export function useQuery<T>(key: string | null, load: () => Promise<T>): Query<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<Error>()
  const [fetching, setFetching] = useState(key !== null)
  const loadRef = useRef(load)
  useLayoutEffect(() => {
    loadRef.current = load
  })
  const seq = useRef(0)

  const run = useCallback(async () => {
    const id = ++seq.current
    setFetching(true)
    try {
      const result = await loadRef.current()
      if (id === seq.current) {
        setData(result)
        setError(undefined)
      }
    } catch (e) {
      if (id === seq.current) setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      if (id === seq.current) setFetching(false)
    }
  }, [])

  useEffect(() => {
    if (key !== null) void run()
  }, [key, run])

  const set = useCallback((d: T) => {
    ++seq.current
    setData(d)
    setError(undefined)
    setFetching(false)
  }, [])

  return { data, error, loading: fetching && data === undefined, fetching, refresh: run, set }
}

/** API status for the drawer footer. */
export function useHealth(): Query<Health> {
  return useQuery('health', api.health)
}
