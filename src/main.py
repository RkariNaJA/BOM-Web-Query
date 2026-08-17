"""FastAPI app for BOM Query Web -- a read-only explorer over the SQL Server
view named in `.env`, served from a local SQLite snapshot of it.

Run from this directory:
    uvicorn main:app --port 8000
Then open http://127.0.0.1:8000

Endpoints:
    GET /                -> the single page
    GET /api/meta        -> columns (grouped), total rows, connection state
    GET /api/distinct    -> distinct values for a filterable column
    GET /api/rows        -> one page of results
    GET /api/export.csv  -> streaming CSV of the full filtered set (uncapped)
"""

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
import db

STATIC_DIR = Path(__file__).parent / "static"

# Maps a view column to its query-string parameter name. Keeps the wire format
# tidy for columns whose real names are awkward in a URL (e.g. "Buy Code").
_PARAM_BY_COLUMN = {
    "STYLE_NBR": "style_nbr",
    "STYLE_SEASON": "style_season",
    "Buy Code": "buy_code",
    "ITEM_NBR": "item_nbr",
    "IM": "im",
}


# No lifespan warm-up: it existed to pre-pay for the column list, the distinct
# lists and the total count, none of which cost anything against the snapshot.
app = FastAPI(title="BOM Query Web")


def _columns_from_query(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [c for c in (part.strip() for part in value.split(",")) if c]


def _filters(
    style_nbr: str,
    style_season: str,
    buy_code: str,
    item_nbr: str,
    im: str,
    updated_from: str,
    updated_to: str,
    partial: bool,
) -> dict:
    return {
        "STYLE_NBR": style_nbr,
        "STYLE_SEASON": style_season,
        "Buy Code": buy_code,
        "ITEM_NBR": item_nbr,
        "IM": im,
        "BOM_UPDATE_DT_from": updated_from,
        "BOM_UPDATE_DT_to": updated_to,
        "partial": partial,
    }


@app.get("/api/meta")
def meta():
    """Column metadata grouped for the picker, plus the unfiltered total."""
    try:
        columns = db.columns()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    groups = []
    for title, start, end in config.COLUMN_GROUPS:
        members = columns[start - 1 : end]
        if members:
            groups.append({"title": title, "columns": [c["name"] for c in members]})

    # Any column beyond the configured ranges still has to appear in the picker.
    grouped = {name for g in groups for name in g["columns"]}
    leftover = [c["name"] for c in columns if c["name"] not in grouped]
    if leftover:
        groups.append({"title": "OTHER", "columns": leftover})

    try:
        total, _ = db.count_rows({})
    except Exception:
        total = None

    try:
        snapshot = db.snapshot_meta()
    except Exception:
        snapshot = {}

    # The filter bar is built from this spec, so adding a filter is a config
    # change plus a query param -- the frontend needs no per-column code.
    filters = [
        {
            "column": name,
            "kind": "text",
            "param": _PARAM_BY_COLUMN[name],
            # Every filter gets a value list now: SELECT DISTINCT cost ~5 s
            # against the view and ~19 ms against the snapshot.
            "suggest": True,
            "note": config.FILTER_NOTES.get(name, ""),
        }
        for name in config.TEXT_FILTERS
    ]
    for name in config.DATE_FILTERS:
        filters.append({
            "column": name,
            "kind": "date",
            "param_from": "updated_from",
            "param_to": "updated_to",
            "suggest": False,
            "note": config.FILTER_NOTES.get(name, ""),
            "bounds": db.date_bounds(name),
        })

    return {
        "columns": columns,
        "groups": groups,
        "pinned": config.PINNED_COLUMN,
        "filters": filters,
        # Every column, always. Nothing is expensive enough to hide.
        "default_columns": db.default_columns(),
        "page_sizes": config.PAGE_SIZES,
        "min_page_size": config.MIN_PAGE_SIZE,
        "default_page_size": config.DEFAULT_PAGE_SIZE,
        "total_rows": total,
        "source": f"{config.DATABASE} / {config.SCHEMA}.{config.VIEW}",
        # How old the data is. With a snapshot this is correctness, not a
        # nicety -- the UI shows it so nobody reads yesterday's rows as today's.
        "snapshot": {
            "built_at": snapshot.get("finished_at"),
            "row_count": int(snapshot["row_count"]) if "row_count" in snapshot else None,
            "duration_seconds": (
                int(snapshot["duration_seconds"])
                if "duration_seconds" in snapshot else None
            ),
        },
    }


@app.get("/api/distinct")
def distinct(column: str = Query(...)):
    """Distinct values feeding a searchable combobox."""
    try:
        return {"column": column, "values": db.distinct_values(column)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")


@app.get("/api/rows")
def rows(
    page: int = Query(1, ge=1),
    # Clamped up to MIN_PAGE_SIZE in db.fetch_page rather than rejected here, so
    # a hand-edited URL degrades to the 100-row minimum instead of a 422.
    page_size: int = Query(config.DEFAULT_PAGE_SIZE, ge=1),
    style_nbr: str = Query(""),
    style_season: str = Query(""),
    buy_code: str = Query(""),
    item_nbr: str = Query(""),
    im: str = Query(""),
    updated_from: str = Query("", description="BOM_UPDATE_DT from, YYYY-MM-DD"),
    updated_to: str = Query("", description="BOM_UPDATE_DT to, inclusive"),
    partial: bool = Query(False),
    columns: str | None = Query(None),
):
    try:
        return db.fetch_page(
            filters=_filters(
                style_nbr, style_season, buy_code, item_nbr, im,
                updated_from, updated_to, partial,
            ),
            page=page,
            page_size=page_size,
            visible=_columns_from_query(columns),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")


@app.get("/api/export.csv")
def export_csv(
    style_nbr: str = Query(""),
    style_season: str = Query(""),
    buy_code: str = Query(""),
    item_nbr: str = Query(""),
    im: str = Query(""),
    updated_from: str = Query("", description="BOM_UPDATE_DT from, YYYY-MM-DD"),
    updated_to: str = Query("", description="BOM_UPDATE_DT to, inclusive"),
    partial: bool = Query(False),
    columns: str | None = Query(None),
):
    """Stream the complete filtered set as CSV. Deliberately uncapped -- this is
    the path that gives the user every matching row without touching the DOM."""
    filters = _filters(
        style_nbr, style_season, buy_code, item_nbr, im,
        updated_from, updated_to, partial,
    )
    visible = _columns_from_query(columns)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = (
        style_nbr or style_season or item_nbr or im or buy_code or "all"
    ).replace(" ", "_")
    # From config, not hardcoded: point .env at another view and the export
    # should be named after it.
    filename = f"{config.VIEW}-{slug}-{stamp}.csv"

    try:
        stream = db.iter_csv(filters, visible)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")

    return StreamingResponse(
        stream,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
def health():
    try:
        return db.test_connection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot connect: {exc}")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
