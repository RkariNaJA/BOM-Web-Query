import type { RowsPayload } from '../api/types'
import { fmt } from '../utils/format'
import Icon from './Icon'
import Segmented from './Segmented'

interface Props {
  payload: RowsPayload | null
  /** Either a live "12.3s elapsed…" ticker or the settled "query 23.1s". */
  elapsedText: string
  pageSize: number
  pageSizes: number[]
  onPageSizeChange: (next: number) => void
  onPrev: () => void
  onNext: () => void
  onExport: () => void
}

export default function FooterBar({
  payload, elapsedText, pageSize, pageSizes,
  onPageSizeChange, onPrev, onNext, onExport,
}: Props) {
  // No cap note: results are never capped now, so `capped` is always false.
  const matched = payload
    ? `${fmt(payload.total)} rows matched`
    : '— rows matched'
  const pageText = payload
    ? `page ${fmt(payload.page)} / ${fmt(payload.pages)}`
    : 'page — / —'

  return (
    <footer className="footerbar">
      <span className="mono">{matched}</span>
      <span className="divider" />
      <span className="mono muted">{elapsedText}</span>
      <span className="spacer" />
      <span className="micro-label">Page size</span>
      <Segmented
        values={pageSizes}
        value={pageSize}
        label={(value) => value.toLocaleString('en-US')}
        onPick={onPageSizeChange}
      />
      <span className="mono muted" style={{ fontSize: '11px' }}>min 100</span>
      <span className="spacer" />
      <div className="pager">
        <button type="button" className="btn-ghost" title="Previous page"
          disabled={!payload || payload.page <= 1} onClick={onPrev}>
          <Icon name="chevron-left" />
        </button>
        <span className="mono">{pageText}</span>
        <button type="button" className="btn-ghost" title="Next page"
          disabled={!payload || payload.page >= payload.pages} onClick={onNext}>
          <Icon name="chevron-right" />
        </button>
      </div>
      <span className="spacer" />
      <button type="button" className="btn-ghost" onClick={onExport}>
        <Icon name="download" />
        <span>Export CSV</span>
      </button>
      <span className="mono muted" style={{ fontSize: '11px' }}>full filtered set</span>
    </footer>
  )
}
