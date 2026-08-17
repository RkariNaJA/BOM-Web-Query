# Snapshot Pipeline Implementation Plan (Plan 1 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a nightly job that extracts all 362,733 rows × 60 columns of `the source view` into a local SQLite file, and prove by a real timed run that it can finish overnight.

**Architecture:** Two modules under `scripts/`. `snapshot_schema.py` holds pure functions — SQL Server → SQLite type mapping, identifier quoting, DDL generation — with no I/O, so it is entirely unit-testable. `build_snapshot.py` performs the job: one streaming `SELECT` consumed in batches, loaded into a throwaway `bom.new.sqlite`, indexed, measured, sanity-gated, then swapped into place. The row source is injected as an iterable of batches, so every stage is testable without touching SQL Server.

**Tech Stack:** Python 3.10+ (3.13.2 in use), `sqlite3` and `pathlib` from the stdlib, `pyodbc` for the source connection, `pytest` for tests. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-08-14-sqlite-snapshot-design.md`

## Global Constraints

- Python 3.10+; no runtime dependency beyond `fastapi`, `uvicorn[standard]`, `pyodbc`. `sqlite3` is stdlib.
- Keep files under 500 lines.
- Tests live in `/tests`, scripts in `/scripts`. Never write working files to the repo root.
- Connection settings come from `.env` via `src/config.py` — never hardcode server, database, or credentials.
- SQLite identifiers use `"double quotes"` with embedded quotes doubled. The view contains names like `GCW#` and `Buy Code`.
- Dates are stored as ISO `YYYY-MM-DD` TEXT so lexicographic range comparison works.
- The two `nvarchar(max)` columns — `TEXT_USE_OF_DETECT` and `TEXT_Color_Code_OF_DETECT` — live in `bom_detect`, never in `bom`. `TEXT_Color_Name_OF_DETECT` stays in `bom`.
- Sanity threshold: a new snapshot with fewer than **90%** of the previous row count must not be swapped in.
- The snapshot file and any `.new`/`.prev` siblings must never be committed.

---

### Task 0: Initialise version control

This project has no git repository. You are about to rewrite the data layer of a
working application, and today the only undo is a manual file copy. Every later
task ends in a commit, so this comes first.

**Files:**
- Modify: `.gitignore` (add the snapshot data directory)

- [ ] **Step 1: Confirm there is no repository yet**

Run: `git rev-parse --is-inside-work-tree`
Expected: fatal error, "not a git repository". If it prints `true`, skip to Step 3.

- [ ] **Step 2: Initialise**

```bash
git init
git branch -M main
```

- [ ] **Step 3: Add the snapshot data directory to .gitignore**

Append to `.gitignore`:

```gitignore
# Snapshot database — rebuilt nightly, can reach several GB
data/
*.sqlite
*.sqlite-journal
```

- [ ] **Step 4: Verify .env is ignored before the first commit**

Run: `git status --porcelain | grep -E "^\?\? \.env$"`
Expected: no output. `.env` holds the connection settings and must not be tracked.
If it appears, stop and fix `.gitignore` before committing.

- [ ] **Step 5: Commit the existing tree**

```bash
git add -A
git commit -m "chore: initial commit of BOM Query Web"
```

---

### Task 1: Type mapping and identifier quoting

**Files:**
- Create: `scripts/snapshot_schema.py`
- Create: `tests/test_snapshot_schema.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: `sqlite_type(sql_server_type: str) -> str`, `quote_ident(name: str) -> str`.

- [ ] **Step 1: Add the test dependency**

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest
```

Run: `pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_snapshot_schema.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from snapshot_schema import quote_ident, sqlite_type


class TestSqliteType:
    def test_integer_families_map_to_integer(self):
        for source in ("int", "bigint", "smallint", "tinyint", "bit"):
            assert sqlite_type(source) == "INTEGER"

    def test_decimal_families_map_to_real(self):
        for source in ("decimal", "numeric", "float", "real", "money", "smallmoney"):
            assert sqlite_type(source) == "REAL"

    def test_dates_map_to_text_for_iso_storage(self):
        # ISO 'YYYY-MM-DD' text compares correctly with < and >, which is what
        # the BOM_UPDATE_DT range filter needs.
        for source in ("date", "datetime", "datetime2", "smalldatetime"):
            assert sqlite_type(source) == "TEXT"

    def test_strings_map_to_text(self):
        for source in ("varchar", "nvarchar", "char", "nchar", "text"):
            assert sqlite_type(source) == "TEXT"

    def test_unknown_type_falls_back_to_text(self):
        assert sqlite_type("geography") == "TEXT"

    def test_matching_is_case_insensitive(self):
        assert sqlite_type("BigInt") == "INTEGER"


class TestQuoteIdent:
    def test_wraps_in_double_quotes(self):
        assert quote_ident("STYLE_NBR") == '"STYLE_NBR"'

    def test_handles_a_space(self):
        # The view really contains this column.
        assert quote_ident("Buy Code") == '"Buy Code"'

    def test_handles_a_hash(self):
        assert quote_ident("GCW#") == '"GCW#"'

    def test_doubles_an_embedded_double_quote(self):
        assert quote_ident('od"d') == '"od""d"'
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_snapshot_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'snapshot_schema'`

