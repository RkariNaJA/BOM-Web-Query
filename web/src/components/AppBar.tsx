import { fmt } from '../utils/format'

/** The ink glyph vocabulary from style.css: filled = ready, half = working,
 *  empty = idle, red = error. */
export type ConnKind = 'idle' | 'ready' | 'working' | 'error'

interface Props {
  source: string
  connKind: ConnKind
  connText: string
  totalRows: number | null
  /** ISO timestamp from snapshot_meta.finished_at, or null if unknown. */
  builtAt: string | null
}

/** "14 Aug 00:41", or a warning past 36 hours -- a snapshot that stopped
 *  refreshing looks exactly like fresh data unless the age is on screen. */
function snapshotAge(builtAt: string | null): { text: string; stale: boolean } {
  if (!builtAt) return { text: 'age unknown', stale: true }
  const built = new Date(builtAt)
  if (Number.isNaN(built.getTime())) return { text: 'age unknown', stale: true }
  const hours = (Date.now() - built.getTime()) / 36e5
  const when = built.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
  return { text: `data as of ${when}`, stale: hours > 36 }
}

export default function AppBar({
  source, connKind, connText, totalRows, builtAt,
}: Props) {
  const age = snapshotAge(builtAt)
  return (
    <header className="appbar">
      <span className="wordmark">BOM Query</span>
      <span className="divider" />
      <span className="mono breadcrumb">{source}</span>
      <span className="spacer" />
      <span className="status">
        <span className={`glyph ${connKind}`} />
        <span className="status-text">{connText}</span>
      </span>
      <span className="divider" />
      <span className={`mono ${age.stale ? 'stale' : 'muted'}`}>{age.text}</span>
      <span className="divider" />
      <span className="mono muted">{fmt(totalRows)} rows</span>
    </header>
  )
}
