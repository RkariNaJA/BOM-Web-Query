"""Read-only data access over the nightly SQLite snapshot.

Every query here runs against a local file built by `scripts/build_snapshot.py`.
Nothing in this module contacts SQL Server; `pyodbc` is not imported.

That removes the reason most of the previous version existed. Gone with it: the
in-process result cache, the per-column cost table, the hidden-by-default
columns, the background warm-up thread, and the 300-second statement timeout.
Measured against the 365,411-row snapshot, an unfiltered COUNT(*) takes 7 ms and
a 100-row page of all 60 columns takes 1 ms, so there is nothing left to hide.

Injection posture is unchanged: column names are whitelisted against the
snapshot's own schema and then double-quoted, and every filter value travels as
a bound parameter.
"""

import sqlite3
import threading
import time

import config

_lock = threading.Lock()
_columns_cache: list[dict] | None = None


# --- Connection ----------------------------------------------------------

def _connect() -> sqlite3.Connection:
    """Open the snapshot read-only.

    A connection per call: SQLite handles this trivially, and FastAPI runs sync
    endpoints in a threadpool where sharing one connection would need locking
    for no benefit.
    """
    path = config.SNAPSHOT_PATH
    if not path.exists():
        raise RuntimeError(
            f"No snapshot at {path}. Build one with "
            f"`python scripts/build_snapshot.py`."
        )
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def quote_ident(name: str) -> str:
    """Double-quote an identifier for SQLite, doubling embedded quotes.

    The view contains names like `GCW#` and `Buy Code`, so this is not optional
    anywhere an identifier is interpolated.
    """
    return '"' + name.replace('"', '""') + '"'


# --- Schema --------------------------------------------------------------

def columns() -> list[dict]:
    """Ordered column metadata for the snapshot, excluding the surrogate key.

    Order comes from the table itself, which the extract created in the source
    view's order. Cached: a snapshot's schema cannot change while it is live.
    """
    global _columns_cache
    with _lock:
        if _columns_cache is not None:
            return _columns_cache

    with _connect() as conn:
        info = conn.execute('PRAGMA table_info("bom")').fetchall()
        # A side table means this snapshot predates the single-table layout, or
        # DETECT_COLUMNS was repopulated. Either way its columns would be
        # silently missing from every response, so refuse rather than serve a
        # partial row.
        side = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bom_detect'"
        ).fetchone()

    if side:
        raise RuntimeError(
            "This snapshot has a bom_detect side table, which this version does "
            "not read. Rebuild it with `python scripts/build_snapshot.py`."
        )
    if not info:
        raise RuntimeError("Snapshot has no `bom` table -- it is not a snapshot.")

    found = [
        {"name": row[1], "type": row[2], "nullable": not row[3]}
        for row in info
        if row[1] != "id"
    ]
    with _lock:
        _columns_cache = found
    return found


def column_names() -> list[str]:
    return [c["name"] for c in columns()]


def default_columns() -> list[str]:
    """Every column. Nothing is expensive enough to hide any more."""
    return column_names()


def resolve_columns(requested: list[str] | None) -> list[str]:
    """Whitelist requested columns against the snapshot, preserving schema order.

    The pinned column is always included. An unrecognised request falls back to
    everything -- which is now also the default, since no column costs anything.
    """
    every = column_names()
    valid = [c for c in (requested or []) if c in set(every)]
    if not valid:
        return every

    wanted = set(valid)
    wanted.add(config.PINNED_COLUMN)
    return [c for c in every if c in wanted]


def snapshot_meta() -> dict:
    """Build provenance recorded by the extract: when, how many rows, from where."""
    with _connect() as conn:
        return {
            k: v for k, v in conn.execute('SELECT "key", "value" FROM "snapshot_meta"')
        }


# --- Filters -------------------------------------------------------------