- [ ] **Step 4: Write the implementation**

Create `scripts/snapshot_schema.py`:

```python
"""Pure schema helpers for the nightly snapshot build.

No I/O and no database handles: everything here is a function of its arguments,
so the whole module is unit-testable without SQL Server or a SQLite file.
"""

# Anything not listed becomes TEXT. Dates are deliberately TEXT: stored as ISO
# 'YYYY-MM-DD' they compare correctly with < and >, which is what the
# BOM_UPDATE_DT range filter needs, and SQLite has no date type anyway.
_TYPE_MAP = {
    "int": "INTEGER",
    "bigint": "INTEGER",
    "smallint": "INTEGER",
    "tinyint": "INTEGER",
    "bit": "INTEGER",
    "decimal": "REAL",
    "numeric": "REAL",
    "float": "REAL",
    "real": "REAL",
    "money": "REAL",
    "smallmoney": "REAL",
}


def sqlite_type(sql_server_type: str) -> str:
    """Map an INFORMATION_SCHEMA DATA_TYPE to a SQLite column type.

    BOM_ROW_NBR is the pinned sort column; as TEXT it would sort "10" before
    "9", so the integer families genuinely matter.
    """
    return _TYPE_MAP.get(sql_server_type.strip().lower(), "TEXT")


def quote_ident(name: str) -> str:
    """Double-quote an identifier for SQLite, doubling embedded quotes.

    The view contains names like `GCW#` and `Buy Code`, so quoting is not
    optional anywhere an identifier is interpolated.
    """
    return '"' + name.replace('"', '""') + '"'
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_snapshot_schema.py -v`
Expected: PASS, 10 tests

- [ ] **Step 6: Commit**

```bash
git add scripts/snapshot_schema.py tests/test_snapshot_schema.py requirements-dev.txt
git commit -m "feat: type mapping and identifier quoting for the snapshot schema"
```

---

### Task 2: DDL generation

**Files:**
- Modify: `scripts/snapshot_schema.py`
- Modify: `tests/test_snapshot_schema.py`

**Interfaces:**
- Consumes: `sqlite_type`, `quote_ident` from Task 1.
- Produces:
  - `split_columns(columns: list[dict], detect_names: list[str]) -> tuple[list[dict], list[dict]]`
  - `create_bom_sql(main_columns: list[dict]) -> str`
  - `create_detect_sql(detect_columns: list[dict]) -> str`
  - `CREATE_META_SQL: str`
  - `index_sql(column_names: list[str]) -> list[str]`

  A column dict is `{"name": str, "type": str, "nullable": bool}` — exactly what
  `src/db.py:65`'s `columns()` already returns from INFORMATION_SCHEMA.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_snapshot_schema.py`:

```python
from snapshot_schema import (
    CREATE_META_SQL,
    create_bom_sql,
    create_detect_sql,
    index_sql,
    split_columns,
)

DETECT = ["TEXT_USE_OF_DETECT", "TEXT_Color_Code_OF_DETECT"]

SAMPLE = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "Buy Code", "type": "nvarchar", "nullable": True},
    {"name": "TEXT_USE_OF_DETECT", "type": "nvarchar", "nullable": True},
    {"name": "BOM_UPDATE_DT", "type": "datetime", "nullable": True},
    {"name": "TEXT_Color_Code_OF_DETECT", "type": "nvarchar", "nullable": True},
]


class TestSplitColumns:
    def test_detect_columns_are_separated_out(self):
        main, detect = split_columns(SAMPLE, DETECT)
        assert [c["name"] for c in detect] == DETECT
        assert "TEXT_USE_OF_DETECT" not in [c["name"] for c in main]

    def test_main_keeps_view_ordering(self):
        main, _ = split_columns(SAMPLE, DETECT)
        assert [c["name"] for c in main] == [
            "STYLE_NBR", "BOM_ROW_NBR", "Buy Code", "BOM_UPDATE_DT",
        ]

    def test_detect_follows_the_requested_order_not_the_view_order(self):
        # The SELECT is built as main + detect, and load_rows slices the row
        # tuple on that boundary, so this ordering is load-bearing.
        _, detect = split_columns(SAMPLE, DETECT)
        assert [c["name"] for c in detect] == DETECT

    def test_missing_detect_column_is_ignored_not_fatal(self):
        # If the view drops a detection column, the build should still run.
        main, detect = split_columns(SAMPLE, DETECT + ["NOT_IN_VIEW"])
        assert [c["name"] for c in detect] == DETECT
        assert len(main) == 4


class TestCreateSql:
    def test_bom_table_has_surrogate_key_first(self):
        main, _ = split_columns(SAMPLE, DETECT)
        sql = create_bom_sql(main)
        assert sql.startswith('CREATE TABLE "bom" (\n  "id" INTEGER PRIMARY KEY')

    def test_bom_table_applies_type_mapping(self):
        main, _ = split_columns(SAMPLE, DETECT)
        sql = create_bom_sql(main)
        assert '"BOM_ROW_NBR" INTEGER' in sql
        assert '"STYLE_NBR" TEXT' in sql
        assert '"BOM_UPDATE_DT" TEXT' in sql

    def test_bom_table_quotes_awkward_names(self):
        main, _ = split_columns(SAMPLE, DETECT)
        assert '"Buy Code" TEXT' in create_bom_sql(main)

    def test_detect_table_references_bom(self):
        _, detect = split_columns(SAMPLE, DETECT)
        sql = create_detect_sql(detect)
        assert '"id" INTEGER PRIMARY KEY REFERENCES "bom"("id")' in sql
        assert '"TEXT_USE_OF_DETECT" TEXT' in sql

    def test_meta_table_is_key_value(self):
        assert '"key" TEXT PRIMARY KEY' in CREATE_META_SQL
        assert '"value" TEXT' in CREATE_META_SQL


class TestIndexSql:
    def test_one_statement_per_column(self):
        statements = index_sql(["STYLE_NBR", "Buy Code"])
        assert len(statements) == 2

    def test_index_names_are_safe_for_awkward_columns(self):
        # "Buy Code" cannot appear raw in an index name.
        statements = index_sql(["Buy Code"])
        assert statements[0].startswith('CREATE INDEX "ix_bom_Buy_Code"')
        assert 'ON "bom"("Buy Code")' in statements[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_snapshot_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'split_columns'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/snapshot_schema.py`:

```python
import re

CREATE_META_SQL = (
    'CREATE TABLE "snapshot_meta" (\n'
    '  "key" TEXT PRIMARY KEY,\n'
    '  "value" TEXT\n'
    ")"
)


def split_columns(
    columns: list[dict], detect_names: list[str]
) -> tuple[list[dict], list[dict]]:
    """Partition view columns into the main table and the detection side table.

    `main` keeps the view's own ordering. `detect` follows the order of
    `detect_names`, because the extract SELECT is built as main + detect and
    `load_rows` slices each row tuple on that boundary.

    A name in `detect_names` that the view does not contain is ignored rather
    than raising: a column disappearing upstream should not stop the build.
    """
    by_name = {c["name"]: c for c in columns}
    detect = [by_name[n] for n in detect_names if n in by_name]
    wanted = {c["name"] for c in detect}
    main = [c for c in columns if c["name"] not in wanted]
    return main, detect


def _column_defs(columns: list[dict]) -> str:
    return ",\n".join(
        f'  {quote_ident(c["name"])} {sqlite_type(c["type"])}' for c in columns
    )


def create_bom_sql(main_columns: list[dict]) -> str:
    """DDL for the main table. `id` is a surrogate key -- the view has none,
    which is also why paging it in SQL Server needed ORDER BY (SELECT NULL)."""
    return (
        'CREATE TABLE "bom" (\n'
        '  "id" INTEGER PRIMARY KEY,\n'
        f"{_column_defs(main_columns)}\n"
        ")"
    )


def create_detect_sql(detect_columns: list[dict]) -> str:
    """DDL for the nvarchar(max) side table, keyed 1:1 to bom.id."""
    return (
        'CREATE TABLE "bom_detect" (\n'
        '  "id" INTEGER PRIMARY KEY REFERENCES "bom"("id"),\n'
        f"{_column_defs(detect_columns)}\n"
        ")"
    )


def index_sql(column_names: list[str]) -> list[str]:
    """One index per filterable column, built after the bulk insert.

    Index names strip anything that is not alphanumeric or underscore, so
    `Buy Code` yields ix_bom_Buy_Code.
    """
    statements = []
    for name in column_names:
        safe = re.sub(r"\W", "_", name)
        statements.append(
            f'CREATE INDEX "ix_bom_{safe}" ON "bom"({quote_ident(name)})'
        )
    return statements
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_snapshot_schema.py -v`
Expected: PASS, 21 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/snapshot_schema.py tests/test_snapshot_schema.py
git commit -m "feat: generate snapshot DDL from view column metadata"
```

---

### Task 3: Load rows into SQLite

**Files:**
- Create: `scripts/build_snapshot.py`
- Create: `tests/test_build_snapshot.py`

**Interfaces:**
- Consumes: `create_bom_sql`, `create_detect_sql`, `CREATE_META_SQL` from Task 2.
- Produces:
  - `create_snapshot(path: Path, main_columns: list[dict], detect_columns: list[dict]) -> sqlite3.Connection`
  - `load_rows(conn, n_main: int, n_detect: int, batches, on_progress=None) -> int`

  `batches` is any iterable of lists of row tuples. Each row tuple is ordered
  main-columns-then-detect-columns. Injecting it this way is what makes the
  loader testable without SQL Server.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_snapshot.py`:

```python
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_snapshot import create_snapshot, load_rows
from snapshot_schema import split_columns

DETECT = ["TEXT_USE_OF_DETECT", "TEXT_Color_Code_OF_DETECT"]

COLUMNS = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "TEXT_USE_OF_DETECT", "type": "nvarchar", "nullable": True},
    {"name": "TEXT_Color_Code_OF_DETECT", "type": "nvarchar", "nullable": True},
]


def build(tmp_path, batches):
    """Create a snapshot at a temp path and load the given batches into it."""
    main, detect = split_columns(COLUMNS, DETECT)
    conn = create_snapshot(tmp_path / "t.sqlite", main, detect)
    written = load_rows(conn, len(main), len(detect), batches)
    return conn, written


class TestCreateSnapshot:
    def test_creates_all_three_tables(self, tmp_path):
        conn, _ = build(tmp_path, [])
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"bom", "bom_detect", "snapshot_meta"} <= names

    def test_fails_if_the_target_already_exists(self, tmp_path):
        main, detect = split_columns(COLUMNS, DETECT)
        (tmp_path / "t.sqlite").write_text("stale")
        try:
            create_snapshot(tmp_path / "t.sqlite", main, detect)
        except FileExistsError:
            return
        raise AssertionError("expected FileExistsError on a leftover file")


class TestLoadRows:
    def test_returns_the_number_of_rows_written(self, tmp_path):
        _, written = build(tmp_path, [[("S1", 1, "use", "code")]])
        assert written == 1

    def test_splits_each_row_across_the_two_tables(self, tmp_path):
        conn, _ = build(tmp_path, [[("S1", 1, "use", "code")]])
        assert conn.execute(
            'SELECT "STYLE_NBR", "BOM_ROW_NBR" FROM "bom"'
        ).fetchone() == ("S1", 1)
        assert conn.execute(
            'SELECT "TEXT_USE_OF_DETECT", "TEXT_Color_Code_OF_DETECT" '
            'FROM "bom_detect"'
        ).fetchone() == ("use", "code")

    def test_ids_align_across_the_two_tables(self, tmp_path):
        conn, _ = build(tmp_path, [
            [("S1", 1, "u1", "c1"), ("S2", 2, "u2", "c2")],
            [("S3", 3, "u3", "c3")],
        ])
        joined = conn.execute(
            'SELECT b."STYLE_NBR", d."TEXT_USE_OF_DETECT" '
            'FROM "bom" b JOIN "bom_detect" d ON d."id" = b."id" '
            'ORDER BY b."id"'
        ).fetchall()
        assert joined == [("S1", "u1"), ("S2", "u2"), ("S3", "u3")]

    def test_ids_continue_across_batches(self, tmp_path):
        conn, _ = build(tmp_path, [[("S1", 1, "u", "c")], [("S2", 2, "u", "c")]])
        assert [r[0] for r in conn.execute('SELECT "id" FROM "bom" ORDER BY "id"')] == [1, 2]

    def test_nulls_survive(self, tmp_path):
        conn, _ = build(tmp_path, [[("S1", 1, None, None)]])
        assert conn.execute(
            'SELECT "TEXT_USE_OF_DETECT" FROM "bom_detect"'
        ).fetchone()[0] is None

    def test_progress_callback_reports_the_running_total(self, tmp_path):
        seen = []
        main, detect = split_columns(COLUMNS, DETECT)
        conn = create_snapshot(tmp_path / "t.sqlite", main, detect)
        load_rows(
            conn, len(main), len(detect),
            [[("S1", 1, "u", "c")], [("S2", 2, "u", "c")]],
            on_progress=seen.append,
        )
        assert seen == [1, 2]

    def test_no_batches_writes_nothing(self, tmp_path):
        conn, written = build(tmp_path, [])
        assert written == 0
        assert conn.execute('SELECT COUNT(*) FROM "bom"').fetchone()[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_snapshot'`

- [ ] **Step 3: Write the implementation**

Create `scripts/build_snapshot.py`:

```python
"""Nightly extract of the source view into a local SQLite snapshot.

