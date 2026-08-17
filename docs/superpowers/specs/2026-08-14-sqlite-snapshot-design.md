# BOM Query Web — SQLite Snapshot Architecture

**Date:** 2026-08-14
**Status:** design, pending review

## 1. Problem

The app queries `the source view` live. The view is slow, and
nearly every design decision in the codebase exists to hide that:

| Measured | Cost |
|---|---|
| `COUNT(*)`, unfiltered | ~20 s |
| `SELECT TOP 3`, unfiltered | ~36 s |
| 40-row fetch, 57 cheap columns | 12.4 s |
| 40-row fetch, all 60 columns | 128.6 s |
| The two `nvarchar(max)` DETECTION columns | ~60 s each |

The workarounds — hidden columns, per-column cost warnings, an in-process result
cache, 300-second timeouts, a background warm-up thread, a row-limit control —
are all symptoms of that one problem.

## 2. Solution

Extract the whole view into a local SQLite file once per night. The web app
reads only from that snapshot and never contacts SQL Server.

```
  SQL Server                Windows Task Scheduler            FastAPI + SQLite
  the source view   ──►    scripts/build_snapshot.py   ──►   bom.sqlite  ──►  browser
  (slow, remote)            (00:00 nightly)                   (local, fast)
```

**Consequences accepted:** data is up to 24 hours old, and a failed build means
users see the previous snapshot. Both are fine for BOM reference data read by
1–2 internal users, provided the snapshot's age is always visible in the UI.

## 3. Decisions already agreed

| Decision | Choice |
|---|---|
| Data source at runtime | SQLite only. `pyodbc` leaves the web app entirely. |
| Backend approach | Rewrite `db.py`'s internals; keep `main.py`'s endpoint shapes. |
| Filters | The existing six. Every one gets an instant dropdown. |
| Default columns | All 60 visible. Unticking is a display preference only. |
| Host | **Phase 1: a local laptop, extract run by hand.** Phase 2, at production: a shared always-on machine reachable on an internal link. |
| Build order | Extract script first, run by hand, before any app changes. |

## 4. Snapshot schema

> **Superseded in part — see §12 Measured.** The `bom_detect` side table below
> was justified by an estimate that the two `nvarchar(max)` columns were ~90% of
> the data volume. Measured across all 365,411 rows they are **4.3%**, so the
> split is being collapsed into a single `bom` table for Plan 2. Everything else
> in this section stands.

One file, three tables.

```sql
CREATE TABLE bom (
  id INTEGER PRIMARY KEY,           -- surrogate; the view has no unique key
  "STYLE_NBR" TEXT, "BOM_ROW_NBR" INTEGER, "Buy Code" TEXT, ...  -- 58 columns
);

CREATE TABLE bom_detect (
  id INTEGER PRIMARY KEY REFERENCES bom(id),
  "TEXT_USE_OF_DETECT" TEXT,
  "TEXT_Color_Code_OF_DETECT" TEXT
);

CREATE TABLE snapshot_meta (key TEXT PRIMARY KEY, value TEXT);
-- started_at, finished_at, duration_seconds, row_count, source_view,
-- detect_avg_bytes, detect_max_bytes,
-- main_columns, detect_columns   -- JSON arrays, in table order
```

**Generated, not hardcoded.** The extract reads `INFORMATION_SCHEMA` — the same
query `db.columns()` uses at `src/db.py:65` — and builds `CREATE TABLE` from it.
A column added to the view appears in the next snapshot instead of being dropped.

**Type mapping.** SQLite is dynamically typed, but `BOM_ROW_NBR` is the pinned
sort column and as TEXT would sort `"10"` before `"9"`:

| SQL Server | SQLite | Stored value |
|---|---|---|
| `int`, `bigint`, `smallint`, `tinyint`, `bit` | `INTEGER` | unchanged |
| `decimal`, `numeric`, `float`, `real`, `money`, `smallmoney` | `REAL` | `float(value)` — a `Decimal` cannot be bound at all |
| `date` | `TEXT` | ISO `YYYY-MM-DD` |
| `datetime`, `datetime2`, `smalldatetime` | `TEXT` | ISO **`YYYY-MM-DD HH:MM:SS`** — the full timestamp, not the day (with a `.ffffff` tail if the source value has sub-second precision) |
| `time` | `TEXT` | ISO `HH:MM:SS` |
| `uniqueidentifier` | `TEXT` | `str(uuid)` |
| `varbinary`, `binary`, `image` | `TEXT` affinity, BLOB value | the raw `bytes`, stored as a BLOB — **not** hexed |
| everything else | `TEXT` | `str(value)` |

