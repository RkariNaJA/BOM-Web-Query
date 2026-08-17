import datetime
import sqlite3
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from snapshot_schema import (
    CREATE_META_SQL,
    create_bom_sql,
    create_detect_sql,
    index_sql,
    quote_ident,
    split_columns,
    sqlite_type,
    to_sqlite_value,
)


class TestSqliteType:
    def test_integer_families_map_to_integer(self):
        for source in ("int", "bigint", "smallint", "tinyint", "bit"):
            assert sqlite_type(source) == "INTEGER"

    def test_decimal_families_map_to_real(self):
        for source in ("decimal", "numeric", "float", "real", "money", "smallmoney"):
            assert sqlite_type(source) == "REAL"

    def test_dates_map_to_text_for_iso_storage(self):
        # ISO text compares correctly with < and >, which is what the
        # BOM_UPDATE_DT range filter needs. The affinity is only half the job:
        # to_sqlite_value has to write the ISO *value*. See TestToSqliteValue.
        for source in ("date", "datetime", "datetime2", "smalldatetime"):
            assert sqlite_type(source) == "TEXT"

    def test_strings_map_to_text(self):
        for source in ("varchar", "nvarchar", "char", "nchar", "text"):
            assert sqlite_type(source) == "TEXT"

    def test_unknown_type_falls_back_to_text(self):
        assert sqlite_type("geography") == "TEXT"

    def test_matching_is_case_insensitive(self):
        assert sqlite_type("BigInt") == "INTEGER"


class TestToSqliteValue:
    """Storage-oriented coercion for every value the extract binds.

    Three of these types (Decimal, time, UUID) cannot be bound by sqlite3 at
    all -- they raise ProgrammingError -- so without this the extract dies on
    the first row containing one. The rest are about storing a value that
    compares and round-trips correctly rather than one that merely binds.
    """

    def test_none_passes_through(self):
        assert to_sqlite_value(None) is None

    def test_str_passes_through(self):
        assert to_sqlite_value("ก text") == "ก text"

    def test_int_passes_through(self):
        value = to_sqlite_value(42)
        assert value == 42 and isinstance(value, int)

    def test_float_passes_through(self):
        value = to_sqlite_value(1.5)
        assert value == 1.5 and isinstance(value, float)

    def test_bool_passes_through_unchanged(self):
        # bool is an int subclass; SQLite stores it as 0/1 either way.
        assert to_sqlite_value(True) is True
        assert to_sqlite_value(False) is False

    def test_bytes_are_not_hexed(self):
        # db.py's display-oriented _cell hexes bytes for JSON. Doing that here
        # would store binary data as text that never round-trips back to bytes.
        # SQLite stores bytes as a BLOB natively.
        value = to_sqlite_value(b"\x00\x01\xff")
        assert value == b"\x00\x01\xff"
        assert isinstance(value, bytes)

    def test_bytearray_passes_through(self):
        value = to_sqlite_value(bytearray(b"\x01\x02"))
        assert bytes(value) == b"\x01\x02"
        assert isinstance(value, (bytes, bytearray))

    def test_decimal_becomes_a_float(self):
        # sqlite3 refuses to bind a Decimal, and the schema declares REAL for
        # decimal/numeric/money/smallmoney, so float is the matching storage.
        value = to_sqlite_value(Decimal("12.34"))
        assert value == 12.34
        assert isinstance(value, float)

    def test_datetime_becomes_iso_text_with_a_space_separator(self):
        assert to_sqlite_value(
            datetime.datetime(2026, 8, 14, 13, 4, 5)
        ) == "2026-08-14 13:04:05"

    def test_date_becomes_iso_text(self):
        assert to_sqlite_value(datetime.date(2026, 8, 14)) == "2026-08-14"

    def test_time_becomes_iso_text(self):
        # datetime.time is one of the types sqlite3 cannot bind at all.
        assert to_sqlite_value(datetime.time(13, 4, 5)) == "13:04:05"

    def test_uuid_becomes_its_string_form(self):
        raw = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert to_sqlite_value(raw) == "12345678-1234-5678-1234-567812345678"

    def test_anything_else_falls_back_to_str(self):
        class Odd:
            def __str__(self):
                return "odd"

        assert to_sqlite_value(Odd()) == "odd"

    def test_datetime_is_matched_before_date(self):
        # datetime is a subclass of date; matched the wrong way round a
        # timestamp would be truncated to its day and the time of day lost.
        assert " " in to_sqlite_value(datetime.datetime(2026, 8, 14, 1, 2, 3))

    def test_every_coerced_value_actually_binds(self):
        # The point of the whole function: sqlite3 must accept the results.
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (v)")
        samples = [
            None, "s", 1, 1.5, True, b"\x00\xff", bytearray(b"\x01"),
            Decimal("12.34"), datetime.datetime(2026, 8, 14, 13, 4, 5),
            datetime.date(2026, 8, 14), datetime.time(13, 4, 5), uuid.uuid4(),
        ]
        conn.executemany(
            "INSERT INTO t VALUES (?)", [(to_sqlite_value(s),) for s in samples]
        )
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == len(samples)
        conn.close()


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


DETECT = ["TEXT_USE_OF_DETECT", "TEXT_Color_Code_OF_DETECT"]

SAMPLE = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "Buy Code", "type": "nvarchar", "nullable": True},
    {"name": "TEXT_Color_Code_OF_DETECT", "type": "nvarchar", "nullable": True},
    {"name": "BOM_UPDATE_DT", "type": "datetime", "nullable": True},
    {"name": "TEXT_USE_OF_DETECT", "type": "nvarchar", "nullable": True},
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

    def test_detect_table_with_no_columns_is_still_valid_sql(self):
        # split_columns documents that it ignores a configured detection column
        # the view no longer has. If BOTH vanished, create_detect_sql is handed
        # [] -- and the naive form emitted a trailing comma after "id", which
        # is a syntax error that fails the build at CREATE TABLE.
        conn = sqlite3.connect(":memory:")
        conn.execute(create_detect_sql([]))
        conn.close()

    def test_bom_table_with_no_columns_is_still_valid_sql(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(create_bom_sql([]))
        conn.close()

    def test_populated_tables_remain_valid_sql(self):
        # The empty-list guard must not have broken the ordinary case.
        main, detect = split_columns(SAMPLE, DETECT)
        conn = sqlite3.connect(":memory:")
        conn.execute(create_bom_sql(main))
        conn.execute(create_detect_sql(detect))
        conn.close()


class TestIndexSql:
    def test_one_statement_per_column(self):
        statements = index_sql(["STYLE_NBR", "Buy Code"])
        assert len(statements) == 2

    def test_index_names_are_safe_for_awkward_columns(self):
        # "Buy Code" cannot appear raw in an index name.
        statements = index_sql(["Buy Code"])
        assert statements[0].startswith('CREATE INDEX "ix_bom_Buy_Code"')
        assert 'ON "bom"("Buy Code")' in statements[0]
