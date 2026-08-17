import type { ReactNode } from 'react'
import type { FilterSpec } from '../api/types'
import FilterField from './FilterField'
import Toggle from './Toggle'

interface Props {
  specs: FilterSpec[]
  values: Record<string, string>
  partial: boolean
  busy: boolean
  /** How many per-column filters are set, and how to clear them. Shown only
   *  when there are any -- with 60 columns a filter set on column 45 is
   *  otherwise invisible from here, and the count is the only clue. */
  columnFilterCount: number
  onClearColumnFilters: () => void
  columnsButton: ReactNode
  onValueChange: (param: string, value: string) => void
  onPartialChange: (next: boolean) => void
  onSearch: () => void
  onReset: () => void
}

export default function FilterPanel({
  specs, values, partial, busy, columnFilterCount, onClearColumnFilters,
  columnsButton, onValueChange, onPartialChange, onSearch, onReset,
}: Props) {
  return (
    <section className="filter-panel">
      <div className="micro-label">Filter</div>

      {/* Driven entirely by /api/meta's filter spec: adding a filter
          server-side needs no change here. */}
      <div className="filter-grid">
        {specs.map((spec) => (
          <FilterField
            key={spec.column}
            spec={spec}
            values={values}
            onChange={onValueChange}
            onSubmit={onSearch}
          />
        ))}
      </div>

      <div className="filter-row">
        <div className="picker-wrap">{columnsButton}</div>
      </div>

      <div className="filter-row">
        <Toggle checked={partial} onChange={onPartialChange} label="partial match (LIKE)" />
        <span className="spacer" />
        {columnFilterCount > 0 && (
          <button
            type="button"
            className="btn-text has-filters"
            onClick={onClearColumnFilters}
          >
            clear {columnFilterCount} column filter
            {columnFilterCount > 1 ? 's' : ''}
          </button>
        )}
        <button type="button" className="btn-text" onClick={onReset}>Reset</button>
        <button
          type="button"
          className="btn-primary"
          disabled={busy}
          onClick={onSearch}
        >
          Search
        </button>
      </div>
    </section>
  )
}
