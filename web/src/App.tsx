import { useReducer, useState } from 'react'
import { exportUrl } from './api/client'
import { exportParams, rowsParams, type ParamOverrides } from './api/params'
import AppBar from './components/AppBar'
import ColumnPicker from './components/ColumnPicker'
import FilterPanel from './components/FilterPanel'
import FooterBar from './components/FooterBar'
import IconSprite from './components/IconSprite'
import ResultsTable from './components/ResultsTable'
import { initialQueryState, queryReducer, hasAnyFilter } from './state/queryReducer'
import { useMeta } from './state/useMeta'
import { useSearch } from './state/useSearch'
import { fmt } from './utils/format'

export default function App() {
  const { meta, source, totalRows, bootError, connected } = useMeta()
  const search = useSearch()
  const [state, dispatch] = useReducer(queryReducer, initialQueryState)
  const [ready, setReady] = useState(false)
  const [hasRun, setHasRun] = useState(false)

  // Seed the reducer from /api/meta exactly once.
  if (meta && !ready) {
    dispatch({ type: 'init', specs: meta.filters, defaultColumns: meta.default_columns })
    setReady(true)
  }

  /** Every query goes through here. Overrides exist because React state
   *  setters are asynchronous: a handler that has just computed a new page or
   *  column set must search with it, not with the value still in state. */
  async function runSearch(overrides?: ParamOverrides) {
    setHasRun(true)
    await search.run(rowsParams(state, overrides))
  }

  /* Every column change re-queries immediately. Against the view this needed
     care -- revealing a detection column cost ~60 s, so the user had to opt in
     by pressing Search. The snapshot answers a 60-column page in ~1 ms, so the
     distinction between a free change and an expensive one no longer exists. */
  function onVisibleChange(next: Set<string>) {
    dispatch({ type: 'setVisible', value: next })
    if (!hasRun) return // nothing fetched yet; Search will pick it up
    void runSearch({ visible: next })
  }

  function onReset() {
    dispatch({ type: 'reset' })
    if (hasRun) {
      void search.run(rowsParams({
        ...state,
        values: Object.fromEntries(Object.keys(state.values).map((k) => [k, ''])),
        partial: false,
        page: 1,
        visible: new Set(state.defaultColumns),
      }))
    }
  }

  function onPageSizeChange(next: number) {
    dispatch({ type: 'setPageSize', value: next })
    if (hasRun) void runSearch({ pageSize: next, page: 1 })
  }

  function onPage(next: number) {
    dispatch({ type: 'setPage', value: next })
    void runSearch({ page: next })
  }

  function onExport() {
    if (!hasAnyFilter(state)) {
      const size = search.payload ? fmt(search.payload.total) : 'every'
      const proceed = window.confirm(
        `No filter is set, so this exports ${size} rows over ` +
        `${state.visible.size} columns. Continue?`,
      )
      if (!proceed) return
    }
    window.location.href = exportUrl(exportParams(state))
  }

  /* Only a HEALTH failure means "not connected". If /api/health succeeded and
     /api/meta then failed, the snapshot is readable and the glyph stays green. */
  const unreachable = bootError !== null && !connected
  const connKind = unreachable ? 'error' : hasRun || search.busy
    ? search.connKind : connected ? 'ready' : 'idle'
  const connText = unreachable ? 'not connected' : hasRun || search.busy
    ? search.connText : connected ? 'connected' : 'connecting…'

  return (
    <>
      <IconSprite />
      <AppBar
        source={source}
        connKind={connKind}
        connText={connText}
        totalRows={totalRows}
        builtAt={meta?.snapshot?.built_at ?? null}
      />

      {meta && (
        <FilterPanel
          specs={meta.filters}
          values={state.values}
          partial={state.partial}
          busy={search.busy}
          columnsButton={
            <ColumnPicker
              groups={meta.groups}
              allColumns={meta.columns.map((column) => column.name)}
              defaultColumns={meta.default_columns}
              pinned={meta.pinned}
              visible={state.visible}
              onVisibleChange={onVisibleChange}
            />
          }
          onValueChange={(param, value) => dispatch({ type: 'setValue', param, value })}
          onPartialChange={(value) => dispatch({ type: 'setPartial', value })}
          onSearch={() => { void runSearch({ page: 1 }) }}
          onReset={onReset}
        />
      )}

      <ResultsTable
        payload={hasRun ? search.payload : null}
        allColumns={meta ? meta.columns.map((column) => column.name) : []}
        visible={state.visible}
        pinned={meta?.pinned ?? ''}
        error={bootError ?? search.error}
      />

      <FooterBar
        payload={hasRun ? search.payload : null}
        elapsedText={search.elapsedText}
        pageSize={state.pageSize}
        pageSizes={meta?.page_sizes ?? [100, 250, 500, 1000]}
        onPageSizeChange={onPageSizeChange}
        onPrev={() => { if (state.page > 1) onPage(state.page - 1) }}
        onNext={() => onPage(state.page + 1)}
        onExport={onExport}
      />
    </>
  )
}
