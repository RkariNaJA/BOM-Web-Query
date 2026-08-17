import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import type { RowsPayload } from '../api/types'
import ResultsTable from './ResultsTable'

const ALL = ['BOM_ROW_NBR', 'STYLE_NBR', 'MASTER_BOM_STATUS']

function payload(overrides: Partial<RowsPayload> = {}): RowsPayload {
  return {
    columns: ALL,
    all_columns: ALL,
    fetched_columns: ALL,
    rows: [[1, 'AB1234', 'ไม่นับ'], [2, null, '']],
    total: 2, page: 1, page_size: 100, pages: 1,
    elapsed: 23.1, cached: false, capped: false,
    ...overrides,
  }
}

function renderTable(overrides: Partial<React.ComponentProps<typeof ResultsTable>> = {}) {
  // Returned, not discarded: three tests below destructure `container` to
  // query the tbody directly, since its cells are written as raw HTML and
  // carry no accessible roles Testing Library can select on.
  return render(
    <ResultsTable
      payload={payload()}
      allColumns={ALL}
      visible={new Set(ALL)}
      pinned="BOM_ROW_NBR"
      error={null}
      {...overrides}
    />,
  )
}

test('prompts for a search before anything has run', () => {
  renderTable({ payload: null })
  expect(screen.getByText('Choose a row limit and press Search.')).toBeInTheDocument()
})

test('shows an error in signal red instead of the table', () => {
  const { container } = render(
    <ResultsTable payload={null} allColumns={ALL} visible={new Set(ALL)}
      pinned="BOM_ROW_NBR" error="Query failed: timeout" />,
  )
  expect(screen.getByText('Query failed: timeout')).toBeInTheDocument()
  expect(container.querySelector('.placeholder')).toHaveClass('error')
})

test('suggests a way out when nothing matched', () => {
  renderTable({ payload: payload({ rows: [], total: 0 }) })
  expect(screen.getByText('No rows match these filters.')).toBeInTheDocument()
  expect(screen.getByText('Try switching partial match on, or clearing a filter.'))
    .toBeInTheDocument()
})

test('renders a header cell per visible column, in view order', () => {
  renderTable()
  const headers = screen.getAllByRole('columnheader').map((th) => th.textContent)
  expect(headers).toEqual(ALL)
})

test('projects to the visible subset without touching the payload', () => {
  renderTable({ visible: new Set(['BOM_ROW_NBR', 'MASTER_BOM_STATUS']) })
  const headers = screen.getAllByRole('columnheader').map((th) => th.textContent)
  expect(headers).toEqual(['BOM_ROW_NBR', 'MASTER_BOM_STATUS'])
})

test('renders values, including Thai, and an em dash for null and empty', () => {
  const { container } = renderTable()
  const cells = [...container.querySelectorAll('tbody td')].map((td) => td.textContent)
  expect(cells).toEqual(['1', 'AB1234', 'ไม่นับ', '2', '—', '—'])
})

test('marks null and empty cells with the null class', () => {
  const { container } = renderTable()
  const secondRow = container.querySelectorAll('tbody tr')[1]
  expect(secondRow.querySelectorAll('td')[1]).toHaveClass('null')
})

test('marks the pinned column on both the header and the body', () => {
  const { container } = renderTable()
  expect(container.querySelector('thead th')).toHaveClass('pinned')
  expect(container.querySelector('tbody td')).toHaveClass('pinned')
})

test('escapes markup in cell values', () => {
  const { container } = render(
    <ResultsTable
      payload={payload({ rows: [[1, '<img src=x onerror=alert(1)>', 'ok']] })}
      allColumns={ALL} visible={new Set(ALL)} pinned="BOM_ROW_NBR" error={null} />,
  )
  expect(container.querySelector('tbody img')).toBeNull()
  expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeInTheDocument()
})

test('escapes markup in the title attribute', () => {
  const { container } = render(
    <ResultsTable
      payload={payload({ rows: [[1, 'a" onmouseover="alert(1)', 'ok']] })}
      allColumns={ALL} visible={new Set(ALL)} pinned="BOM_ROW_NBR" error={null} />,
  )
  const cell = container.querySelectorAll('tbody td')[1]
  expect(cell.getAttribute('onmouseover')).toBeNull()
  expect(cell.getAttribute('title')).toBe('a" onmouseover="alert(1)')
})

test('escapes markup in column names', () => {
  // A hostile name must actually flow through, or this test passes against an
  // implementation that interpolates header names into an HTML string.
  const hostile = '<script>alert(1)</script>'
  const columns = ['BOM_ROW_NBR', hostile]
  const { container } = render(
    <ResultsTable
      payload={payload({
        columns, all_columns: columns, fetched_columns: columns, rows: [[1, 'ok']],
      })}
      allColumns={columns} visible={new Set(columns)}
      pinned="BOM_ROW_NBR" error={null} />,
  )
  expect(container.querySelector('thead script')).toBeNull()
  expect(screen.getAllByRole('columnheader').map((th) => th.textContent))
    .toEqual(['BOM_ROW_NBR', hostile])
})

test('renders an em dash for a visible column the payload does not carry', () => {
  // Reachable in normal use: /api/rows reports `fetched_columns` that can
  // exceed the `columns` it actually returned, so a shown column may have no
  // index in a given row. It must degrade, not crash or misalign.
  const { container } = renderTable({
    payload: payload({ columns: ['BOM_ROW_NBR'], rows: [[1]] }),
  })
  const cells = [...container.querySelectorAll('tbody td')].map((td) => td.textContent)
  expect(cells).toEqual(['1', '—', '—'])
  expect(container.querySelectorAll('tbody td')[1]).toHaveClass('null')
})
