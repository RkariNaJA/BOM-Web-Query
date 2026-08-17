import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import Combobox from './Combobox'

const VALUES = ['AB1234', 'AB1235', 'XX0001']

function stubDistinct(values: string[] = VALUES) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ column: 'STYLE_NBR', values }),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderCombo(overrides: Partial<React.ComponentProps<typeof Combobox>> = {}) {
  const props = {
    column: 'STYLE_NBR', suggest: true, placeholder: 'e.g. AB1234',
    value: '', onChange: vi.fn(), onSubmit: vi.fn(), ...overrides,
  }
  render(<Combobox {...props} />)
  return props
}

beforeEach(() => { stubDistinct() })
afterEach(() => { vi.unstubAllGlobals() })

test('does not fetch values until the input is focused', () => {
  const fetchMock = stubDistinct()
  renderCombo()
  expect(fetchMock).not.toHaveBeenCalled()
})

test('fetches once on first focus and not again on refocus', async () => {
  const fetchMock = stubDistinct()
  renderCombo()
  const input = screen.getByPlaceholderText('e.g. AB1234')
  await userEvent.click(input)
  await screen.findByText('AB1234')
  await userEvent.tab()
  await userEvent.click(input)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

test('never fetches when suggest is false', async () => {
  const fetchMock = stubDistinct()
  renderCombo({ suggest: false })
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  expect(fetchMock).not.toHaveBeenCalled()
})

test('filters case-insensitively on the typed value', async () => {
  renderCombo({ value: 'ab123' })
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  await screen.findByText('AB1234')
  expect(screen.getByText('AB1235')).toBeInTheDocument()
  expect(screen.queryByText('XX0001')).not.toBeInTheDocument()
})

test('caps the list at 200 and says how many more there are', async () => {
  stubDistinct(Array.from({ length: 250 }, (_, i) => `V${i}`))
  renderCombo()
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  await screen.findByText('V0')
  expect(screen.getByText('50 more — keep typing')).toBeInTheDocument()
  expect(screen.queryByText('V200')).not.toBeInTheDocument()
})

test('tells the user free text is still accepted when nothing matches', async () => {
  renderCombo({ value: 'ZZZZ' })
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  expect(await screen.findByText('no match — free text is still accepted'))
    .toBeInTheDocument()
})

test('a failed fetch is not fatal — the field still takes free text', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
  const props = renderCombo()
  const input = screen.getByPlaceholderText('e.g. AB1234')
  await userEvent.click(input)
  await userEvent.type(input, 'AB1234')
  expect(props.onChange).toHaveBeenCalled()
})

test('picking a value reports it and closes the list', async () => {
  const props = renderCombo()
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  await userEvent.click(await screen.findByText('AB1235'))
  expect(props.onChange).toHaveBeenCalledWith('AB1235')
  expect(screen.queryByText('AB1234')).not.toBeInTheDocument()
})

test('Enter submits and closes the list', async () => {
  const props = renderCombo()
  const input = screen.getByPlaceholderText('e.g. AB1234')
  await userEvent.click(input)
  await screen.findByText('AB1234')
  await userEvent.keyboard('{Enter}')
  expect(props.onSubmit).toHaveBeenCalledTimes(1)
  expect(screen.queryByText('AB1234')).not.toBeInTheDocument()
})

test('Escape closes the list without submitting', async () => {
  const props = renderCombo()
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  await screen.findByText('AB1234')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByText('AB1234')).not.toBeInTheDocument()
  expect(props.onSubmit).not.toHaveBeenCalled()
})

test('a click outside closes the list', async () => {
  render(<div data-testid="outside">elsewhere</div>)
  renderCombo()
  await userEvent.click(screen.getByPlaceholderText('e.g. AB1234'))
  await screen.findByText('AB1234')
  await userEvent.click(screen.getByTestId('outside'))
  expect(screen.queryByText('AB1234')).not.toBeInTheDocument()
})

/* The original registered one document listener per combobox and never removed
   it; not leaking is a stated reason this task exists. Without this test,
   deleting the useEffect's cleanup return leaves every other test green —
   Testing Library unmounts the tree between tests, so the orphaned handler's
   `host.current?.contains` just goes undefined and fails silently. */
test('removes its document click listener on unmount', () => {
  const addSpy = vi.spyOn(document, 'addEventListener')
  const removeSpy = vi.spyOn(document, 'removeEventListener')
  const { unmount } = render(
    <Combobox
      column="STYLE_NBR" suggest placeholder="e.g. AB1234"
      value="" onChange={vi.fn()} onSubmit={vi.fn()}
    />,
  )
  const registered = addSpy.mock.calls.find((call) => call[0] === 'click')
  expect(registered).toBeDefined()
  unmount()
  expect(removeSpy).toHaveBeenCalledWith('click', registered![1])
  addSpy.mockRestore()
  removeSpy.mockRestore()
})
