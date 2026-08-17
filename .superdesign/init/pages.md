# Page Dependency Trees

**Status: GREENFIELD.** No pages exist yet, so no import tracing is possible.

## / (BOM Query — the only page)

Planned entry: `static/index.html`
Planned dependencies:
- `static/style.css`        — all tokens + layout + table styling
- `static/app.js`           — filter state, fetch, table render, paging, CSV export
- `main.py`                 — FastAPI routes (serves this page)
- `db.py`                   — pyodbc access to `the source view`

When designing this page, the `--context-file` set is `.superdesign/design-system.md` +
`.superdesign/init/theme.md` until `static/style.css` exists.