def _like_escape(value: str) -> str:
    """Escape LIKE wildcards so a literal % or _ in a code does not widen the
    search. Paired with an explicit ESCAPE clause -- SQLite has no default."""
    return (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def _build_where(filters: dict) -> tuple[str, list]:
    """Build a parameterised WHERE clause from the text and date filters.

    filters keys: one per config.TEXT_FILTERS, plus "<col>_from"/"<col>_to" per
    config.DATE_FILTERS, plus "partial": bool. All conditions are ANDed.
    """
    clauses: list[str] = []
    params: list = []
    partial = bool(filters.get("partial"))

    for col in config.TEXT_FILTERS:
        value = (filters.get(col) or "").strip()
        if not value:
            continue
        ident = quote_ident(col)
        if partial:
            clauses.append(f"{ident} LIKE ? ESCAPE '\\'")
            params.append(f"%{_like_escape(value)}%")
        else:
            clauses.append(f"{ident} = ?")
            params.append(value)

    # Per-column filters from the row under the table header. Any column may
    # appear, so each name is whitelisted against the snapshot's own schema
    # before it is quoted -- an unknown name is ignored rather than
    # interpolated. Always a contains-match: these are a scanning aid, and the
    # top filter bar is where exact matching lives.
    #
    # Unindexed columns cost ~220 ms here (one full scan of 365k rows) against
    # ~0.1 ms for the six indexed ones. Stacking them is free: three ANDed
    # filters measured the same ~246 ms as one, since it is a single scan
    # either way.
    known = set(column_names())
    for col, raw in (filters.get("columns") or {}).items():
        value = (raw or "").strip()
        if not value or col not in known:
            continue
        ident = quote_ident(col)
        clauses.append(f"{ident} LIKE ? ESCAPE '\\'")
        params.append(f"%{_like_escape(value)}%")

    for col in config.DATE_FILTERS:
        ident = quote_ident(col)
        start = (filters.get(f"{col}_from") or "").strip()
        end = (filters.get(f"{col}_to") or "").strip()
        if start:
            clauses.append(f"{ident} >= ?")
            params.append(start)
        if end:
            # Datetimes are stored as 'YYYY-MM-DD HH:MM:SS', so a plain <=
            # against a 10-character date would drop everything after midnight
            # on the end date. Compare against the next day instead -- the same
            # correction the SQL Server version made with DATEADD.
            clauses.append(f"{ident} < date(?, '+1 day')")
            params.append(end)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _order_by() -> str:
    """Deterministic ordering for every query.

    The old version sorted only when filtered, because sorting 362k rows in the
    view cost more than the query itself. The snapshot has a surrogate primary
    key, so ordering is free and paging is finally deterministic -- which fixes
    the row-skipping the unfiltered `ORDER BY (SELECT NULL)` path allowed.
    """
    cols = ", ".join(quote_ident(c) for c in config.ORDER_BY_COLUMNS)
    return f'ORDER BY {cols}, "id"'


# --- Value lists ---------------------------------------------------------

def distinct_values(column: str) -> list[str]:
    """Distinct non-empty values for a column, sorted.

    No whitelist of "suggestable" columns any more: SELECT DISTINCT cost ~5 s
    against the view and takes ~19 ms here, so every filter can have one.
    """
    if column not in set(column_names()):
        raise ValueError(f"Unknown column {column!r}.")

    ident = quote_ident(column)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {ident} FROM \"bom\" "
            f"WHERE {ident} IS NOT NULL AND TRIM({ident}) <> '' "
            f"ORDER BY {ident}"
        ).fetchall()
    return [str(r[0]) for r in rows]


def date_bounds(column: str, compute: bool = True) -> dict | None:
    """Earliest and latest day present in a date column, as ISO strings.

    `compute` is accepted for call-site compatibility and ignored -- it existed
    to let /api/meta skip a slow query, and the query is no longer slow.
    """
    if column not in config.DATE_FILTERS:
        raise ValueError(f"Column {column!r} is not a date filter.")

    ident = quote_ident(column)
    with _connect() as conn:
        low, high = conn.execute(
            f"SELECT substr(MIN({ident}), 1, 10), substr(MAX({ident}), 1, 10) "
            f'FROM "bom" WHERE {ident} IS NOT NULL'
        ).fetchone()
    if low is None:
        return None
    return {"min": low, "max": high}


