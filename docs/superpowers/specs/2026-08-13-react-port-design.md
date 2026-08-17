# BOM Query Web — React port

**Date:** 2026-08-13
**Status:** approved, ready for implementation planning

## Goal

Replace the vanilla-JS frontend (`src/static/app.js`, `filters.js`, `index.html`) with a
React + TypeScript application built by Vite. The screen looks and behaves identically —
this is an implementation change, not a redesign.

The Python backend (`config.py`, `db.py`, `main.py`) is **not modified**. Its six endpoints,
its caching, and its performance characteristics are unchanged.

## Why

The current frontend is 603 lines of imperative DOM code across two files sharing implicit
globals (`filters.js` reads `state`, `$`, `escapeHtml`, `fmt`, `readJson`, `search` and
`onVisibilityChange` declared in `app.js`). Adding a feature means finding every place that
touches `state` and updating the DOM by hand. React makes the render a function of state and
lets the pieces be tested in isolation.

## Non-goals

- No change to any endpoint, query, or caching behaviour.
- No visual redesign. `style.css` and `controls.css` move over byte-for-byte.
- No new runtime CDN dependency. The Google Fonts `<link>` stays exactly as it is today
  (a progressive enhancement that degrades to `system-ui` / Consolas / local Noto Sans Thai);
  everything else is bundled locally.
- No server-side rendering, routing, or state-management library.

---

## Architecture

### Serving

`main.py` serves `src/static/index.html` at `/` and mounts `src/static` at `/static`. Vite
builds into `src/static` with `base: '/static/'`, so hashed assets resolve to
`/static/assets/index-<hash>.js` and the existing mount serves them.

**`main.py` requires no changes.** This is the reason for this layout rather than a
separate `dist/` directory.

| Mode | Command | Behaviour |
|---|---|---|
| Development | `npm run dev` (:5180) + `uvicorn main:app --port 8000` | Vite serves the app; `server.proxy` forwards `/api` to `127.0.0.1:8000`. `base` is `/`. |
| Production | `npm run build`, then `uvicorn main:app --port 8000` | Single server on :8000, no CORS. `base` is `/static/`. |

Node is a **build-time dependency only**. Deploying still means running uvicorn against a
pre-built `src/static`. Verified available on the dev machine: Node v24.11.1, npm 11.6.2.

### Directory layout

```
BOM Query Web/
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts                  replaces the current unused stub
  web/                            Vite root — all React source
    index.html                    font link, inline icon sprite, <div id="root">
    src/
      main.tsx                    mount + CSS imports
      App.tsx                     composition and top-level state
      api/
        types.ts                  Meta, FilterSpec, RowsPayload, Health, DistinctPayload
        client.ts                 fetch wrappers, readJson error extraction
        params.ts                 pure query-string builder
      state/
        queryReducer.ts           filter values, partial, limit, page, pageSize, visible
        useSearch.ts              query execution, busy guard, elapsed ticker
        useMeta.ts                boot: health -> meta -> total-row polling
      components/
        AppBar.tsx      Notice.tsx      FilterPanel.tsx
        FilterField.tsx Combobox.tsx    DateRange.tsx
        Segmented.tsx   Toggle.tsx      ColumnPicker.tsx
        ResultsTable.tsx FooterBar.tsx  IconSprite.tsx
      styles/
        style.css                 copied verbatim from src/static/
        controls.css              copied verbatim from src/static/
  src/                            Python — unchanged
    static/                       Vite build output (generated)
  legacy-static/                  today's frontend, preserved
  docs/superpowers/specs/         this document
```

The project is **not under version control**. The current frontend is therefore moved to
`legacy-static/` rather than deleted, so there is a fallback. Vite's `emptyOutDir` will
clear `src/static` on every build, which is why the originals must move out first.

---

## State

Two groups, deliberately separate.

**Query-shaping** — a `useReducer` in `queryReducer.ts`. This is what the user manipulates:

| Field | Type | Notes |
|---|---|---|
| `values` | `Record<string, string>` | keyed by the filter spec's `param` name, never by column |
| `partial` | `boolean` | the LIKE toggle |
| `limit` | `'100' \| '1000' \| '10000' \| 'all'` | |
| `page` | `number` | |
| `pageSize` | `100 \| 250 \| 500 \| 1000` | |
| `visible` | `Set<string>` | the column picker's selection |

**Server-derived** — plain `useState` in `App.tsx`: `meta`, `payload`, `fetched: Set<string>`,
`busy`, `error`, `elapsed`.

### The invariant that must survive the port

The table renders from `payload`, **never** from live filter state. `visible` only *projects*
the columns the payload already holds. This is why hiding a column costs 0.0s today, and in
React it falls out for free — changing `visible` re-renders `ResultsTable` from the payload
already in memory, with no fetch.

### Column visibility: free vs expensive

`added = visible − fetched`.

- `added` is empty → the server already holds those columns → search immediately from cache.
- `added` is non-empty → **do not query**. Flag the Search button `stale` and show
  `+N column(s), ~Ss — press Search`, where `S` sums `meta.column_costs`. The two
  `nvarchar(max)` detection columns cost roughly 60s each; ticking one must never fire a
  query implicitly.

This is implemented as an **explicit handler, not a `useEffect` on `visible`**. An effect
would fire on mount and could launch a 60-second query nobody asked for. Because `setVisible`
is asynchronous, `runSearch` accepts an overrides argument — `runSearch({ visible: next })` —
so it can never build parameters from a stale set. `params.ts` is a pure function of
`(state, overrides)` for exactly this reason, and is directly testable.

---

## Components

Each is a direct counterpart of existing markup; no new UI concepts.

| Component | Replaces | Notes |
|---|---|---|
| `IconSprite` | the inline `<svg>` sprite | rendered once at the top of `App`; `<use href="#i-…">` unchanged |
| `AppBar` | `header.appbar` | source, connection glyph, total rows |
| `Notice` | `#notice` | the dismissible ALL-limit warning |
| `Segmented` | `buildSegmented` | generic over value type, renders row-limit and page-size |
| `Toggle` | `#partialToggle` | keeps `role="switch"`, `aria-checked`, Space/Enter handling |
| `FilterPanel` | `section.filter-panel` | maps `meta.filters` to `FilterField` |
| `FilterField` | `buildFilterFields` | dispatches on `spec.kind`, renders label and note |
| `Combobox` | `makeCombo` | see below |
| `DateRange` | `buildDateRange` | two `input[type=date]`, min/max from `spec.bounds` |
| `ColumnPicker` | `buildPicker` / `syncPicker` | groups, search box, All/Default/None, cost badges |
| `ResultsTable` | `render` | see below |
| `FooterBar` | `footer.footerbar` | matched count, elapsed, page size, pager, export |

### Combobox

Preserves every behaviour of `makeCombo`:

- Values fetched from `/api/distinct` on **first focus only**, tracked by a ref (each
  `DISTINCT` is a multi-second query, and most searches touch one or two fields).
- A failed fetch is non-fatal — the field still accepts free text.
- Case-insensitive `includes` match, **capped at 200 rendered options** with an
  `N more — keep typing` note. 2,405 options are pointless to paint.
- No match shows `no match — free text is still accepted`.
- Enter closes the list and searches. Escape closes it. An outside click closes it
  (document listener registered in a `useEffect`, cleaned up on unmount — the current code
  leaks one listener per combo).

### ResultsTable

`render()` writes the entire tbody in a single `innerHTML` assignment because 60 columns ×
1,000 rows is 60,000 cells and per-node DOM calls are visibly slower at that count. React
reconciling 60,000 fibers is the same problem.

**Decision: keep the string build.** The tbody HTML is produced in a `useMemo` keyed on
`(payload, visible)` and applied via `dangerouslySetInnerHTML`, reusing the existing
`escapeHtml`. This preserves both the measured performance and the sticky-header /
sticky-pinned-column CSS, which is the highest-risk part of a 1:1 visual port.

