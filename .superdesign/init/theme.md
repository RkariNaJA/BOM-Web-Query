# Theme Tokens

**Status: GREENFIELD.** No `globals.css`, no `tailwind.config` — this file plus
`.superdesign/design-system.md` are the source of truth until `static/style.css` exists.

Direction chosen by the user: **E-Ink Paper** (light monochrome print-console).

```css
:root {
  /* Grounds */
  --paper:            #f4f1ea;              /* app canvas, warm paper */
  --paper-raised:     #faf8f3;              /* cards, header, filter panel, table container */

  /* Ink */
  --ink:              #141310;              /* primary text, filled glyphs, primary button */
  --ink-secondary:    rgba(20, 19, 16, 0.62);
  --ink-muted:        rgba(20, 19, 16, 0.42);
  --hairline:         rgba(20, 19, 16, 0.14); /* 1px, does ALL separating */
  --ink-wash:         rgba(20, 19, 16, 0.05); /* dot-grain texture, hover row */

  /* The only chroma on the page */
  --signal-red:       #c8321e;              /* NULL markers, errors, destructive confirm only */

  /* Type */
  --font-ui:   'IBM Plex Sans', 'Noto Sans Thai', system-ui, sans-serif;
  --font-data: 'IBM Plex Mono', 'Noto Sans Thai Looped', ui-monospace, monospace;

  /* Radii — tight */
  --r-sm: 2px;
  --r-md: 5px;
  --r-lg: 8px;

  /* Density */
  --row-h:    30px;   /* data row — tighter than the 44px source style; 60 cols demand it */
  --header-h: 52px;
  --cell-px:  10px;   /* horizontal cell padding */
}
```

## Hard rules

- **No drop shadows. No gradients.** 1px hairlines do all separation.
- **No zebra striping** on the table — hairline row dividers only.
- Hierarchy from **size and weight only**, never color.
- Micro-headers: uppercase, 10.5–11px, weight 600, `letter-spacing: 0.08em`, muted ink.
- Every number, code, id, and date renders in `--font-data` with
  `font-variant-numeric: tabular-nums` so 60 columns align down the page.
- Dot-grain texture (`radial-gradient(var(--ink-wash) 0.5px, transparent 0.5px)` on a 4px grid)
  is allowed **only** on the filter panel.
- Signal red is rationed: `NULL` cell markers, error banners, and the "this will export 362,733
  rows" warning. Nothing else.

## Thai text requirement (from real data)

`MASTER_BOM_STATUS` contains Thai values (e.g. `ไม่นับ`), and `BNR_REMARK` / `DESCRIPTION` may too.
Both font stacks **must** carry a Thai fallback or those cells render as tofu boxes.
