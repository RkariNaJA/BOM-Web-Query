import datetime
import json
import os
import sqlite3
import sys
import types
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_snapshot
from build_snapshot import SnapshotUnreadableError, build_indexes, create_snapshot, load_rows, measure_detect, read_meta, write_meta, previous_row_count, sanity_ok, swap_in
from snapshot_schema import split_columns

DETECT = ["TEXT_USE_OF_DETECT", "TEXT_Color_Code_OF_DETECT"]

COLUMNS = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "TEXT_USE_OF_DETECT", "type": "nvarchar", "nullable": True},
    {"name": "TEXT_Color_Code_OF_DETECT", "type": "nvarchar", "nullable": True},
]

# A view shaped like the real one in the ways that matter for value coercion:
# a REAL-affinity decimal, a TEXT-affinity datetime and a binary column, plus
# the two detection columns that live in the side table.
TYPED_COLUMNS = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "UNIT_PRICE", "type": "decimal", "nullable": True},
    {"name": "BOM_UPDATE_DT", "type": "datetime", "nullable": True},
    {"name": "ROW_HASH", "type": "varbinary", "nullable": True},
    {"name": "TEXT_USE_OF_DETECT", "type": "nvarchar", "nullable": True},
    {"name": "TEXT_Color_Code_OF_DETECT", "type": "nvarchar", "nullable": True},
]


def build(tmp_path, batches):
    """Create a snapshot at a temp path and load the given batches into it."""
    main, detect = split_columns(COLUMNS, DETECT)
    conn = create_snapshot(tmp_path / "t.sqlite", main, detect)
    written = load_rows(conn, len(main), len(detect), batches)
    return conn, written


def build_typed(tmp_path, batches):
    """As `build`, but over TYPED_COLUMNS. Row tuples are main-then-detect:
    STYLE_NBR, BOM_ROW_NBR, UNIT_PRICE, BOM_UPDATE_DT, ROW_HASH, then the two
    detection columns."""
    main, detect = split_columns(TYPED_COLUMNS, DETECT)
    conn = create_snapshot(tmp_path / "typed.sqlite", main, detect)
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


class TestValueCoercion:
    """load_rows must coerce every value before binding it.

    Bound raw, `decimal.Decimal`, `datetime.time` and `uuid.UUID` each raise
    `sqlite3.ProgrammingError: type ... is not supported`, so the extract would
    die on the first row carrying one -- and the schema deliberately maps
    decimal/numeric/money to REAL, so such columns are expected to be there.
    """

    def test_a_batch_of_non_primitive_values_loads_and_round_trips(self, tmp_path):
        conn, written = build_typed(tmp_path, [[
            ("S1", 1, Decimal("12.34"),
             datetime.datetime(2026, 8, 14, 13, 4, 5), b"\x00\x01\xff",
             "use", "code"),
        ]])
        assert written == 1
        price, updated, row_hash = conn.execute(
            'SELECT "UNIT_PRICE", "BOM_UPDATE_DT", "ROW_HASH" FROM "bom"'
        ).fetchone()
        assert price == 12.34 and isinstance(price, float)
        assert updated == "2026-08-14 13:04:05"
        assert row_hash == b"\x00\x01\xff" and isinstance(row_hash, bytes)

    def test_bytes_are_stored_as_a_blob_not_hex_text(self, tmp_path):
        conn, _ = build_typed(tmp_path, [[
            ("S1", 1, None, None, b"\xde\xad", None, None),
        ]])
        assert conn.execute(
            'SELECT typeof("ROW_HASH") FROM "bom"'
        ).fetchone()[0] == "blob"

    def test_the_detect_slice_is_coerced_too(self, tmp_path):
        # Both slices pass through the coercion, not just the main one. A UUID
        # is the sharpest probe: sqlite3 raises ProgrammingError on binding one
        # outright, so this row could not be written at all without it.
        raw = uuid.UUID("12345678-1234-5678-1234-567812345678")
        conn, _ = build_typed(tmp_path, [[
            ("S1", 1, None, None, None, raw, Decimal("1.5")),
        ]])
        # bom_detect's columns are nvarchar -> TEXT affinity, so the float from
        # a Decimal is stored as its text form. What matters here is that the
        # bind succeeded and the value survived.
        assert conn.execute(
            'SELECT "TEXT_USE_OF_DETECT", "TEXT_Color_Code_OF_DETECT" '
            'FROM "bom_detect"'
        ).fetchone() == ("12345678-1234-5678-1234-567812345678", "1.5")