Run by Task Scheduler at 00:00. The long extract writes a throwaway file while
the web app keeps serving the previous snapshot; only the final swap is
disruptive, and that takes seconds.

The row source is injected rather than opened here, so every stage below can be
tested without SQL Server.
"""

import sqlite3
from pathlib import Path

from snapshot_schema import (
    CREATE_META_SQL,
    create_bom_sql,
    create_detect_sql,
)


def create_snapshot(
    path: Path, main_columns: list[dict], detect_columns: list[dict]
) -> sqlite3.Connection:
    """Create an empty snapshot file and return an open connection.

    Refuses to open an existing file: a leftover .new from a crashed run must
    not be appended to, or the sanity gate would pass on doubled data.
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
            main_rows.append((row_id, *record[:n_main]))
            detect_rows.append((row_id, *record[n_main:]))
        conn.executemany(main_sql, main_rows)
        conn.executemany(detect_sql, detect_rows)
        total += len(batch)
        if on_progress:
            on_progress(total)
    conn.commit()
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/build_snapshot.py tests/test_build_snapshot.py
git commit -m "feat: load view rows into the snapshot, split across bom and bom_detect"
```

---

### Task 4: Indexes, metadata and detection-size measurement

**Files:**
- Modify: `scripts/build_snapshot.py`
- Modify: `tests/test_build_snapshot.py`

**Interfaces:**
- Consumes: `load_rows` from Task 3, `index_sql` from Task 2.
- Produces:
  - `build_indexes(conn, column_names: list[str]) -> None`
  - `measure_detect(conn, detect_columns: list[str]) -> tuple[int, int]` returning `(avg_bytes, max_bytes)`
  - `write_meta(conn, values: dict) -> None`
  - `read_meta(conn) -> dict`

  `measure_detect` answers the open question in spec §7: whether a 100-row page
  of all 60 columns is a 400 KB payload or a 10 MB one.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build_snapshot.py`:

```python
from build_snapshot import build_indexes, measure_detect, read_meta, write_meta


class TestBuildIndexes:
    def test_creates_an_index_per_column(self, tmp_path):
        conn, _ = build(tmp_path, [[("S1", 1, "u", "c")]])
        build_indexes(conn, ["STYLE_NBR", "BOM_ROW_NBR"])
        names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert {"ix_bom_STYLE_NBR", "ix_bom_BOM_ROW_NBR"} <= names

    def test_index_is_actually_used_by_a_filter(self, tmp_path):
        conn, _ = build(tmp_path, [[("S1", 1, "u", "c")]])
        build_indexes(conn, ["STYLE_NBR"])
        plan = conn.execute(
            'EXPLAIN QUERY PLAN SELECT * FROM "bom" WHERE "STYLE_NBR" = ?', ("S1",)
        ).fetchall()
        assert any("ix_bom_STYLE_NBR" in str(row) for row in plan)


class TestMeasureDetect:
    def test_reports_average_and_max_bytes(self, tmp_path):
        conn, _ = build(tmp_path, [[
            ("S1", 1, "a" * 100, "b" * 100),    # 200 bytes
            ("S2", 2, "a" * 300, "b" * 300),    # 600 bytes
        ]])
        avg, largest = measure_detect(conn, DETECT)
        assert avg == 400
        assert largest == 600

    def test_counts_bytes_not_characters(self, tmp_path):
        # MASTER_BOM_STATUS and BNR_REMARK carry Thai text; a 3-byte character
        # must not be counted as 1, or the payload estimate is wrong by 3x.
        conn, _ = build(tmp_path, [[("S1", 1, "ก", None)]])
        avg, largest = measure_detect(conn, DETECT)
        assert largest == 3

    def test_nulls_count_as_zero_not_null(self, tmp_path):
        conn, _ = build(tmp_path, [[("S1", 1, None, None)]])
        assert measure_detect(conn, DETECT) == (0, 0)

    def test_empty_table_reports_zero(self, tmp_path):
        conn, _ = build(tmp_path, [])
        assert measure_detect(conn, DETECT) == (0, 0)


class TestMeta:
    def test_round_trips_values(self, tmp_path):
        conn, _ = build(tmp_path, [])
        write_meta(conn, {"row_count": 5, "source_view": "dbo.V"})
        assert read_meta(conn) == {"row_count": "5", "source_view": "dbo.V"}

    def test_rewriting_a_key_replaces_it(self, tmp_path):
        conn, _ = build(tmp_path, [])
        write_meta(conn, {"row_count": 1})
        write_meta(conn, {"row_count": 2})
        assert read_meta(conn)["row_count"] == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_indexes'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/build_snapshot.py` (add `index_sql` and `quote_ident` to the existing `snapshot_schema` import):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: PASS, 17 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/build_snapshot.py tests/test_build_snapshot.py
