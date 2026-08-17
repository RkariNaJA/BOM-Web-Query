"""Tests for the SQLite-backed data layer.

Every test builds a real snapshot with the real extract functions, so the
schema under test is the one build_snapshot.py actually produces. Nothing here
touches SQL Server.
"""

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import build_snapshot  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from snapshot_schema import split_columns  # noqa: E402

COLUMNS = [
    {"name": "STYLE_NBR", "type": "nvarchar", "nullable": True},
    {"name": "BOM_ROW_NBR", "type": "int", "nullable": False},
    {"name": "Buy Code", "type": "nvarchar", "nullable": True},
    {"name": "STYLE_SEASON", "type": "nvarchar", "nullable": True},
    {"name": "ITEM_NBR", "type": "nvarchar", "nullable": True},
    {"name": "IM", "type": "nvarchar", "nullable": True},
    {"name": "BOM_UPDATE_DT", "type": "datetime", "nullable": True},
]

# (STYLE_NBR, BOM_ROW_NBR, Buy Code, STYLE_SEASON, ITEM_NBR, IM, BOM_UPDATE_DT)
ROWS = [
    ("S1", 2, "BC1", "SS26", "I1", "M1", datetime.datetime(2026, 8, 14, 13, 4, 5)),
    ("S1", 1, None, "SS26", "I2", "M2", datetime.datetime(2026, 8, 15, 9, 0, 0)),
    ("S2", 1, "BC2", "FW26", "I3", "M1", datetime.datetime(2026, 8, 16, 0, 0, 0)),
    ("100%", 1, "BC2", "FW26", "I4", "M3", None),
]


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    """A real single-table snapshot, with db pointed at it."""
    path = tmp_path / "bom.sqlite"
    main, detect = split_columns(COLUMNS, [])
    conn = build_snapshot.create_snapshot(path, main, detect)
    build_snapshot.load_rows(conn, len(main), len(detect), [ROWS])
    build_snapshot.build_indexes(conn, config.TEXT_FILTERS + config.DATE_FILTERS)
    build_snapshot.write_meta(conn, {
        "row_count": len(ROWS),
        "finished_at": "2026-08-17T09:29:56",
        "duration_seconds": 111,
        "source_view": "dbo.TEST_VIEW",
    })
    conn.close()

    monkeypatch.setattr(config, "SNAPSHOT_PATH", path)
    monkeypatch.setattr(db, "_columns_cache", None)
    return path


def rows_of(payload, column="STYLE_NBR"):
    i = payload["columns"].index(column)
    return [r[i] for r in payload["rows"]]


class TestSchema:
    def test_columns_exclude_the_surrogate_key(self, snapshot):
        assert "id" not in db.column_names()
        assert db.column_names() == [c["name"] for c in COLUMNS]

    def test_default_is_every_column(self, snapshot):
        # The whole point of the rewrite: nothing is expensive enough to hide.
        assert db.default_columns() == db.column_names()

    def test_unknown_requests_fall_back_to_everything(self, snapshot):
        assert db.resolve_columns(["nope"]) == db.column_names()

    def test_pinned_column_is_always_included(self, snapshot):
        assert config.PINNED_COLUMN in db.resolve_columns(["STYLE_NBR"])

    def test_resolve_preserves_schema_order(self, snapshot):
        assert db.resolve_columns(["IM", "STYLE_NBR"]) == [
            "STYLE_NBR", "BOM_ROW_NBR", "IM",
        ]

    def test_a_side_table_is_refused_rather_than_silently_dropped(
        self, tmp_path, monkeypatch
    ):
        # A snapshot from the two-table era would otherwise serve partial rows.
        path = tmp_path / "old.sqlite"
        main, detect = split_columns(COLUMNS, ["IM"])
        conn = build_snapshot.create_snapshot(path, main, detect)
        build_snapshot.load_rows(conn, len(main), len(detect), [])
        conn.close()
        monkeypatch.setattr(config, "SNAPSHOT_PATH", path)
        monkeypatch.setattr(db, "_columns_cache", None)
        with pytest.raises(RuntimeError, match="bom_detect"):
            db.columns()


class TestFilters:
    def test_exact_match(self, snapshot):
        payload = db.fetch_page({"STYLE_NBR": "S1"}, page=1, page_size=100)
        assert payload["total"] == 2

    def test_partial_match(self, snapshot):
        payload = db.fetch_page(
            {"STYLE_NBR": "S", "partial": True}, page=1, page_size=100
        )
        assert payload["total"] == 3

    def test_a_literal_percent_is_not_a_wildcard(self, snapshot):
        # SQLite has no default LIKE escape, so this needs an explicit ESCAPE
        # clause -- without it "100%" would match every row.
        payload = db.fetch_page(
            {"STYLE_NBR": "100%", "partial": True}, page=1, page_size=100
        )
        assert payload["total"] == 1
        assert rows_of(payload) == ["100%"]

    def test_filters_are_anded(self, snapshot):
        payload = db.fetch_page(
            {"STYLE_NBR": "S1", "IM": "M2"}, page=1, page_size=100
        )
        assert payload["total"] == 1

    def test_blank_filters_are_ignored(self, snapshot):
        payload = db.fetch_page({"STYLE_NBR": "  "}, page=1, page_size=100)
        assert payload["total"] == len(ROWS)


