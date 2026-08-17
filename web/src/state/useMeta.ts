import { useEffect, useState } from 'react'
import { getHealth, getMeta } from '../api/client'
import type { Meta } from '../api/types'

/** /api/meta only peeks at the cached row count, so on a cold server it comes
 *  back null. Check back a few times while the background warm-up runs, then
 *  give up quietly — the header total is informational only. */
const POLL_ATTEMPTS = 6
const POLL_INTERVAL_MS = 10_000

export interface MetaState {
  meta: Meta | null
  source: string
  totalRows: number | null
  bootError: string | null
  connected: boolean
}

export function useMeta(): MetaState {
  const [meta, setMeta] = useState<Meta | null>(null)
  // Neutral until /api/health answers with the real source. Hardcoding the
  // database and view here would ship them in the JS bundle.
  const [source, setSource] = useState('—')
  const [totalRows, setTotalRows] = useState<number | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    /* A closure variable per effect invocation, NOT a ref. Under StrictMode
       React mounts, cleans up, then mounts again; a shared ref would be reset
       to false by the second mount, un-cancelling the first chain at exactly
       the moment the guard exists to stop it. */
    let cancelled = false

    async function boot() {
      try {
        const health = await getHealth()
        if (cancelled) return
        setConnected(true)
        setSource(`${health.database} / ${health.view}`)
      } catch (error) {
        if (cancelled) return
        setBootError(`Cannot reach the database. ${(error as Error).message}`)
        return
      }

      let loaded: Meta
      try {
        loaded = await getMeta()
      } catch (error) {
        if (cancelled) return
        setBootError(`Could not load column metadata. ${(error as Error).message}`)
        return
      }
      if (cancelled) return
      setMeta(loaded)
      setSource(loaded.source)
      setTotalRows(loaded.total_rows)
      if (loaded.total_rows === null) void pollTotal(0)
    }

    async function pollTotal(attempt: number) {
      if (attempt >= POLL_ATTEMPTS || cancelled) return
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
      if (cancelled) return
      try {
        const again = await getMeta()
        if (cancelled) return
        if (again.total_rows !== null) {
          setTotalRows(again.total_rows)
          return
        }
      } catch {
        // leave the dash in place
      }
      void pollTotal(attempt + 1)
    }

    void boot()
    return () => { cancelled = true }
  }, [])

  return { meta, source, totalRows, bootError, connected }
}