The affinity is only half the job. The *value* is coerced by
`snapshot_schema.to_sqlite_value`, applied to every cell in `load_rows`.
Without it the extract dies on the first row: `sqlite3` refuses to bind
`decimal.Decimal`, `datetime.time` and `uuid.UUID` outright
(`ProgrammingError: type ... is not supported`), and the one type it does
accept, `datetime.datetime`, it accepts only through an adapter deprecated in
Python 3.12 and slated for removal.

> ### ⚠️ Date range filters: an inclusive to-date bound must NOT be written `col <= '<to-date>'`
>
> Datetime columns store the **full timestamp**, e.g. `'2026-08-14 13:04:05'`.
> That was chosen over truncating to `'2026-08-14'` because the app displays
> the time of day today, and the full form still sorts and range-compares
> correctly. But it makes the obvious inclusive upper bound silently wrong:
>
> ```sql
> -- WRONG. Matches nothing on 2026-08-14: every timestamp that day sorts
> -- after the 10-character string '2026-08-14'.
> WHERE "BOM_UPDATE_DT" <= '2026-08-14'
>
> -- CORRECT, either form:
> WHERE "BOM_UPDATE_DT" < '2026-08-15'                   -- the day AFTER
> WHERE substr("BOM_UPDATE_DT", 1, 10) <= '2026-08-14'   -- compare the day part
> ```
>
> A `>=` from-date bound needs no adjustment. `BOM_UPDATE_DT` is a datetime and
> is the only date filter, so the naive form would drop the final day of every
> range across all 362,733 rows — quietly, with no error. `src/db.py` already
> does the equivalent against SQL Server with `DATEADD(day, 1, ...)`; the
> SQLite rewrite must keep that behaviour. Pinned by
> `TestStoredDatetimeComparison` in `tests/test_build_snapshot.py`.

**Why `bom_detect` is separate.** Those two columns are roughly 90% of the data
volume. Inline, every row is large, so fewer rows fit per page and any scan,
count, or sort drags gigabytes through memory. Split out, `bom` stays dense.
The grid `LEFT JOIN`s on every page (all columns are visible by default), which
costs microseconds — 100 rows on an integer primary key. `TEXT_Color_Name_OF_DETECT`
stays in `bom`; it is `nvarchar(4000)`, not `max`.

**Indexes** on the six filter columns, created *after* the bulk insert — building
them during insert is several times slower.

## 5. The nightly build

`scripts/build_snapshot.py`, run by Task Scheduler at 00:00.

1. Connect to SQL Server using the existing `.env` settings.
2. Read column metadata; generate the schema.
3. Create `bom.new.sqlite` with `PRAGMA journal_mode=OFF`, `synchronous=OFF` —
   safe because the file is worthless until the swap, and much faster.
4. **One streaming `SELECT`** of all 60 columns, consumed with
   `cur.fetchmany(2000)` and written with `executemany`. Not chunked into
   separate queries: if the view's cost is mostly fixed per query, twenty chunks
   pay it twenty times.
5. Log a throughput line at most every 30 seconds (not every N batches — batch
   time varies, wall-clock spacing does not): rows written, elapsed, rows/sec,
   projected total time. This is what makes the first manual run double as the
   feasibility measurement. The line separates the view's large fixed
   per-query cost from the marginal per-row rate.
6. Create indexes. Record `snapshot_meta`, including average and maximum byte
   length of the two detection columns.
7. **Sanity gate:** if a previous snapshot exists and the new row count is under
   90% of it, abort without swapping and exit non-zero. A truncated extract must
   never replace good data. *Present but unreadable* is not *absent*: if the live
   file exists and its `row_count` cannot be read — corrupt, or locked by
   antivirus or another process — the gate cannot verify anything, so the run
   refuses to swap and exits non-zero rather than passing by default. Only a
   genuinely missing file (the first run) is treated as "nothing to compare".
8. **Swap** (see 5.1). Keep the outgoing file as `bom.prev.sqlite` — one
   generation back, so a bad snapshot is one rename away from undone.