git commit -m "feat: snapshot indexes, build metadata and detection-size measurement"
```

---

### Task 5: Sanity gate and atomic swap

**Files:**
- Modify: `scripts/build_snapshot.py`
- Modify: `tests/test_build_snapshot.py`

**Interfaces:**
- Consumes: `read_meta` from Task 4.
- Produces:
  - `previous_row_count(live_path: Path) -> int | None`
  - `sanity_ok(new_count: int, previous_count: int | None, threshold: float = 0.9) -> bool`
  - `swap_in(new_path: Path, live_path: Path, prev_path: Path) -> None`

  This is the task that stops a truncated extract from replacing good data.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build_snapshot.py`:

```python
from build_snapshot import previous_row_count, sanity_ok, swap_in


class TestSanityGate:
    def test_passes_when_counts_match(self):
        assert sanity_ok(362_733, 362_733) is True

    def test_passes_on_a_small_shrink(self):
        assert sanity_ok(360_000, 362_733) is True

    def test_fails_below_the_threshold(self):
        # A half-finished extract must never replace a good snapshot.
        assert sanity_ok(40_000, 362_733) is False

    def test_passes_exactly_at_the_threshold(self):
        assert sanity_ok(90, 100) is True

    def test_passes_on_growth(self):
        assert sanity_ok(400_000, 362_733) is True

    def test_passes_when_there_is_no_previous_snapshot(self):
        # First ever run has nothing to compare against.
        assert sanity_ok(362_733, None) is True

    def test_fails_on_an_empty_extract_even_with_no_previous(self):
        assert sanity_ok(0, None) is False


class TestPreviousRowCount:
    def test_reads_the_count_from_a_live_snapshot(self, tmp_path):
        conn, _ = build(tmp_path, [])
        write_meta(conn, {"row_count": 1234})
        conn.close()
        assert previous_row_count(tmp_path / "t.sqlite") == 1234

    def test_returns_none_when_there_is_no_file(self, tmp_path):
        assert previous_row_count(tmp_path / "absent.sqlite") is None

    def test_returns_none_when_the_file_is_unreadable(self, tmp_path):
        broken = tmp_path / "broken.sqlite"
        broken.write_text("not a database")
        assert previous_row_count(broken) is None


class TestSwapIn:
    def _paths(self, tmp_path):
        return (
            tmp_path / "bom.new.sqlite",
            tmp_path / "bom.sqlite",
            tmp_path / "bom.prev.sqlite",
        )

    def test_new_becomes_live(self, tmp_path):
        new, live, prev = self._paths(tmp_path)
        new.write_text("NEW")
        live.write_text("LIVE")
        swap_in(new, live, prev)
        assert live.read_text() == "NEW"
        assert not new.exists()

    def test_outgoing_snapshot_is_retained(self, tmp_path):
        new, live, prev = self._paths(tmp_path)
        new.write_text("NEW")
        live.write_text("LIVE")
        swap_in(new, live, prev)
        assert prev.read_text() == "LIVE"

    def test_only_one_generation_is_kept(self, tmp_path):
        new, live, prev = self._paths(tmp_path)
        new.write_text("NEW")
        live.write_text("LIVE")
        prev.write_text("ANCIENT")
        swap_in(new, live, prev)
        assert prev.read_text() == "LIVE"

    def test_works_on_a_first_run_with_no_live_file(self, tmp_path):
        new, live, prev = self._paths(tmp_path)
        new.write_text("NEW")
        swap_in(new, live, prev)
        assert live.read_text() == "NEW"
        assert not prev.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'previous_row_count'`