class TestStoredDatetimeComparison:
    """A datetime is stored as full ISO text, 'YYYY-MM-DD HH:MM:SS'.

    That sorts and range-compares correctly, but it makes the obvious form of
    an inclusive to-date bound wrong. The design spec, section 4, documents the
    two forms that ARE correct; these tests pin all three behaviours so the
    trap cannot be rediscovered in production.
    """

    ROWS = [[
        ("A", 1, None, datetime.datetime(2026, 8, 13, 9, 0, 0), None, None, None),
        ("B", 2, None, datetime.datetime(2026, 8, 14, 0, 0, 1), None, None, None),
        ("C", 3, None, datetime.datetime(2026, 8, 14, 23, 59, 59), None, None, None),
        ("D", 4, None, datetime.datetime(2026, 8, 15, 8, 0, 0), None, None, None),
    ]]

    def _styles(self, conn, where, *params):
        return [
            r[0] for r in conn.execute(
                f'SELECT "STYLE_NBR" FROM "bom" WHERE {where} '
                f'ORDER BY "BOM_UPDATE_DT"', params
            )
        ]

    def test_lexicographic_order_is_chronological_order(self, tmp_path):
        conn, _ = build_typed(tmp_path, self.ROWS)
        assert [
            r[0] for r in conn.execute(
                'SELECT "STYLE_NBR" FROM "bom" ORDER BY "BOM_UPDATE_DT"'
            )
        ] == ["A", "B", "C", "D"]

    def test_a_from_bound_works_as_written(self, tmp_path):
        conn, _ = build_typed(tmp_path, self.ROWS)
        assert self._styles(
            conn, '"BOM_UPDATE_DT" >= ?', "2026-08-14"
        ) == ["B", "C", "D"]

    def test_the_naive_inclusive_to_bound_silently_drops_the_final_day(self, tmp_path):
        # This is the trap. `<= '2026-08-14'` compares against a 10-character
        # string, so every timestamp on the 14th sorts after it and is lost.
        conn, _ = build_typed(tmp_path, self.ROWS)
        assert self._styles(conn, '"BOM_UPDATE_DT" <= ?', "2026-08-14") == ["A"]

    def test_the_documented_day_after_form_is_inclusive(self, tmp_path):
        conn, _ = build_typed(tmp_path, self.ROWS)
        assert self._styles(
            conn, '"BOM_UPDATE_DT" < ?', "2026-08-15"
        ) == ["A", "B", "C"]

    def test_the_documented_substr_form_is_inclusive(self, tmp_path):
        conn, _ = build_typed(tmp_path, self.ROWS)
        assert self._styles(
            conn, 'substr("BOM_UPDATE_DT", 1, 10) <= ?', "2026-08-14"
        ) == ["A", "B", "C"]


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
        # The detection columns measured here -- TEXT_USE_OF_DETECT and
        # TEXT_Color_Code_OF_DETECT -- carry Thai text; a 3-byte character must
        # not be counted as 1, or the payload estimate is wrong by 3x.
        conn, _ = build(tmp_path, [[("S1", 1, "ก", None)]])
        avg, largest = measure_detect(conn, DETECT)
        assert largest == 3

    def test_nulls_count_as_zero_not_null(self, tmp_path):
        # If COALESCE is missing, SQLite's AVG excludes NULL rows rather than
        # counting them as zero. Without this, the average bytes-per-row would be
        # overstated when real data has NULLs in detection columns on most rows.
        # With two rows (one all-NULL, one with 200 bytes), the average is 100
        # only if the NULL row counted as 0; without COALESCE it would be 200.
        conn, _ = build(tmp_path, [[
            ("S1", 1, None, None),              # 0 bytes
            ("S2", 2, "a" * 100, "b" * 100),    # 200 bytes
        ]])
        avg, largest = measure_detect(conn, DETECT)
        assert avg == 100  # (0 + 200) / 2
        assert largest == 200

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

    def test_json_encoded_column_lists_round_trip(self, tmp_path):
        # The snapshot's column ORDER differs from the view's -- bom is the
        # view minus the two detection columns -- so config.COLUMN_GROUPS'
        # ordinals cannot be applied to it. Recording the names lets the app
        # rebuild its grouping without guessing. Names include "Buy Code" and
        # "GCW#", so the encoding has to survive spaces and punctuation.
        conn, _ = build(tmp_path, [])
        names = ["STYLE_NBR", "Buy Code", "GCW#"]
        write_meta(conn, {"main_columns": json.dumps(names, ensure_ascii=False)})
        assert json.loads(read_meta(conn)["main_columns"]) == names


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
        # Absent really is absent: a first run has nothing to protect, and the
        # gate is expected to pass on it.
        assert previous_row_count(tmp_path / "absent.sqlite") is None
        assert sanity_ok(362_733, previous_row_count(tmp_path / "absent.sqlite"))

    def test_raises_when_the_file_is_present_but_unreadable(self, tmp_path):
        # Unreadable is NOT absent. Returning None here would hand sanity_ok a
        # "no previous snapshot" answer, and any extract of one row or more
        # would then pass the gate and replace a live file we never read --
        # possibly 362,733 good rows -- while main() returned 0.
        broken = tmp_path / "broken.sqlite"
        broken.write_text("not a database")
        with pytest.raises(SnapshotUnreadableError):
            previous_row_count(broken)

    def test_raises_when_the_file_records_no_row_count(self, tmp_path):
        # A real snapshot always records one, so its absence means this file is
        # not a snapshot we can vouch for -- same protection as above.
        conn, _ = build(tmp_path, [])
        conn.close()
        with pytest.raises(SnapshotUnreadableError):
            previous_row_count(tmp_path / "t.sqlite")

    def test_raises_when_the_recorded_row_count_is_not_an_integer(self, tmp_path):
        conn, _ = build(tmp_path, [])
        write_meta(conn, {"row_count": "not a number"})
        conn.close()
        with pytest.raises(SnapshotUnreadableError):
            previous_row_count(tmp_path / "t.sqlite")


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

    def test_live_path_survives_a_crash_during_swap(self, tmp_path, monkeypatch):
        """Verify that live_path is never absent on disk, even if the process
        dies partway through swap_in. This proves the hardlink approach works."""
        new, live, prev = self._paths(tmp_path)
        new.write_text("NEW")
        live.write_text("ORIGINAL")

        # Make the final os.replace(new_path, live_path) fail to simulate a crash
        original_replace = os.replace

        def failing_replace(src, dst):
            # Fail when trying to replace new into live (the final operation)
            if Path(src) == new and Path(dst) == live:
                raise OSError("Simulated crash during final swap")
            return original_replace(src, dst)

        monkeypatch.setattr(os, "replace", failing_replace)

        # Try to swap and catch the error
        with pytest.raises(OSError, match="Simulated crash"):
            swap_in(new, live, prev)

        # Even though the swap failed, live_path must still exist with ORIGINAL content
        assert live.exists()
        assert live.read_text() == "ORIGINAL"


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


