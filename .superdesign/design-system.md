# BOM Query Web — Design System

## 1. Product context

An internal read-only data explorer over a single SQL Server view:
`the source view` on the instance named in `.env` — **60 columns, 362,733 rows**.
The view joins apparel style/merch header data to per-line Bill-of-Materials detail (fabric, trim,
colorway, vendor, zipper attributes) for a garment manufacturer.

**Users:** merchandisers and BOM/development staff who already know the column names. They are
power users reading codes, not browsing a catalogue.

**Jobs to be done**
1. Pull the BOM lines for one style (`STYLE_NBR`) or one style-season (`STYLE_SEASON`) and read them.
2. Eyeball a slice of the view quickly — first 100 / 1,000 / 10,000 rows — without waiting on the
   full 362k.
3. Get the complete filtered set out to Excel via CSV.

**Hard performance truth that shapes the UI:** the view is slow. `COUNT(*)` measured ~20 s and even
`SELECT TOP 3` measured ~36 s. Every query needs a visible pending state with an elapsed timer, and
the UI must never look frozen or silently idle. This is a design constraint, not an afterthought.

## 2. Screens

One screen only. No nav, no sidebar, no routing.

`/` — **BOM Query**: header bar → filter panel → results table → pagination footer.

## 3. Key features

| Feature | Behaviour |
|---|---|
| Row-limit segmented control | `100` / `1,000` / `10,000` / `ALL`. Default `100`. `ALL` does **not** dump every row into the DOM — it pages through server-side at 500/page and enables CSV export. |
| `STYLE_NBR` filter | Searchable combobox over distinct values, free text also accepted. |
| `STYLE_SEASON` filter | Same pattern. |
| Partial match toggle | Off = exact `=`. On = `LIKE '%value%'`. |
| Search / Reset | One solid-ink primary `SEARCH`; ghost `Reset` clears filters back to defaults. |
| Results table | 58 of 60 columns by default (see below). Sticky header row, sticky `BOM_ROW_NBR` first column, hairline rules between every column as well as every row, horizontal + vertical scroll inside its own container. The page body never scrolls sideways. |
| Expensive columns | `TEXT_USE_OF_DETECT` and `TEXT_Color_Code_OF_DETECT` are **opt-in**: measured at +60 s and +57 s per query against a 12.4 s baseline. `TEXT_Color_Name_OF_DETECT` (+9 s) stays visible. The picker shows each cost, and ticking one flags the Search button rather than firing a two-minute query silently. |
| Pagination footer | `N rows matched`, `page X / Y`, prev/next. |
| CSV export | Streams the full filtered set — no row cap. Confirms first when the set is large. |
| Query status | Elapsed-seconds readout while pending; row count + duration when done; red banner on error. |

## 4. Visual direction — E-Ink Paper

The whole app reads as **near-black ink printed on warm paper**, like a monochrome e-reader or a
printed spec sheet. Flat and border-only. **Data density IS the aesthetic.**

### Palette — the complete allowed set

| Token | Value | Use |
|---|---|---|
| `--paper` | `#f4f1ea` | app canvas |
| `--paper-raised` | `#faf8f3` | header bar, filter panel, table container, footer |
| `--ink` | `#141310` | primary text, filled glyphs, the one primary button |
| `--ink-secondary` | `rgba(20,19,16,0.62)` | column headers, secondary values |
| `--ink-muted` | `rgba(20,19,16,0.42)` | micro-labels, meta, `NULL` placeholders |
| `--hairline` | `rgba(20,19,16,0.14)` | every 1px border and divider |
| `--ink-wash` | `rgba(20,19,16,0.05)` | dot-grain texture, row hover |
| `--signal-red` | `#c8321e` | **rationed**: error banner, large-export warning, nothing else |

**No other colors exist.** No blue, green, amber, or violet. No drop shadows. No gradients (the
4px radial dot-grain on the filter panel is the only texture). Hierarchy comes from size and weight
only, never from color.

### Type

- **UI** — `'IBM Plex Sans', 'Noto Sans Thai', system-ui, sans-serif` at 400/500/600.
- **Data** — `'IBM Plex Mono', 'Noto Sans Thai Looped', ui-monospace, monospace` with
  `font-variant-numeric: tabular-nums`, for **every** cell value, column header, row count, code,
  date, and duration. 60 columns only stay readable if the figures align vertically.
- **Micro-labels** — uppercase, 10.5–11px, weight 600, `letter-spacing: 0.08em`, muted ink.
- Data cells 11.5–12px; the table is meant to be dense.

**Thai support is mandatory.** Real values in `MASTER_BOM_STATUS` are Thai (`ไม่นับ`), and
`BNR_REMARK` / `DESCRIPTION` may be. Both stacks carry a Thai fallback so no cell renders as tofu.