# --- Counting ------------------------------------------------------------

def count_rows(filters: dict, compute: bool = True) -> tuple[int | None, float]:
    """Total matching rows, and how long it took.

    `compute` is accepted and ignored, as with date_bounds: this was the ~20 s
    query the caller used to skip, and it now runs in single-digit milliseconds.
    """
    where, params = _build_where(filters)
    started = time.perf_counter()
    with _connect() as conn:
        total = conn.execute(
            f'SELECT COUNT(*) FROM "bom"{where}', params
        ).fetchone()[0]
    return total, time.perf_counter() - started


# --- Rows ----------------------------------------------------------------

def fetch_page(
    filters: dict,
    page: int,
    page_size: int,
    visible: list[str] | None = None,
) -> dict:
    """One page of results.

    No row cap and no result cache: both existed because a query cost 5-40 s.
    Paging is a plain LIMIT/OFFSET against an ordered, indexed local table.
    """
    page = max(1, int(page))
    page_size = max(config.MIN_PAGE_SIZE, int(page_size))
    shown = resolve_columns(visible)

    total, count_elapsed = count_rows(filters)
    pages = max(1, -(-total // page_size)) if total else 1
    page = min(page, pages)
    offset = (page - 1) * page_size

    select_list = ", ".join(quote_ident(c) for c in shown)
    where, params = _build_where(filters)
    query = (
        f'SELECT {select_list} FROM "bom"{where} {_order_by()} '
        f"LIMIT ? OFFSET ?"
    )

    started = time.perf_counter()
    with _connect() as conn:
        rows = conn.execute(query, [*params, page_size, offset]).fetchall()
    elapsed = time.perf_counter() - started + count_elapsed

    return {
        "columns": shown,
        "all_columns": column_names(),
        # Retained for the frontend's contract. Every column is always
        # available now, so this is simply the full set.
        "fetched_columns": column_names(),
        "rows": [list(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "elapsed": round(elapsed, 3),
        "cached": False,
        "capped": False,
    }


# --- CSV export ----------------------------------------------------------

def iter_csv(filters: dict, visible: list[str] | None = None):
    """Stream the full filtered set as CSV rows.

    Starts with a UTF-8 BOM so Excel on Windows reads the Thai values in
    MASTER_BOM_STATUS / BNR_REMARK correctly instead of mojibake.
    """
    import csv
    import io

    shown = resolve_columns(visible)
    select_list = ", ".join(quote_ident(c) for c in shown)
    where, params = _build_where(filters)
    query = f'SELECT {select_list} FROM "bom"{where} {_order_by()}'

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    def drain() -> str:
        chunk = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return chunk

    yield "﻿"
    writer.writerow(shown)
    yield drain()

    with _connect() as conn:
        cursor = conn.execute(query, params)
        while True:
            batch = cursor.fetchmany(2000)
            if not batch:
                break
            for record in batch:
                writer.writerow(["" if v is None else v for v in record])
            yield drain()


# --- Status --------------------------------------------------------------

def test_connection() -> dict:
    """Snapshot health, in the shape /api/health has always returned.

    `server` now names the snapshot file rather than a SQL Server instance --
    the app no longer has one.
    """
    started = time.perf_counter()
    meta = snapshot_meta()
    with _connect() as conn:
        conn.execute("SELECT 1").fetchone()
    return {
        "connected": True,
        "server": str(config.SNAPSHOT_PATH.name),
        "database": "snapshot",
        "view": meta.get("source_view", "unknown"),
        "built_at": meta.get("finished_at"),
        "row_count": int(meta["row_count"]) if "row_count" in meta else None,
        "elapsed": round(time.perf_counter() - started, 3),
    }