class TestMainArgumentGuards:
    """Pins the two argument guards in main() that stop an accidental
    multi-hour production extract: a bad --limit, and an --out that points at
    a path swap_in treats as sacred. Both are supposed to terminate before
    pyodbc.connect is ever called.

    Every test here backstops that with monkeypatch.setattr(pyodbc,
    "connect", self._forbid_connect): if a future edit ever breaks the guard
    under test, main() reaches the real connect call and the test fails
    loudly with an AssertionError, instead of silently querying the live
    production SQL Server view during an ordinary `pytest` run. A prior round
    proved this is not a hypothetical: a reviewer testing these guards by
    temporarily disabling the --limit check found that the two --limit tests,
    as originally written, ran to completion against production. Every test
    also redirects the log directory and the snapshot paths to tmp_path, so a
    regressed guard still can't write to the real data/ or scripts/logs/.

    The --out tests reach the point where main() imports pyodbc and config, so
    they need pyodbc importable and a readable .env -- an importability
    dependency, not a database one. Skip cleanly where that is not available.
    (The --limit tests are rejected by argparse before either import, but keep
    the same setup so the tmp_path redirection applies to them too.)
    """

    @staticmethod
    def _forbid_connect(*args, **kwargs):
        raise AssertionError(
            "main() must not connect: the guard under test should have "
            "returned before any database connection was attempted"
        )

    def _prepare(self, tmp_path, monkeypatch, pyodbc):
        """Import the real config module and redirect its snapshot paths,
        plus build_snapshot's own __file__ (which log_dir is derived from),
        to tmp_path -- so exercising a guard's mkdir/log-open side effects
        never touches the real data/ or scripts/logs/ directories, even if
        the guard itself has regressed. Also installs the pyodbc.connect
        backstop described on the class.

        Importing `config` here first (via the real src/ path) means it is
        already cached in sys.modules by the time main() does its own
        `sys.path.insert(...); import config` -- that becomes a harmless
        cache hit even though __file__ is about to point somewhere fake.
        """
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        sys.path.insert(0, src_dir)
        import config as real_config

        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )
        data_dir = tmp_path / "data"
        monkeypatch.setattr(real_config, "SNAPSHOT_DIR", data_dir)
        monkeypatch.setattr(real_config, "SNAPSHOT_PATH", data_dir / "bom.sqlite")
        monkeypatch.setattr(real_config, "SNAPSHOT_NEW_PATH", data_dir / "bom.new.sqlite")
        monkeypatch.setattr(real_config, "SNAPSHOT_PREV_PATH", data_dir / "bom.prev.sqlite")
        monkeypatch.setattr(pyodbc, "connect", self._forbid_connect)
        return real_config

    def test_limit_zero_is_rejected_by_argparse(self, tmp_path, monkeypatch, capsys):
        pyodbc = pytest.importorskip("pyodbc")
        self._prepare(tmp_path, monkeypatch, pyodbc)

        with pytest.raises(SystemExit) as exc_info:
            build_snapshot.main(["--limit", "0"])
        assert exc_info.value.code == 2
        assert "positive integer" in capsys.readouterr().err

    def test_limit_negative_is_rejected_by_argparse(self, tmp_path, monkeypatch, capsys):
        pyodbc = pytest.importorskip("pyodbc")
        self._prepare(tmp_path, monkeypatch, pyodbc)

        with pytest.raises(SystemExit) as exc_info:
            build_snapshot.main(["--limit", "-5"])
        assert exc_info.value.code == 2
        assert "positive integer" in capsys.readouterr().err

    def test_out_pointing_at_the_live_snapshot_is_refused(self, tmp_path, monkeypatch):
        pyodbc = pytest.importorskip("pyodbc")
        real_config = self._prepare(tmp_path, monkeypatch, pyodbc)
        live = real_config.SNAPSHOT_PATH
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_text("LIVE")

        result = build_snapshot.main(["--out", str(live)])

        assert result == 1
        assert live.read_text() == "LIVE"  # not unlinked

    def test_out_pointing_at_the_retained_generation_is_refused(self, tmp_path, monkeypatch):
        pyodbc = pytest.importorskip("pyodbc")
        real_config = self._prepare(tmp_path, monkeypatch, pyodbc)
        prev = real_config.SNAPSHOT_PREV_PATH
        prev.parent.mkdir(parents=True, exist_ok=True)
        prev.write_text("PREV")

        result = build_snapshot.main(["--out", str(prev)])

        assert result == 1
        assert prev.read_text() == "PREV"  # not unlinked


