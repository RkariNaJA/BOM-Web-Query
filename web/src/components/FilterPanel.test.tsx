// web/src/components/FilterPanel.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { FilterSpec } from '../api/types'
import FilterPanel from './FilterPanel'

const SPECS: FilterSpec[] = [
  { column: 'STYLE_NBR', kind: 'text', param: 'style_nbr', suggest: true, note: '' },
  {
    column: 'Buy Code', kind: 'text', param: 'buy_code', suggest: true,
    note: 'null on 87% of rows (316,623 of 362,733)',
  },
  {
    column: 'BOM_UPDATE_DT', kind: 'date', param_from: 'updated_from',
    param_to: 'updated_to', suggest: false, note: '',
    bounds: { min: '2025-10-29', max: '2026-08-09' },
  },
]

function renderPanel(overrides: Partial<React.ComponentProps<typeof FilterPanel>> = {}) {
  const props = {
    specs: SPECS,
    values: { style_nbr: '', buy_code: '', updated_from: '', updated_to: '' },
    partial: false,
    busy: false,
    columnsButton: <button type="button">Columns</button>,
    onValueChange: vi.fn(),
    onPartialChange: vi.fn(),
    onSearch: vi.fn(),
    onReset: vi.fn(),
    ...overrides,
  }
  render(<FilterPanel {...props} />)
  return props
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ column: '', values: [] }),
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

test('renders a field per spec, labelled by column name', () => {
  renderPanel()
  expect(screen.getByText('STYLE_NBR')).toBeInTheDocument()
  expect(screen.getByText('Buy Code')).toBeInTheDocument()
  expect(screen.getByText('BOM_UPDATE_DT')).toBeInTheDocument()
})

test('shows the spec note under a field', () => {
  renderPanel()
  expect(screen.getByText('null on 87% of rows (316,623 of 362,733)'))
    .toBeInTheDocument()
})

test('derives a note from the date bounds when the spec has none', () => {
  renderPanel()
  expect(screen.getByText('data spans 2025-10-29 → 2026-08-09')).toBeInTheDocument()
})

test('bounds the date inputs', () => {
  renderPanel()
  const from = screen.getByLabelText('BOM_UPDATE_DT from')
  expect(from).toHaveAttribute('min', '2025-10-29')
  expect(from).toHaveAttribute('max', '2026-08-09')
})

test('disables Search while a query is running', () => {
  renderPanel({ busy: true })
  expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
})

test('reports a filter value change by param name', async () => {
  const props = renderPanel()
  await userEvent.type(screen.getByPlaceholderText('e.g. AB1234'), 'I')
  expect(props.onValueChange).toHaveBeenCalledWith('style_nbr', 'I')
})

test('Search and Reset call their handlers', async () => {
  const props = renderPanel()
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await userEvent.click(screen.getByRole('button', { name: 'Reset' }))
  expect(props.onSearch).toHaveBeenCalledTimes(1)
  expect(props.onReset).toHaveBeenCalledTimes(1)
})