### Geometry & density

Radii 2–8px, tight. Buttons are rectangles with tight corners; the single primary action is a solid
`#141310` fill with paper-colored text. Data rows ~30px (tighter than a typical 44px console row —
60 columns demand it). Cell padding 10px horizontal. Table row dividers are 1px hairlines with
**no zebra striping**.

### Ink glyph language

State is drawn in ink, never color — reuse one vocabulary everywhere:

- connected / ready — solid filled ink circle
- querying — half-filled ring (subtle pulse)
- idle / not yet run — empty hairline ring
- error — the only red glyph, a filled `#c8321e` circle with a paper-colored `x`
- `NULL` cell — a muted `—` em dash, never the literal word "null"

### Motion

Near-none, in keeping with e-ink. Allowed: the querying-ring pulse, a 120ms hairline-color
transition on row hover, and an instant (no-fade) table swap on new results. No slide-ins, no
skeleton shimmer — a mono elapsed-time counter communicates progress instead.

## 5. Sample content for mockups

**Fabricated, not real.** Style numbers, item numbers, vendor names and team names below are
invented; only the *shape* of the data is real. Do not paste production rows into this file —
it is committed to a public repository.

Column order (first 20 of 60): `BOM_ROW_NBR`, `MSC_CODE`, `MSC_LEVEL_1`, `MSC_LEVEL_2`,
`MSC_LEVEL_3`, `SILHOUETTE`, `SEASON_CD`, `SEASON_YR`, `STYLE_NM`, `STYLE_NBR`, `STYLE_SEASON`,
`BASE_STYLE`, `MER_TEAM`, `MER_DEV`, `PROGRAM`, `FOCUS_PRIORITY`, `Glb_Buy_Dt`, `Buy Code`, `CAP`,
`STYLE_CW_CD` … then `STATUS`, `SSC`, `HIT_BR_STATUS`, `ITEM_TYPE_1`, `ITEM_TYPE_2`, `ITEM_NBR`,
`IM`, `BOM Type`, `MASTER_BOM_STATUS`, `ITEM_COLOR_CD`, `ITEM_COLOR_NM`, `VEND_CD`, `VEND_NM`,
`UOM`, `Tape`, `Teeth`, `Puller`, `Slider`, `Stopper`, `Condition`.

Sample rows in the real shape (style AB1234, SU 2027 — invented values):

```
BOM_ROW_NBR  MSC_CODE  MSC_LEVEL_1  SILHOUETTE        SEASON  YR    STYLE_NBR  STYLE_NM
1            SMPL      MENS         HIP LENGTH JKT    SU      2027  AB1234     M SMP LWT WVN JACKET LS-C
2            SMPL      MENS         HIP LENGTH JKT    SU      2027  AB1234     M SMP LWT WVN JACKET LS-C
3            SMPL      MENS         HIP LENGTH JKT    SU      2027  AB1234     M SMP LWT WVN JACKET LS-C

MER_TEAM  PROGRAM       STYLE_CW_CD  STATUS  SSC             HIT_BR_STATUS
SAMPLE1   PROGRAM ONE  PEO          P       AB1234SU27PEO   Buy Not Ready

row 1: ITEM_TYPE_1 STATEMENT, ITEM_NBR 9000003,   IM TEXT,          BOM Type TEXT, MASTER_BOM_STATUS ไม่นับ
row 2: ITEM_TYPE_1 FABRIC / WOVEN, ITEM_NBR 9000001, IM FPLNI9000001, BOM Type BOM, MASTER_BOM_STATUS FB&Trim,
       ITEM_COLOR_CD 00A, ITEM_COLOR_NM BLACK, VEND_CD SMP1, VEND_NM SAMPLE TEXTILE CO LTD, UOM LY
row 3: ITEM_TYPE_1 FABRIC / WOVEN, ITEM_NBR 9000002, IM FPLNI9000002, BOM Type BOM, MASTER_BOM_STATUS FB&Trim,
       ITEM_COLOR_CD 00A, ITEM_COLOR_NM BLACK, VEND_CD SMP1, VEND_NM SAMPLE TEXTILE CO LTD, UOM LY
```

Sample filter values: `STYLE_NBR` = `AB1234`; `STYLE_SEASON` = `AB1234SU27`.
Approximate totals: `362,733 rows` total, `726 pages` at 500/page.

## 6. Project requirements

- Desktop-first — this is a wide-table tool used on office monitors. Below `lg`, the filter fields
  stack and the table keeps scrolling horizontally in its container.
- Read-only. No create/edit/delete affordances anywhere in the UI.
- The wide table must scroll **inside its own `overflow-x: auto` container**; the page body must
  never scroll horizontally.
- Show the source object (`<database> / <schema>.<view>`) in the header so users know exactly
  what they are looking at.