# --- An offline stand-in for the ODBC driver ------------------------------
#
# These fakes are plain Python objects: no socket, no driver, no connection
# string handling of any kind, so a test using them cannot reach SQL Server
# even if a guard in main() regresses. That is the point. The paths exercised
# below -- the sanity gate's refusal to swap over an unreadable live snapshot,
# and the guarded unlink of a locked leftover -- sit downstream of a
# successful extract, and there is no safe way to reach them any other way.

FAKE_VIEW_COLUMNS = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "BOM_UPDATE_DT", "type": "datetime", "nullable": True},
    {"name": "TEXT_USE_OF_DETECT", "type": "nvarchar", "nullable": True},
    {"name": "TEXT_Color_Code_OF_DETECT", "type": "nvarchar", "nullable": True},
]

# Ordered main-then-detect, exactly as _source_query builds the SELECT.
FAKE_ROWS = [
    ("S1", 1, datetime.datetime(2026, 8, 14, 13, 4, 5), "use one", "code one"),
    ("S2", 2, datetime.datetime(2026, 8, 13, 9, 0, 0), "use two", "code two"),
]


class _FakeCursor:
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows
        self._pending = []

    def execute(self, sql, *params):
        if "INFORMATION_SCHEMA" in sql:
            self._pending = [
                (c["name"], c["type"], "YES" if c["nullable"] else "NO")
                for c in self._columns
            ]
        else:
            self._pending = list(self._rows)
        return self

    def fetchall(self):
        rows, self._pending = self._pending, []
        return rows

    def fetchmany(self, size):
        batch, self._pending = self._pending[:size], self._pending[size:]
        return batch