9. Log to `scripts/logs/snapshot-YYYYMMDD-HHMMSS.log` — one file per run, so a
   manual trial during the day cannot overwrite the night's record — and exit
   non-zero on any failure. Task Scheduler's "last run result" is the only other
   signal and nobody checks it. Argument parsing runs first — deliberately, so
   that `--help` and a bad command line need no log file and cannot fail for an
   environment reason — and the log file is opened immediately after. Anything
   that fails before the log exists (a missing or incomplete `.env`, a removed
   ODBC driver, an unwritable `scripts/logs/`, a rejected argument) is appended
   to `scripts/snapshot-bootstrap-failures.log` as well as printed to stderr, so
   a startup fault is never invisible.

### 5.1 The swap, and the Windows trap

Windows will not let you rename over a file another process holds open, and the
running web app holds `bom.sqlite` open. A naive `os.replace` fails with a
sharing violation — at midnight, unattended.

**Chosen fix: stop the web service, swap, start it.** The long extract happens
while the app still serves the old file, so downtime is the few seconds the
rename takes, at 1am, with no users. Deterministic and simple.

```
build bom.new.sqlite   (minutes to hours; app still serving)
sanity check           (abort here changes nothing)
stop web service       (seconds)
os.replace()           (atomic, same volume)
start web service
```

The stop/start mechanism depends on how the app ends up hosted (Windows service,
NSSM, or an "At startup" scheduled task), so the script takes the two commands as
configuration rather than hardcoding them. Decided during deployment.

*Alternative considered:* versioned filenames (`bom-20260814.sqlite`) plus a
pointer file the app re-reads, avoiding any downtime. Rejected as unnecessary
indirection for 1–2 users who are asleep when it runs.

## 6. Backend changes

### `src/db.py` — rewritten internals, same public functions

Keep: `columns()`, `distinct_values()`, `count_rows()`, `fetch_page()`,
`iter_csv()`. `test_connection()` becomes `snapshot_status()`, returning the
build stamp instead of a live connection probe.

Delete outright: `_result_cache`, `_fetch_capped`, `_fetch_offset_page`,
`warm_cache()`, `_distinct_cache`, `_count_cache`, `_bounds_cache`. All of it
exists to avoid re-running slow queries that are about to become instant.

- Read-only connections: `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`,
  one per request (FastAPI runs sync endpoints in a threadpool).
- `quote_ident` switches from `[...]` to SQLite's `"..."`, doubling embedded
  quotes. The view really does contain names like `GCW#` and `Buy Code`.
- Filter values stay parameterised; column names stay whitelisted against the
  snapshot's own schema. The SQL-injection posture does not change.

### `src/config.py`

Delete `COLUMN_COST_SECONDS`, `DEFAULT_HIDDEN_COLUMNS`, `ROW_LIMITS`,
`DEFAULT_ROW_LIMIT`, `MAX_CACHED_RESULT_SETS`, `CACHE_TTL_SECONDS`,
`CONNECT_TIMEOUT`, `QUERY_TIMEOUT`, `EXPORT_TIMEOUT`, `SUGGEST_COLUMNS` — the
suggest whitelist existed because `SELECT DISTINCT` cost ~5 s a column; on
SQLite it is instant, so all six filters simply get dropdowns.

Keep `TEXT_FILTERS`, `DATE_FILTERS`, `FILTER_NOTES`, `ORDER_BY_COLUMNS`,
`PINNED_COLUMN`, `COLUMN_GROUPS`, page sizes. Add `SNAPSHOT_PATH` and
`DETECT_COLUMNS`. The `.env` connection settings stay — the extract script uses
them, even though the web app no longer does.

> **`COLUMN_GROUPS` must be revisited when the app reads the snapshot.** Its
> ranges (`DETECTION 50-52`, `DATES 53-54`, `ZIPPER 55-60`) are 1-based ordinals
> into the **view's** column layout, and `src/main.py` slices `columns()` by
> them. The snapshot's `bom` table is the view minus the two detection columns,
> which sit in `bom_detect` — so every group from ordinal 50 onward shifts by
> two and the picker mislabels columns, silently and plausibly. The extract
> therefore records the ordered table layouts by name in `snapshot_meta` as the
> JSON keys `main_columns` and `detect_columns`; rebuild the grouping from those
> names rather than reapplying the view's ordinals.

### `src/main.py`

Endpoint shapes are preserved so the frontend change stays a deletion. `/api/rows`
drops its `limit` parameter; `/api/meta` drops `column_costs`, `default_hidden`,
`row_limits` and gains `snapshot`; `/api/health` reports snapshot age rather than
connection state.

## 7. Frontend changes

Almost entirely deletions:

- The row-limit segmented control and its `ALL` mode — every query is fast now.
- Column-cost badges and warnings.
- `fetched_columns` / `addedColumns` logic in `useSearch` and `format.ts` — the
  distinction between a free column change and an expensive one is gone.