class TestDateFilters:
    def test_from_bound_is_inclusive(self, snapshot):
        payload = db.fetch_page(
            {"BOM_UPDATE_DT_from": "2026-08-15"}, page=1, page_size=100
        )
        assert payload["total"] == 2

    def test_to_bound_includes_the_whole_final_day(self, snapshot):
        # The trap this exists to catch: values are stored as
        # 'YYYY-MM-DD HH:MM:SS', so a naive <= '2026-08-14' would match nothing
        # on the 14th and silently drop a day off every range.
        payload = db.fetch_page(
            {"BOM_UPDATE_DT_to": "2026-08-14"}, page=1, page_size=100
        )
        assert payload["total"] == 1

    def test_a_range_spans_both_bounds(self, snapshot):
        payload = db.fetch_page(
            {"BOM_UPDATE_DT_from": "2026-08-14", "BOM_UPDATE_DT_to": "2026-08-15"},
            page=1, page_size=100,
        )
        assert payload["total"] == 2

    def test_bounds_report_the_day_not_the_timestamp(self, snapshot):
        assert db.date_bounds("BOM_UPDATE_DT") == {
            "min": "2026-08-14", "max": "2026-08-16",
        }

    def test_bounds_reject_a_non_date_column(self, snapshot):
        with pytest.raises(ValueError):
            db.date_bounds("STYLE_NBR")


class TestPaging:
    def test_ordering_is_deterministic(self, snapshot):
        # The view had no unique key so unfiltered paging could repeat or skip
        # rows; the snapshot's surrogate key makes the order total.
        first = db.fetch_page({}, page=1, page_size=100)["rows"]
        second = db.fetch_page({}, page=1, page_size=100)["rows"]
        assert first == second

    def test_pages_do_not_overlap(self, snapshot):
        a = db.fetch_page({}, page=1, page_size=100)
        b = db.fetch_page({}, page=2, page_size=100)
        assert b["page"] == 1  # clamped: only one page exists
        assert a["pages"] == 1

    def test_page_size_is_clamped_to_the_minimum(self, snapshot):
        assert db.fetch_page({}, page=1, page_size=1)["page_size"] == (
            config.MIN_PAGE_SIZE
        )

    def test_an_out_of_range_page_clamps_to_the_last(self, snapshot):
        assert db.fetch_page({}, page=99, page_size=100)["page"] == 1

    def test_payload_reports_every_column_as_available(self, snapshot):
        payload = db.fetch_page({}, page=1, page_size=100, visible=["STYLE_NBR"])
        assert payload["fetched_columns"] == db.column_names()
        assert payload["capped"] is False


class TestCountAndValues:
    def test_unfiltered_count(self, snapshot):
        total, _ = db.count_rows({})
        assert total == len(ROWS)

    def test_filtered_count(self, snapshot):
        total, _ = db.count_rows({"STYLE_NBR": "S1"})
        assert total == 2

    def test_distinct_skips_nulls_and_blanks(self, snapshot):
        assert db.distinct_values("Buy Code") == ["BC1", "BC2"]

    def test_distinct_works_for_any_column(self, snapshot):
        # No SUGGEST_COLUMNS whitelist any more -- DISTINCT is ~19 ms here.
        assert db.distinct_values("IM") == ["M1", "M2", "M3"]

    def test_distinct_rejects_an_unknown_column(self, snapshot):
        with pytest.raises(ValueError):
            db.distinct_values("nope; DROP TABLE bom")


class TestExportAndStatus:
    def test_csv_starts_with_a_bom_and_a_header(self, snapshot):
        chunks = list(db.iter_csv({}))
        assert chunks[0] == "﻿"
        assert chunks[1].startswith("STYLE_NBR,BOM_ROW_NBR")

    def test_csv_streams_every_filtered_row(self, snapshot):
        body = "".join(db.iter_csv({"STYLE_NBR": "S1"}))
        assert len(body.strip().splitlines()) == 3  # header + 2

    def test_status_reports_the_build_stamp(self, snapshot):
        status = db.test_connection()
        assert status["connected"] is True
        assert status["built_at"] == "2026-08-17T09:29:56"
        assert status["row_count"] == len(ROWS)

    def test_a_missing_snapshot_fails_clearly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "SNAPSHOT_PATH", tmp_path / "absent.sqlite")
        monkeypatch.setattr(db, "_columns_cache", None)
        with pytest.raises(RuntimeError, match="No snapshot"):
            db.columns()