class _FakeSource:
    def __init__(self, columns, rows):
        self.timeout = 0
        self._cursor = _FakeCursor(columns, rows)
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def _real_config():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    try:
        import config
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"src/config.py is not importable here: {exc}")
    return config


def _redirect(tmp_path, monkeypatch):
    """Point build_snapshot's log directory and every configured snapshot path
    at tmp_path, so no test can touch the real data/ or scripts/logs/."""
    config = _real_config()
    monkeypatch.setattr(
        build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
    )
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config, "SNAPSHOT_DIR", data_dir)
    monkeypatch.setattr(config, "SNAPSHOT_PATH", data_dir / "bom.sqlite")
    monkeypatch.setattr(config, "SNAPSHOT_NEW_PATH", data_dir / "bom.new.sqlite")
    monkeypatch.setattr(config, "SNAPSHOT_PREV_PATH", data_dir / "bom.prev.sqlite")
    return config


def _install_fake_driver(monkeypatch, rows=FAKE_ROWS, columns=FAKE_VIEW_COLUMNS):
    monkeypatch.setitem(sys.modules, "pyodbc", types.SimpleNamespace(
        connect=lambda *a, **k: _FakeSource(columns, rows)
    ))


def _run_log_text(tmp_path):
    logs = sorted((tmp_path / "logs").glob("snapshot-*.log"))
    assert len(logs) == 1, f"expected exactly one run log, got {logs}"
    return logs[0].read_text(encoding="utf-8")


