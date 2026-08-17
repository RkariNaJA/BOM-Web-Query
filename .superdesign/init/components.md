# Shared UI Components

**Status: GREENFIELD.** This project directory contained only `.claude/settings.local.json` at init time.
There are no existing components, no framework installed, and no component library.

## Detected stack (planned, mirrors sibling projects in this folder)

| Layer | Choice | Precedent |
|---|---|---|
| Backend | FastAPI + uvicorn | `../SQL Chat Bot/main.py` |
| DB driver | `pyodbc`, ODBC Driver 17 for SQL Server, Trusted_Connection | `../SQL Chat Bot/db.py` |
| Frontend | Static HTML + vanilla JS + hand-written CSS served from `static/` | `../SQL Chat Bot/static/` |
| CSS approach | Plain CSS with custom properties in `static/style.css` — no Tailwind, no build step |
| Component library | None (hand-rolled) |

## Components to be built

None exist yet. The design draft defines them. Planned primitives, all hand-rolled in
`static/style.css` + `static/app.js`:

- `SegmentedControl` — row-limit selector (100 / 1,000 / 10,000 / ALL)
- `ComboBox` — searchable dropdown over distinct values, free-text entry allowed
- `Toggle` — partial-match (LIKE) switch
- `DataTable` — 60-column horizontally-scrolling table, sticky header, sticky first column
- `PaginationBar` — page N of M, prev/next, total row count
- `Button` — one solid-ink primary (Search), ghost secondary (Export CSV, Reset)
- `StatusLine` — connection / query-timing readout
