import type { FilterSpec } from '../api/types'

export interface QueryState {
  /** Keyed by the filter spec's query-param name, never by column name — the
   *  view has columns like "Buy Code" that are awkward in a URL. */
  values: Record<string, string>
  partial: boolean
  page: number
  pageSize: number
  visible: Set<string>
  /** Kept so `reset` can return here rather than to all 60 columns. */
  defaultColumns: string[]
}

export type QueryAction =
  | { type: 'init'; specs: FilterSpec[]; defaultColumns: string[] }
  | { type: 'setValue'; param: string; value: string }
  | { type: 'setPartial'; value: boolean }
  | { type: 'setPageSize'; value: number }
  | { type: 'setPage'; value: number }
  | { type: 'setVisible'; value: Set<string> }
  | { type: 'reset' }

export const initialQueryState: QueryState = {
  values: {},
  partial: false,
  page: 1,
  pageSize: 100,
  visible: new Set(),
  defaultColumns: [],
}

function paramNames(specs: FilterSpec[]): string[] {
  return specs.flatMap((spec) =>
    spec.kind === 'date' ? [spec.param_from, spec.param_to] : [spec.param],
  )
}

export function queryReducer(state: QueryState, action: QueryAction): QueryState {
  switch (action.type) {
    case 'init': {
      const values: Record<string, string> = {}
      for (const param of paramNames(action.specs)) values[param] = ''
      return {
        ...state,
        values,
        visible: new Set(action.defaultColumns),
        defaultColumns: action.defaultColumns,
      }
    }
    // Anything that changes which rows match invalidates the page number.
    case 'setValue':
      return { ...state, values: { ...state.values, [action.param]: action.value }, page: 1 }
    case 'setPartial':
      return { ...state, partial: action.value, page: 1 }
    case 'setPageSize':
      return { ...state, pageSize: action.value, page: 1 }
    case 'setPage':
      return { ...state, page: action.value }
    // Column visibility changes projection, not matching, so the page holds.
    case 'setVisible':
      return { ...state, visible: action.value }
    case 'reset': {
      const values: Record<string, string> = {}
      for (const param of Object.keys(state.values)) values[param] = ''
      return {
        ...state,
        values,
        partial: false,
        page: 1,
        // The default set is every column now that none of them cost
        // anything; resetting simply un-hides whatever the user hid.
        visible: new Set(state.defaultColumns),
      }
    }
  }
}

export function hasAnyFilter(state: QueryState): boolean {
  return Object.values(state.values).some((value) => value.trim() !== '')
}