class TestMainBootstrapFailures:
    """A failure before the log file exists must still leave a record.

    `import config` (RuntimeError on a missing or incomplete .env) and
    `import pyodbc` (ImportError if the ODBC driver disappears in an upgrade)
    are the two most likely production-config faults, and both used to produce
    a traceback on a stderr that Task Scheduler discards, with scripts/logs/
    gaining nothing at all -- not even a `started` line.
    """

    @staticmethod
    def _break_log_dir(monkeypatch):
        original_mkdir = Path.mkdir

        def failing_mkdir(self, *args, **kwargs):
            if self.name == "logs":
                raise PermissionError("access is denied")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", failing_mkdir)

    def test_a_failure_before_the_log_opens_is_written_to_a_fallback_file(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )
        self._break_log_dir(monkeypatch)

        assert build_snapshot.main([]) == 1

        text = (tmp_path / "snapshot-bootstrap-failures.log").read_text(
            encoding="utf-8"
        )
        assert "FAILED during startup" in text
        assert "PermissionError" in text
        assert "FAILED during startup" in capsys.readouterr().err

    def test_the_fallback_file_is_appended_not_overwritten(
        self, tmp_path, monkeypatch
    ):
        # Successive nightly failures must all be visible, not just the last.
        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )
        self._break_log_dir(monkeypatch)

        build_snapshot.main([])
        build_snapshot.main([])

        text = (tmp_path / "snapshot-bootstrap-failures.log").read_text(
            encoding="utf-8"
        )
        assert text.count("FAILED during startup") == 2

    def test_help_does_not_create_a_run_log(self, tmp_path, monkeypatch):
        # --help does no work. Opening a log for it would litter scripts/logs/
        # with an empty file on every invocation.
        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )
        with pytest.raises(SystemExit) as exc_info:
            build_snapshot.main(["--help"])
        assert exc_info.value.code == 0
        assert not (tmp_path / "logs").exists()
        assert not (tmp_path / "snapshot-bootstrap-failures.log").exists()

    def test_a_bad_command_line_is_recorded_in_the_fallback_file(
        self, tmp_path, monkeypatch
    ):
        # A scheduled task with a typo in its arguments must not be invisible.
        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )
        with pytest.raises(SystemExit) as exc_info:
            build_snapshot.main(["--limit", "0"])
        assert exc_info.value.code == 2
        text = (tmp_path / "snapshot-bootstrap-failures.log").read_text(
            encoding="utf-8"
        )
        assert "FAILED during startup (parsing arguments)" in text

    def test_an_unexpected_error_still_leaves_a_failed_line(
        self, tmp_path, monkeypatch
    ):
        # _run guards each stage; this pins the net under all of them, so a
        # gap between stages cannot produce a run that exits with a bare
        # traceback and a log ending mid-sentence.
        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )

        def boom(*args, **kwargs):
            raise ZeroDivisionError("something nobody anticipated")

        monkeypatch.setattr(build_snapshot, "_run", boom)

        assert build_snapshot.main([]) == 1
        text = _run_log_text(tmp_path)
        assert "FAILED: unhandled ZeroDivisionError" in text
        assert "ZeroDivisionError" in text

    def test_an_import_failure_lands_in_the_run_log(self, tmp_path, monkeypatch):
        _real_config()  # cache it, so only the pyodbc import is made to fail
        monkeypatch.setattr(
            build_snapshot, "__file__", str(tmp_path / "build_snapshot.py")
        )
        monkeypatch.setitem(sys.modules, "pyodbc", None)  # -> ImportError

        assert build_snapshot.main([]) == 1

        text = _run_log_text(tmp_path)
        assert text.startswith("started ")
        assert "FAILED during startup" in text


class TestMainLeftoverFile:
    def test_a_leftover_new_file_that_cannot_be_deleted_aborts_the_run(
        self, tmp_path, monkeypatch
    ):
        """A manual --limit trial still streaming at 00:00 holds the .new file
        open, and Windows refuses to delete a file another process has open.
        The scheduled run must report that and stop, not die on an unhandled
        PermissionError that leaves the log holding only `started`."""
        _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch)

        out = tmp_path / "data" / "bom.new.sqlite"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("LEFTOVER")

        original_unlink = Path.unlink

        def failing_unlink(self, *args, **kwargs):
            if self == out:
                raise PermissionError("used by another process")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", failing_unlink)

        assert build_snapshot.main(["--out", str(out)]) == 1
        assert out.read_text() == "LEFTOVER"  # left alone for the other run
        text = _run_log_text(tmp_path)
        assert "FAILED" in text
        assert "another build may still hold it open" in text


