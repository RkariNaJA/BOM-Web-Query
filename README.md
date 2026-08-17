# BOM Query Web

A read-only web explorer over the SQL Server view `the source view`
— **60 columns, ~365,000 rows** of apparel style/merch header data joined to per-line
Bill-of-Materials detail (fabric, trim, colorway, vendor, zipper attributes).

Built for merchandisers and BOM/development staff who already know the column names:
filter by style or item, read the rows, export the full set to Excel.

---

## Quick start

**First time**, from the repo root:

```bash
cp .env.example .env             # then fill in the server, database and view
npm ci                           # install frontend deps, exactly as pinned in package-lock.json
npm run build                    # compile React into plain HTML/CSS/JS in src/static
pip install -r requirements.txt  # install backend deps (fastapi, uvicorn, pyodbc)

python scripts/build_snapshot.py # ~2 min: extract the view into data/bom.sqlite

cd src
uvicorn main:app --port 8000     # serve the FastAPI `app` object from main.py on 127.0.0.1:8000
```

Then open <http://127.0.0.1:8000>.

Only `build_snapshot.py` talks to SQL Server. `uvicorn` reads the snapshot and nothing else,
which is why the app starts instantly and never blocks on the view.

**Rebuilding the snapshot later** — the app reads only `data/bom.sqlite` and never
contacts SQL Server, so this is the only thing that fetches new data:

```bash
# 1. Stop the web app (Ctrl-C in the uvicorn terminal).
#    The swap cannot rename over a file the app holds open; if it is still
#    running the build fails with a logged PermissionError and exits non-zero.
#    Nothing is lost, but nothing is updated either.

# 2. From the repo root -- note the path if you are still in src/:
python scripts/build_snapshot.py
cd .. && python scripts/build_snapshot.py     # if your shell is in src/

# 3. Start the app again.
cd src && uvicorn main:app --port 8000
```

Useful variants:

| Command                                                                 | What it does                                   |
| ----------------------------------------------------------------------- | ---------------------------------------------- |
| `python scripts/build_snapshot.py`                                      | full rebuild, promotes to `data/bom.sqlite`    |
| `python scripts/build_snapshot.py --no-swap`                            | builds `data/bom.new.sqlite`, promotes nothing |
| `python scripts/build_snapshot.py --limit 1000 --out data/trial.sqlite` | quick trial against the view; never promotes   |
| `python scripts/build_snapshot.py --max-age-hours 20`                   | rebuild only if the snapshot is older than 20 h |

### Refreshing automatically

`scripts/refresh_snapshot.cmd` is a Task Scheduler entry point. Register it once from a
normal Command Prompt — **not** as administrator, so the task runs as you and inherits
your database access:

```bat
schtasks /Create /TN "BOM Snapshot Refresh" /SC ONLOGON ^
  /TR "\"C:\path\to\BOM Query Web\scripts\refresh_snapshot.cmd\"" /RL LIMITED /F
```

**Logon, not midnight** — a laptop is asleep at midnight. That means the task may fire
several times a day, so the script rebuilds only when the snapshot is older than
`MAX_AGE_HOURS` (20 by default, set at the top of the file). Otherwise it exits in under
a second without querying anything.

It also **refuses to run while the web app is up**. The swap cannot rename over a
snapshot the app holds open, so rather than spend two minutes and a heavy production
query only to fail at the last step, it checks whether anything is listening on
`APP_PORT` and skips with an explanation.

| Exit code | Meaning                                                        |
| --------- | -------------------------------------------------------------- |
| `0`       | rebuilt, or already fresh                                      |
| `1`       | failed — see `scripts/logs/`                                   |
| `2`       | sanity gate rejected the extract; live snapshot left untouched |
| `3`       | skipped, the web app is holding the snapshot open              |

Task Scheduler's "last run result" shows that code. Inspect with
`schtasks /Query /TN "BOM Snapshot Refresh" /V /FO LIST`, trigger with `schtasks /Run`,
remove with `schtasks /Delete /TN "BOM Snapshot Refresh" /F`.

Each run writes a timestamped log to `scripts/logs/`. The line worth reading is
`extract finished: N rows in Xs total`. A run that fails the sanity check — fewer
than 90% of the previous row count — refuses to promote and exits `2`, leaving the
current snapshot untouched. The previous generation is kept as `data/bom.prev.sqlite`.

