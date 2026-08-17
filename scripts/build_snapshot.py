"""Nightly extract of the configured source view into a local SQLite snapshot.

Run by Task Scheduler at 00:00. The long extract writes a throwaway file while
the web app keeps serving the previous snapshot; only the final swap is
disruptive, and that takes seconds.

The row source is injected rather than opened here, so every stage below can be
tested without SQL Server.
"""

import os
import sqlite3
import sys
from pathlib import Path

from snapshot_schema import (
    CREATE_META_SQL,
    create_bom_sql,
    create_detect_sql,
    index_sql,
    quote_ident,
    split_columns,
    to_sqlite_value,
)


class SnapshotUnreadableError(Exception):
    """The live snapshot is present on disk but its row count cannot be read.

    Distinct from "there is no live snapshot", which is an ordinary first run.
    Raised by `previous_row_count` so the sanity gate cannot be silently
    disabled by a locked or corrupt file -- see its docstring.
    """


def create_snapshot(
    path: Path, main_columns: list[dict], detect_columns: list[dict]
) -> sqlite3.Connection:
    """Create an empty snapshot file and return an open connection.

    Refuses to open an existing file, so nothing is ever appended to a
    half-built snapshot -- that would leave doubled rows the sanity gate would
    pass. This is a backstop, not the mechanism the scheduled run relies on:
    the driver deletes a leftover .new just before calling this, deleting being
    the right answer since a crashed extract has no resumable state.
    """
    path = Path(path)
    if path.exists():
        raise FileExistsError(
            f"{path} already exists -- delete the leftover before rebuilding."
        )
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    # Safe because the file is worthless until the swap, and much faster: no
    # journal to write and no fsync per transaction.
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute(create_bom_sql(main_columns))
    # No side table when nothing is assigned to one. The split existed to keep
    # bulky columns out of `bom`; measurement across all 365,411 rows showed the
    # detection columns are 4.3% of the file, not the ~90% assumed, so
    # config.DETECT_COLUMNS is now empty and every column lives in `bom`.
    # The parameter stays because the split is one config change away if a
    # genuinely large column ever appears.
    if detect_columns:
        conn.execute(create_detect_sql(detect_columns))
    conn.execute(CREATE_META_SQL)
    return conn


def load_rows(
    conn: sqlite3.Connection,
    n_main: int,
    n_detect: int,
    batches,
    on_progress=None,
) -> int:
    """Insert batches of view rows, splitting each across bom and bom_detect.

    Each row tuple is ordered main-columns-then-detect-columns, matching the
    SELECT the caller built, so the split is a slice at `n_main`.

    Every value passes through `to_sqlite_value` first: pyodbc returns objects
    sqlite3 refuses to bind (Decimal, time, UUID), and the ones it does bind it
    binds through a deprecated adapter that does not produce the ISO text the
    date filters need.

    Returns the number of rows written.
    """
    main_sql = f'INSERT INTO "bom" VALUES ({",".join("?" * (n_main + 1))})'
    detect_sql = f'INSERT INTO "bom_detect" VALUES ({",".join("?" * (n_detect + 1))})'

    row_id = 0
    total = 0
    for batch in batches:
        main_rows = []
        detect_rows = []
        for record in batch:
            row_id += 1
            values = [to_sqlite_value(v) for v in record]
            main_rows.append((row_id, *values[:n_main]))
            # n_detect == 0 means create_snapshot built no side table, so there
            # is nothing to insert into -- see its docstring.
            if n_detect:
                detect_rows.append((row_id, *values[n_main:]))
        conn.executemany(main_sql, main_rows)
        if n_detect:
            conn.executemany(detect_sql, detect_rows)
        total += len(batch)
        if on_progress:
            on_progress(total)
    conn.commit()
    return total


def build_indexes(conn: sqlite3.Connection, column_names: list[str]) -> None:
    """Create the filter indexes. Called after the bulk insert -- maintaining
    them during the insert is several times slower."""
    for statement in index_sql(column_names):
        conn.execute(statement)
    conn.commit()


