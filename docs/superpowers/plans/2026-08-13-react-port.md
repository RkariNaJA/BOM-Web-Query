# BOM Query Web React Port — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vanilla-JS frontend of BOM Query Web with a React + TypeScript app built by Vite, with no change to the Python backend and no change to how the screen looks or behaves.

**Architecture:** Vite builds from `web/` into `src/static` with `base: '/static/'`, which the existing FastAPI `StaticFiles` mount and `FileResponse` already serve — so `src/main.py` is not touched. Query-shaping state lives in one `useReducer`; server-derived state lives in `useState` in `App`. The results table renders from the last payload, never from live filter state, which is what makes hiding a column free.

**Tech Stack:** React 19.2, TypeScript 7.0, Vite 8.2, Vitest 4.1, @testing-library/react 16 + jsdom 29. No state-management, routing, or UI library. Existing `style.css` / `controls.css` are reused verbatim.

> Versions resolved by unpinned `npm install` during Task 1 and are newer than this plan originally assumed (TS 5 / Vite 7 / Vitest 3). Build, typecheck and tests all pass on them, so they stand. TypeScript 7 is stricter than 5 about ambient types — `web/src/vite-env.d.ts` (`/// <reference types="vite/client" />`) is required for the CSS side-effect imports in `main.tsx` to typecheck, and was added in Task 1 though no step names it.

**Spec:** `docs/superpowers/specs/2026-08-13-react-port-design.md`

## Global Constraints

- **The Python backend is never modified.** `src/main.py`, `src/db.py`, `src/config.py` are read-only for this work. If a task appears to need a backend change, stop and raise it.
- **No new runtime CDN dependency.** The Google Fonts `<link>` in `index.html` is the only external request and it carries over unchanged. Everything else is bundled locally.
- **This project is not under version control.** There is no `git`, so the usual "commit" step is replaced by a **Checkpoint** step that runs `npm test -- --run` and `npx tsc --noEmit`. Do not run `git init`; that decision was made deliberately.
- **`legacy-static/` is never deleted.** It holds the working pre-port frontend and is the only rollback path.
- **CSS is copied byte-for-byte.** Do not reformat, rename a class, or "tidy" `style.css` or `controls.css`. Class names in JSX must match them exactly.
- Every value rendered from database content passes through `escapeHtml`.
- Node v24.11.1 / npm 11.6.2 are installed and verified on the dev machine.
- All commands run from the project root, `C:\Users\chayodom.k\Desktop\Pyrhon Refresh File\BOM Query Web`, unless a step says otherwise.

## File Structure

| File | Responsibility |
|---|---|
| `package.json`, `tsconfig.json`, `tsconfig.node.json` | toolchain |
| `vite.config.ts` | build + dev proxy (replaces the unused `vite.config.js` stub) |
| `vitest.config.ts` | test runner — separate file so Vitest is not affected by `root: 'web'` |
| `web/index.html` | font link, `<div id="root">` |
| `web/src/main.tsx` | mount, CSS imports |
| `web/src/App.tsx` | composition, server-derived state, handlers |
| `web/src/api/types.ts` | wire types for all five endpoints |
| `web/src/api/client.ts` | fetch wrappers, error extraction |
| `web/src/api/params.ts` | pure query-string builders |
| `web/src/state/queryReducer.ts` | filter values, partial, limit, page, pageSize, visible |
| `web/src/state/useMeta.ts` | boot sequence + total-row polling |
| `web/src/state/useSearch.ts` | query execution, busy guard, elapsed ticker |
| `web/src/utils/format.ts` | `fmt`, `escapeHtml`, `addedColumns`, `staleNote` |
| `web/src/components/*.tsx` | 12 presentational components, one per existing markup block |
| `web/src/styles/style.css`, `controls.css` | copied verbatim |
| `web/src/test/setup.ts` | jest-dom matchers |

---

## Task 1: Toolchain scaffold

Stands up the build, the test runner, and the served-through-FastAPI path — and proves the loop works end to end before any component exists.

**Files:**
- Move: `src/static/` → `legacy-static/`
- Delete: `vite.config.js` (the unused stub)
- Create: `package.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`, `vitest.config.ts`, `.gitignore`
- Create: `web/index.html`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/test/setup.ts`, `web/src/test/smoke.test.tsx`
- Copy: `legacy-static/style.css` → `web/src/styles/style.css`, `legacy-static/controls.css` → `web/src/styles/controls.css`

**Interfaces:**
- Consumes: nothing.
- Produces: `npm run dev`, `npm run build`, `npm test`; a mountable `App` component; the `web/src/styles/` CSS location every later task relies on.

- [ ] **Step 1: Preserve the existing frontend**

```bash
mv src/static legacy-static
rm vite.config.js
```

Verify `legacy-static/` now contains `index.html`, `app.js`, `filters.js`, `style.css`, `controls.css`.

- [ ] **Step 2: Copy the stylesheets into the React tree**

```bash
mkdir -p web/src/styles web/src/api web/src/state web/src/utils web/src/components web/src/test
cp legacy-static/style.css web/src/styles/style.css
cp legacy-static/controls.css web/src/styles/controls.css
```

Do not edit either file.

- [ ] **Step 3: Install dependencies**

```bash
npm init -y
npm install react react-dom
npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom \
  vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom
```

- [ ] **Step 4: Write `package.json` scripts**

Replace the `"scripts"` block that `npm init -y` generated with:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "typecheck": "tsc --noEmit"
  },
  "type": "module"
}
```

- [ ] **Step 5: Write `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["web/src", "vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 6: Write `vite.config.ts`**

`base` differs between dev and build: in dev Vite serves at `/`, but the production bundle is served by FastAPI's `/static` mount, so built asset URLs must be prefixed.

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Builds into src/static so FastAPI's existing StaticFiles mount and the
// FileResponse at "/" serve the app with no change to main.py.
export default defineConfig(({ command }) => ({
  root: 'web',
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: {
    outDir: '../src/static',
    emptyOutDir: true,
  },
}))
```

- [ ] **Step 7: Write `vitest.config.ts`**

A separate file, so the test runner is not subject to `root: 'web'`.

```ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    css: false,
    setupFiles: ['./web/src/test/setup.ts'],
    include: ['web/src/**/*.test.{ts,tsx}'],
  },
})
```

- [ ] **Step 8: Write `web/src/test/setup.ts`**

```ts
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 9: Write `web/index.html`**

The font `<link>` and its two `preconnect`s are copied exactly from `legacy-static/index.html`; they are a progressive enhancement that degrades to system fonts and local Noto Sans Thai when the network blocks Google Fonts.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BOM Query</title>
<!-- Webfonts are a progressive enhancement: if the network blocks Google
     Fonts, the stacks in style.css fall back to system-ui / Consolas and any
     locally installed Noto Sans Thai, so Thai values still render. -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=Noto+Sans+Thai:wght@400;600&family=Noto+Sans+Thai+Looped:wght@400;600&display=swap">
</head>
<body>
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
</body>
</html>
```

- [ ] **Step 10: Write `web/src/main.tsx`**

`style.css` must be imported before `controls.css` — `controls.css` reads the `:root` tokens the other defines.

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles/style.css'
import './styles/controls.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

> A third import, `./styles/root.css`, is added in Task 11 after live
> verification found that the `#root` wrapper breaks the body-level flex column
> the original relies on. See Task 11, Step 2b.

- [ ] **Step 11: Write a placeholder `web/src/App.tsx`**

```tsx
export default function App() {
  return <div className="wordmark">BOM Query</div>
}
```

- [ ] **Step 12: Write the smoke test**

```tsx
// web/src/test/smoke.test.tsx
import { render, screen } from '@testing-library/react'
import App from '../App'

test('App renders', () => {
  render(<App />)
  expect(screen.getByText('BOM Query')).toBeInTheDocument()
})
```

- [ ] **Step 13: Run the test**

Run: `npm test -- --run`
Expected: 1 passed.

- [ ] **Step 14: Build and verify FastAPI serves it**

```bash
npm run build
```

Expected: `src/static/index.html` and `src/static/assets/index-<hash>.js` exist. Open `src/static/index.html` and confirm the script tag reads `src="/static/assets/index-<hash>.js"` — the `/static/` prefix is what makes the FastAPI mount work.

Then, from `src/`, run `uvicorn main:app --port 8000` and open <http://127.0.0.1:8000>. Expected: the words "BOM Query" render, and the browser devtools Network tab shows the JS and CSS loading from `/static/assets/` with status 200.

- [ ] **Step 15: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`
Expected: tests pass, no type errors.

---

## Task 2: Wire types and API client

**Files:**
- Create: `web/src/api/types.ts`, `web/src/api/client.ts`
- Test: `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: all wire types; `ApiError`; `getHealth()`, `getMeta()`, `getDistinct(column)`, `getRows(params)`, `exportUrl(params)`.

- [ ] **Step 1: Write `web/src/api/types.ts`**

Shapes are taken from `src/db.py` and `src/main.py`. `rows` is an array of arrays positionally aligned to `columns`, not an array of objects.

```ts
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
  default_hidden: string[]
  /** Measured seconds each expensive column adds. Only the 3 DETECTION columns appear. */
  column_costs: Record<string, number>
  row_limits: string[]
  page_sizes: number[]
  min_page_size: number
  default_page_size: number
  default_row_limit: number
  /** null on a cold server — /api/meta only peeks at the cached count. */
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
```

- [ ] **Step 2: Write the failing test**

```ts
// web/src/api/client.test.ts
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npm test -- --run web/src/api/client.test.ts`
Expected: FAIL — `Failed to resolve import "./client"`.

- [ ] **Step 4: Write `web/src/api/client.ts`**

```ts
import type { DistinctPayload, Health, Meta, RowsPayload } from './types'

/** Carries the HTTP status so callers can tell "db down" from "bad request". */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

/** FastAPI puts the human-readable message in `detail`. Fall back to the
 *  status line when the body is not JSON (e.g. a proxy error page). */
export async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      if (body && typeof body.detail === 'string') detail = body.detail
    } catch {
      // leave the status-line fallback in place
    }
    throw new ApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

export async function getHealth(): Promise<Health> {
  return readJson<Health>(await fetch('/api/health'))
}

export async function getMeta(): Promise<Meta> {
  return readJson<Meta>(await fetch('/api/meta'))
}

export async function getDistinct(column: string): Promise<DistinctPayload> {
  return readJson<DistinctPayload>(
    await fetch(`/api/distinct?column=${encodeURIComponent(column)}`),
  )
}

export async function getRows(params: URLSearchParams): Promise<RowsPayload> {
  return readJson<RowsPayload>(await fetch(`/api/rows?${params}`))
}

/** Export is a navigation, not a fetch, so the browser handles the streaming
 *  download and the Content-Disposition filename. */
export function exportUrl(params: URLSearchParams): string {
  return `/api/export.csv?${params}`
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npm test -- --run web/src/api/client.test.ts`
Expected: 7 passed.

- [ ] **Step 6: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`

---

## Task 3: Query state and pure helpers

The reducer and the parameter builder. Both are pure, and they hold the rules that must not regress: reset returns to the default 58 columns rather than all 60, and search parameters can be built from an override so a just-changed `visible` set is never stale.

**Files:**
- Create: `web/src/utils/format.ts`, `web/src/state/queryReducer.ts`, `web/src/api/params.ts`
- Test: `web/src/utils/format.test.ts`, `web/src/state/queryReducer.test.ts`, `web/src/api/params.test.ts`

**Interfaces:**
- Consumes: `FilterSpec` from `web/src/api/types.ts`.
- Produces:
  - `fmt(n: number | null | undefined): string`
  - `escapeHtml(value: unknown): string`
  - `addedColumns(visible: Set<string>, fetched: Set<string>): string[]`
  - `staleNote(added: string[], costs: Record<string, number>): string`
  - `type RowLimit = '100' | '1000' | '10000' | 'all'`
  - `interface QueryState`, `type QueryAction`, `initialQueryState`, `queryReducer`, `hasAnyFilter(state)`
  - `rowsParams(state, overrides?)`, `exportParams(state, overrides?)`

- [ ] **Step 1: Write the failing test for `format.ts`**

```ts
// web/src/utils/format.test.ts
import { describe, expect, test } from 'vitest'
import { addedColumns, escapeHtml, fmt, staleNote } from './format'

describe('fmt', () => {
  test('groups thousands', () => { expect(fmt(362733)).toBe('362,733') })
  test('renders an em dash for null', () => { expect(fmt(null)).toBe('—') })
  test('renders an em dash for undefined', () => { expect(fmt(undefined)).toBe('—') })
  test('renders zero as zero, not a dash', () => { expect(fmt(0)).toBe('0') })
})