class TestMainSanityGate:
    """The end of the pipeline: what main() does with the live snapshot."""

    def test_a_first_run_with_no_live_snapshot_swaps_in(self, tmp_path, monkeypatch):
        config = _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch)
        out = tmp_path / "data" / "bom.new.sqlite"

        assert build_snapshot.main(["--out", str(out)]) == 0
        assert config.SNAPSHOT_PATH.exists()
        assert not out.exists()
        assert not config.SNAPSHOT_PREV_PATH.exists()

    def test_the_snapshot_records_its_own_column_order_by_name(
        self, tmp_path, monkeypatch
    ):
        # config.COLUMN_GROUPS' ordinals address the view, so the app must read
        # the snapshot's own recorded order rather than assume it matches.
        config = _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch)

        assert build_snapshot.main(
            ["--out", str(tmp_path / "data" / "n.sqlite")]
        ) == 0

        conn = sqlite3.connect(config.SNAPSHOT_PATH)
        meta = read_meta(conn)
        tables = {
            r[0] for r in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        # DETECT_COLUMNS is empty by default, so every column lives in bom and
        # no side table is created at all.
        assert json.loads(meta["main_columns"]) == [
            c["name"] for c in FAKE_VIEW_COLUMNS
        ]
        assert json.loads(meta["detect_columns"]) == []
        assert "bom_detect" not in tables
        assert meta["row_count"] == "2"

    def test_a_configured_split_still_produces_a_side_table(
        self, tmp_path, monkeypatch
    ):
        # Splitting a column out is one config entry away if a genuinely bulky
        # one ever appears, so that path stays exercised even though the
        # shipped default no longer uses it.
        config = _redirect(tmp_path, monkeypatch)
        monkeypatch.setattr(config, "DETECT_COLUMNS", DETECT)
        _install_fake_driver(monkeypatch)

        assert build_snapshot.main(
            ["--out", str(tmp_path / "data" / "n.sqlite")]
        ) == 0

        conn = sqlite3.connect(config.SNAPSHOT_PATH)
        meta = read_meta(conn)
        tables = {
            r[0] for r in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        first_detect = conn.execute(
            'SELECT "TEXT_USE_OF_DETECT" FROM "bom_detect" ORDER BY "id" LIMIT 1'
        ).fetchone()[0]
        conn.close()
        assert "bom_detect" in tables
        assert json.loads(meta["main_columns"]) == [
            "STYLE_NBR", "BOM_ROW_NBR", "BOM_UPDATE_DT",
        ]
        assert json.loads(meta["detect_columns"]) == DETECT
        assert first_detect == "use one"

    def test_datetimes_reach_the_snapshot_as_iso_text(self, tmp_path, monkeypatch):
        # End-to-end proof of the coercion: the source hands main() real
        # datetime objects, and what lands in the file is ISO text rather than
        # whatever sqlite3's deprecated adapter would have produced.
        config = _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch)

        assert build_snapshot.main(
            ["--out", str(tmp_path / "data" / "n.sqlite")]
        ) == 0

        conn = sqlite3.connect(config.SNAPSHOT_PATH)
        stored = [
            r[0] for r in conn.execute(
                'SELECT "BOM_UPDATE_DT" FROM "bom" ORDER BY "id"'
            )
        ]
        conn.close()
        assert stored == ["2026-08-14 13:04:05", "2026-08-13 09:00:00"]

    def test_an_unreadable_live_snapshot_refuses_the_swap(self, tmp_path, monkeypatch):
        """The gate must not disable itself. A locked or corrupt live file is
        not an absent one: swapping over it would destroy data the gate was
        never able to check, and exit 0 having done so."""
        config = _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch)
        config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        config.SNAPSHOT_PATH.write_text("not a database")
        out = tmp_path / "data" / "bom.new.sqlite"

        assert build_snapshot.main(["--out", str(out)]) == 2
        assert config.SNAPSHOT_PATH.read_text() == "not a database"  # untouched
        assert out.exists()  # the new snapshot is kept for inspection
        text = _run_log_text(tmp_path)
        assert "FAILED" in text
        assert "cannot be read" in text

    def test_a_truncated_extract_does_not_replace_a_good_snapshot(
        self, tmp_path, monkeypatch
    ):
        # The ordinary gate still works alongside the unreadable case.
        config = _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch, rows=FAKE_ROWS[:1])
        config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        main_cols, detect_cols = split_columns(FAKE_VIEW_COLUMNS, DETECT)
        live = create_snapshot(config.SNAPSHOT_PATH, main_cols, detect_cols)
        write_meta(live, {"row_count": 1000})
        live.close()

        assert build_snapshot.main(
            ["--out", str(tmp_path / "data" / "n.sqlite")]
        ) == 2
        conn = sqlite3.connect(config.SNAPSHOT_PATH)
        assert read_meta(conn)["row_count"] == "1000"
        conn.close()