def measure_detect(
    conn: sqlite3.Connection, detect_columns: list[str]
) -> tuple[int, int]:
    """Average and maximum combined byte size of the detection columns per row.

    CAST to BLOB so LENGTH counts bytes rather than characters -- the data
    contains Thai text, where a character is three bytes, and the point of this
    measurement is to predict JSON payload size.
    """
    if not detect_columns:
        return (0, 0)

    total = " + ".join(
        f"COALESCE(LENGTH(CAST({quote_ident(c)} AS BLOB)), 0)"
        for c in detect_columns
    )
    row = conn.execute(
        f'SELECT AVG({total}), MAX({total}) FROM "bom_detect"'
    ).fetchone()
    if row is None or row[0] is None:
        return (0, 0)
    return (int(row[0]), int(row[1]))


def write_meta(conn: sqlite3.Connection, values: dict) -> None:
    """Upsert build provenance. Values are stored as TEXT."""
    conn.executemany(
        'INSERT INTO "snapshot_meta" ("key", "value") VALUES (?, ?) '
        'ON CONFLICT("key") DO UPDATE SET "value" = excluded."value"',
        [(k, str(v)) for k, v in values.items()],
    )
    conn.commit()


def read_meta(conn: sqlite3.Connection) -> dict:
    return {
        k: v for k, v in conn.execute('SELECT "key", "value" FROM "snapshot_meta"')
    }


def previous_row_count(live_path: Path) -> int | None:
    """Row count recorded in the current live snapshot.

    Returns None only when there is genuinely nothing to compare against: no
    live snapshot on disk, i.e. the first ever run. `sanity_ok` passes on that,
    correctly -- there is no good data at risk.

    Raises SnapshotUnreadableError when the file IS there but its row count
    cannot be read: corrupt, or -- the likely production case -- locked by
    antivirus or another process while the gate runs. Unreadable is NOT absent.
    Folding it into None would disable the sanity gate exactly when it matters,
    letting a truncated extract replace 362,733 good rows and exit 0. A file
    with no usable `row_count` counts the same way: every snapshot this script
    writes records one, so its absence means we cannot vouch for the file.
    """
    live_path = Path(live_path)
    if not live_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
        try:
            value = read_meta(conn).get("row_count")
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SnapshotUnreadableError(f"{live_path}: {exc}") from exc
    if value is None:
        raise SnapshotUnreadableError(
            f"{live_path}: no row_count recorded in snapshot_meta"
        )
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotUnreadableError(
            f"{live_path}: row_count is not an integer ({value!r})"
        ) from exc


def sanity_ok(
    new_count: int, previous_count: int | None, threshold: float = 0.9
) -> bool:
    """Whether a freshly built snapshot may replace the live one.

    An extract that dies partway through still produces a valid SQLite file, so
    without this a truncated dataset would be served all day with nothing
    obviously wrong. An empty extract never passes.
    """
    if new_count <= 0:
        return False
    if previous_count is None:
        return True
    return new_count >= previous_count * threshold


def swap_in(new_path: Path, live_path: Path, prev_path: Path) -> None:
    """Promote the new snapshot, retaining one generation.

    Uses os.link to create a hardlink (not a second rename) so that live_path
    never becomes absent on disk. If the process dies between operations, the
    old snapshot survives via the hardlink, and a bad snapshot is one rename
    away from undone. The final os.replace is atomic within a volume.

    The caller must stop the web app first: Windows refuses to rename over a
    file another process holds open, and the app keeps the snapshot open for reads.
    """
    new_path, live_path, prev_path = Path(new_path), Path(live_path), Path(prev_path)
    if live_path.exists():
        if prev_path.exists():
            prev_path.unlink()
        os.link(live_path, prev_path)
    os.replace(new_path, live_path)


def progress_line(rows: int, elapsed: float, expected_total: int) -> str:
    """A single throughput line for the build log.

    This is what turns the first manual run into the feasibility measurement:
    the rate after a few minutes says whether the full extract takes half an
    hour or is impossible.
    """
    rate = rows / elapsed if elapsed > 0 else 0
    line = f"{rows:,} rows | {elapsed:,.0f}s | {rate:,.0f} rows/s"
    if rate > 0 and expected_total > rows:
        eta_min = (expected_total - rows) / rate / 60
        line += f" | eta {eta_min:,.1f} min"
    return line


