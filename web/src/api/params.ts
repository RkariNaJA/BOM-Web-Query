import type { QueryState } from '../state/queryReducer'

/** React state setters are asynchronous, so a handler that has just computed a
 *  new visible set or page must be able to search with it immediately rather
 *  than with the value still in state. */
export type ParamOverrides = Partial<Pick<QueryState, 'visible' | 'page' | 'pageSize' | 'columnFilters'>>

function resolve(state: QueryState, overrides?: ParamOverrides) {
  return { ...state, ...overrides }
}

/** Filters only — shared by /api/rows and /api/export.csv. */
function filterParams(state: QueryState): URLSearchParams {
  const params = new URLSearchParams()
  for (const [param, value] of Object.entries(state.values)) {
    const trimmed = value.trim()
    if (trimmed) params.set(param, trimmed)
  }
  // Always sent: the server defaults it to false, but being explicit keeps the
  // URL self-describing and makes a bookmarked query unambiguous.
  params.set('partial', String(state.partial))
  // Only when something is actually typed: an empty object would put a
  // meaningless `col_filters={}` on every request and in every bookmark.
  if (Object.keys(state.columnFilters).length > 0) {
    params.set('col_filters', JSON.stringify(state.columnFilters))
  }
  return params
}

export function rowsParams(state: QueryState, overrides?: ParamOverrides): URLSearchParams {
  const resolved = resolve(state, overrides)
  const params = filterParams(resolved)
  params.set('page', String(resolved.page))
  params.set('page_size', String(resolved.pageSize))
  // Ask for exactly what is on screen. This is now a projection choice
  // only -- no column costs anything to fetch from the snapshot.
  params.set('columns', [...resolved.visible].join(','))
  return params
}

export function exportParams(state: QueryState, overrides?: ParamOverrides): URLSearchParams {
  const resolved = resolve(state, overrides)
  const params = filterParams(resolved)
  params.set('columns', [...resolved.visible].join(','))
  return params
}
