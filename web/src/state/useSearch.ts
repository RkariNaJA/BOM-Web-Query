import { useCallback, useEffect, useRef, useState } from 'react'
import { getRows } from '../api/client'
import type { RowsPayload } from '../api/types'
import type { ConnKind } from '../components/AppBar'

export interface SearchState {
  payload: RowsPayload | null
  busy: boolean
  error: string | null
  elapsedText: string
  connKind: ConnKind
  connText: string
  run: (params: URLSearchParams) => Promise<void>
}

export function useSearch(): SearchState {
  const [payload, setPayload] = useState<RowsPayload | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [elapsedText, setElapsedText] = useState('not run')
  const [connKind, setConnKind] = useState<ConnKind>('idle')
  const [connText, setConnText] = useState('connecting…')
  // A ref, not `busy`: the guard must see the current value inside a callback
  // that may have closed over a stale render.
  const inFlight = useRef(false)
  const ticker = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopTicker = () => {
    if (ticker.current !== null) {
      clearInterval(ticker.current)
      ticker.current = null
    }
  }

  useEffect(() => stopTicker, [])

  const run = useCallback(async (params: URLSearchParams) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setConnKind('working')
    setConnText('querying…')

    // A live counter, kept from the SQL Server era. Snapshot queries settle
    // in milliseconds, so it rarely paints -- it costs nothing and still
    // covers a first call that has to open a cold 359 MB file.
    const started = performance.now()
    stopTicker()
    ticker.current = setInterval(() => {
      setElapsedText(`${((performance.now() - started) / 1000).toFixed(1)}s elapsed…`)
    }, 100)

    try {
      const result = await getRows(params)
      setPayload(result)
      setError(null)
      setConnKind('ready')
      setConnText('connected')
      // Milliseconds, because seconds now round to "0.0s" for every query.
      setElapsedText(`query ${Math.max(1, Math.round(result.elapsed * 1000))} ms`)
    } catch (caught) {
      setError((caught as Error).message)
      setConnKind('error')
      setConnText('query failed')
      setElapsedText('failed')
    } finally {
      stopTicker()
      inFlight.current = false
      setBusy(false)
    }
  }, [])

  return { payload, busy, error, elapsedText, connKind, connText, run }
}