def _log(message: str, handle=None) -> None:
    """Write one line to the run log, then echo it to the console.

    File first, and a failing console write cannot abort it: under Task
    Scheduler no console is attached, and a `print` that raises there would
    otherwise take down the one record the log file exists to preserve.
    """
    if handle:
        handle.write(message + "\n")
        handle.flush()
    try:
        print(message, flush=True)
    except Exception:
        pass


def _extract_batches(cursor, batch_size: int):
    """Yield row batches from an open pyodbc cursor until it is exhausted."""
    while True:
        batch = cursor.fetchmany(batch_size)
        if not batch:
            return
        yield batch


def _source_query(
    schema: str, view: str, columns: list[dict], limit: int | None
) -> str:
    """The extract SELECT.

    Note this is SQL Server syntax -- [brackets] -- not the "double quotes"
    snapshot_schema.quote_ident produces for SQLite. The two quoting styles are
    easy to confuse, which is why this is a named function rather than inline.

    Column order is the caller's: main columns then detection columns, matching
    the boundary load_rows slices each row tuple on.
    """
    select_list = ", ".join(
        "[" + c["name"].replace("]", "]]") + "]" for c in columns
    )
    top = f"TOP ({int(limit)}) " if limit is not None else ""
    return f"SELECT {top}{select_list} FROM [{schema}].[{view}]"


