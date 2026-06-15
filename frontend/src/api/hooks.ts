import { useCallback, useEffect, useRef, useState } from 'react'
import { BridgeApiError } from './client'

interface ApiState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null })

  const load = useCallback(async () => {
    setState(s => ({ ...s, loading: true, error: null }))
    try {
      const data = await fn()
      setState({ data, loading: false, error: null })
    } catch (err) {
      const msg = err instanceof BridgeApiError ? err.message : String(err)
      setState({ data: null, loading: false, error: msg })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => { void load() }, [load])

  return { ...state, reload: load, refetch: load }
}

export function usePoll<T>(fn: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: true, error: null })
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fn()
      setState({ data, loading: false, error: null })
    } catch (err) {
      const msg = err instanceof BridgeApiError ? err.message : String(err)
      setState(s => ({ ...s, loading: false, error: msg }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    setState(s => ({ ...s, loading: true }))
    void load()
    timerRef.current = setInterval(() => { void load() }, intervalMs)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [load, intervalMs])

  return { ...state, reload: load }
}