- [ ] **Step 3: Write the implementation**

Append to `scripts/build_snapshot.py` (add `import os` at the top):

```python
def previous_row_count(live_path: Path) -> int | None:
    """Row count recorded in the current live snapshot, or None if there isn't
    one to compare against. A corrupt or unreadable file counts as absent --
    there is nothing to protect in that case."""
    live_path = Path(live_path)
    if not live_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{live_path}?mode=ro", uri=True)
        try:
            value = read_meta(conn).get("row_count")
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(value) if value is not None else None


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

    The previous generation is retained by HARDLINK, not by renaming the live
    file aside. Renaming would leave live_path absent between the two calls, so
    a crash in that window (scheduler timeout, power loss, disk full) leaves the
    app with no snapshot at all. Linking keeps live_path readable at every
    instant; os.replace then swaps it atomically and the old inode survives
    under prev_path. Do not "simplify" this back into two renames.

    Both paths sit in the same directory, so the hardlink is same-volume. A
    filesystem that cannot hardlink should fail the build loudly here rather
    than silently reintroduce the window, so the OSError is left to propagate.

    The caller must stop the web app first: Windows refuses to rename over a
    file another process holds open, and the app keeps the snapshot open.
    """
    new_path, live_path, prev_path = Path(new_path), Path(live_path), Path(prev_path)
    if live_path.exists():
        if prev_path.exists():
            prev_path.unlink()
        os.link(live_path, prev_path)
    os.replace(new_path, live_path)
```

> **Corrected during execution.** This originally used
> `os.replace(live_path, prev_path)` followed by `os.replace(new_path, live_path)`.
> The Task 5 review flagged it Critical: the two renames are individually atomic
> but not atomic together, so a crash between them removes the live snapshot
> entirely. Fixed under a controller ruling — spec §5 requires the retained
> generation precisely so recovery is cheap, and a window that deletes the live
> file defeats that. The accompanying test monkeypatches `os.replace` to raise
> and asserts the original live content survives.

**Not yet handled — deliberately.** `swap_in` requires that nothing holds the
live snapshot open, and on Windows that means stopping the web app first. That
cannot bite during this plan: nothing reads the snapshot until Plan 2 rewires
`src/db.py`, and Task 7 runs with `--limit`/`--no-swap` throughout. Wiring the
service stop/start around the swap belongs to Plan 2's deployment task. Until
then, do not run `build_snapshot.py` without `--no-swap` on a machine serving
the app.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: PASS, 31 tests

- [ ] **Step 5: Commit**

```bash
git add scripts/build_snapshot.py tests/test_build_snapshot.py
git commit -m "feat: sanity gate and atomic swap for the nightly snapshot"
```

---

### Task 6: Progress reporting and the command-line entry point

**Files:**
- Modify: `scripts/build_snapshot.py`
- Modify: `tests/test_build_snapshot.py`
- Modify: `src/config.py`

**Interfaces:**
- Consumes: everything from Tasks 3–5.
- Produces:
  - `progress_line(rows: int, elapsed: float, expected_total: int) -> str`
  - `main(argv: list[str] | None = None) -> int` — process exit code, 0 on success.

  `main` accepts `--limit N` (extract only the first N rows, for the timed trial
  runs in Task 7), `--no-swap` (build but leave the live snapshot alone), and
  `--out PATH`.

