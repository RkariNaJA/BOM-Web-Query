import type { DistinctPayload, Health, Meta, RowsPayload } from './types'

/** Carries the HTTP status so callers can tell "db down" from "bad request". */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

/** FastAPI puts the human-readable message in `detail`. Fall back to the
 *  status line when the body is not JSON (e.g. a proxy error page). */
export async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // leave the status-line fallback in place
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

export async function getHealth(): Promise<Health> {
  return readJson<Health>(await fetch('/api/health'))
}

export async function getMeta(): Promise<Meta> {
  return readJson<Meta>(await fetch('/api/meta'))
}

export async function getDistinct(column: string): Promise<DistinctPayload> {
  return readJson<DistinctPayload>(
    await fetch(`/api/distinct?column=${encodeURIComponent(column)}`),
  )
}

export async function getRows(params: URLSearchParams): Promise<RowsPayload> {
  return readJson<RowsPayload>(await fetch(`/api/rows?${params}`))
}

/** Export is a navigation, not a fetch, so the browser handles the streaming
 *  download and the Content-Disposition filename. */
export function exportUrl(params: URLSearchParams): string {
  return `/api/export.csv?${params}`
}
