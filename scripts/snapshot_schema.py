"""Pure schema helpers for the nightly snapshot build.

No I/O and no database handles: everything here is a function of its arguments,
so the whole module is unit-testable without SQL Server or a SQLite file.
"""

import datetime
import decimal
import re
import uuid

# Anything not listed becomes TEXT. Dates are deliberately TEXT: `to_sqlite_value`
# stores them as ISO text ('YYYY-MM-DD' for a date, 'YYYY-MM-DD HH:MM:SS' for a
# datetime), which compares correctly with < and >, which is what the
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


def to_sqlite_value(value):
    """Coerce one source cell into something `sqlite3` can bind and store.

    pyodbc hands back objects sqlite3 refuses outright -- `decimal.Decimal`,
    `datetime.time` and `uuid.UUID` each raise
    `sqlite3.ProgrammingError: type ... is not supported` on bind -- so every
    value has to pass through here before it reaches `executemany`.

    This is deliberately NOT `db.py`'s `_cell`. That one is display-oriented:
    it hexes `bytes` and stringifies anything unknown so the value can go into
    JSON. Here the target is storage, so:

    - `bytes`/`bytearray` are passed through untouched; SQLite stores them as a
      BLOB natively, and hexing would turn binary data into a text column that
      no longer round-trips.
    - `decimal.Decimal` becomes `float`, matching the REAL affinity
      `sqlite_type` declares for decimal/numeric/money/smallmoney.
    - dates and times become ISO text, matching the TEXT affinity and, more
      importantly, making lexicographic range comparison correct. Writing the
      `.isoformat()` explicitly also drops the build's dependence on sqlite3's
      built-in datetime adapter, which is deprecated in Python 3.12 and slated
      for removal.

    Datetimes keep their time of day ('YYYY-MM-DD HH:MM:SS', with a
    '.ffffff' tail when the source value carries sub-second precision) rather
    than being truncated to a day: the app displays that time today. See the
    date-filter warning in the design spec, section 4 -- an inclusive to-date
    bound must be written as `col < '<the day after>'`, never `col <= '<the
    to-date>'`.
    """
    if value is None or isinstance(value, (str, int, float, bytes, bytearray)):
        # bool is a subclass of int, so it lands here and stays as-is.
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        # Must precede datetime.date -- datetime is a subclass of date.
        return value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def quote_ident(name: str) -> str:
    """Double-quote an identifier for SQLite, doubling embedded quotes.

    The view contains names like `GCW#` and `Buy Code`, so quoting is not
    optional anywhere an identifier is interpolated.
    """
    return '"' + name.replace('"', '""') + '"'


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
    """The `,`-joined column definitions that follow the `id` column.

    Returns "" for an empty list, including the leading comma and newline that
    would otherwise dangle. `split_columns` documents that it silently ignores
    a configured detection column the view no longer has, so if BOTH detection
    columns disappeared upstream `create_detect_sql` would be handed [] -- and
    an unconditional `"id" ...,\\n\\n)` is a syntax error that would fail the
    build at CREATE TABLE rather than degrading to an empty side table.
    """
    if not columns:
        return ""
    return ",\n" + ",\n".join(
        f'  {quote_ident(c["name"])} {sqlite_type(c["type"])}' for c in columns
    )


def create_bom_sql(main_columns: list[dict]) -> str:
    """DDL for the main table. `id` is a surrogate key -- the view has none,
    which is also why paging it in SQL Server needed ORDER BY (SELECT NULL)."""
    return (
        'CREATE TABLE "bom" (\n'
        '  "id" INTEGER PRIMARY KEY'
        f"{_column_defs(main_columns)}\n"
        ")"
    )


def create_detect_sql(detect_columns: list[dict]) -> str:
    """DDL for the nvarchar(max) side table, keyed 1:1 to bom.id."""
    return (
        'CREATE TABLE "bom_detect" (\n'
        '  "id" INTEGER PRIMARY KEY REFERENCES "bom"("id")'
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
