# Layout Components

**Status: GREENFIELD.** No layout components exist yet.

## Planned shell

Single-page app, no router, no sidebar nav (there is only one screen).

```
+---------------------------------------------------------------+
| HEADER BAR  ~52px                                             |
|   "BOM QUERY" wordmark | breadcrumb the database / dbo.VIEW_... |
|   right: connection status glyph + row-count readout           |
+---------------------------------------------------------------+
| FILTER PANEL  (raised paper card, hairline border)             |
|   ROWS segmented control: 100 | 1,000 | 10,000 | ALL           |
|   STYLE_NBR combobox      STYLE_SEASON combobox                |
|   [x] partial match (LIKE)     [ SEARCH ]  [ Reset ]           |
+---------------------------------------------------------------+
| RESULTS  (fills remaining height)                              |
|   60-column table, sticky header row, sticky BOM_ROW_NBR col   |
|   horizontal + vertical scroll inside its own container         |
+---------------------------------------------------------------+
| FOOTER BAR  (sticky bottom)                                    |
|   "362,733 rows matched"  page 1/726  [<] [>]  [ Export CSV ]  |
+---------------------------------------------------------------+
```

Files that will own this: `static/index.html` (structure), `static/style.css` (all layout),
`static/app.js` (fetch + render + paging).