How often to rebuild is up to how fresh you need the data; the header shows the
snapshot's age and turns red past 36 hours.

Tests are Python and TypeScript side by side, and neither needs a database:

```bash
pip install -r requirements-dev.txt && python -m pytest tests/ -q   # 133 tests
npm test                                                            # 47 tests
```

`.env` holds everything environment-specific — which SQL Server instance, which
database and view, and credentials if the deployment does not use Windows auth.
It is git-ignored; `.env.example` is the template. Any of its keys can also be
set as a real environment variable, which takes precedence over the file. The app
refuses to start if `BOM_DB_SERVER`, `BOM_DB_DATABASE` or `BOM_DB_VIEW` is missing.

For frontend work, run `npm run dev` on port 5180 alongside uvicorn — it proxies
`/api` to port 8000 and hot-reloads, so you skip the `npm run build` step while
iterating.

⚠️ Start uvicorn from **inside `src/`** — `main.py` imports `config` and `db` as
top-level modules.

### Prerequisites

| Requirement                               | Notes                                                                    |
| ----------------------------------------- | ------------------------------------------------------------------------ |
| Python 3.10+                              | developed on 3.13.2                                                      |
| Node 20+                                  | build-time only; not needed to run a pre-built app                       |
| `ODBC Driver 17 for SQL Server`           | needed only to **build** a snapshot; serving one does not use it         |
| Windows account with SELECT on the view   | connection defaults to `Trusted_Connection=yes` — no credentials in code |
| Network access to the SQL Server instance | again, only to build a snapshot                                          |

Dependencies are only `fastapi`, `uvicorn[standard]`, `pyodbc`.

---

## Project layout

```
.env                  git-ignored: server, database, view, credentials
.env.example          template for the above
requirements.txt
requirements-dev.txt  the above plus pytest
package.json          npm scripts: build (tsc --noEmit && vite build), dev, test, typecheck
tsconfig.json
vite.config.ts
vitest.config.ts
scripts/              the nightly snapshot extract -- the app's only data source
  snapshot_schema.py  pure helpers: type mapping, quoting, DDL, value coercion
  build_snapshot.py   the job: stream, load, index, measure, sanity-gate, swap
  logs/               git-ignored, one log file per run
tests/                pytest, 133 tests, none of which need a database
  test_snapshot_schema.py
  test_build_snapshot.py
  test_db.py
data/                 git-ignored: bom.sqlite and its .new / .prev siblings
docs/superpowers/
  specs/              design documents
  plans/              implementation plans
src/
  config.py           reads `.env`, then snapshot paths, filter spec, picker groups
  db.py               read-only data layer over the snapshot -- no pyodbc
  main.py             FastAPI app and 6 endpoints
  static/             built output of `npm run build` -- served at `/` and mounted at `/static`
    index.html
    assets/           hashed JS/CSS bundles
web/
  index.html          Vite entry HTML
  src/
    main.tsx          React root
    App.tsx           top-level component: state, boot, query orchestration
    api/               client.ts, params.ts, types.ts -- fetch layer and query-param builders
    components/        AppBar, FilterPanel, ColumnPicker, Combobox, DateRange, ResultsTable,
                        FooterBar, Notice, Segmented, Toggle, Icon/IconSprite (+ *.test.tsx)
    state/             queryReducer, useMeta, useSearch (+ *.test.ts)
    styles/            style.css, controls.css -- the ported design tokens and layout
    utils/             format.ts (escapeHtml, tabular formatting; unit-tested)
    test/              Vitest setup and a smoke test
.superdesign/
  design-system.md   the visual system and product context
  init/              repo context files used by the superdesign workflow
legacy-static/         the pre-port vanilla-JS app -- kept as a rollback path, untouched
  index.html, style.css, controls.css, app.js, filters.js
```

---

## Features

### Filters

Six filters, all ANDed together.

| Filter          | Type                            | Distinct values | Notes                                              |
| --------------- | ------------------------------- | --------------- | -------------------------------------------------- |
| `STYLE_NBR`     | searchable dropdown + free text | 1,512           |                                                    |
| `STYLE_SEASON`  | searchable dropdown + free text | 2,405           |                                                    |
| `Buy Code`      | searchable dropdown + free text | 9               | **null on 86% of rows** (316,021 of 365,411)       |
| `ITEM_NBR`      | searchable dropdown + free text | 1,267           |                                                    |
| `IM`            | searchable dropdown + free text | 1,024           |                                                    |
| `BOM_UPDATE_DT` | inclusive from/to date range    | 138 dates       | data spans `2025-10-29` → `2026-08-13`, zero nulls |