- The column picker opens fully ticked; unticking hides.

Additions: a snapshot-age readout in the `AppBar` (*"data as of 14 Aug 00:41"*),
styled as a warning past 36 hours. Value dropdowns extend to all six filters.

**Payload risk.** With all 60 columns visible, a 100-row page includes both
`nvarchar(max)` columns. At ~2 KB per cell that is ~400 KB of JSON — fine. At
~50 KB per cell it is ~10 MB — not fine. The first extract reports the real
sizes. The row endpoint will therefore support truncating those two columns to
a configurable length, with the full value in CSV export and on expand; it stays
switched off unless the measurement says otherwise.

## 8. Deployment

Two phases. **Phase 1 is a laptop, run by hand**; the shared-server setup below
is deferred until this goes to production.

### 8.1 Phase 1 — local laptop (current)

Single user, no internal link, no scheduled task. The extract is run manually
when fresher data is wanted:

```bash
python scripts/build_snapshot.py          # stop the web app first
uvicorn main:app --port 8000              # 127.0.0.1 is correct here
```

This removes most of §8.2's difficulty rather than deferring it:

- **No scheduled-task identity problem.** Run by hand, the extract authenticates
  as the logged-in user, who already has SELECT on the view. The SYSTEM /
  machine-account trap simply does not arise.
- **No service hosting, no firewall rule, no `--host 0.0.0.0`.** One user on
  localhost. The README's `uvicorn main:app --port 8000` is correct unchanged.
- **The Windows swap lock is manageable by hand.** `swap_in` cannot rename over
  a snapshot the web app holds open, so stop the app before running the extract.
  A laptop user can simply do that; §5.1's service stop/start automation is a
  Phase 2 concern.
- **No unattended-failure problem.** The operator is watching the log. The sanity
  gate, the retained generation and the bootstrap logging all still apply — they
  are simply less load-bearing when someone is present.

Two things that matter *more* on a laptop than on a server:

- **Disk.** During a build `data/` holds live + prev + new simultaneously. If the
  snapshot lands in the multi-GB range, that is three copies on a laptop SSD.
  Check free space before the first full extract, and delete `bom.prev.sqlite`
  if space is tight.
- **Sleep and network.** A laptop suspends and moves between networks. A run
  interrupted by sleep or a dropped VPN fails partway; the sanity gate and the
  `.new` file mean that costs a rerun, not data. Run the extract while plugged
  in and on the corporate network.

### 8.2 Phase 2 — shared internal server (at production)

On the shared machine:

- Python, the ODBC driver, and the repo; `.env` filled in.
- **Scheduled task** running `build_snapshot.py` at 00:00, as an account with
  SELECT on the view. Not SYSTEM — the DB would see the machine account. If no
  suitable domain account exists, set `BOM_DB_USER`/`BOM_DB_PASSWORD` in `.env`
  and use SQL auth, which is identity-independent.
  - **MANDATORY: tick "Stop the task if it runs longer than" on the task's
    Settings tab** and set it to a value comfortably above the measured extract
    time (start at 4 hours until the first run gives a real number). The script
    sets `source.timeout = 0` — no statement timeout, deliberately, because the
    view is slow — so nothing inside the script can end a run that hangs on the
    source connection. Without this setting an unattended build can still be
    running, holding the `.new` file and a source connection, when the next
    night's build starts. Task Scheduler is the *only* wall-clock cap.
- **Web app** as a service or an "At startup" task, `uvicorn main:app --host
  0.0.0.0 --port 8000`, so it survives reboot and logoff and is reachable off the
  host. Today it binds to 127.0.0.1 and dies with the console.
- **Firewall** inbound rule for the port. The app has no authentication; anyone
  on the internal network who finds the port can read it. Acceptable for internal
  read-only BOM data, but a deliberate choice.

## 9. Testing

The Python side currently has no tests; this adds the first, against a small
fixture snapshot rather than the live database:

- Schema generation and the type-mapping table.
- Value coercion (`to_sqlite_value`): one test per source type, including that
  `bytes` stays a BLOB rather than being hexed, and that a stored datetime
  sorts and range-compares under the two correct filter forms in section 4.
- Identifier quoting, including `GCW#` and `Buy Code`.
- Filter/WHERE building, partial-match toggle, date ranges.
- Paging arithmetic and ordering.
- The sanity gate: a short extract must not swap.

