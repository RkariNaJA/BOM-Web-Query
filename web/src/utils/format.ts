export function fmt(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toLocaleString('en-US')
}

/** The results table is written as an HTML string for performance, so this is
 *  the only thing between database content and injected markup. `&` must be
 *  replaced first or the other replacements' entities get double-escaped. */
export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    // The original escapes only the four above, and every attribute this app
    // generates is double-quoted, so this is defence in depth rather than a
    // live fix: it renders identically and keeps the function safe if a future
    // caller ever builds a single-quoted attribute.
    .replace(/'/g, '&#39;')
}