- **`partial match (LIKE)`** toggle applies to the five text filters. Literal `%` and `_` in a
  value are escaped, so a code containing a wildcard can't silently widen the search.
- Value lists load on first focus. Against the view each `DISTINCT` was a multi-second
  query and only five columns were offered one; against the snapshot it is ~19 ms, so any
  column can have a list. Free text is always accepted regardless.
- Filters are driven by a spec published on `/api/meta`, so adding one is a `config.py` entry
  plus a query parameter — no per-column frontend code.

### Paging

- **Page size**: `100` / `250` / `500` / `1,000`, with a hard **minimum of 100**. An
  out-of-range value clamps rather than returning an error.
- Out-of-range page numbers clamp to the last page.
- Paging is **deterministic**. The view had no unique key, so the unfiltered path ordered by
  `(SELECT NULL)` and could in principle repeat or skip rows between pages. The snapshot gives
  every row a surrogate key, so that class of bug is gone.
- There is no row-limit control. `100 / 1,000 / 10,000 / ALL` existed only to stop a user
  accidentally triggering a 40-second query; every query now settles in milliseconds.

### Columns

All 60 columns are available. The picker groups them as the view is actually laid out:

| Group        | Columns |
| ------------ | ------- |
| STYLE HEADER | 21      |
| BUY READY    | 6       |
| BOM LINE     | 22      |
| DETECTION    | 3       |
| DATES        | 2       |
| ZIPPER       | 6       |

- `BOM_ROW_NBR` is pinned to the left edge and cannot be hidden.
- **All 60 are shown by default.** Unticking is purely a display preference — no column costs
  anything to fetch, and ticking one re-queries immediately rather than flagging Search.
- The picker has a search box plus `All` / `Default` / `None`.

### CSV export

Streams the complete filtered set with no row cap, honouring the current column selection.
Starts with a UTF-8 BOM so Excel on Windows reads the Thai values in `MASTER_BOM_STATUS`
and `BNR_REMARK` correctly instead of as mojibake. Filenames are timestamped, e.g.
`<view>-AB1234-20260811-152020.csv`.

---

## Performance

Queries run against a local SQLite snapshot, so the app is fast in a way the numbers below
make almost boring:

| Query                        | Live view (before) | Snapshot (now) |
| ---------------------------- | ------------------ | -------------- |
| Unfiltered `COUNT(*)`        | ~20 s              | **7.1 ms**     |
| `COUNT(*)` filtered by style | ~5 s               | **0.1 ms**     |
| `DISTINCT STYLE_SEASON`      | ~9.5 s             | **19.3 ms**    |
| All 60 columns, 100 rows     | ~128 s             | **1.0 ms**     |

