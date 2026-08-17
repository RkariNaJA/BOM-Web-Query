import { useLayoutEffect, useMemo, useRef } from 'react'
import type { RowsPayload } from '../api/types'
import { escapeHtml } from '../utils/format'

interface Props {
  payload: RowsPayload | null
  /** Every column in view order — the projection preserves this order. */
  allColumns: string[]
  visible: Set<string>
  pinned: string
  error: string | null
  /** Contains-filters keyed by column name, and the handler for the row of
   *  inputs under the header. */
  columnFilters: Record<string, string>
  onColumnFilterChange: (column: string, value: string) => void
}

export default function ResultsTable({
  payload, allColumns, visible, pinned, error,
  columnFilters, onColumnFilterChange,
}: Props) {
  const container = useRef<HTMLDivElement>(null)

  const shown = useMemo(
    () => allColumns.filter((name) => visible.has(name)),
    [allColumns, visible],
  )

  /* One HTML string rather than 60,000 React elements. Measured: at 60 columns
     x 1,000 rows, per-node rendering is visibly slower, and this is also what
     keeps hiding a column at 0.0 s. escapeHtml is therefore the only thing
     between database content and injected markup -- every value goes through
     it, cell text and title attribute alike. */
  const bodyHtml = useMemo(() => {
    if (!payload) return ''
    const indexOf = new Map(payload.columns.map((name, i) => [name, i]))
    return payload.rows.map((row) => {
      const cells = shown.map((name) => {
        const at = indexOf.get(name)
        const value = at === undefined ? null : row[at]
        const blank = value === null || value === ''
        const classes = []
        if (name === pinned) classes.push('pinned')
        if (blank) classes.push('null')
        const text = blank ? '—' : escapeHtml(value)
        const title = blank ? '' : ` title="${escapeHtml(value)}"`
        return `<td class="${classes.join(' ')}"${title}>${text}</td>`
      }).join('')
      return `<tr>${cells}</tr>`
    }).join('')
  }, [payload, shown, pinned])

  /* New results start at the first row, otherwise they sit hidden above the
     scroll position and the table looks truncated.

     Vertical only. Resetting scrollLeft too would yank the user back to column
     one every time results arrive -- which is exactly what happens when they
     type in the filter box of, say, the 30th column: the results they asked
     for appear, and the column they were looking at scrolls off screen. The
     horizontal position is where the user put it, so leave it alone. */
  useLayoutEffect(() => {
    if (container.current) {
      container.current.scrollTop = 0
    }
  }, [payload])

  if (error) {
    return (
      <section className="results">
        <div className="placeholder error">
          <span className="mono">{error}</span>
          <span className="mono muted" style={{ fontSize: '11px' }} />
        </div>
      </section>
    )
  }

  if (!payload) {
    return (
      <section className="results">
        <div className="placeholder">
          <span className="mono">Choose a row limit and press Search.</span>
          <span className="mono muted" style={{ fontSize: '11px' }} />
        </div>
      </section>
    )
  }

  if (payload.rows.length === 0) {
    return (
      <section className="results">
        <div className="placeholder">
          <span className="mono">No rows match these filters.</span>
          <span className="mono muted" style={{ fontSize: '11px' }}>
            Try clearing a column filter, or switching partial match on.
          </span>
        </div>
      </section>
    )
  }

  return (
    <section className="results">
      <div className="table-container" ref={container}>
        <table>
          <thead>
            <tr>
              {shown.map((name) => (
                <th key={name} className={name === pinned ? 'pinned' : ''}>{name}</th>
              ))}
            </tr>
            {/* Second header row rather than a separate element: it has to
                scroll sideways in lockstep with its columns, and being inside
                <thead> makes it sticky for free. NB the class is
                `col-filter-row`, not `filter-row` -- that one belongs to the
                filter panel, where it is a flex row that goes column-direction
                on narrow screens, which stacks these cells vertically. */}
            <tr className="col-filter-row">
              {shown.map((name) => (
                <th key={name} className={name === pinned ? 'pinned' : ''}>
                  <input
                    type="text"
                    className="col-filter"
                    value={columnFilters[name] ?? ''}
                    placeholder="filter"
                    aria-label={`Filter ${name}`}
                    onChange={(event) =>
                      onColumnFilterChange(name, event.target.value)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody dangerouslySetInnerHTML={{ __html: bodyHtml }} />
        </table>
      </div>
    </section>
  )
}
