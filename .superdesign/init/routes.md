# Routes

**Status: GREENFIELD.** No router. Single page + JSON API.

| Path | Method | Serves | Notes |
|---|---|---|---|
| `/` | GET | `static/index.html` | the only screen |
| `/static/*` | GET | css / js assets | mounted StaticFiles |
| `/api/meta` | GET | column list + total row count | cached |
| `/api/distinct` | GET | distinct STYLE_NBR / STYLE_SEASON values | cached at startup; feeds the comboboxes |
| `/api/rows` | GET | `{columns, rows, total, page, pages}` | params: `limit`, `page`, `style_nbr`, `style_season`, `partial` |
| `/api/export.csv` | GET | streaming CSV of the full filtered set | same filter params, no row cap |

Backing object for every data route: `the source view` (60 columns, 362,733 rows).