This is the one deliberately non-idiomatic component. It carries a comment stating the
measurement and the reason, and `escapeHtml` is unit-tested, since it is now the only thing
standing between database content and injected markup. Every value — cell text and `title`
attribute alike — goes through it.

Also preserved: `—` for null and empty, the `null` class on those cells, the `pinned` class
on the pinned column, and resetting `scrollTop`/`scrollLeft` to 0 after each search so the
first rows are not hidden above the scroll position.

---

## Data flow

**Boot** (`useMeta`): `GET /api/health` → set connection state and source. On failure, show
the error placeholder and stop. Then `GET /api/meta` → columns, groups, pinned, filter spec,
`default_columns`, `column_costs`, `total_rows`. On failure, error placeholder and stop.
`visible` initialises to `default_columns` — 58 of 60, omitting the two ~60s columns.

`/api/meta` only peeks at the cached row count, so `total_rows` is `null` on a cold server.
When it is, poll every 10s for up to 6 attempts, then give up silently — the header total is
informational. The poll is cancelled on unmount.

**Search** (`useSearch`): guard on `busy`; start a 100ms elapsed ticker; build params from
`params.ts` including `columns=[...visible].join(',')`; `GET /api/rows`. On success, set
`payload`, set `fetched` from `payload.fetched_columns ?? payload.columns`, clear the stale
flag, reset table scroll. On failure, connection glyph `error` and the server's `detail`
string in the placeholder. The ticker is always cleared in `finally`, and on unmount.

**Reset**: clears all filter values and both date inputs, sets `partial` false, returns
`visible` to `default_columns` — **not** all 60, so a reset never silently re-enables the two
expensive columns — clears the stale flag, and re-searches only if a search has already run.

**Export**: if no filter is set, `confirm()` first, naming the row count and column count.
Then navigate to `/api/export.csv?…` with the current filters and column selection. Kept as a
navigation, not a fetch, so the browser handles the streaming download.

---

## Error handling

| Failure | Behaviour |
|---|---|
| `/api/health` unreachable | glyph `error`, `not connected`, error placeholder, boot stops |
| `/api/meta` fails | error placeholder with the message, boot stops |
| `/api/rows` fails | glyph `error`, footer reads `failed`, placeholder shows the server `detail` |
| `/api/distinct` fails | silent — the combobox still accepts free text |
| `total_rows` stays null | header keeps `— rows` after 6 polls |

`readJson` extracts `detail` from a JSON error body, falling back to `HTTP <status>`.

---

## Testing

Vitest + React Testing Library. No test setup exists today. Live-database tests are not
viable — a default query takes 23 seconds — so `fetch` is mocked throughout.

**Pure logic** (highest value, no DOM):

- `params.ts`: empty and whitespace-only filters omitted; values trimmed; `partial` always
  sent; `columns` reflects `visible`; overrides beat state.
- `escapeHtml`: `&`, `<`, `>`, `"`; Thai text passes through intact.
- Cost calculation: `added` set difference; summed seconds; singular vs plural; the
  sub-1s message variant.
- `queryReducer`: reset returns `visible` to defaults not all-60; page resets to 1 on filter,
  limit and page-size changes.

**Components:**

- `Combobox`: fetches once on first focus and not again; filters case-insensitively; caps at
  200 with the overflow note; Enter searches; outside click closes; a fetch rejection still
  leaves the input usable.
- `ColumnPicker`: toggling a fetched column searches; toggling an unfetched column does
  **not** fetch and flags Search; the pinned column cannot be unticked; All/Default/None.
- `ResultsTable`: nulls and empties render `—`; the pinned class lands on the right column;
  a value containing `<script>` is escaped.

---

## Follow-on work (not part of this port)

- **`README.md` needs updating.** It currently states the app has no build step and that
  `vite.config.js` is an unused stub that can be deleted. Both become false. The project
  layout section and Quick start need a build step added.
- `src/db.py` remains 519 lines, over the 500-line guideline. Out of scope — it is backend.