- [ ] **Step 1: Add snapshot settings to config.py**

Add to `src/config.py`, after the connection block:

```python
# --- Snapshot ------------------------------------------------------------
# The nightly SQLite extract. The web app reads this and never SQL Server.
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_PATH = SNAPSHOT_DIR / "bom.sqlite"
SNAPSHOT_NEW_PATH = SNAPSHOT_DIR / "bom.new.sqlite"
SNAPSHOT_PREV_PATH = SNAPSHOT_DIR / "bom.prev.sqlite"

# Held in a side table: two nvarchar(max) columns that are ~90% of the data
# volume and would otherwise slow every scan, count and sort.
DETECT_COLUMNS = [
    "TEXT_USE_OF_DETECT",
    "TEXT_Color_Code_OF_DETECT",
]

# Rows read from the source cursor at a time. Larger batches mean fewer
# round trips but more memory held per batch.
EXTRACT_BATCH_SIZE = 2000

# Only used to project a completion time in the progress log.
EXPECTED_ROWS = 362_733

# A new snapshot with less than this share of the previous row count is
# rejected rather than swapped in.
SANITY_THRESHOLD = 0.9
```

`Path` is already imported at the top of `config.py` by the `.env` loader.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_build_snapshot.py`:

```python
from build_snapshot import progress_line


class TestProgressLine:
    def test_reports_rows_elapsed_and_rate(self):
        line = progress_line(10_000, 20.0, 362_733)
        assert "10,000" in line
        assert "500 rows/s" in line

    def test_projects_remaining_minutes(self):
        # 10,000 done at 500/s leaves 352,733 to go -> ~11.8 minutes.
        line = progress_line(10_000, 20.0, 362_733)
        assert "11.8 min" in line

    def test_survives_a_zero_elapsed_time(self):
        # The first callback can arrive within the timer's resolution.
        assert "0 rows/s" in progress_line(100, 0.0, 362_733)

    def test_reports_no_eta_once_past_the_expected_total(self):
        line = progress_line(400_000, 100.0, 362_733)
        assert "eta" not in line
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: FAIL — `ImportError: cannot import name 'progress_line'`

- [ ] **Step 4: Write the implementation**

Append to `scripts/build_snapshot.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_build_snapshot.py -v`
Expected: PASS, 35 tests

- [ ] **Step 6: Write the entry point**

Append to `scripts/build_snapshot.py`:

```python
def _log(message: str, handle=None) -> None:
    print(message, flush=True)
    if handle:
        handle.write(message + "\n")
        handle.flush()


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
    top = f"TOP ({int(limit)}) " if limit else ""
    return f"SELECT {top}{select_list} FROM [{schema}].[{view}]"


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time
    from datetime import datetime

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    import config
    import pyodbc

    parser = argparse.ArgumentParser(description="Build the BOM SQLite snapshot.")
    parser.add_argument("--limit", type=int, default=None,
                        help="extract only the first N rows (for timed trials)")
    parser.add_argument("--no-swap", action="store_true",
                        help="build the file but leave the live snapshot alone")
    parser.add_argument("--out", type=Path, default=config.SNAPSHOT_NEW_PATH)
    args = parser.parse_args(argv)

    config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now()
    log_path = log_dir / f"snapshot-{stamp:%Y%m%d-%H%M%S}.log"

    with open(log_path, "w", encoding="utf-8") as log:
        started = time.perf_counter()
        _log(f"started {stamp:%Y-%m-%d %H:%M:%S}", log)

        if args.out.exists():
            args.out.unlink()

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

            expected = args.limit or config.EXPECTED_ROWS
            last_report = [0.0]

            def report(rows: int) -> None:
                elapsed = time.perf_counter() - started
                if elapsed - last_report[0] >= 30 or rows == expected:
                    _log(progress_line(rows, elapsed, expected), log)
                    last_report[0] = elapsed

            written = load_rows(
                conn, len(main_cols), len(detect_cols),
                _extract_batches(cur, config.EXTRACT_BATCH_SIZE),
                on_progress=report,
            )
            extract_seconds = time.perf_counter() - started
            _log(f"extract finished: {written:,} rows in "
                 f"{extract_seconds:,.0f}s", log)
        except Exception as exc:
            _log(f"FAILED during extract: {exc}", log)
            return 1
        finally:
            source.close()

        _log("building indexes...", log)
        build_indexes(conn, config.TEXT_FILTERS + config.DATE_FILTERS)

        avg_bytes, max_bytes = measure_detect(conn, config.DETECT_COLUMNS)
        _log(f"detection columns: avg {avg_bytes:,} bytes/row, "
             f"max {max_bytes:,} bytes", log)
        _log(f"  -> a 100-row page carries ~{avg_bytes * 100 / 1_000_000:,.1f} MB",
             log)

        write_meta(conn, {
            "started_at": stamp.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": int(time.perf_counter() - started),
            "row_count": written,
            "source_view": f"{config.SCHEMA}.{config.VIEW}",
            "detect_avg_bytes": avg_bytes,
            "detect_max_bytes": max_bytes,
        })
        conn.close()

        size_mb = args.out.stat().st_size / 1_000_000
        _log(f"snapshot written: {args.out} ({size_mb:,.0f} MB)", log)

        if args.no_swap or args.limit:
            _log("swap skipped", log)
            return 0

        previous = previous_row_count(config.SNAPSHOT_PATH)
        if not sanity_ok(written, previous, config.SANITY_THRESHOLD):
            _log(f"FAILED sanity gate: {written:,} rows vs previous "
                 f"{previous:,} -- not swapping", log)
            return 2

        swap_in(args.out, config.SNAPSHOT_PATH, config.SNAPSHOT_PREV_PATH)
        _log(f"swapped in. total {time.perf_counter() - started:,.0f}s", log)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `import sys` to the imports at the top of the module, and add
`split_columns` to the existing `from snapshot_schema import ...` line — `main`
uses it and Tasks 3 and 4 did not need it.

- [ ] **Step 7: Verify the whole suite still passes**

Run: `python -m pytest tests/ -v`
Expected: PASS, 56 tests (21 schema + 35 build)

- [ ] **Step 8: Verify the entry point parses without touching the database**

Run: `python scripts/build_snapshot.py --help`
Expected: usage text listing `--limit`, `--no-swap`, `--out`

- [ ] **Step 9: Commit**

```bash
git add scripts/build_snapshot.py tests/test_build_snapshot.py src/config.py
git commit -m "feat: snapshot build entry point with throughput logging"
```

---

### Task 7: The real extract — feasibility measurement

**This task is a measurement, not code.** Everything in Plan 2 rests on its
result. Run it when the SQL Server instance is quiet.

**Files:** none modified. Output goes to `scripts/logs/`.

- [ ] **Step 1: Trial run at 1,000 rows**

Run: `python scripts/build_snapshot.py --limit 1000 --out data/trial-1k.sqlite`

Record: wall clock to first batch, total seconds, file size, and the reported
`detection columns: avg N bytes/row`.

- [ ] **Step 2: Trial run at 10,000 rows**

Run: `python scripts/build_snapshot.py --limit 10000 --out data/trial-10k.sqlite`

- [ ] **Step 3: Compare and decide**

| Observation | Meaning | Action |
|---|---|---|
| 10k takes roughly the same as 1k | Cost is fixed per query — the view materialises before filtering | **Proceed.** Full extract is feasible. |
| 10k takes ~10× the 1k time | Cost is per-row | Extrapolate: `1k_seconds × 363` = full extract seconds. Under ~4 hours, proceed. Over that, **stop and report** — the plan needs a different source. |

- [ ] **Step 4: Full extract**

Only if Step 3 says proceed:

Run: `python scripts/build_snapshot.py --no-swap`

Watch the throughput log. Kill it if the projected ETA exceeds four hours —
that will not fit in a nightly window.

- [ ] **Step 5: Verify the snapshot**

```bash
python -c "import sqlite3; c=sqlite3.connect('data/bom.new.sqlite'); \
print(c.execute('SELECT COUNT(*) FROM bom').fetchone()); \
print(dict(c.execute('SELECT key,value FROM snapshot_meta')))"
```

Expected: a row count at or near 362,733, and metadata with a plausible duration.

- [ ] **Step 6: Time a representative query against the snapshot**

```bash
python -c "import sqlite3,time; c=sqlite3.connect('data/bom.new.sqlite'); \
s=c.execute('SELECT \"STYLE_NBR\" FROM bom WHERE \"STYLE_NBR\" IS NOT NULL LIMIT 1').fetchone()[0]; \
t=time.perf_counter(); \
r=c.execute('SELECT COUNT(*) FROM bom WHERE \"STYLE_NBR\" = ?', (s,)).fetchone(); \
print(s, r, f'{time.perf_counter()-t:.3f}s')"
```

It picks a style out of the snapshot itself, so there is nothing to fill in.

Expected: milliseconds. This is the number that replaces the current 5–40 s.

- [ ] **Step 7: Record the findings**

Append a "Measured" section to the spec at
`docs/superpowers/specs/2026-08-14-sqlite-snapshot-design.md` with: full extract
duration, snapshot file size, detection column average and maximum bytes, and
the sample query time. **Plan 2 is written from these numbers** — specifically,
`detect_avg_bytes × 100` decides whether the row endpoint needs the truncation
flag from spec §7.

- [ ] **Step 8: Clean up trial files and commit**

```bash
rm -f data/trial-1k.sqlite data/trial-10k.sqlite
git add docs/superpowers/specs/2026-08-14-sqlite-snapshot-design.md
git commit -m "docs: record measured extract performance"
```

---

## What Plan 2 covers

Written after Task 7 reports its numbers: the `src/db.py` rewrite against
SQLite, `config.py` and `main.py` cleanup, the frontend deletions and
snapshot-age readout, and deployment on the shared machine (scheduled task
identity, service hosting, firewall).