def main(argv: list[str] | None = None) -> int:
    # argparse, time, datetime, config and pyodbc are imported here rather than
    # at module level because tests/test_build_snapshot.py imports this module
    # on a machine with no ODBC driver and no reachable SQL Server. A
    # module-level `import pyodbc` or `import config` (which requires a valid
    # .env) would break the entire test suite at collection time -- not one
    # test, all of them, because collection would fail on the import. Keep
    # these imports local to main() -- do not "tidy" them to the top.
    import argparse
    import json
    import time
    import traceback
    from datetime import datetime

    # Bootstrap. Until the log file is open there is no durable place to report
    # a failure -- Task Scheduler discards stderr, so a traceback here left
    # scripts/logs/ with nothing at all, not even a "started" line, and the only
    # symptom was a snapshot that quietly stopped being rebuilt. So: open the
    # log as early as anything environment-dependent can fail, and until it is
    # open, append failures to a fallback file beside the log directory as well
    # as printing them.
    stamp = datetime.now()
    script_dir = Path(__file__).resolve().parent
    log_dir = script_dir / "logs"
    fallback_path = script_dir / "snapshot-bootstrap-failures.log"

    def _bootstrap_failed(what: str, exc: BaseException) -> int:
        message = (
            f"{stamp:%Y-%m-%d %H:%M:%S} FAILED during startup ({what}): "
            f"{type(exc).__name__}: {exc}"
        )
        try:
            print(message, file=sys.stderr, flush=True)
        except Exception:
            pass
        try:
            with open(fallback_path, "a", encoding="utf-8") as fallback:
                fallback.write(message + "\n")
                fallback.write(traceback.format_exc())
                fallback.write("\n")
        except Exception:
            # Nowhere left to write. The non-zero return is the last signal.
            pass
        return 1

    def _positive_int(value: str) -> int:
        """argparse type for --limit: rejects 0 and negative values.

        0 is falsy, so a bare truthiness check on args.limit would silently
        treat `--limit 0` as "no limit" -- running (and, without --no-swap,
        swapping in) the full multi-hour production extract. Reject it here
        instead of relying on truthiness anywhere downstream.
        """
        n = int(value)
        if n <= 0:
            raise argparse.ArgumentTypeError(
                f"--limit must be a positive integer, got {value}"
            )
        return n

    def _positive_number(value: str) -> float:
        """argparse type for --max-age-hours. Fractions are allowed (0.5 = 30
        minutes); 0 is rejected for the same reason as --limit, since it would
        mean "never fresh enough" while reading as "no threshold"."""
        n = float(value)
        if n <= 0:
            raise argparse.ArgumentTypeError(
                f"--max-age-hours must be greater than 0, got {value}"
            )
        return n

    # Arguments are parsed before the log is opened, and the parser touches no
    # configuration to do it -- `--out` defaults to None here and is resolved
    # against config inside _run. That keeps `--help` from creating an empty
    # run log on every invocation, and it cannot itself fail for an
    # environment reason. A genuinely bad command line (a scheduled task with
    # a typo) still reaches the fallback file below.
    parser = argparse.ArgumentParser(description="Build the BOM SQLite snapshot.")
    parser.add_argument("--limit", type=_positive_int, default=None,
                        help="extract only the first N rows (for timed trials)")
    parser.add_argument("--no-swap", action="store_true",
                        help="build the file but leave the live snapshot alone")
    parser.add_argument(
        "--max-age-hours", type=_positive_number, default=None,
        help="skip the rebuild if the live snapshot is younger than this "
             "(for a scheduled task that may fire several times a day)")
    parser.add_argument("--out", type=Path, default=None,
                        help="where to build (default: the configured .new path)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            _bootstrap_failed("parsing arguments", exc)
        raise  # --help and --version exit 0; nothing to record

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"snapshot-{stamp:%Y%m%d-%H%M%S}.log"
        log_handle = open(log_path, "w", encoding="utf-8")
    except Exception as exc:
        return _bootstrap_failed("creating the log directory or file", exc)

    with log_handle as log:
        try:
            return _run(args, log, stamp, script_dir, json, time, datetime)
        except Exception as exc:
            # The last net. _run guards each stage individually; anything that
            # slips between them still gets a FAILED line and a traceback in
            # the log rather than escaping to a stderr nobody reads.
            _log(f"FAILED: unhandled {type(exc).__name__}: {exc}", log)
            try:
                log.write(traceback.format_exc())
                log.flush()
            except Exception:
                pass
            return 1


def _snapshot_age_hours(live_path: Path, datetime) -> float | None:
    """Hours since the live snapshot finished building, or None if unknown.

    None means "cannot vouch for the age" -- no file, no `finished_at`, or an
    unparseable one -- and the caller rebuilds rather than skipping. Erring
    towards a rebuild is the safe direction: the cost is two minutes, whereas
    wrongly skipping serves stale data indefinitely.
    """
    live_path = Path(live_path)
    if not live_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
        try:
            built = read_meta(conn).get("finished_at")
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not built:
        return None
    try:
        delta = datetime.now() - datetime.fromisoformat(built)
    except (TypeError, ValueError):
        return None
    return delta.total_seconds() / 3600


def _run(args, log, stamp, script_dir, json, time, datetime) -> int:
    """The build itself, with the log file already open.

    Split out of main() only so main() can stay a thin bootstrap whose every
    line sits inside a handler with somewhere durable to report to. The
    module-level import ban still applies: config and pyodbc are imported
    below, inside the function, never at module scope.
    """
    started = time.perf_counter()
    _log(f"started {stamp:%Y-%m-%d %H:%M:%S}", log)

    # The two most likely production faults: a missing or incomplete .env
    # (config raises RuntimeError) and an ODBC driver removed by an upgrade.
    try:
        sys.path.insert(0, str(script_dir.parent / "src"))
        import config
        import pyodbc
    except Exception as exc:
        _log(f"FAILED during startup: cannot import config or pyodbc: "
             f"{type(exc).__name__}: {exc}", log)
        return 1

    if args.out is None:
        args.out = config.SNAPSHOT_NEW_PATH

    # Freshness gate, deliberately before the connection: a logon-triggered
    # task fires whenever the machine wakes, and re-extracting an hour-old
    # snapshot costs two minutes and a heavy query against a production view
    # for nothing. Exit 0 -- "already fresh" is success, not failure.
    if args.max_age_hours is not None:
        age = _snapshot_age_hours(config.SNAPSHOT_PATH, datetime)
        if age is None:
            _log("no readable snapshot age; rebuilding", log)
        elif age < args.max_age_hours:
            _log(f"snapshot is {age:.1f} h old, under the "
                 f"{args.max_age_hours:g} h threshold -- nothing to do", log)
            return 0
        else:
            _log(f"snapshot is {age:.1f} h old, at or over the "
                 f"{args.max_age_hours:g} h threshold -- rebuilding", log)

    try:
        config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _log(f"FAILED during startup: cannot create {config.SNAPSHOT_DIR}: "
             f"{type(exc).__name__}: {exc}", log)
        return 1

    # Reserved paths --out must never be: the live snapshot (swap_in would
    # be replacing it with itself) and the retained-generation file (a run
    # aimed there would have swap_in unlink the extract just built as the
    # "outgoing" snapshot, hardlink the OLD live file into its place, and
    # replace live with that -- destroying the night's work while main()
    # still returns 0, the worst failure shape in this script: silent and
    # successful-looking). .resolve() is not what makes this case-insensitive
    # -- WindowsPath comparison and hashing are case-folded regardless. It is
    # here to normalise a path's spelling: relative segments, "..", and
    # links, so `--out data\bom.sqlite` equals the configured absolute path.
    reserved = {
        config.SNAPSHOT_PATH.resolve(): config.SNAPSHOT_PATH,
        config.SNAPSHOT_PREV_PATH.resolve(): config.SNAPSHOT_PREV_PATH,
    }
    out_resolved = args.out.resolve()
    if out_resolved in reserved:
        _log(f"FAILED: --out must not be the reserved path "
             f"{reserved[out_resolved]}", log)
        return 1

    # A leftover .new is deleted, not resumed. The unlink can legitimately
    # fail though: Windows refuses to delete a file another process holds open,
    # and a human whose manual --limit trial is still streaming at 00:00 holds
    # exactly this file. Unguarded, that PermissionError escaped as a traceback
    # and the night's log held one line, "started", with no FAILED marker.
    if args.out.exists():
        try:
            args.out.unlink()
        except OSError as exc:
            _log(f"FAILED: cannot remove the leftover {args.out}: "
                 f"{type(exc).__name__}: {exc}", log)
            _log("  -> another build may still hold it open (a manual --limit "
                 "trial, or a run that has not exited). Nothing was changed; "
                 "the live snapshot is untouched.", log)
            return 1

    try:
        source = pyodbc.connect(
            config.CONNECTION_STRING, timeout=config.CONNECT_TIMEOUT
        )
    except Exception as exc:
        _log(f"FAILED: cannot connect: {exc}", log)
        return 1
    source.timeout = 0  # no statement timeout; this query runs for a long time

    try:
        cur = source.cursor()
        meta_rows = cur.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            config.SCHEMA, config.VIEW,
        ).fetchall()
        columns = [
            {"name": r[0], "type": r[1], "nullable": r[2] == "YES"}
            for r in meta_rows
        ]
        if not columns:
            _log(f"FAILED: {config.SCHEMA}.{config.VIEW} not found", log)
            return 1

        main_cols, detect_cols = split_columns(columns, config.DETECT_COLUMNS)
        _log(f"{len(columns)} columns: {len(main_cols)} main, "
             f"{len(detect_cols)} detection", log)

        conn = create_snapshot(args.out, main_cols, detect_cols)

        query = _source_query(
            config.SCHEMA, config.VIEW, main_cols + detect_cols, args.limit
        )

        _log("querying source (first batch may take minutes)...", log)
        cur.execute(query)

        # The SELECT above pays a large, fixed cost on this slow view before
        # the first row is available (measured minutes, not seconds). Timing
        # rows-per-second from `started` would fold that fixed cost into the
        # rate and understate it, worst right when the number is first read.
        # `stream_started` isolates the marginal per-row cost from it.
        stream_started = time.perf_counter()
        fixed_cost = stream_started - started
        _log(f"first batch after {fixed_cost:,.0f}s (fixed query cost)", log)

        expected = args.limit if args.limit is not None else config.EXPECTED_ROWS
        last_report = [0.0]

        def report(rows: int) -> None:
            elapsed = time.perf_counter() - stream_started
            if elapsed - last_report[0] >= 30 or rows == expected:
                _log(progress_line(rows, elapsed, expected), log)
                last_report[0] = elapsed

        written = load_rows(
            conn, len(main_cols), len(detect_cols),
            _extract_batches(cur, config.EXTRACT_BATCH_SIZE),
            on_progress=report,
        )
        finished_extract = time.perf_counter()
        extract_seconds = finished_extract - started
        stream_seconds = finished_extract - stream_started
        stream_rate = written / stream_seconds if stream_seconds > 0 else 0
        _log(f"extract finished: {written:,} rows in {extract_seconds:,.0f}s "
             f"total ({stream_seconds:,.0f}s streaming, "
             f"{stream_rate:,.0f} rows/s)", log)
    except Exception as exc:
        _log(f"FAILED during extract: {exc}", log)
        return 1
    finally:
        source.close()

    # Everything below runs after the source cursor is done with, so a
    # failure here (an index on a vanished column, a bad write_meta value,
    # or -- the concrete case that motivated this -- os.replace() raising
    # PermissionError in swap_in because Task Scheduler didn't stop the web
    # app first) used to raise past main() as a bare traceback: discarded
    # by Task Scheduler, with the log file's last line still reading
    # "building indexes..." as if nothing had gone wrong. Guard it all, and
    # make sure conn is closed on the failure path too.
    try:
        _log("building indexes...", log)
        main_col_names = {c["name"] for c in main_cols}
        requested_filters = config.TEXT_FILTERS + config.DATE_FILTERS
        index_columns = [c for c in requested_filters if c in main_col_names]
        missing_filters = [c for c in requested_filters if c not in main_col_names]
        if missing_filters:
            _log(f"skipping filter index(es) for column(s) not in this "
                 f"extract: {', '.join(missing_filters)}", log)
        build_indexes(conn, index_columns)

        # Use the detection columns actually created in bom_detect, not the
        # configured list -- split_columns silently drops a name the view no
        # longer has, and querying for a column that was never created
        # raises sqlite3.OperationalError.
        detect_names = [c["name"] for c in detect_cols]
        avg_bytes, max_bytes = measure_detect(conn, detect_names)
        _log(f"detection columns: avg {avg_bytes:,} bytes/row, "
             f"max {max_bytes:,} bytes", log)
        _log(f"  -> a 100-row page carries ~{avg_bytes * 100 / 1_000_000:,.1f} MB",
             log)

        # main_columns / detect_columns record the snapshot's layout by NAME.
        # config.COLUMN_GROUPS addresses the picker's groups as 1-based
        # ordinals into the *view's* layout, and `bom` is the view minus the
        # two detection columns -- so every group from DETECTION onward is
        # shifted by two here. The app must rebuild its grouping from these
        # names, not the view's ordinals, or it mislabels columns silently.
        write_meta(conn, {
            "started_at": stamp.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": int(time.perf_counter() - started),
            "row_count": written,
            "source_view": f"{config.SCHEMA}.{config.VIEW}",
            "detect_avg_bytes": avg_bytes,
            "detect_max_bytes": max_bytes,
            "main_columns": json.dumps(
                [c["name"] for c in main_cols], ensure_ascii=False
            ),
            "detect_columns": json.dumps(
                [c["name"] for c in detect_cols], ensure_ascii=False
            ),
        })
        conn.close()

        size_mb = args.out.stat().st_size / 1_000_000
        _log(f"snapshot written: {args.out} ({size_mb:,.0f} MB)", log)

        if args.no_swap or args.limit is not None:
            _log("swap skipped", log)
            return 0

        try:
            previous = previous_row_count(config.SNAPSHOT_PATH)
        except SnapshotUnreadableError as exc:
            # Present but unreadable is not absent: treating it as absent would
            # pass the gate on any non-empty extract and overwrite a snapshot
            # we could not verify.
            _log(f"FAILED: the live snapshot exists but cannot be read: {exc}", log)
            _log("  -> refusing to swap; it may be locked by antivirus or "
                 f"another process. The new snapshot is kept at {args.out}.", log)
            return 2
        if not sanity_ok(written, previous, config.SANITY_THRESHOLD):
            previous_display = f"{previous:,}" if previous is not None else "none"
            _log(f"FAILED sanity gate: {written:,} rows vs previous "
                 f"{previous_display} -- not swapping", log)
            return 2

        swap_in(args.out, config.SNAPSHOT_PATH, config.SNAPSHOT_PREV_PATH)
        _log(f"swapped in. total {time.perf_counter() - started:,.0f}s", log)
        return 0
    except Exception as exc:
        _log(f"FAILED after extract: {exc}", log)
        return 1
    finally:
        # A failure here would escape as the exact bare, undiscoverable
        # traceback Finding 1 exists to prevent, discarding whatever
        # return code is already in flight -- swallow it rather than let
        # a close-time error undo the reporting above. conn is already
        # closed on the success path, so this is normally a harmless
        # second call.
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
