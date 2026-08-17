import { afterEach, describe, expect, test, vi } from 'vitest'
import { ApiError, getDistinct, getRows, exportUrl, readJson } from './client'

afterEach(() => { vi.unstubAllGlobals() })

/** A partial Response needs the double assertion: TypeScript 7 rejects a
 *  direct `as Response` on an object missing headers, statusText and 11 other
 *  members. Going through `unknown` states the intent explicitly. */
function fakeResponse(
  init: { ok: boolean; status: number; json: () => Promise<unknown> },
): Response {
  return init as unknown as Response
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('readJson', () => {
  test('returns the parsed body when ok', async () => {
    const body = { column: 'IM', values: ['A'] }
    const result = await readJson<typeof body>(fakeResponse({
      ok: true, status: 200, json: async () => body,
    }))
    expect(result).toEqual(body)
  })

  test('throws the server detail string on an error body', async () => {
    await expect(readJson(fakeResponse({
      ok: false, status: 500, json: async () => ({ detail: 'Query failed: timeout' }),
    }))).rejects.toThrow('Query failed: timeout')
  })

  test('falls back to the status when the error body is not JSON', async () => {
    await expect(readJson(fakeResponse({
      ok: false, status: 503, json: async () => { throw new Error('not json') },
    }))).rejects.toThrow('HTTP 503')
  })

  test('throws ApiError, carrying the status', async () => {
    // `.catch` widens to unknown under strict mode, so narrow before reading
    // `.status` rather than asserting on an untyped value.
    const error: unknown = await readJson(fakeResponse({
      ok: false, status: 503, json: async () => ({ detail: 'Cannot connect' }),
    })).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(503)
  })
})

describe('endpoints', () => {
  test('getDistinct encodes an awkward column name', async () => {
    const fetchMock = stubFetch(fakeResponse({
      ok: true, status: 200, json: async () => ({ column: 'Buy Code', values: [] }),
    }))
    await getDistinct('Buy Code')
    expect(fetchMock).toHaveBeenCalledWith('/api/distinct?column=Buy%20Code')
  })

  test('getRows appends the params to /api/rows', async () => {
    const fetchMock = stubFetch(fakeResponse({
      ok: true, status: 200, json: async () => ({}),
    }))
    await getRows(new URLSearchParams({ limit: '100', page: '1' }))
    expect(fetchMock).toHaveBeenCalledWith('/api/rows?limit=100&page=1')
  })

  test('exportUrl builds a navigable URL rather than fetching', () => {
    expect(exportUrl(new URLSearchParams({ im: 'FPLNI1' })))
      .toBe('/api/export.csv?im=FPLNI1')
  })
})
