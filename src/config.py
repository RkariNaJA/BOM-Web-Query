"""Connection settings and tuning constants for BOM Query Web.

Where the database lives -- host, database, view, credentials -- is not in this
file: it comes from the git-ignored `.env` beside the project root (see
`.env.example`). Everything below the connection block is measured tuning that
belongs with the code.

Connection mirrors ../SQL Chat Bot/db.py, which is already proven against this
instance: Windows (Trusted) auth to the named instance over ODBC Driver 17.
"""

import os
from pathlib import Path

# --- Environment ---------------------------------------------------------

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env_file(path: Path) -> None:
    """Read KEY=VALUE lines from `.env` into the process environment.

    Hand-rolled rather than python-dotenv so running the app needs nothing
    beyond requirements.txt. A real environment variable always wins, which is
    what lets a deployment override the file without editing it.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Values are taken literally apart from optional surrounding quotes --
        # the server name contains a backslash, so no escape handling here.
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env_file(ENV_FILE)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _require_env(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in "
            f"(looked for {ENV_FILE})."
        )
    return value


# --- Connection ----------------------------------------------------------
DRIVER = _env("BOM_DB_DRIVER", "ODBC Driver 17 for SQL Server")
SERVER = _require_env("BOM_DB_SERVER")
DATABASE = _require_env("BOM_DB_DATABASE")
SCHEMA = _env("BOM_DB_SCHEMA", "dbo")
VIEW = _require_env("BOM_DB_VIEW")

# Blank credentials mean Windows (Trusted) auth, which is how this instance is
# reached today; setting both switches to SQL Server authentication.
_USER = _env("BOM_DB_USER")
_PASSWORD = _env("BOM_DB_PASSWORD")
_AUTH = f"UID={_USER};PWD={_PASSWORD};" if _USER else "Trusted_Connection=yes;"

CONNECTION_STRING = (
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"{_AUTH}"
)

# --- Snapshot ------------------------------------------------------------
# The nightly SQLite extract, built by scripts/build_snapshot.py and read by
# db.py. This is the app's only data source -- nothing at runtime contacts SQL
# Server; the connection settings above exist solely for the extract.
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data"
SNAPSHOT_PATH = SNAPSHOT_DIR / "bom.sqlite"
SNAPSHOT_NEW_PATH = SNAPSHOT_DIR / "bom.new.sqlite"
SNAPSHOT_PREV_PATH = SNAPSHOT_DIR / "bom.prev.sqlite"

# Columns to hold in a side table rather than in `bom`, for when a column is
# bulky enough that carrying it inline would slow every scan, count and sort.
#
# Empty, deliberately. This originally held the two nvarchar(max) DETECTION
# columns on the estimate that they were ~90% of the data volume. Measured
# across all 365,411 rows they are 15.5 MB of a 359 MB file -- 4.3%. They are
# expensive for the source view to *compute* (its FOR XML PATH aggregation) and
# cheap to *store*; the estimate conflated the two. See spec section 12.
#
# Adding a name here is all that is needed to split a column back out.
DETECT_COLUMNS: list[str] = []

# Rows read from the source cursor at a time. Larger batches mean fewer
# round trips but more memory held per batch.
EXTRACT_BATCH_SIZE = 2000

# Only used to project a completion time in the progress log.
EXPECTED_ROWS = 365_000  # ETA projection only; the real count comes from the view

# A new snapshot with less than this share of the previous row count is
# rejected rather than swapped in.
SANITY_THRESHOLD = 0.9

# --- Extract connection --------------------------------------------------
# Only the snapshot build talks to SQL Server now, and it deliberately runs
# with no statement timeout (the view is slow by design) -- Task Scheduler's
# own timeout is the wall-clock cap. See spec section 8.
CONNECT_TIMEOUT = 15  # seconds to establish a connection

# --- Paging --------------------------------------------------------------
# The row-limit control (100/1,000/10,000/ALL) is gone: it existed only to
# cap a 5-40 s query, and every query now runs in single-digit milliseconds.
# Page sizes offered in the footer. The user requires a 100-row minimum.
PAGE_SIZES = [100, 250, 500, 1000]
MIN_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 100

# --- Filtering / ordering ------------------------------------------------
# Text filters match with = or LIKE depending on the partial-match toggle.
# Every one is low-cardinality enough to offer a searchable value list;
# measured distinct counts against the live view:
#   STYLE_NBR 1,512 | STYLE_SEASON 2,405 | Buy Code 9 | ITEM_NBR 1,267 | IM 1,024
TEXT_FILTERS = ["STYLE_NBR", "STYLE_SEASON", "Buy Code", "ITEM_NBR", "IM"]

# Date filters match on an inclusive from/to day range.
DATE_FILTERS = ["BOM_UPDATE_DT"]

# Shown under a field in the UI where the data has a trap worth flagging.
FILTER_NOTES = {
    "Buy Code": "null on 87% of rows (316,021 of 365,411)",
}

# Paging order. The view had no unique key, so the unfiltered path used
# ORDER BY (SELECT NULL) and could repeat or skip rows across pages. The
# snapshot gives every row a surrogate primary key, so db.py now orders by
# these four plus `id` on every query and paging is finally deterministic.
ORDER_BY_COLUMNS = ["STYLE_NBR", "STYLE_SEASON", "BOM_ROW_NBR", "ITEM_NBR"]

# The pinned left-hand column in the UI; cannot be hidden.
PINNED_COLUMN = "BOM_ROW_NBR"

# --- Column picker grouping ----------------------------------------------
# Groups for the COLUMNS picker, expressed as inclusive 1-based ordinal ranges
# so they stay correct without restating all 60 names. Ranges follow the view's
# actual layout: style/merch header, buy-ready block, BOM line detail,
# detection text, dates, then zipper attributes.
#
# These ordinals address the source view's layout, which the snapshot's `bom`
# table reproduces exactly now that DETECT_COLUMNS is empty and no side table
# is created. If a column is ever split out again, these ranges shift and must
# be rebuilt from the `main_columns` names recorded in snapshot_meta.
COLUMN_GROUPS = [
    ("STYLE HEADER", 1, 21),
    ("BUY READY", 22, 27),
    ("BOM LINE", 28, 49),
    ("DETECTION", 50, 52),
    ("DATES", 53, 54),
    ("ZIPPER", 55, 60),
]
