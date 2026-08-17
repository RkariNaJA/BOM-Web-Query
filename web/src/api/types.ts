/** GET /api/health — db.test_connection() */
export interface Health {
  connected: boolean
  server: string
  database: string
  view: string
  elapsed: number
}

/** One entry of Meta.columns — db.columns() */
export interface ColumnMeta {
  name: string
  type: string
  nullable: boolean
}

/** One column-picker group — main.meta() */
export interface ColumnGroup {
  title: string
  columns: string[]
}

/** db.date_bounds(); null until the background warm-up finishes. */
export interface DateBounds {
  min: string
  max: string
}

export interface TextFilterSpec {
  column: string
  kind: 'text'
  param: string
  suggest: boolean
  note: string
}

export interface DateFilterSpec {
  column: string
  kind: 'date'
  param_from: string
  param_to: string
  suggest: boolean
  note: string
  bounds: DateBounds | null
}

export type FilterSpec = TextFilterSpec | DateFilterSpec

/** GET /api/meta */
export interface Meta {
  columns: ColumnMeta[]
  groups: ColumnGroup[]
  pinned: string
  filters: FilterSpec[]
  default_columns: string[]
  /** Measured seconds each expensive column adds. Only the 3 DETECTION columns appear. */
  page_sizes: number[]
  min_page_size: number
  default_page_size: number
  /** How old the data is. With a snapshot this is correctness, not a nicety. */
  snapshot: {
    built_at: string | null
    row_count: number | null
    duration_seconds: number | null
  }
  /** Never null now: the count is a single-digit-millisecond query. */
  total_rows: number | null
  source: string
}

/** GET /api/distinct */
export interface DistinctPayload {
  column: string
  values: string[]
}

export type CellValue = string | number | null

/** GET /api/rows — db.fetch_page() */
export interface RowsPayload {
  /** The columns present in each row, in order. */
  columns: string[]
  all_columns: string[]
  /** What the server actually holds for this filter — may exceed `columns`. */
  fetched_columns: string[]
  rows: CellValue[][]
  total: number
  page: number
  page_size: number
  pages: number
  elapsed: number
  cached: boolean
  capped: boolean
}