Frontend: the five surviving suites (`format`, `client`, `ResultsTable`,
`Combobox`, `FilterPanel`) updated as the props they cover change. The
`addedColumns` test in `format.test.ts` is deleted with the helper.

The extract script's own end-to-end behaviour is verified by the first manual run.

## 10. Risks

| Risk | Handling |
|---|---|
| **Full extract duration unmeasured.** If the view's cost is per-row rather than per-query, the extract cannot complete overnight and the whole plan fails. | Build the script first and run it by hand while watching the throughput log. Kill it early if the projection is absurd. Nothing downstream is built until this passes. |
| Detection columns too large for a 100-row JSON payload | Measured on the first run; truncation flag ready. |
| Snapshot silently stale after a failed build | Age shown in the AppBar; non-zero exit; previous generation retained. |
| Scheduled task runs as the wrong identity | Documented; SQL auth via `.env` as the fallback. |
| A local copy of production data on a workstation | Deliberate, acknowledged: read-only, internal, single view. |
| **No wall-clock cap on an unattended run.** The script sets `source.timeout = 0` on purpose — the view is slow enough that any statement timeout would abort a legitimate build — so a hung source connection at 00:00 has nothing inside the process to end it. It can still be running, holding the `.new` file and a connection, when the next night's build starts. | Task Scheduler's **"Stop the task if it runs longer than"** is the only cap, and section 8 marks it MANDATORY. Set it above the measured extract time. The next run's guarded unlink then reports the held `.new` file and exits non-zero rather than crashing. |
| **Disk space.** During a build `data/` holds three files at once — live, the retained `prev` generation, and the `.new` being written — so peak usage is roughly 3x one snapshot. A sanity-gate rejection or an unreadable-live refusal deliberately leaves the rejected `.new` in place for inspection, so the 3x peak can persist until someone looks. | Size the volume for at least 4x one snapshot; the first manual run gives the real figure (the build logs it). Check `data/` after any non-zero exit — a rejected `.new` is evidence, but it is not cleaned up automatically. |

## 11. Out of scope

Per-column header filters; filtering on columns outside the existing six;
FTS5 global search; incremental refresh; authentication; anything touching the
source view.

---

## 12. Measured — 2026-08-17

Full extract run by hand on the laptop (`--no-swap`). This discharges §10's
gating risk: **the view's cost is fixed per query, not per row.**

| | |
|---|---|
| Fixed query cost (time to first batch) | **100 s** |
| Streaming 365,411 rows | **12 s** @ 31,752 rows/s |
| **Total extract** | **111 s** |
| Snapshot size | **359 MB** |
| Rows | **365,411** (up from the 362,733 quoted throughout — the view has grown) |

The earlier 40-row fetch of all 60 columns took 128.6 s; 365,411 rows took 111 s.
Twenty-five thousand times the rows, no increase — the view materialises fully
before returning row 1. A nightly window is not remotely a constraint; the job
fits in two minutes.

### Query performance against the snapshot

| Query | Live view | Snapshot |
|---|---|---|
| Unfiltered `COUNT(*)` | ~20 s | **7.1 ms** |
| `COUNT(*)` filtered by `STYLE_NBR` | ~5 s | **0.1 ms** |
| `DISTINCT STYLE_SEASON` | ~9.5 s | **19.3 ms** |
| All 60 columns, 100 rows, joined | ~128 s | **1.0 ms** |

### Two design decisions this settles

**No response truncation.** Detection columns average **42 bytes/row**, maximum
**262 bytes** across the entire dataset. A 100-row page carries ~4 KB of
detection text. §7's truncation flag is unnecessary — drop it from Plan 2.

**Collapse `bom_detect` into `bom`.** Those two columns total **15.5 MB of the
359 MB file (4.3%)**, not the ~90% assumed in §4. They are expensive to
*compute* — the view's `FOR XML PATH` aggregation — and cheap to *store*; the
original estimate conflated the two. The side table therefore protects against
nothing. Note this is not a performance decision: the joined 60-column page
measured 1.0 ms, so keeping the split would cost nothing at runtime. It is
collapsed to remove a permanent conditional from Plan 2's query builder
("join only when a detection column is visible") that buys no benefit.

### Consequential for Plan 2

- `config.EXPECTED_ROWS` (362,733) is stale; it affects only the progress ETA.
- The row-limit control has no purpose left. Every query above is sub-20 ms.
- The snapshot gives every row the unique key the view lacks, which fixes the
  non-deterministic unfiltered paging noted in the README.