class TestFreshnessGate:
    """--max-age-hours lets a scheduled task fire often and cheaply.

    A logon-triggered task runs whenever the machine wakes. Without a gate it
    would re-extract an hour-old snapshot every time -- two minutes and a heavy
    query against a production view, for nothing.
    """

    def _build_live(self, tmp_path, monkeypatch, finished_at):
        """A live snapshot whose recorded build time is `finished_at`."""
        config = _redirect(tmp_path, monkeypatch)
        config.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        main_c, detect_c = split_columns(FAKE_VIEW_COLUMNS, [])
        conn = build_snapshot.create_snapshot(
            config.SNAPSHOT_PATH, main_c, detect_c
        )
        build_snapshot.write_meta(conn, {
            "row_count": 2, "finished_at": finished_at,
        })
        conn.close()
        return config

    def test_a_fresh_snapshot_is_left_alone(self, tmp_path, monkeypatch):
        pyodbc = pytest.importorskip("pyodbc")
        recent = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        self._build_live(tmp_path, monkeypatch, recent)

        # The gate must return BEFORE any connection is attempted, so a broken
        # gate fails loudly here instead of querying production.
        def forbidden(*a, **k):
            raise AssertionError("must not connect: the snapshot is fresh")
        monkeypatch.setattr(pyodbc, "connect", forbidden)

        assert build_snapshot.main(["--max-age-hours", "24"]) == 0
        assert "nothing to do" in _run_log_text(tmp_path)

    def test_a_stale_snapshot_is_rebuilt(self, tmp_path, monkeypatch):
        old = (datetime.datetime.now() - datetime.timedelta(hours=40)).isoformat()
        config = self._build_live(tmp_path, monkeypatch, old)
        _install_fake_driver(monkeypatch)

        assert build_snapshot.main(["--max-age-hours", "24"]) == 0
        text = _run_log_text(tmp_path)
        assert "rebuilding" in text
        conn = sqlite3.connect(config.SNAPSHOT_PATH)
        rebuilt = read_meta(conn)["row_count"]
        conn.close()
        assert rebuilt == "2"

    def test_no_snapshot_at_all_rebuilds(self, tmp_path, monkeypatch):
        _redirect(tmp_path, monkeypatch)
        _install_fake_driver(monkeypatch)
        assert build_snapshot.main(["--max-age-hours", "24"]) == 0
        assert "no readable snapshot age" in _run_log_text(tmp_path)

    def test_an_unreadable_build_time_rebuilds_rather_than_skipping(
        self, tmp_path, monkeypatch
    ):
        # Erring towards a rebuild is the safe direction: the cost is two
        # minutes, whereas wrongly skipping serves stale data indefinitely.
        config = self._build_live(tmp_path, monkeypatch, "not-a-timestamp")
        _install_fake_driver(monkeypatch)
        assert build_snapshot.main(["--max-age-hours", "24"]) == 0
        assert "no readable snapshot age" in _run_log_text(tmp_path)

    def test_without_the_flag_the_gate_does_not_apply(self, tmp_path, monkeypatch):
        recent = datetime.datetime.now().isoformat()
        self._build_live(tmp_path, monkeypatch, recent)
        _install_fake_driver(monkeypatch)
        # No --max-age-hours: an explicit manual rebuild always rebuilds.
        assert build_snapshot.main([]) == 0
        assert "nothing to do" not in _run_log_text(tmp_path)