describe('escapeHtml', () => {
  test('escapes the four dangerous characters', () => {
    expect(escapeHtml('<a href="x">&</a>'))
      .toBe('&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;')
  })
  test('escapes the ampersand first so entities are not doubled', () => {
    expect(escapeHtml('&lt;')).toBe('&amp;lt;')
  })
  test('escapes the apostrophe so single-quoted attributes stay safe', () => {
    expect(escapeHtml("it's")).toBe('it&#39;s')
  })
  test('passes Thai text through unchanged', () => {
    expect(escapeHtml('ไม่นับ')).toBe('ไม่นับ')
  })
  test('stringifies numbers', () => { expect(escapeHtml(42)).toBe('42') })
})

describe('addedColumns', () => {
  test('returns columns not already held by the server', () => {
    expect(addedColumns(new Set(['A', 'B', 'C']), new Set(['A', 'B'])))
      .toEqual(['C'])
  })
  test('returns empty when visible is a subset of fetched', () => {
    expect(addedColumns(new Set(['A']), new Set(['A', 'B']))).toEqual([])
  })
})

describe('staleNote', () => {
  const costs = { TEXT_USE_OF_DETECT: 60.3, TEXT_Color_Code_OF_DETECT: 57.4 }

  test('is empty when nothing was added', () => {
    expect(staleNote([], costs)).toBe('')
  })
  test('rounds and singularises one expensive column', () => {
    expect(staleNote(['TEXT_USE_OF_DETECT'], costs))
      .toBe('+1 column, ~60s — press Search')
  })
  test('sums and pluralises two expensive columns', () => {
    expect(staleNote(['TEXT_USE_OF_DETECT', 'TEXT_Color_Code_OF_DETECT'], costs))
      .toBe('+2 columns, ~118s — press Search')
  })
  test('omits the seconds for a column with no measured cost', () => {
    expect(staleNote(['STYLE_NBR'], costs)).toBe('+1 column — press Search')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run web/src/utils/format.test.ts`
Expected: FAIL — `Failed to resolve import "./format"`.

- [ ] **Step 3: Write `web/src/utils/format.ts`**

```ts
export function fmt(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toLocaleString('en-US')
}

/** The results table is written as an HTML string for performance, so this is
 *  the only thing between database content and injected markup. `&` must be
 *  replaced first or the other replacements' entities get double-escaped. */
export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    // The original escapes only the four above, and every attribute this app
    // generates is double-quoted, so this is defence in depth rather than a
    // live fix: it renders identically and keeps the function safe if a future
    // caller ever builds a single-quoted attribute.
    .replace(/'/g, '&#39;')
}

/** Columns the user wants that the server does not already hold. A non-empty
 *  result means the next search is a real query, potentially ~60 s per column. */
export function addedColumns(visible: Set<string>, fetched: Set<string>): string[] {
  return [...visible].filter((column) => !fetched.has(column))
}

export function staleNote(added: string[], costs: Record<string, number>): string {
  if (added.length === 0) return ''
  const seconds = added.reduce((sum, column) => sum + (costs[column] ?? 0), 0)
  const plural = added.length > 1 ? 's' : ''
  return seconds >= 1
    ? `+${added.length} column${plural}, ~${Math.round(seconds)}s — press Search`
    : `+${added.length} column${plural} — press Search`
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run web/src/utils/format.test.ts`
Expected: 15 passed.

- [ ] **Step 5: Write the failing test for `queryReducer.ts`**

```ts
// web/src/state/queryReducer.test.ts
import { describe, expect, test } from 'vitest'
import type { FilterSpec } from '../api/types'
import { hasAnyFilter, initialQueryState, queryReducer } from './queryReducer'

const SPECS: FilterSpec[] = [
  { column: 'STYLE_NBR', kind: 'text', param: 'style_nbr', suggest: true, note: '' },
  {
    column: 'BOM_UPDATE_DT', kind: 'date', param_from: 'updated_from',
    param_to: 'updated_to', suggest: false, note: '', bounds: null,
  },
]

const DEFAULTS = ['BOM_ROW_NBR', 'STYLE_NBR', 'TEXT_Color_Name_OF_DETECT']

function booted() {
  return queryReducer(initialQueryState, {
    type: 'init', specs: SPECS, defaultColumns: DEFAULTS,
  })
}

describe('init', () => {
  test('seeds an empty value for every filter param, dates included', () => {
    expect(Object.keys(booted().values).sort())
      .toEqual(['style_nbr', 'updated_from', 'updated_to'])
    expect(Object.values(booted().values)).toEqual(['', '', ''])
  })

  test('seeds visible from the server default set', () => {
    expect([...booted().visible].sort()).toEqual([...DEFAULTS].sort())
  })
})

describe('page resets', () => {
  test('changing a filter value returns to page 1', () => {
    const onPage5 = queryReducer(booted(), { type: 'setPage', value: 5 })
    const next = queryReducer(onPage5, {
      type: 'setValue', param: 'style_nbr', value: 'AB1234',
    })
    expect(next.page).toBe(1)
  })

  test('changing the row limit returns to page 1', () => {
    const onPage5 = queryReducer(booted(), { type: 'setPage', value: 5 })
    expect(queryReducer(onPage5, { type: 'setLimit', value: 'all' }).page).toBe(1)
  })

  test('changing the page size returns to page 1', () => {
    const onPage5 = queryReducer(booted(), { type: 'setPage', value: 5 })
    expect(queryReducer(onPage5, { type: 'setPageSize', value: 500 }).page).toBe(1)
  })

  test('changing the partial toggle returns to page 1', () => {
    const onPage5 = queryReducer(booted(), { type: 'setPage', value: 5 })
    expect(queryReducer(onPage5, { type: 'setPartial', value: true }).page).toBe(1)
  })

  test('changing visible columns does NOT reset the page', () => {
    const onPage5 = queryReducer(booted(), { type: 'setPage', value: 5 })
    const next = queryReducer(onPage5, {
      type: 'setVisible', value: new Set(['BOM_ROW_NBR']),
    })
    expect(next.page).toBe(5)
  })
})

describe('reset', () => {
  test('clears every filter value and the partial toggle', () => {
    let state = queryReducer(booted(), {
      type: 'setValue', param: 'style_nbr', value: 'AB1234',
    })
    state = queryReducer(state, { type: 'setPartial', value: true })
    const reset = queryReducer(state, { type: 'reset' })
    expect(reset.values.style_nbr).toBe('')
    expect(reset.partial).toBe(false)
    expect(reset.page).toBe(1)
  })

  test('returns visible to the default set, not to all columns', () => {
    const widened = queryReducer(booted(), {
      type: 'setVisible',
      value: new Set([...DEFAULTS, 'TEXT_USE_OF_DETECT', 'TEXT_Color_Code_OF_DETECT']),
    })
    const reset = queryReducer(widened, { type: 'reset' })
    expect([...reset.visible].sort()).toEqual([...DEFAULTS].sort())
    expect(reset.visible.has('TEXT_USE_OF_DETECT')).toBe(false)
  })

  test('keeps the row limit and page size', () => {
    let state = queryReducer(booted(), { type: 'setLimit', value: '10000' })
    state = queryReducer(state, { type: 'setPageSize', value: 500 })
    const reset = queryReducer(state, { type: 'reset' })
    expect(reset.limit).toBe('10000')
    expect(reset.pageSize).toBe(500)
  })
})

describe('hasAnyFilter', () => {
  test('is false when every value is blank', () => {
    expect(hasAnyFilter(booted())).toBe(false)
  })
  test('is false for whitespace only', () => {
    const state = queryReducer(booted(), {
      type: 'setValue', param: 'style_nbr', value: '   ',
    })
    expect(hasAnyFilter(state)).toBe(false)
  })
  test('is true once a date bound is set', () => {
    const state = queryReducer(booted(), {
      type: 'setValue', param: 'updated_from', value: '2026-01-01',
    })
    expect(hasAnyFilter(state)).toBe(true)
  })
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npm test -- --run web/src/state/queryReducer.test.ts`
Expected: FAIL — `Failed to resolve import "./queryReducer"`.

- [ ] **Step 7: Write `web/src/state/queryReducer.ts`**

```ts
import type { FilterSpec } from '../api/types'

export type RowLimit = '100' | '1000' | '10000' | 'all'

export interface QueryState {
  /** Keyed by the filter spec's query-param name, never by column name — the
   *  view has columns like "Buy Code" that are awkward in a URL. */
  values: Record<string, string>
  partial: boolean
  limit: RowLimit
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
  | { type: 'setLimit'; value: RowLimit }
  | { type: 'setPageSize'; value: number }
  | { type: 'setPage'; value: number }
  | { type: 'setVisible'; value: Set<string> }
  | { type: 'reset' }

export const initialQueryState: QueryState = {
  values: {},
  partial: false,
  limit: '100',
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
    case 'setLimit':
      return { ...state, limit: action.value, page: 1 }
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
        // Deliberately the default set: resetting must not silently re-enable
        // the two nvarchar(max) detection columns at ~60 s each.
        visible: new Set(state.defaultColumns),
      }
    }
  }
}

export function hasAnyFilter(state: QueryState): boolean {
  return Object.values(state.values).some((value) => value.trim() !== '')
}
```

- [ ] **Step 8: Run it to verify it passes**

Run: `npm test -- --run web/src/state/queryReducer.test.ts`
Expected: 13 passed.

- [ ] **Step 9: Write the failing test for `params.ts`**

```ts
// web/src/api/params.test.ts
import { describe, expect, test } from 'vitest'
import type { QueryState } from '../state/queryReducer'
import { exportParams, rowsParams } from './params'

const BASE: QueryState = {
  values: { style_nbr: '', style_season: '', updated_from: '', updated_to: '' },
  partial: false,
  limit: '100',
  page: 1,
  pageSize: 100,
  visible: new Set(['BOM_ROW_NBR', 'STYLE_NBR']),
  defaultColumns: ['BOM_ROW_NBR', 'STYLE_NBR'],
}

describe('rowsParams', () => {
  test('omits blank filters entirely', () => {
    expect(rowsParams(BASE).has('style_nbr')).toBe(false)
  })

  test('omits whitespace-only filters', () => {
    const params = rowsParams({ ...BASE, values: { ...BASE.values, style_nbr: '   ' } })
    expect(params.has('style_nbr')).toBe(false)
  })

  test('trims the values it does send', () => {
    const params = rowsParams({ ...BASE, values: { ...BASE.values, style_nbr: ' AB1234 ' } })
    expect(params.get('style_nbr')).toBe('AB1234')
  })

  test('always sends partial, even when false', () => {
    expect(rowsParams(BASE).get('partial')).toBe('false')
  })

  test('sends limit, page and page_size', () => {
    const params = rowsParams({ ...BASE, limit: 'all', page: 3, pageSize: 500 })
    expect(params.get('limit')).toBe('all')
    expect(params.get('page')).toBe('3')
    expect(params.get('page_size')).toBe('500')
  })

  test('sends columns in the visible set', () => {
    expect(rowsParams(BASE).get('columns')).toBe('BOM_ROW_NBR,STYLE_NBR')
  })

  test('an overridden visible set wins over state', () => {
    const params = rowsParams(BASE, { visible: new Set(['ITEM_NBR']) })
    expect(params.get('columns')).toBe('ITEM_NBR')
  })

  test('an overridden page wins over state', () => {
    expect(rowsParams(BASE, { page: 7 }).get('page')).toBe('7')
  })
})

describe('exportParams', () => {
  test('carries the filters and columns but no paging', () => {
    const params = exportParams({ ...BASE, values: { ...BASE.values, style_nbr: 'AB1234' } })
    expect(params.get('style_nbr')).toBe('AB1234')
    expect(params.get('columns')).toBe('BOM_ROW_NBR,STYLE_NBR')
    expect(params.has('limit')).toBe(false)
    expect(params.has('page')).toBe(false)
    expect(params.has('page_size')).toBe(false)
  })
})
```

- [ ] **Step 10: Run it to verify it fails**

Run: `npm test -- --run web/src/api/params.test.ts`
Expected: FAIL — `Failed to resolve import "./params"`.

- [ ] **Step 11: Write `web/src/api/params.ts`**

```ts
import type { QueryState } from '../state/queryReducer'

/** React state setters are asynchronous, so a handler that has just computed a
 *  new visible set or page must be able to search with it immediately rather
 *  than with the value still in state. */
export type ParamOverrides = Partial<Pick<QueryState, 'visible' | 'page' | 'limit' | 'pageSize'>>

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
  return params
}

export function rowsParams(state: QueryState, overrides?: ParamOverrides): URLSearchParams {
  const resolved = resolve(state, overrides)
  const params = filterParams(resolved)
  params.set('limit', resolved.limit)
  params.set('page', String(resolved.page))
  params.set('page_size', String(resolved.pageSize))
  // Ask for exactly what is on screen: column choice dominates query cost.
  params.set('columns', [...resolved.visible].join(','))
  return params
}

export function exportParams(state: QueryState, overrides?: ParamOverrides): URLSearchParams {
  const resolved = resolve(state, overrides)
  const params = filterParams(resolved)
  params.set('columns', [...resolved.visible].join(','))
  return params
}
```

- [ ] **Step 12: Run it to verify it passes**

Run: `npm test -- --run web/src/api/params.test.ts`
Expected: 9 passed.

- [ ] **Step 13: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`
Expected: 44 passed across 5 files, no type errors.

---

## Task 4: Chrome components

The icon sprite, the two segmented controls, the LIKE toggle, the header, and the notice bar. All presentational.

**Files:**
- Create: `web/src/components/IconSprite.tsx`, `Icon.tsx`, `Segmented.tsx`, `Toggle.tsx`, `AppBar.tsx`, `Notice.tsx`
- Test: `web/src/components/Segmented.test.tsx`, `web/src/components/Toggle.test.tsx`

**Interfaces:**
- Consumes: `fmt` from `web/src/utils/format.ts`.
- Produces:
  - `<IconSprite />` — no props
  - `<Icon name="search" className?="muted" />` where `name` is `'search' | 'chevron-down' | 'chevron-left' | 'chevron-right' | 'grid' | 'download' | 'tick' | 'x'`
  - `<Segmented values={T[]} value={T} label={(v: T) => string} onPick={(v: T) => void} />`
  - `<Toggle checked={boolean} onChange={(next: boolean) => void} label={string} />`
  - `<AppBar source={string} connKind={ConnKind} connText={string} totalRows={number | null} />` with `export type ConnKind = 'idle' | 'ready' | 'working' | 'error'`
  - `<Notice text={string} onDismiss={() => void} />`

- [ ] **Step 1: Write `web/src/components/IconSprite.tsx`**

The eight symbols are copied exactly from `legacy-static/index.html`. This is rendered once at the top of `App`; every `<Icon>` references it by id. No icon font, no CDN.

```tsx
export default function IconSprite() {
  return (
    <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
      <symbol id="i-search" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
        <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" />
      </symbol>
      <symbol id="i-chevron-down" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
        <path d="M4 6.5 8 10.5l4-4" />
      </symbol>
      <symbol id="i-chevron-left" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M9.5 3.5 5 8l4.5 4.5" />
      </symbol>
      <symbol id="i-chevron-right" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M6.5 3.5 11 8l-4.5 4.5" />
      </symbol>
      <symbol id="i-grid" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
        <path d="M2 2h3.2v12H2zM6.4 2h3.2v12H6.4zM10.8 2H14v12h-3.2z" />
      </symbol>
      <symbol id="i-download" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
        <path d="M8 2v8m0 0 3-3M8 10 5 7M2.5 12.5h11" />
      </symbol>
      <symbol id="i-tick" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2">
        <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />
      </symbol>
      <symbol id="i-x" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M4 4l8 8M12 4l-8 8" />
      </symbol>
    </svg>
  )
}
```

- [ ] **Step 2: Write `web/src/components/Icon.tsx`**

```tsx
export type IconName =
  | 'search' | 'chevron-down' | 'chevron-left' | 'chevron-right'
  | 'grid' | 'download' | 'tick' | 'x'

interface Props {
  name: IconName
  className?: string
  style?: React.CSSProperties
}

export default function Icon({ name, className = '', style }: Props) {
  return (
    <svg className={`icon ${className}`.trim()} style={style} aria-hidden="true">
      <use href={`#i-${name}`} />
    </svg>
  )
}
```

- [ ] **Step 3: Write the failing test for `Segmented`**

```tsx
// web/src/components/Segmented.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import Segmented from './Segmented'

test('renders one button per value using the label function', () => {
  render(
    <Segmented
      values={['100', '1000', 'all']}
      value="100"
      label={(v) => (v === 'all' ? 'ALL' : Number(v).toLocaleString('en-US'))}
      onPick={() => {}}
    />,
  )
  expect(screen.getByRole('button', { name: '100' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '1,000' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'ALL' })).toBeInTheDocument()
})

test('marks only the selected value active', () => {
  render(
    <Segmented values={[100, 250]} value={250} label={String} onPick={() => {}} />,
  )
  expect(screen.getByRole('button', { name: '250' })).toHaveClass('active')
  expect(screen.getByRole('button', { name: '100' })).not.toHaveClass('active')
})

test('reports the picked value', async () => {
  const onPick = vi.fn()
  render(<Segmented values={[100, 250]} value={100} label={String} onPick={onPick} />)
  await userEvent.click(screen.getByRole('button', { name: '250' }))
  expect(onPick).toHaveBeenCalledWith(250)
})
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npm test -- --run web/src/components/Segmented.test.tsx`
Expected: FAIL — `Failed to resolve import "./Segmented"`.

- [ ] **Step 5: Write `web/src/components/Segmented.tsx`**

```tsx
interface Props<T> {
  values: readonly T[]
  value: T
  label: (value: T) => string
  onPick: (value: T) => void
}

/** Replaces buildSegmented(). Active state is derived from `value` rather than
 *  held in the DOM, so the row-limit and page-size controls stay in sync with
 *  the reducer even when something else changes them (e.g. Reset). */
export default function Segmented<T extends string | number>({
  values, value, label, onPick,
}: Props<T>) {
  return (
    <div className="segmented">
      {values.map((candidate) => (
        <button
          key={String(candidate)}
          type="button"
          className={candidate === value ? 'active' : ''}
          onClick={() => onPick(candidate)}
        >
          {label(candidate)}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 6: Run it to verify it passes**

Run: `npm test -- --run web/src/components/Segmented.test.tsx`
Expected: 3 passed.

- [ ] **Step 7: Write the failing test for `Toggle`**

```tsx
// web/src/components/Toggle.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import Toggle from './Toggle'

test('exposes switch semantics', () => {
  render(<Toggle checked={false} onChange={() => {}} label="partial match (LIKE)" />)
  const toggle = screen.getByRole('switch', { name: /partial match/ })
  expect(toggle).toHaveAttribute('aria-checked', 'false')
})

test('carries the on class when checked', () => {
  render(<Toggle checked onChange={() => {}} label="partial match (LIKE)" />)
  expect(screen.getByRole('switch')).toHaveClass('on')
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
})

test('flips on click', async () => {
  const onChange = vi.fn()
  render(<Toggle checked={false} onChange={onChange} label="partial match (LIKE)" />)
  await userEvent.click(screen.getByRole('switch'))
  expect(onChange).toHaveBeenCalledWith(true)
})

test('flips on Space and on Enter', async () => {
  const onChange = vi.fn()
  render(<Toggle checked onChange={onChange} label="partial match (LIKE)" />)
  screen.getByRole('switch').focus()
  await userEvent.keyboard(' ')
  await userEvent.keyboard('{Enter}')
  expect(onChange).toHaveBeenCalledTimes(2)
  expect(onChange).toHaveBeenCalledWith(false)
})
```

- [ ] **Step 8: Run it to verify it fails**

Run: `npm test -- --run web/src/components/Toggle.test.tsx`
Expected: FAIL — `Failed to resolve import "./Toggle"`.

- [ ] **Step 9: Write `web/src/components/Toggle.tsx`**

```tsx
interface Props {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
}

/** A div rather than a checkbox because controls.css styles .toggle-track /
 *  .toggle-knob directly. role/aria-checked/tabIndex restore the semantics. */
export default function Toggle({ checked, onChange, label }: Props) {
  const flip = () => onChange(!checked)
  return (
    <div
      className={`toggle${checked ? ' on' : ''}`}
      role="switch"
      aria-checked={checked}
      tabIndex={0}
      onClick={flip}
      onKeyDown={(event) => {
        if (event.key === ' ' || event.key === 'Enter') {
          event.preventDefault()
          flip()
        }
      }}
    >
      <span className="toggle-track"><span className="toggle-knob" /></span>
      <span>{label}</span>
    </div>
  )
}
```

- [ ] **Step 10: Run it to verify it passes**

Run: `npm test -- --run web/src/components/Toggle.test.tsx`
Expected: 4 passed.

- [ ] **Step 11: Write `web/src/components/AppBar.tsx`**

```tsx
import { fmt } from '../utils/format'

/** The ink glyph vocabulary from style.css: filled = ready, half = working,
 *  empty = idle, red = error. */
export type ConnKind = 'idle' | 'ready' | 'working' | 'error'

interface Props {
  source: string
  connKind: ConnKind
  connText: string
  totalRows: number | null
}

export default function AppBar({ source, connKind, connText, totalRows }: Props) {
  return (
    <header className="appbar">
      <span className="wordmark">BOM Query</span>
      <span className="divider" />
      <span className="mono breadcrumb">{source}</span>
      <span className="spacer" />
      <span className="status">
        <span className={`glyph ${connKind}`} />
        <span className="status-text">{connText}</span>
      </span>
      <span className="divider" />
      <span className="mono muted">{fmt(totalRows)} rows</span>
    </header>
  )
}
```

- [ ] **Step 12: Write `web/src/components/Notice.tsx`**

```tsx
interface Props {
  text: string
  onDismiss: () => void
}

export default function Notice({ text, onDismiss }: Props) {
  return (
    <div className="notice">
      <span className="glyph" />
      <span className="mono">{text}</span>
      <span className="spacer" />
      <button type="button" className="btn-text" onClick={onDismiss}>Dismiss</button>
    </div>
  )
}
```

`App` renders `<Notice>` conditionally rather than toggling a `hidden` class, which is why there is no `hidden` prop.

- [ ] **Step 13: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`
Expected: 51 passed across 7 files, no type errors.

---

## Task 5: Combobox

The searchable dropdown behind the five text filters. It is the most behaviour-heavy component: lazy loading on first focus, a 200-row display cap, free text always accepted, and outside-click dismissal that — unlike the current code — is cleaned up on unmount.

**Files:**
- Create: `web/src/components/Combobox.tsx`
- Test: `web/src/components/Combobox.test.tsx`

**Interfaces:**
- Consumes: `getDistinct` from `web/src/api/client.ts`; `escapeHtml` is *not* used here (React escapes JSX text automatically); `fmt` from `web/src/utils/format.ts`; `Icon` from `web/src/components/Icon.tsx`.
- Produces: `<Combobox column={string} suggest={boolean} placeholder={string} value={string} onChange={(v: string) => void} onSubmit={() => void} />`

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/components/Combobox.test.tsx
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run web/src/components/Combobox.test.tsx`
Expected: FAIL — `Failed to resolve import "./Combobox"`.

- [ ] **Step 3: Write `web/src/components/Combobox.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import { getDistinct } from '../api/client'
import { fmt } from '../utils/format'
import Icon from './Icon'

/** 2,405 options would be pointless to paint; the search narrows it. */
const MAX_SHOWN = 200

interface Props {
  column: string
  suggest: boolean
  placeholder: string
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
}

export default function Combobox({
  column, suggest, placeholder, value, onChange, onSubmit,
}: Props) {
  const [values, setValues] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  // A ref, not state: this must gate the fetch without triggering a re-render,
  // and it must survive across focus cycles.
  const requested = useRef(false)
  const host = useRef<HTMLDivElement>(null)

  /* Fetched on first focus, not at boot: each DISTINCT is a several-second
     query against a slow view, and most searches touch one or two fields. */
  async function ensureValues() {
    if (requested.current || !suggest) return
    requested.current = true
    setLoading(true)
    try {
      const data = await getDistinct(column)
      setValues(data.values)
    } catch {
      setValues([]) // not fatal: the field still takes free text
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    function onDocumentClick(event: MouseEvent) {
      if (!host.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onDocumentClick)
    return () => document.removeEventListener('click', onDocumentClick)
  }, [])

  const needle = value.trim().toUpperCase()
  const matches = values.filter((v) => v.toUpperCase().includes(needle))
  const shown = matches.slice(0, MAX_SHOWN)

  return (
    <div className="combo" ref={host}>
      <div className="combo-field">
        <Icon name="search" className="muted" />
        <input
          autoComplete="off"
          placeholder={placeholder}
          value={value}
          onFocus={() => { void ensureValues(); setOpen(true) }}
          onChange={(event) => { setOpen(true); onChange(event.target.value) }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') { setOpen(false); onSubmit() }
            if (event.key === 'Escape') setOpen(false)
          }}
        />
        <Icon name="chevron-down" className="muted" />
      </div>
      {open && (
        <div className="combo-list">
          {loading ? (
            <div className="combo-note">loading values…</div>
          ) : shown.length === 0 ? (
            <div className="combo-note">no match — free text is still accepted</div>
          ) : (
            <>
              {shown.map((option) => (
                <div
                  key={option}
                  onClick={() => { setOpen(false); onChange(option) }}
                >
                  {option}
                </div>
              ))}
              {matches.length > shown.length && (
                <div className="combo-note">
                  {fmt(matches.length - shown.length)} more — keep typing
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run web/src/components/Combobox.test.tsx`
Expected: 12 passed.

- [ ] **Step 5: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`

---

## Task 6: Filter panel

The date range, the per-spec field wrapper, and the panel that lays out all six filters from `/api/meta`. Nothing here knows any column name — adding a filter stays a `config.py` change.

**Files:**
- Create: `web/src/components/DateRange.tsx`, `web/src/components/FilterField.tsx`, `web/src/components/FilterPanel.tsx`
- Test: `web/src/components/FilterPanel.test.tsx`

**Interfaces:**
- Consumes: `Combobox`, `Segmented`, `Toggle`, `Icon`; `FilterSpec`, `DateFilterSpec` from `api/types`; `RowLimit` from `state/queryReducer`.
- Produces:
  - `<DateRange spec={DateFilterSpec} from={string} to={string} onChange={(param: string, value: string) => void} onSubmit={() => void} />`
  - `<FilterField spec={FilterSpec} values={Record<string,string>} onChange={(param, value) => void} onSubmit={() => void} />`
  - `<FilterPanel ... />` — full prop list in Step 5.

- [ ] **Step 1: Write `web/src/components/DateRange.tsx`**

```tsx
import type { DateFilterSpec } from '../api/types'

interface Props {
  spec: DateFilterSpec
  from: string
  to: string
  onChange: (param: string, value: string) => void
  onSubmit: () => void
}

export default function DateRange({ spec, from, to, onChange, onSubmit }: Props) {
  const bounds = spec.bounds
  const fields: Array<{ param: string; value: string; edge: 'from' | 'to' }> = [
    { param: spec.param_from, value: from, edge: 'from' },
    { param: spec.param_to, value: to, edge: 'to' },
  ]

  return (
    <div className="date-range">
      {fields.map((field, index) => (
        <span key={field.param} style={{ display: 'contents' }}>
          {index === 1 && <span className="mono muted">→</span>}
          <div className="combo-field">
            <input
              type="date"
              aria-label={`${spec.column} ${field.edge}`}
              // Absent until the background warm-up finishes; the inputs simply
              // go unbounded until then rather than blocking on it.
              min={bounds?.min}
              max={bounds?.max}
              value={field.value}
              onChange={(event) => onChange(field.param, event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') onSubmit() }}
            />
          </div>
        </span>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Write `web/src/components/FilterField.tsx`**

```tsx
import type { FilterSpec } from '../api/types'
import Combobox from './Combobox'
import DateRange from './DateRange'

/** Hint text only — purely cosmetic, falls back for any column not listed. */
const PLACEHOLDERS: Record<string, string> = {
  STYLE_NBR: 'e.g. AB1234',
  STYLE_SEASON: 'e.g. AB1234SU27',
  ITEM_NBR: 'e.g. 9000001',
  IM: 'e.g. FPLNI9000001',
}

interface Props {
  spec: FilterSpec
  values: Record<string, string>
  onChange: (param: string, value: string) => void
  onSubmit: () => void
}

export default function FilterField({ spec, values, onChange, onSubmit }: Props) {
  let note = spec.note
  let control

  if (spec.kind === 'date') {
    control = (
      <DateRange
        spec={spec}
        from={values[spec.param_from] ?? ''}
        to={values[spec.param_to] ?? ''}
        onChange={onChange}
        onSubmit={onSubmit}
      />
    )
    if (!note && spec.bounds) {
      note = `data spans ${spec.bounds.min} → ${spec.bounds.max}`
    }
  } else {
    control = (
      <Combobox
        column={spec.column}
        suggest={spec.suggest}
        placeholder={PLACEHOLDERS[spec.column] ?? `any ${spec.column}`}
        value={values[spec.param] ?? ''}
        onChange={(value) => onChange(spec.param, value)}
        onSubmit={onSubmit}
      />
    )
  }

  return (
    <label className="field">
      <span className="micro-label">{spec.column}</span>
      {control}
      {note && <span className="mono field-note">{note}</span>}
    </label>
  )
}
```

- [ ] **Step 3: Write the failing test for `FilterPanel`**

```tsx
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
    limit: '100' as const,
    rowLimits: ['100', '1000', '10000', 'all'],
    pageSize: 100,
    busy: false,
    stale: false,
    staleNote: '',
    columnsButton: <button type="button">Columns</button>,
    onValueChange: vi.fn(),
    onPartialChange: vi.fn(),
    onLimitChange: vi.fn(),
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

test('notes that a finite limit is fetched once and paged in memory', () => {
  renderPanel()
  expect(screen.getByText('capped, fetched once then paged in memory'))
    .toBeInTheDocument()
})

test('notes the page-through behaviour when the limit is ALL, naming the page size', () => {
  renderPanel({ limit: 'all', pageSize: 500 })
  // The original prints the actual number, not a generic phrase.
  expect(screen.getByText('pages at 500 rows/page')).toBeInTheDocument()
})

test('disables Search while a query is running', () => {
  renderPanel({ busy: true })
  expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
})

test('flags Search and shows the cost note when the column set is stale', () => {
  renderPanel({ stale: true, staleNote: '+1 column, ~60s — press Search' })
  expect(screen.getByRole('button', { name: 'Search' })).toHaveClass('stale')
  expect(screen.getByText('+1 column, ~60s — press Search')).toBeInTheDocument()
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
```

- [ ] **Step 4: Run it to verify it fails**

Run: `npm test -- --run web/src/components/FilterPanel.test.tsx`
Expected: FAIL — `Failed to resolve import "./FilterPanel"`.

- [ ] **Step 5: Write `web/src/components/FilterPanel.tsx`**

`columnsButton` is a slot rather than a prop bundle: the column picker owns a lot of state, so `App` composes it and hands it in.

```tsx
import type { ReactNode } from 'react'
import type { FilterSpec } from '../api/types'
import type { RowLimit } from '../state/queryReducer'
import FilterField from './FilterField'
import Segmented from './Segmented'
import Toggle from './Toggle'

interface Props {
  specs: FilterSpec[]
  values: Record<string, string>
  partial: boolean
  limit: RowLimit
  rowLimits: string[]
  /** Only used for the ALL-limit note, which names the actual page size. */
  pageSize: number
  busy: boolean
  stale: boolean
  staleNote: string
  columnsButton: ReactNode
  onValueChange: (param: string, value: string) => void
  onPartialChange: (next: boolean) => void
  onLimitChange: (next: RowLimit) => void
  onSearch: () => void
  onReset: () => void
}

export default function FilterPanel({
  specs, values, partial, limit, rowLimits, pageSize, busy, stale, staleNote,
  columnsButton, onValueChange, onPartialChange, onLimitChange, onSearch, onReset,
}: Props) {
  return (
    <section className="filter-panel">
      <div className="micro-label">Filter</div>

      <div className="filter-row">
        <span className="micro-label">Rows</span>
        <Segmented
          values={rowLimits as RowLimit[]}
          value={limit}
          label={(value) => (value === 'all' ? 'ALL' : Number(value).toLocaleString('en-US'))}
          onPick={onLimitChange}
        />
        <span className="mono muted" style={{ fontSize: '11px' }}>
          {limit === 'all'
            ? `pages at ${pageSize} rows/page`
            : 'capped, fetched once then paged in memory'}
        </span>
      </div>

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
        <span className="mono muted" style={{ fontSize: '11px' }}>{staleNote}</span>
        <button type="button" className="btn-text" onClick={onReset}>Reset</button>
        <button
          type="button"
          className={`btn-primary${stale ? ' stale' : ''}`}
          disabled={busy}
          onClick={onSearch}
        >
          Search
        </button>
      </div>
    </section>
  )
}
```

- [ ] **Step 6: Run it to verify it passes**

Run: `npm test -- --run web/src/components/FilterPanel.test.tsx`
Expected: 10 passed.

- [ ] **Step 7: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`

---

## Task 7: Column picker

Owns the rule that protects the user from a 60-second query: ticking a column the server does not hold must never fire one.

**Files:**
- Create: `web/src/components/ColumnPicker.tsx`
- Test: `web/src/components/ColumnPicker.test.tsx`

**Interfaces:**
- Consumes: `ColumnGroup` from `api/types`; `Icon`.
- Produces: `<ColumnPicker groups={ColumnGroup[]} allColumns={string[]} defaultColumns={string[]} pinned={string} costs={Record<string, number>} visible={Set<string>} onVisibleChange={(next: Set<string>) => void} />`

The component renders the whole `.picker-wrap` — button and popover — and is passed to `FilterPanel` as `columnsButton`. `onVisibleChange` is the single output; deciding whether the change is free or expensive belongs to `App`, not here.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/components/ColumnPicker.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import ColumnPicker from './ColumnPicker'

const ALL = [
  'BOM_ROW_NBR', 'STYLE_NBR', 'ITEM_NBR',
  'TEXT_USE_OF_DETECT', 'TEXT_Color_Name_OF_DETECT',
]
const DEFAULTS = ['BOM_ROW_NBR', 'STYLE_NBR', 'ITEM_NBR', 'TEXT_Color_Name_OF_DETECT']

function renderPicker(overrides: Partial<React.ComponentProps<typeof ColumnPicker>> = {}) {
  const props = {
    groups: [
      { title: 'STYLE HEADER', columns: ['BOM_ROW_NBR', 'STYLE_NBR', 'ITEM_NBR'] },
      { title: 'DETECTION', columns: ['TEXT_USE_OF_DETECT', 'TEXT_Color_Name_OF_DETECT'] },
    ],
    allColumns: ALL,
    defaultColumns: DEFAULTS,
    pinned: 'BOM_ROW_NBR',
    costs: { TEXT_USE_OF_DETECT: 60.3, TEXT_Color_Name_OF_DETECT: 9.2 },
    visible: new Set(DEFAULTS),
    onVisibleChange: vi.fn(),
    ...overrides,
  }
  render(<ColumnPicker {...props} />)
  return props
}

async function open() {
  await userEvent.click(screen.getByRole('button', { name: /Columns/ }))
}


test('shows the visible count on the button', () => {
  renderPicker()
  expect(screen.getByRole('button', { name: /4 \/ 5 shown/ })).toBeInTheDocument()
})

test('the popover is closed until the button is clicked', async () => {
  renderPicker()
  expect(screen.queryByText('STYLE HEADER')).not.toBeInTheDocument()
  await open()
  expect(screen.getByText('STYLE HEADER')).toBeInTheDocument()
})

test('shows the measured cost of the expensive columns', async () => {
  renderPicker()
  await open()
  expect(screen.getByText('+60s')).toBeInTheDocument()
  expect(screen.getByText('+9s')).toBeInTheDocument()
})

test('marks a cost of 30s or more as heavy', async () => {
  renderPicker()
  await open()
  expect(screen.getByText('+60s')).toHaveClass('heavy')
  expect(screen.getByText('+9s')).not.toHaveClass('heavy')
})

test('ticking a hidden column adds it', async () => {
  const props = renderPicker()
  await open()
  await userEvent.click(screen.getByText('TEXT_USE_OF_DETECT'))
  expect(props.onVisibleChange).toHaveBeenCalledWith(new Set([...DEFAULTS, 'TEXT_USE_OF_DETECT']))
})

test('unticking a shown column removes it', async () => {
  const props = renderPicker()
  await open()
  await userEvent.click(screen.getByText('ITEM_NBR'))
  // Asserted through toHaveBeenCalledWith rather than reading `.mock.calls`:
  // spreading `overrides` over the defaults widens `onVisibleChange` to
  // `((next: Set<string>) => void) | Mock`, and TypeScript 7 rejects `.mock`
  // on that union. Vitest compares Sets structurally, so this is equivalent.
  expect(props.onVisibleChange).toHaveBeenCalledWith(
    new Set(DEFAULTS.filter((column) => column !== 'ITEM_NBR')),
  )
})

test('the pinned column is locked and cannot be unticked', async () => {
  const props = renderPicker()
  await open()
  expect(screen.getByText('pinned')).toBeInTheDocument()
  await userEvent.click(screen.getByText('BOM_ROW_NBR'))
  expect(props.onVisibleChange).not.toHaveBeenCalled()
})

test('All selects every column', async () => {
  const props = renderPicker()
  await open()
  await userEvent.click(screen.getByRole('button', { name: 'All' }))
  expect(props.onVisibleChange).toHaveBeenCalledWith(new Set(ALL))
})

test('None leaves only the pinned column', async () => {
  const props = renderPicker()
  await open()
  await userEvent.click(screen.getByRole('button', { name: 'None' }))
  expect(props.onVisibleChange).toHaveBeenCalledWith(new Set(['BOM_ROW_NBR']))
})

test('Default returns to the server default set', async () => {
  const props = renderPicker({ visible: new Set(ALL) })
  await open()
  await userEvent.click(screen.getByRole('button', { name: 'Default' }))
  expect(props.onVisibleChange).toHaveBeenCalledWith(new Set(DEFAULTS))
})

test('the search box hides non-matching columns and empty groups', async () => {
  renderPicker()
  await open()
  await userEvent.type(screen.getByPlaceholderText('filter columns…'), 'ITEM')
  expect(screen.getByText('ITEM_NBR')).toBeInTheDocument()
  expect(screen.queryByText('STYLE_NBR')).not.toBeInTheDocument()
  expect(screen.queryByText('DETECTION')).not.toBeInTheDocument()
})

test('shows no cost badge for a column measured at zero', async () => {
  renderPicker({ costs: { ITEM_NBR: 0 } })
  await open()
  expect(screen.queryByText('+0s')).not.toBeInTheDocument()
})

/* Same gap that surfaced on Combobox in Task 5: the cleanup is correct, but
   without this test, deleting the useEffect's return leaves every other test
   green — Testing Library unmounts between tests, so the orphaned handler's
   `host.current?.contains` goes undefined and fails silently. */
test('removes its document click listener on unmount', () => {
  const addSpy = vi.spyOn(document, 'addEventListener')
  const removeSpy = vi.spyOn(document, 'removeEventListener')
  const { unmount } = render(
    <ColumnPicker
      groups={[{ title: 'STYLE HEADER', columns: ALL }]}
      allColumns={ALL} defaultColumns={DEFAULTS} pinned="BOM_ROW_NBR"
      costs={{}} visible={new Set(DEFAULTS)} onVisibleChange={vi.fn()}
    />,
  )
  const registered = addSpy.mock.calls.find((call) => call[0] === 'click')
  expect(registered).toBeDefined()
  unmount()
  expect(removeSpy).toHaveBeenCalledWith('click', registered![1])
  addSpy.mockRestore()
  removeSpy.mockRestore()
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run web/src/components/ColumnPicker.test.tsx`
Expected: FAIL — `Failed to resolve import "./ColumnPicker"`.

- [ ] **Step 3: Write `web/src/components/ColumnPicker.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import type { ColumnGroup } from '../api/types'
import Icon from './Icon'

interface Props {
  groups: ColumnGroup[]
  allColumns: string[]
  defaultColumns: string[]
  pinned: string
  costs: Record<string, number>
  visible: Set<string>
  onVisibleChange: (next: Set<string>) => void
}

export default function ColumnPicker({
  groups, allColumns, defaultColumns, pinned, costs, visible, onVisibleChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const [needle, setNeedle] = useState('')
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDocumentClick(event: MouseEvent) {
      if (!host.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onDocumentClick)
    return () => document.removeEventListener('click', onDocumentClick)
  }, [])

  function toggle(name: string) {
    if (name === pinned) return // pinned column cannot be hidden
    const next = new Set(visible)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    onVisibleChange(next)
  }

  const lower = needle.trim().toLowerCase()
  const matches = (name: string) => name.toLowerCase().includes(lower)

  return (
    <div ref={host} style={{ display: 'contents' }}>
      <button
        type="button"
        className="btn-ghost"
        onClick={() => setOpen((was) => !was)}
      >
        <Icon name="grid" />
        <span className="micro-label" style={{ color: 'inherit' }}>Columns</span>
        <span className="mono muted">{visible.size} / {allColumns.length} shown</span>
        <Icon name="chevron-down" />
      </button>

      {open && (
        <div className="picker">
          <div className="picker-head">
            <div className="picker-search">
              <Icon name="search" className="muted" />
              <input
                placeholder="filter columns…"
                autoComplete="off"
                value={needle}
                onChange={(event) => setNeedle(event.target.value)}
              />
            </div>
            <button type="button" className="btn-text"
              onClick={() => onVisibleChange(new Set(allColumns))}>All</button>
            <span className="divider" />
            <button type="button" className="btn-text"
              onClick={() => onVisibleChange(new Set(defaultColumns))}>Default</button>
            <span className="divider" />
            <button type="button" className="btn-text"
              onClick={() => onVisibleChange(new Set([pinned]))}>None</button>
          </div>

          {groups.map((group) => {
            const shown = group.columns.filter(matches)
            if (shown.length === 0) return null
            return (
              <div className="picker-group" key={group.title}>
                <div className="picker-group-head">
                  <span className="micro-label">{group.title}</span>
                </div>
                <div className="picker-grid">
                  {shown.map((name) => {
                    const locked = name === pinned
                    const cost = costs[name]
                    return (
                      <div
                        key={name}
                        className={`picker-item${locked ? ' locked' : ''}`}
                        onClick={() => toggle(name)}
                      >
                        <span className={`checkbox${visible.has(name) ? ' checked' : ''}`}>
                          <Icon name="tick" style={{ width: '9px', height: '9px' }} />
                        </span>
                        <span className="picker-name">{name}</span>
                        {locked && <span className="pin">pinned</span>}
                        {/* Measured cost shown inline so nobody ticks a 60 s
                            column blind. */}
                        {/* Falsy check, not `!== undefined`: the original
                            suppresses the badge on any falsy cost, and `+0s`
                            would be noise. */}
                        {cost ? (
                          <span className={`cost${cost >= 30 ? ' heavy' : ''}`}>
                            +{Math.round(cost)}s
                          </span>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run web/src/components/ColumnPicker.test.tsx`
Expected: 13 passed.

- [ ] **Step 5: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`

---

## Task 8: Results table and footer

The table is the one deliberately non-idiomatic component. 60 columns × 1,000 rows is 60,000 cells; the original code builds the body as one HTML string for measured reasons, and React reconciling 60,000 fibers has the same problem.

**Files:**
- Create: `web/src/components/ResultsTable.tsx`, `web/src/components/FooterBar.tsx`
- Test: `web/src/components/ResultsTable.test.tsx`

**Interfaces:**
- Consumes: `escapeHtml`, `fmt`; `RowsPayload` from `api/types`; `Icon`.
- Produces:
  - `<ResultsTable payload={RowsPayload | null} allColumns={string[]} visible={Set<string>} pinned={string} error={string | null} />`
  - `<FooterBar payload={RowsPayload | null} limit={RowLimit} elapsedText={string} pageSize={number} pageSizes={number[]} onPageSizeChange={(n: number) => void} onPrev={() => void} onNext={() => void} onExport={() => void} />`

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/components/ResultsTable.test.tsx
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run web/src/components/ResultsTable.test.tsx`
Expected: FAIL — `Failed to resolve import "./ResultsTable"`.

- [ ] **Step 3: Write `web/src/components/ResultsTable.tsx`**

```tsx
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
}

export default function ResultsTable({
  payload, allColumns, visible, pinned, error,
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

  /* A new search or page starts at the top-left, otherwise the first rows sit
     hidden above the scroll position and the table looks truncated. */
  useLayoutEffect(() => {
    if (container.current) {
      container.current.scrollTop = 0
      container.current.scrollLeft = 0
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
            Try switching partial match on, or clearing a filter.
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
          </thead>
          <tbody dangerouslySetInnerHTML={{ __html: bodyHtml }} />
        </table>
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run web/src/components/ResultsTable.test.tsx`
Expected: 12 passed.

- [ ] **Step 5: Write `web/src/components/FooterBar.tsx`**

```tsx
import type { RowsPayload } from '../api/types'
import type { RowLimit } from '../state/queryReducer'
import { fmt } from '../utils/format'
import Icon from './Icon'
import Segmented from './Segmented'

interface Props {
  payload: RowsPayload | null
  /** Only used by the cap note, which names the actual limit. */
  limit: RowLimit
  /** Either a live "12.3s elapsed…" ticker or the settled "query 23.1s". */
  elapsedText: string
  pageSize: number
  pageSizes: number[]
  onPageSizeChange: (next: number) => void
  onPrev: () => void
  onNext: () => void
  onExport: () => void
}

export default function FooterBar({
  payload, limit, elapsedText, pageSize, pageSizes,
  onPageSizeChange, onPrev, onNext, onExport,
}: Props) {
  // The original names the number: "10,000 rows matched (capped at 10,000)".
  // `capped` is only ever true for a finite limit, so Number() is safe.
  const capNote = payload?.capped ? ` (capped at ${fmt(Number(limit))})` : ''
  const matched = payload
    ? `${fmt(payload.total)} rows matched${capNote}`
    : '— rows matched'
  const pageText = payload
    ? `page ${fmt(payload.page)} / ${fmt(payload.pages)}`
    : 'page — / —'

  return (
    <footer className="footerbar">
      <span className="mono">{matched}</span>
      <span className="divider" />
      <span className="mono muted">{elapsedText}</span>
      <span className="spacer" />
      <span className="micro-label">Page size</span>
      <Segmented
        values={pageSizes}
        value={pageSize}
        label={(value) => value.toLocaleString('en-US')}
        onPick={onPageSizeChange}
      />
      <span className="mono muted" style={{ fontSize: '11px' }}>min 100</span>
      <span className="spacer" />
      <div className="pager">
        <button type="button" className="btn-ghost" title="Previous page"
          disabled={!payload || payload.page <= 1} onClick={onPrev}>
          <Icon name="chevron-left" />
        </button>
        <span className="mono">{pageText}</span>
        <button type="button" className="btn-ghost" title="Next page"
          disabled={!payload || payload.page >= payload.pages} onClick={onNext}>
          <Icon name="chevron-right" />
        </button>
      </div>
      <span className="spacer" />
      <button type="button" className="btn-ghost" onClick={onExport}>
        <Icon name="download" />
        <span>Export CSV</span>
      </button>
      <span className="mono muted" style={{ fontSize: '11px' }}>full filtered set</span>
    </footer>
  )
}
```

- [ ] **Step 6: Write the FooterBar tests**

`FooterBar` carries four conditional branches — the cap note, the page text, and
the two pager disabled states — and none were covered.

```tsx
// web/src/components/FooterBar.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { RowsPayload } from '../api/types'
import FooterBar from './FooterBar'

function payload(overrides: Partial<RowsPayload> = {}): RowsPayload {
  return {
    columns: [], all_columns: [], fetched_columns: [], rows: [],
    total: 2, page: 1, page_size: 100, pages: 1,
    elapsed: 23.1, cached: false, capped: false, ...overrides,
  }
}

function renderFooter(overrides: Partial<React.ComponentProps<typeof FooterBar>> = {}) {
  const props = {
    payload: payload(),
    limit: '100' as const,
    elapsedText: 'query 23.1s',
    pageSize: 100,
    pageSizes: [100, 250, 500, 1000],
    onPageSizeChange: vi.fn(),
    onPrev: vi.fn(),
    onNext: vi.fn(),
    onExport: vi.fn(),
    ...overrides,
  }
  render(<FooterBar {...props} />)
  return props
}

test('shows placeholders before anything has run', () => {
  renderFooter({ payload: null })
  expect(screen.getByText('— rows matched')).toBeInTheDocument()
  expect(screen.getByText('page — / —')).toBeInTheDocument()
})

test('names the actual limit in the cap note', () => {
  renderFooter({ payload: payload({ total: 10000, capped: true }), limit: '10000' })
  // The original prints the number, not a bare "(capped)".
  expect(screen.getByText('10,000 rows matched (capped at 10,000)')).toBeInTheDocument()
})

test('omits the cap note when the result is not capped', () => {
  renderFooter()
  expect(screen.getByText('2 rows matched')).toBeInTheDocument()
})

test('disables both pagers on a single-page result', () => {
  renderFooter({ payload: payload({ page: 1, pages: 1 }) })
  expect(screen.getByTitle('Previous page')).toBeDisabled()
  expect(screen.getByTitle('Next page')).toBeDisabled()
})

test('enables both pagers mid-run and reports each click', async () => {
  const props = renderFooter({ payload: payload({ page: 2, pages: 3 }) })
  expect(screen.getByText('page 2 / 3')).toBeInTheDocument()
  await userEvent.click(screen.getByTitle('Previous page'))
  await userEvent.click(screen.getByTitle('Next page'))
  expect(props.onPrev).toHaveBeenCalledTimes(1)
  expect(props.onNext).toHaveBeenCalledTimes(1)
})

test('exports on demand', async () => {
  const props = renderFooter()
  await userEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
  expect(props.onExport).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 7: Run the FooterBar tests**

Run: `npm test -- --run web/src/components/FooterBar.test.tsx`
Expected: 6 passed.

- [ ] **Step 8: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`
Expected: 105 passed across 12 files, no type errors.

---

## Task 9: Boot and search hooks

`useMeta` runs the boot sequence and polls for the row total. `useSearch` runs queries with a busy guard and a live elapsed ticker.

**Files:**
- Create: `web/src/state/useMeta.ts`, `web/src/state/useSearch.ts`
- Test: `web/src/state/useMeta.test.ts`, `web/src/state/useSearch.test.ts`

**Interfaces:**
- Consumes: `getHealth`, `getMeta`, `getRows` from `api/client`; `Meta`, `RowsPayload` from `api/types`; `ConnKind` from `components/AppBar`.
- Produces:
  - `useMeta(): { meta: Meta | null; source: string; totalRows: number | null; bootError: string | null; connected: boolean }`
  - `useSearch(): { payload, fetched, busy, error, elapsedText, run(params: URLSearchParams): Promise<void>, connKind: ConnKind, connText: string }`

- [ ] **Step 1: Write the failing test for `useMeta`**

```ts
// web/src/state/useMeta.test.ts
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { useMeta } from './useMeta'

const HEALTH = {
  connected: true, server: 'S', database: 'the database',
  view: 'the source view', elapsed: 0.1,
}

function metaBody(totalRows: number | null) {
  return {
    columns: [{ name: 'BOM_ROW_NBR', type: 'int', nullable: false }],
    groups: [], pinned: 'BOM_ROW_NBR', filters: [],
    default_columns: ['BOM_ROW_NBR'], default_hidden: [], column_costs: {},
    row_limits: ['100'], page_sizes: [100], min_page_size: 100,
    default_page_size: 100, default_row_limit: 100,
    total_rows: totalRows, source: '<database> / <schema>.<view>',
  }
}

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body }
}

beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

test('loads health then meta, and reports connected', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(ok(HEALTH))
    .mockResolvedValueOnce(ok(metaBody(362733))))

  const { result } = renderHook(() => useMeta())
  await waitFor(() => expect(result.current.meta).not.toBeNull())
  expect(result.current.connected).toBe(true)
  expect(result.current.totalRows).toBe(362733)
  expect(result.current.source).toBe('<database> / <schema>.<view>')
})

test('a health failure stops the boot and reports the error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, status: 503, json: async () => ({ detail: 'Cannot connect: timeout' }),
  }))

  const { result } = renderHook(() => useMeta())
  await waitFor(() => expect(result.current.bootError).not.toBeNull())
  expect(result.current.bootError).toContain('Cannot connect')
  expect(result.current.meta).toBeNull()
  expect(result.current.connected).toBe(false)
})

test('a meta failure reports the error', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(ok(HEALTH))
    .mockResolvedValueOnce({
      ok: false, status: 500, json: async () => ({ detail: 'Database error: x' }),
    }))

  const { result } = renderHook(() => useMeta())
  await waitFor(() => expect(result.current.bootError).not.toBeNull())
  expect(result.current.bootError).toContain('Database error')
})

test('polls for the row total when meta comes back cold', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(ok(HEALTH))
    .mockResolvedValueOnce(ok(metaBody(null)))
    .mockResolvedValue(ok(metaBody(362733)))
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useMeta())
  await waitFor(() => expect(result.current.meta).not.toBeNull())
  expect(result.current.totalRows).toBeNull()

  await vi.advanceTimersByTimeAsync(10_000)
  await waitFor(() => expect(result.current.totalRows).toBe(362733))
})

test('stops polling once unmounted', async () => {
  // The poll is a self-rescheduling chain, not a setInterval: without the
  // `cancelled` ref it would keep firing /api/meta after the component is gone.
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(ok(HEALTH))
    .mockResolvedValue(ok(metaBody(null)))
  vi.stubGlobal('fetch', fetchMock)

  const { result, unmount } = renderHook(() => useMeta())
  await waitFor(() => expect(result.current.meta).not.toBeNull())

  const callsBefore = fetchMock.mock.calls.length
  unmount()
  await vi.advanceTimersByTimeAsync(10_000 * 3)
  expect(fetchMock.mock.calls.length).toBe(callsBefore)
})

test('gives up polling after 6 attempts and leaves the total null', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(ok(HEALTH))
    .mockResolvedValue(ok(metaBody(null)))
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useMeta())
  await waitFor(() => expect(result.current.meta).not.toBeNull())

  await vi.advanceTimersByTimeAsync(10_000 * 8)
  expect(result.current.totalRows).toBeNull()
  // 1 health + 1 meta + exactly 6 polls. Pinned with toBe, not
  // toBeLessThanOrEqual: the latter would not notice the cap being LOWERED.
  expect(fetchMock.mock.calls.length).toBe(8)
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run web/src/state/useMeta.test.ts`
Expected: FAIL — `Failed to resolve import "./useMeta"`.

- [ ] **Step 3: Write `web/src/state/useMeta.ts`**

```ts
import { useEffect, useState } from 'react'
import { getHealth, getMeta } from '../api/client'
import type { Meta } from '../api/types'

/** /api/meta only peeks at the cached row count, so on a cold server it comes
 *  back null. Check back a few times while the background warm-up runs, then
 *  give up quietly — the header total is informational only. */
const POLL_ATTEMPTS = 6
const POLL_INTERVAL_MS = 10_000

export interface MetaState {
  meta: Meta | null
  source: string
  totalRows: number | null
  bootError: string | null
  connected: boolean
}

export function useMeta(): MetaState {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [source, setSource] = useState('<database> / <schema>.<view>')
  const [totalRows, setTotalRows] = useState<number | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    /* A closure variable per effect invocation, NOT a ref. Under StrictMode
       React mounts, cleans up, then mounts again; a shared ref would be reset
       to false by the second mount, un-cancelling the first chain at exactly
       the moment the guard exists to stop it. */
    let cancelled = false

    async function boot() {
      try {
        const health = await getHealth()
        if (cancelled) return
        setConnected(true)
        setSource(`${health.database} / ${health.view}`)
      } catch (error) {
        if (cancelled) return
        setBootError(`Cannot reach the database. ${(error as Error).message}`)
        return
      }

      let loaded: Meta
      try {
        loaded = await getMeta()
      } catch (error) {
        if (cancelled) return
        setBootError(`Could not load column metadata. ${(error as Error).message}`)
        return
      }
      if (cancelled) return
      setMeta(loaded)
      setSource(loaded.source)
      setTotalRows(loaded.total_rows)
      if (loaded.total_rows === null) void pollTotal(0)
    }

    async function pollTotal(attempt: number) {
      if (attempt >= POLL_ATTEMPTS || cancelled) return
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
      if (cancelled) return
      try {
        const again = await getMeta()
        if (cancelled) return
        if (again.total_rows !== null) {
          setTotalRows(again.total_rows)
          return
        }
      } catch {
        // leave the dash in place
      }
      void pollTotal(attempt + 1)
    }

    void boot()
    return () => { cancelled = true }
  }, [])

  return { meta, source, totalRows, bootError, connected }
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run web/src/state/useMeta.test.ts`
Expected: 6 passed.

- [ ] **Step 5: Write the failing test for `useSearch`**

```ts
// web/src/state/useSearch.test.ts
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import type { RowsPayload } from '../api/types'
import { useSearch } from './useSearch'

const PAYLOAD: RowsPayload = {
  columns: ['BOM_ROW_NBR'], all_columns: ['BOM_ROW_NBR'],
  fetched_columns: ['BOM_ROW_NBR', 'STYLE_NBR'],
  rows: [[1]], total: 1, page: 1, page_size: 100, pages: 1,
  elapsed: 23.1, cached: false, capped: false,
}

afterEach(() => { vi.unstubAllGlobals() })

test('stores the payload and the server-held column set', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => PAYLOAD,
  }))
  const { result } = renderHook(() => useSearch())
  await act(async () => { await result.current.run(new URLSearchParams()) })

  expect(result.current.payload).toEqual(PAYLOAD)
  // fetched_columns, not columns: the server may hold more than it returned.
  expect([...result.current.fetched].sort()).toEqual(['BOM_ROW_NBR', 'STYLE_NBR'])
  expect(result.current.error).toBeNull()
  expect(result.current.connKind).toBe('ready')
  expect(result.current.elapsedText).toBe('query 23.1s')
})

test('marks a cached result', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({ ...PAYLOAD, cached: true, elapsed: 0 }),
  }))
  const { result } = renderHook(() => useSearch())
  await act(async () => { await result.current.run(new URLSearchParams()) })
  expect(result.current.elapsedText).toBe('query 0.0s (cached)')
})

test('reports a query failure without discarding the previous payload', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: async () => PAYLOAD })
    .mockResolvedValueOnce({
      ok: false, status: 500, json: async () => ({ detail: 'Query failed: timeout' }),
    })
  vi.stubGlobal('fetch', fetchMock)
  const { result } = renderHook(() => useSearch())

  await act(async () => { await result.current.run(new URLSearchParams()) })
  expect(result.current.payload).toEqual(PAYLOAD)

  await act(async () => { await result.current.run(new URLSearchParams()) })
  // The rows on screen must survive a failed refresh: losing a 23-second
  // result to a transient error would be worse than showing stale rows.
  expect(result.current.payload).toEqual(PAYLOAD)
  expect(result.current.error).toBe('Query failed: timeout')
  expect(result.current.connKind).toBe('error')
  expect(result.current.elapsedText).toBe('failed')
  expect(result.current.busy).toBe(false)
})

test('clears the elapsed ticker if unmounted mid-query', async () => {
  // The ticker is cleared in `finally` on a normal path, so only an unmount
  // while a query is still in flight exercises the useEffect cleanup.
  let release: (value: unknown) => void = () => {}
  const gate = new Promise((resolve) => { release = resolve })
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => {
    await gate
    return { ok: true, status: 200, json: async () => PAYLOAD }
  }))
  const clearSpy = vi.spyOn(globalThis, 'clearInterval')

  const { result, unmount } = renderHook(() => useSearch())
  act(() => { void result.current.run(new URLSearchParams()) })
  await waitFor(() => expect(result.current.busy).toBe(true))

  clearSpy.mockClear()
  unmount()
  expect(clearSpy).toHaveBeenCalled()

  release(null)
  clearSpy.mockRestore()
})

test('ignores a second run while one is in flight', async () => {
  let release: (value: unknown) => void = () => {}
  const gate = new Promise((resolve) => { release = resolve })
  const fetchMock = vi.fn().mockImplementation(async () => {
    await gate
    return { ok: true, status: 200, json: async () => PAYLOAD }
  })
  vi.stubGlobal('fetch', fetchMock)

  const { result } = renderHook(() => useSearch())
  // Definite-assignment: TS cannot see that the act() callback runs synchronously.
  let first!: Promise<void>
  act(() => { first = result.current.run(new URLSearchParams()) })
  await waitFor(() => expect(result.current.busy).toBe(true))

  await act(async () => { await result.current.run(new URLSearchParams()) })
  expect(fetchMock).toHaveBeenCalledTimes(1)

  await act(async () => { release(null); await first })
  expect(result.current.busy).toBe(false)
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `npm test -- --run web/src/state/useSearch.test.ts`
Expected: FAIL — `Failed to resolve import "./useSearch"`.

- [ ] **Step 7: Write `web/src/state/useSearch.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from 'react'
import { getRows } from '../api/client'
import type { RowsPayload } from '../api/types'
import type { ConnKind } from '../components/AppBar'

export interface SearchState {
  payload: RowsPayload | null
  /** The column set the server holds for this filter — may exceed what it
   *  returned. Anything inside it can be shown without a new query. */
  fetched: Set<string>
  busy: boolean
  error: string | null
  elapsedText: string
  connKind: ConnKind
  connText: string
  run: (params: URLSearchParams) => Promise<void>
}

export function useSearch(): SearchState {
  const [payload, setPayload] = useState<RowsPayload | null>(null)
  const [fetched, setFetched] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [elapsedText, setElapsedText] = useState('not run')
  const [connKind, setConnKind] = useState<ConnKind>('idle')
  const [connText, setConnText] = useState('connecting…')
  // A ref, not `busy`: the guard must see the current value inside a callback
  // that may have closed over a stale render.
  const inFlight = useRef(false)
  const ticker = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopTicker = () => {
    if (ticker.current !== null) {
      clearInterval(ticker.current)
      ticker.current = null
    }
  }

  useEffect(() => stopTicker, [])

  const run = useCallback(async (params: URLSearchParams) => {
    if (inFlight.current) return
    inFlight.current = true
    setBusy(true)
    setConnKind('working')
    setConnText('querying…')

    // A live counter so a cold 130 s query never looks like a hang.
    const started = performance.now()
    stopTicker()
    ticker.current = setInterval(() => {
      setElapsedText(`${((performance.now() - started) / 1000).toFixed(1)}s elapsed…`)
    }, 100)

    try {
      const result = await getRows(params)
      setPayload(result)
      setFetched(new Set(result.fetched_columns ?? result.columns))
      setError(null)
      setConnKind('ready')
      setConnText('connected')
      setElapsedText(
        `query ${result.elapsed.toFixed(1)}s${result.cached ? ' (cached)' : ''}`,
      )
    } catch (caught) {
      setError((caught as Error).message)
      setConnKind('error')
      setConnText('query failed')
      setElapsedText('failed')
    } finally {
      stopTicker()
      inFlight.current = false
      setBusy(false)
    }
  }, [])

  return { payload, fetched, busy, error, elapsedText, connKind, connText, run }
}
```

- [ ] **Step 8: Run it to verify it passes**

Run: `npm test -- --run web/src/state/useSearch.test.ts`
Expected: 5 passed.

- [ ] **Step 9: Checkpoint**

Run: `npm test -- --run && npx tsc --noEmit`

---

## Task 10: App composition

Wires everything together and holds the two rules that matter most: ticking an unfetched column must not fire a query, and a search must never be built from a stale `visible` set.

**Files:**
- Modify: `web/src/App.tsx` (replaces the Task 1 placeholder entirely)
- Test: `web/src/App.test.tsx`

**Interfaces:**
- Consumes: everything produced by Tasks 2–9.
- Produces: the finished application.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/App.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

const HEALTH = {
  connected: true, server: 'S', database: 'the database',
  view: 'the source view', elapsed: 0.1,
}

const ALL = ['BOM_ROW_NBR', 'STYLE_NBR', 'TEXT_USE_OF_DETECT']
const DEFAULTS = ['BOM_ROW_NBR', 'STYLE_NBR']

const META = {
  columns: ALL.map((name) => ({ name, type: 'nvarchar', nullable: true })),
  groups: [{ title: 'STYLE HEADER', columns: ALL }],
  pinned: 'BOM_ROW_NBR',
  filters: [
    { column: 'STYLE_NBR', kind: 'text', param: 'style_nbr', suggest: true, note: '' },
  ],
  default_columns: DEFAULTS,
  default_hidden: ['TEXT_USE_OF_DETECT'],
  column_costs: { TEXT_USE_OF_DETECT: 60.3 },
  row_limits: ['100', '1000', '10000', 'all'],
  page_sizes: [100, 250, 500, 1000],
  min_page_size: 100, default_page_size: 100, default_row_limit: 100,
  total_rows: 362733, source: '<database> / <schema>.<view>',
}

const ROWS = {
  columns: DEFAULTS, all_columns: ALL, fetched_columns: DEFAULTS,
  rows: [[1, 'AB1234'], [2, 'AB1235']],
  total: 2, page: 1, page_size: 100, pages: 1,
  elapsed: 23.1, cached: false, capped: false,
}

/** Routes by URL so the order of calls does not matter. */
function stubApi(rowsBody: unknown = ROWS) {
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.startsWith('/api/health') ? HEALTH
      : url.startsWith('/api/meta') ? META
      : url.startsWith('/api/rows') ? rowsBody
      : { column: '', values: ['AB1234', 'AB1235'] }
    return { ok: true, status: 200, json: async () => body } as unknown as Response
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function rowsCalls(fetchMock: ReturnType<typeof stubApi>) {
  return fetchMock.mock.calls
    .map((call) => call[0] as string)
    .filter((url) => url.startsWith('/api/rows'))
}
/* Column names appear in up to three places at once — the filter field label,
   the picker row, and the results-table header — so picker clicks must be
   scoped or `getByText` throws on the ambiguity. */
function pickerItem(name: string) {
  return screen.getByText(name, { selector: '.picker-name' })
}

afterEach(() => { vi.unstubAllGlobals() })

test('boots: shows the source, the total and a connected glyph', async () => {
  stubApi()
  render(<App />)
  expect(await screen.findByText('<database> / <schema>.<view>')).toBeInTheDocument()
  expect(screen.getByText('362,733 rows')).toBeInTheDocument()
  expect(await screen.findByText('connected')).toBeInTheDocument()
})

test('does not query on boot', async () => {
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  expect(rowsCalls(fetchMock)).toHaveLength(0)
  expect(screen.getByText('Choose a row limit and press Search.')).toBeInTheDocument()
})

test('starts with the server default column set, not all columns', async () => {
  stubApi()
  render(<App />)
  expect(await screen.findByRole('button', { name: /2 \/ 3 shown/ })).toBeInTheDocument()
})

test('Search queries with the visible columns and renders the rows', async () => {
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))

  await waitFor(() => expect(screen.getByText('AB1234')).toBeInTheDocument())
  expect(rowsCalls(fetchMock)[0]).toContain('columns=BOM_ROW_NBR%2CSTYLE_NBR')
  expect(screen.getByText('2 rows matched')).toBeInTheDocument()
  expect(screen.getByText('query 23.1s')).toBeInTheDocument()
})

test('hiding a fetched column re-queries a subset the server already holds', async () => {
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(screen.getByText('AB1234')).toBeInTheDocument())

  await userEvent.click(screen.getByRole('button', { name: /shown/ }))
  await userEvent.click(pickerItem('STYLE_NBR'))

  // A subset request DOES hit /api/rows -- the server answers it from its own
  // result cache in ~0.0 s. What must not happen is a query for a column the
  // server does not hold; that is the next test.
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(2))
  expect(rowsCalls(fetchMock)[1]).toContain('columns=BOM_ROW_NBR')
  expect(rowsCalls(fetchMock)[1]).not.toContain('STYLE_NBR')
})

test('ticking an unfetched column does NOT query — it flags Search', async () => {
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(screen.getByText('AB1234')).toBeInTheDocument())

  await userEvent.click(screen.getByRole('button', { name: /shown/ }))
  await userEvent.click(pickerItem('TEXT_USE_OF_DETECT'))

  expect(rowsCalls(fetchMock)).toHaveLength(1)
  expect(screen.getByText('+1 column, ~60s — press Search')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Search' })).toHaveClass('stale')
  // ...and the table is untouched: no phantom em-dash column appears before
  // the query that would actually populate it.
  expect(screen.getAllByRole('columnheader').map((th) => th.textContent))
    .toEqual(DEFAULTS)
})

test('Search after ticking an expensive column sends it', async () => {
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(screen.getByText('AB1234')).toBeInTheDocument())

  await userEvent.click(screen.getByRole('button', { name: /shown/ }))
  await userEvent.click(pickerItem('TEXT_USE_OF_DETECT'))
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))

  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(2))
  expect(rowsCalls(fetchMock)[1]).toContain('TEXT_USE_OF_DETECT')
})

test('a filter value reaches the query string trimmed', async () => {
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.type(screen.getByPlaceholderText('e.g. AB1234'), '  AB1234  ')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(1))
  expect(rowsCalls(fetchMock)[0]).toContain('style_nbr=AB1234')
})

test('Reset clears the filter and returns to the default column set', async () => {
  stubApi()
  render(<App />)
  await screen.findByText('connected')

  await userEvent.click(screen.getByRole('button', { name: /shown/ }))
  await userEvent.click(pickerItem('TEXT_USE_OF_DETECT'))
  // Clicking outside the picker closes it, which is what gives access to the
  // filter field below.
  const input = screen.getByPlaceholderText('e.g. AB1234')
  await userEvent.type(input, 'AB1234')

  await userEvent.click(screen.getByRole('button', { name: 'Reset' }))
  expect(input).toHaveValue('')
  expect(screen.getByRole('button', { name: /2 \/ 3 shown/ })).toBeInTheDocument()
})

test('selecting the ALL row limit shows the slow-paging notice', async () => {
  stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'ALL' }))
  expect(await screen.findByText(/ALL selected/)).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  expect(screen.queryByText(/ALL selected/)).not.toBeInTheDocument()
})

test('a boot failure shows the error and no filter panel', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false, status: 503, json: async () => ({ detail: 'Cannot connect: timeout' }),
  }))
  render(<App />)
  expect(await screen.findByText(/Cannot reach the database/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Search' })).not.toBeInTheDocument()
  expect(await screen.findByText('not connected')).toBeInTheDocument()
})

test('the next page is requested and the pager reflects the payload', async () => {
  const fetchMock = stubApi({ ...ROWS, pages: 3, total: 250 })
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(screen.getByText('page 1 / 3')).toBeInTheDocument())

  await userEvent.click(screen.getByTitle('Next page'))
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(2))
  expect(rowsCalls(fetchMock)[1]).toContain('page=2')
})

test('Reset re-searches with the default columns, not the pre-reset set', async () => {
  // The regression this guards is specific: if Reset ever re-queried from state
  // instead of an explicit object, it would fire with the ~60s column that was
  // ticked just before it — an expensive query triggered by pressing Reset.
  const fetchMock = stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(1))

  await userEvent.type(screen.getByPlaceholderText('e.g. AB1234'), 'AB1234')
  await userEvent.click(screen.getByRole('button', { name: /shown/ }))
  await userEvent.click(pickerItem('TEXT_USE_OF_DETECT'))
  await userEvent.click(screen.getByRole('button', { name: 'Reset' }))

  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(2))
  const url = rowsCalls(fetchMock)[1]
  expect(url).not.toContain('TEXT_USE_OF_DETECT')
  expect(url).not.toContain('style_nbr')
  expect(url).toContain('columns=BOM_ROW_NBR%2CSTYLE_NBR')
})

test('changing the page size re-searches at the new size from page 1', async () => {
  const fetchMock = stubApi({ ...ROWS, pages: 3, total: 250 })
  render(<App />)
  await screen.findByText('connected')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(1))

  await userEvent.click(screen.getByTitle('Next page'))
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(2))

  // 500 is unique across both segmented controls; 100 and 1,000 are not.
  await userEvent.click(screen.getByRole('button', { name: '500' }))
  await waitFor(() => expect(rowsCalls(fetchMock)).toHaveLength(3))
  const url = rowsCalls(fetchMock)[2]
  expect(url).toContain('page_size=500')
  expect(url).toContain('page=1')
})

test('exporting with a filter set does not ask for confirmation', async () => {
  stubApi()
  render(<App />)
  await screen.findByText('connected')
  await userEvent.type(screen.getByPlaceholderText('e.g. AB1234'), 'AB1234')
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

  await userEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
  expect(confirmSpy).not.toHaveBeenCalled()
  confirmSpy.mockRestore()
})

test('exporting with no filter asks for confirmation first', async () => {
  stubApi()
  render(<App />)
  await screen.findByText('connected')
  const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

  await userEvent.click(screen.getByRole('button', { name: /Export CSV/ }))
  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('No filter is set'))
  confirmSpy.mockRestore()
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm test -- --run web/src/App.test.tsx`
Expected: FAIL — the placeholder `App` renders none of this.

- [ ] **Step 3: Write `web/src/App.tsx`**

```tsx
import { useMemo, useReducer, useState } from 'react'
import { exportUrl } from './api/client'
import { exportParams, rowsParams, type ParamOverrides } from './api/params'
import AppBar from './components/AppBar'
import ColumnPicker from './components/ColumnPicker'
import FilterPanel from './components/FilterPanel'
import FooterBar from './components/FooterBar'
import IconSprite from './components/IconSprite'
import Notice from './components/Notice'
import ResultsTable from './components/ResultsTable'
import {
  initialQueryState, queryReducer, hasAnyFilter, type RowLimit,
} from './state/queryReducer'
import { useMeta } from './state/useMeta'
import { useSearch } from './state/useSearch'
import { addedColumns, fmt, staleNote } from './utils/format'

const ALL_LIMIT_NOTICE =
  'ALL selected — the full filtered set streams to CSV; the table pages ' +
  'through it. Unfiltered deep pages are slow (the view scans everything ' +
  'it skips), so filter by style where you can.'

export default function App() {
  const { meta, source, totalRows, bootError, connected } = useMeta()
  const search = useSearch()
  const [state, dispatch] = useReducer(queryReducer, initialQueryState)
  const [ready, setReady] = useState(false)
  const [hasRun, setHasRun] = useState(false)
  const [stale, setStale] = useState<string[]>([])
  const [notice, setNotice] = useState<string | null>(null)

  // Seed the reducer from /api/meta exactly once.
  if (meta && !ready) {
    dispatch({ type: 'init', specs: meta.filters, defaultColumns: meta.default_columns })
    setReady(true)
  }

  /** Every query goes through here. Overrides exist because React state
   *  setters are asynchronous: a handler that has just computed a new page or
   *  column set must search with it, not with the value still in state. */
  async function runSearch(overrides?: ParamOverrides) {
    setStale([])
    setHasRun(true)
    await search.run(rowsParams(state, overrides))
  }

  /* Hiding a column, or revealing one the server already holds, is a subset of
     `fetched` and refreshes instantly from the payload in memory. Ticking a
     column outside that set means a real query -- up to ~60 s each for the two
     nvarchar(max) detection columns -- so it is never triggered silently: the
     button is flagged and the user decides. */
  function onVisibleChange(next: Set<string>) {
    dispatch({ type: 'setVisible', value: next })
    if (!hasRun) return // nothing fetched yet; Search will pick it up
    const added = addedColumns(next, search.fetched)
    if (added.length === 0) void runSearch({ visible: next })
    else setStale(added)
  }

  function onReset() {
    dispatch({ type: 'reset' })
    setStale([])
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

  function onLimitChange(next: RowLimit) {
    dispatch({ type: 'setLimit', value: next })
    if (next === 'all') setNotice(ALL_LIMIT_NOTICE)
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
        `${state.visible.size} columns. It will take several minutes. Continue?`,
      )
      if (!proceed) return
    }
    window.location.href = exportUrl(exportParams(state))
  }

  /* Only columns the server actually holds are painted. Ticking an unfetched
     column must not add a phantom all-em-dash column before the user presses
     Search: the original never re-renders the table on a stale tick
     (`onVisibilityChange` calls `markStale` and nothing else), and a column
     that appears instantly full of dashes reads as a bug. */
  const displayed = useMemo(
    () => new Set([...state.visible].filter((column) => search.fetched.has(column))),
    [state.visible, search.fetched],
  )

  /* Only a HEALTH failure means "not connected". If /api/health succeeded and
     /api/meta then failed, the database is reachable and the original leaves
     the glyph green — app.js's meta catch calls fail() but never setConn. */
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
      />
      {notice && <Notice text={notice} onDismiss={() => setNotice(null)} />}

      {meta && (
        <FilterPanel
          specs={meta.filters}
          values={state.values}
          partial={state.partial}
          limit={state.limit}
          rowLimits={meta.row_limits}
          pageSize={state.pageSize}
          busy={search.busy}
          stale={stale.length > 0}
          staleNote={staleNote(stale, meta.column_costs)}
          columnsButton={
            <ColumnPicker
              groups={meta.groups}
              allColumns={meta.columns.map((column) => column.name)}
              defaultColumns={meta.default_columns}
              pinned={meta.pinned}
              costs={meta.column_costs}
              visible={state.visible}
              onVisibleChange={onVisibleChange}
            />
          }
          onValueChange={(param, value) => dispatch({ type: 'setValue', param, value })}
          onPartialChange={(value) => dispatch({ type: 'setPartial', value })}
          onLimitChange={onLimitChange}
          onSearch={() => { void runSearch({ page: 1 }) }}
          onReset={onReset}
        />
      )}

      <ResultsTable
        payload={hasRun ? search.payload : null}
        allColumns={meta ? meta.columns.map((column) => column.name) : []}
        visible={displayed}
        pinned={meta?.pinned ?? ''}
        error={bootError ?? search.error}
      />

      <FooterBar
        payload={hasRun ? search.payload : null}
        limit={state.limit}
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
```

Note the `onSearch` handler passes `{ page: 1 }`: pressing Search always starts at the first page, matching `$('searchBtn').onclick = () => { state.page = 1; search(); }` in the original.

- [ ] **Step 4: Run it to verify it passes**

Run: `npm test -- --run web/src/App.test.tsx`
Expected: 16 passed. If `dispatch({ type: 'setPage' })` and `runSearch` disagree on the page number, the override in `onPage` is the fix — do not reorder the dispatch.

- [ ] **Step 5: Run the whole suite**

Run: `npm test -- --run && npx tsc --noEmit`
Expected: 132 passed across 15 files, no type errors.

- [ ] **Step 6: Checkpoint**

---

## Task 11: Live verification and documentation

Unit tests cannot prove a 1:1 visual port. This task compares the two apps side by side against the real database and brings the README back in line.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Build and start the app**

```bash
npm run build
```

Then from `src/`: `uvicorn main:app --port 8000`, and open <http://127.0.0.1:8000>.

- [ ] **Step 2: Walk the checklist against the running app**

Tick each. Any failure is a bug in the port, not an acceptable difference.

- [ ] Header shows `<database> / <schema>.<view>`, `connected`, and a row total (or `— rows` on a cold server, filling in within a minute).
- [ ] Columns button reads `58 / 60 shown` before anything else is touched.
- [ ] The picker's six groups are STYLE HEADER, BUY READY, BOM LINE, DETECTION, DATES, ZIPPER.
- [ ] `TEXT_USE_OF_DETECT` shows `+60s` in bold ink; `TEXT_Color_Name_OF_DETECT` shows `+9s` in muted grey.
- [ ] `BOM_ROW_NBR` reads `pinned` and does not respond to a click.
- [ ] Focusing `STYLE_NBR` shows `loading values…`, then a list; typing `IB` narrows it.
- [ ] Searching `STYLE_NBR = AB1234` returns rows; the footer elapsed counter ticks during the query and settles on `query N.Ns`.
- [ ] The table scrolls horizontally inside its own container; the page body does not scroll. The header row stays put vertically and `BOM_ROW_NBR` stays put horizontally, including at the corner where both meet.
- [ ] Hiding a column is instant and the footer still reads the previous `query N.Ns` — no new query.
- [ ] Ticking `TEXT_USE_OF_DETECT` fires no query, rings the Search button, and shows `+1 column, ~60s — press Search`.
- [ ] Pressing Search then runs, and the column appears.
- [ ] Unticking it is instant.
- [ ] `MASTER_BOM_STATUS` renders Thai (e.g. `ไม่นับ`) rather than boxes or mojibake.
- [ ] Null cells show `—` in muted grey; hovering a populated cell shows its full value as a tooltip.
- [ ] Reset clears the fields, returns the picker to `58 / 60 shown`, and re-runs.
- [ ] Selecting ALL raises the red notice; Dismiss removes it.
- [ ] Export CSV with a filter downloads `<view>-<filter>-<stamp>.csv`; opening it in Excel shows Thai correctly.
- [ ] Export CSV with no filter warns first.
- [ ] Narrowing the window below 1024px stacks the filter fields and wraps the footer.
- [ ] Comparing against `legacy-static/index.html` in a second tab, nothing has moved.

Items deferred from earlier reviews, verifiable only here:

- [ ] **Previous page** works (Task 10 left it untested — the unit fixture could not
      make `state.page` and `payload.page` agree). Page forward twice, then back
      twice, and confirm the rows change each time and the pager text tracks.
- [ ] **Scroll resets to top-left** on a new search and on each page change
      (`useLayoutEffect`; jsdom has no layout so no test can cover it). Scroll
      right and down, then page forward — the table must jump back to the corner.
- [ ] **No phantom column.** Tick `TEXT_USE_OF_DETECT`, and confirm the table does
      NOT immediately grow an all-em-dash column; it must stay unchanged until
      Search is pressed.
- [ ] **Reset after ticking an expensive column does not fire a 60s query.** Search,
      tick `TEXT_USE_OF_DETECT`, press Reset, and confirm the query returns in
      seconds rather than a minute.
- [ ] **Filter-change page reset** (the one intentional divergence from the original).
      Page to 3, change `STYLE_NBR`, press Enter: the port searches page 1, where
      the original searched page 3 and relied on server clamping. Confirm this
      reads as correct rather than surprising.
- [ ] **A metadata failure keeps the glyph green.** Not reproducible without breaking
      the server; skip unless it occurs naturally, and note it as unverified.
- [ ] **The cost model itself** — the claim the whole design rests on. Record actual
      seconds for: default 58-column search, hiding a column, ticking
      `TEXT_USE_OF_DETECT` then searching, and unticking it. Compare against the
      README's measured 23.1s / 0.0s / 75.9s / 0.0s. **If these do not hold, say
      so plainly — the design's premise would be wrong, not just the numbers.**

- [ ] **Step 2b: Fix the `#root` layout break found by Step 2**

Live verification found the page body scrolling and the sticky header failing.
Cause: in the original, `.appbar`, `.notice`, `.filter-panel`, `.results` and
`.footerbar` are **direct children of `body`**, which is the
`display: flex; flex-direction: column; overflow: hidden` container. React nests
them inside `<div id="root">`, which has no CSS — so `body`'s flex applies to
`#root` alone, `.results { flex: 1; min-height: 0 }` has no flex parent to size
against, and the table container never becomes the scroll region.

`display: contents` removes `#root` from the box tree, making its children
`body`'s flex items exactly as in the original. Every existing rule — including
the `max-width: 1024px` media query that switches `body` to `overflow: auto` —
then applies unchanged, with no new layout semantics to reason about. This is
why the fix is one declaration rather than a re-creation of `body`'s rules on
`#root`, which would have to be kept in sync with them.

Create `web/src/styles/root.css`:

```css
/* React mounts into <div id="root">, but style.css puts the app shell's flex
   column on `body` and expects .appbar / .filter-panel / .results / .footerbar
   to be its direct children. `display: contents` takes #root out of the box
   tree so they are, restoring the original layout exactly: the table scrolls
   inside .table-container and the page body never does.

   Do not replace this with flex properties on #root -- they would duplicate
   body's rules and drift from them. */
#root {
  display: contents;
}
```

Then add the import to `web/src/main.tsx`, after the other two:

```tsx
import './styles/root.css'
```

`style.css` and `controls.css` stay byte-identical to their originals; this is a
new file, not an edit to them.

- [ ] **Step 2c: Re-verify the two failed checks**

Rebuild, reload, and confirm at a 1440x900 viewport:

- The page body does **not** scroll vertically when results exceed a screenful.
  Only `.table-container` scrolls.
- The header row stays fixed while scrolling down, and `BOM_ROW_NBR` stays fixed
  while scrolling right, including where the two meet.
- Scrolling right and down then paging forward returns the table to the
  top-left corner.
- Below 1024px the filter fields still stack and the footer still wraps.

- [ ] **Step 3: Confirm the fallback still works**

`legacy-static/` must still hold `index.html`, `app.js`, `filters.js`, `style.css` and `controls.css`. Confirm the directory is intact and untouched.

- [ ] **Step 4: Update `README.md`**

Four edits; leave everything else alone.

1. In **Quick start**, add the build step before the uvicorn command. Use
   `npm ci`, not `npm install` — the dependencies are caret-ranged, and only the
   lockfile pins the majors this port was verified against (React 19.2,
   TypeScript 7.0, Vite 8.2, Vitest 4.1):

```bash
npm ci
npm run build
pip install -r requirements.txt
cd src
uvicorn main:app --port 8000
```

Add below it: "`npm run build` compiles the React frontend into `src/static`. For frontend work, run `npm run dev` on port 5180 alongside uvicorn — it proxies `/api` to port 8000 and hot-reloads."

2. In **Prerequisites**, add a row: `| Node 20+ | build-time only; not needed to run a pre-built app |`.

3. Replace the **Project layout** block with the tree from this plan's File Structure section, and **delete the sentence** "`vite.config.js` in the root is an unused stub dropped by the superdesign CLI. This app has no build step and no Node dependencies; the file can be deleted." It is now false in all three claims.

4. In **Known limitations**, replace the `src/db.py is 519 lines` bullet's neighbours as needed and add: "The results table body is written as an HTML string via `dangerouslySetInnerHTML` rather than as React elements. 60 columns × 1,000 rows is 60,000 cells, where per-node rendering is measurably slower; `escapeHtml` in `web/src/utils/format.ts` is consequently security-relevant and is unit-tested."

- [ ] **Step 5: Final checkpoint**

Run: `npm test -- --run && npx tsc --noEmit && npm run build`
Expected: all tests pass, no type errors, build succeeds.

---

## Self-Review Notes

Checked against `docs/superpowers/specs/2026-08-13-react-port-design.md`:

- Every spec section maps to a task. Serving → 1. Types/client → 2. State + params → 3. All 12 components → 4–8. Boot, polling, search, export → 9–10. Testing is inside each task rather than deferred. README follow-on → 11.
- Names are consistent across tasks: `escapeHtml`, `fmt`, `addedColumns`, `staleNote`, `rowsParams`, `exportParams`, `queryReducer`, `useMeta`, `useSearch`, `ConnKind`, `RowLimit`, `ParamOverrides`.
- `ConnKind` is defined in `AppBar.tsx` (Task 4) and imported by `useSearch.ts` (Task 9) — check the import path if Task 9 is done out of order.
- The `hidden` CSS class is used only by `legacy-static/`; React conditionally renders instead. This is the single intentional divergence from the original DOM, and it is invisible.