What building a snapshot costs is in [The nightly snapshot](#the-nightly-snapshot) below.

---

## API

| Endpoint                    | Purpose                                                                |
| --------------------------- | ---------------------------------------------------------------------- |
| `GET /`                     | the single page                                                        |
| `GET /api/health`           | snapshot readable, and when it was built                               |
| `GET /api/meta`             | columns, picker groups, filter spec, defaults, row total, snapshot age |
| `GET /api/distinct?column=` | value list for any column                                              |
| `GET /api/rows`             | one page of results                                                    |
| `GET /api/export.csv`       | streaming CSV of the full filtered set, uncapped                       |

`/api/rows` and `/api/export.csv` share these query parameters:

| Parameter                                                 | Meaning                                             |
| --------------------------------------------------------- | --------------------------------------------------- |
| `style_nbr`, `style_season`, `buy_code`, `item_nbr`, `im` | text filters                                        |
| `updated_from`, `updated_to`                              | `BOM_UPDATE_DT` bounds, `YYYY-MM-DD`, end inclusive |
| `partial`                                                 | `true` for `LIKE`, `false` for `=`                  |
| `columns`                                                 | comma-separated column list; omitted means all 60   |
| `page`, `page_size`                                       | `/api/rows` only                                    |

There is no `limit` parameter any more: it existed to cap a 5–40 s query. `/api/rows` still
returns `fetched_columns` for wire compatibility, but it is now always the full column set —
the distinction between a free column change and an expensive one no longer exists.

---

## Design

Visual direction is **E-Ink Paper**: near-black ink on warm paper, hairlines doing all
separation, zero shadows, zero gradients (bar a 4px dot-grain on the filter panel), no zebra
striping, hierarchy from size and weight only. Signal red `#c8321e` is rationed to errors and
the large-export notice.

- Complete spec: `.superdesign/design-system.md`
- Type: IBM Plex Sans for UI, IBM Plex Mono with `tabular-nums` for every data value — 60
  columns only stay readable if figures align vertically.
- **Thai support is mandatory**, not cosmetic: real values in `MASTER_BOM_STATUS` are Thai
  (e.g. `ไม่นับ`). Both font stacks carry a Noto Sans Thai fallback.
- Webfonts are a progressive enhancement. If the network blocks Google Fonts the page falls
  back to `system-ui` / Consolas and any locally installed Noto Sans Thai. There are **no CDN
  dependencies** for scripts, styles or icons — icons are an inline SVG sprite — so the app
  works on a locked-down network.

Design drafts produced during this work:

- [Initial](https://p.superdesign.dev/draft/9c846c67-dca5-4be6-b612-9b536ef2e880)
- [With column picker and page size](https://p.superdesign.dev/draft/78cf109f-512a-4b81-82ca-f96b99627503)

---

## Notable implementation decisions

**An inclusive end date is `< next day`, never `<=`.** `BOM_UPDATE_DT` values carry a time, so
`<= '2026-08-09'` means midnight and silently drops everything later that day. Measured against
the view, a naive `<=` discarded **6,072 rows**. The snapshot stores the full ISO timestamp
(`'2026-08-14 13:04:05'`), which sorts correctly but has the same trap, so `db.py` compares
`< date(?, '+1 day')` — the SQLite equivalent of the `DATEADD` the SQL Server version used.
Pinned by tests in both `tests/test_db.py` and `tests/test_build_snapshot.py`.

**Two quoting styles, deliberately.** SQLite identifiers are `"double quoted"`; SQL Server
identifiers are `[bracketed]`. Both appear in this repo — the extract's `SELECT` targets the
view, everything else targets the snapshot — because the source really does contain `GCW#`,
`Buy Code` and `BOM Type`.

**Column names are whitelisted against the snapshot's own schema** before reaching a query, and
every filter value travels as a bound parameter. Nothing in the app writes.

**`LIKE` needs an explicit `ESCAPE`.** SQLite has no default escape character, so a literal `%`
in a style code would match everything without one. `db.py` escapes `%`, `_` and `\` and passes
an explicit `ESCAPE` clause naming the backslash.

**Values are coerced on the way into the snapshot, not on the way out.** `sqlite3` refuses to
bind `Decimal`, `datetime.time` and `UUID` outright, and accepts `datetime` only through an
adapter deprecated in Python 3.12. `snapshot_schema.to_sqlite_value` converts every cell during
the extract, so the file holds ISO text and floats rather than whatever the driver returned.

**Every query is ordered.** The view had no unique key, so the unfiltered path used
`ORDER BY (SELECT NULL)` and could repeat or skip rows between pages. The snapshot's surrogate
key makes the ordering total, so paging is deterministic.

**A snapshot with a `bom_detect` side table is refused, not read.** An older two-table snapshot
would otherwise serve rows with two columns silently missing.

**The wide table scrolls inside its own container**, never the page body. Sticky header row plus
a sticky pinned first column; the header cell carries the higher `z-index` so it wins where the
two sticky axes meet.

---

## Known limitations

- **The data is a snapshot, not live.** It is as fresh as the last `build_snapshot.py` run, and
  the header says so. Rebuild when you need current rows.
- **The snapshot is 359 MB**, and a rebuild briefly holds three generations (live, previous, new).
- **The view's SQL definition is not readable** with the current login — `OBJECT_DEFINITION`,
  `sys.sql_modules` and `sys.sql_expression_dependencies` all come back empty, and DMV access is
  denied. This no longer affects users, but it still means nobody can explain the 100 s the
  extract pays each run.
- `scripts/build_snapshot.py` is 628 lines, over the project's 500-line guideline (357 of them
  executable; the rest are blank lines and the rationale comments recording why each safety
  property exists). The worthwhile split is internal: `_run` is a single 237-line function.
- `src/db.py` is comfortably within the guideline now — it went from 519 lines to roughly 300
  when the caching and column-cost machinery came out.
- The results table body is written as an HTML string via `dangerouslySetInnerHTML` rather than
  as React elements. 60 columns × 1,000 rows is 60,000 cells, where per-node rendering is
  measurably slower; `escapeHtml` in `web/src/utils/format.ts` is consequently security-relevant
  and is unit-tested.

---

## The nightly snapshot

The view is slow in a way no amount of app-side cleverness fixed: an unfiltered `COUNT(*)` took
~20 s and a 40-row fetch of all 60 columns took ~128 s, of which the three `TEXT_*_OF_DETECT`
columns were ~90% — they are built by `FOR XML PATH` string aggregation inside the view.

The app used to hide that with hidden columns, per-column cost warnings, an in-process result
cache, a background warm-up thread and a row-limit control. All of it is gone. The extract pays
the cost once a day instead of once per user query, and the app reads a local file.

**Design:** `docs/superpowers/specs/2026-08-14-sqlite-snapshot-design.md`
**Plan 1 (this work):** `docs/superpowers/plans/2026-08-14-snapshot-pipeline.md`

### Status — in use

`scripts/build_snapshot.py` builds the snapshot and `src/db.py` reads it. The app does not
import `pyodbc` at all; the only thing that contacts SQL Server is the extract.

Measured on 2026-08-17 against the real view:

|                                      |                      |
| ------------------------------------ | -------------------- |
| Fixed query cost (time to first row) | 100 s                |
| Streaming 365,411 rows               | 12 s @ 31,752 rows/s |
| **Total extract**                    | **111 s**            |
| Snapshot size                        | 359 MB               |

The view's cost turned out to be **fixed per query, not per row** — a 40-row fetch took 128 s
and the full 365,411 rows took 111 s. That was the risk the whole architecture rested on.

The detection columns measured 42 bytes/row average, 262 max — 4.3% of the file, not the ~90%
first assumed. They are expensive for the view to _compute_, not to _store_, so they live in
the main table like everything else and no response truncation is needed.

### Safety properties worth knowing

- **Sanity gate.** A new snapshot with under 90% of the previous row count is rejected rather than
  swapped in — a truncated extract still produces a _valid_ SQLite file, so without this the failure
  would present as "the BOM data is missing rows" rather than "last night's job broke". If the live
  snapshot exists but cannot be read, the run refuses to swap rather than passing by default.
- **The swap keeps the live file present at every instant.** The outgoing generation is retained by
  hardlink, not by renaming the live file aside, so a crash mid-swap cannot leave the app with no
  snapshot. One generation back is kept as `bom.prev.sqlite`.
- **Every failure is logged and exits non-zero,** including faults that happen before the log file
  exists (a broken `.env`, a missing ODBC driver), which append to
  `scripts/snapshot-bootstrap-failures.log`. Task Scheduler discards stderr, so anything not written
  to a file is invisible.

### Running it day to day

Currently a **laptop, run by hand** — one user, localhost, no scheduled task. Rebuild the snapshot
when you want fresher data, stopping the web app first. `uvicorn main:app --port 8000` binding to
127.0.0.1 is correct for this.

### Moving to the internal server

Still to do, when this goes to production on the shared always-on machine:

- A **midnight scheduled task** running `build_snapshot.py`. It must **not** run as SYSTEM, or SQL
  Server sees the machine account rather than a user with SELECT on the view and the job fails
  silently every night. Use a domain account, or fill in `BOM_DB_USER`/`BOM_DB_PASSWORD` in `.env`
  to switch to SQL auth, which is identity-independent.
- **Tick "Stop the task if it runs longer than"** on the task's Settings tab. The extract sets no
  statement timeout deliberately, so Task Scheduler is the only wall-clock cap.
- **Stop and start the web app around the swap.** Windows will not let the rename replace a file
  the app holds open. Today that is a manual step; automating it is part of this move.
- **`--host 0.0.0.0`**, a firewall rule for the port, and running uvicorn as a service so it
  survives reboot and logoff. Note the app has no authentication: anyone on the internal network
  who finds the port can read it.

Spec §8 covers both phases in full.

---
