import { useEffect, useRef, useState } from 'react'
import type { ColumnGroup } from '../api/types'
import Icon from './Icon'

interface Props {
  groups: ColumnGroup[]
  allColumns: string[]
  defaultColumns: string[]
  pinned: string
  visible: Set<string>
  onVisibleChange: (next: Set<string>) => void
}

export default function ColumnPicker({
  groups, allColumns, defaultColumns, pinned, visible, onVisibleChange,
}: Props) {
  const [open, setOpen] = useState(false)
  const [needle, setNeedle] = useState('')
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDocumentClick(event: MouseEvent) {
      if (!host.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onDocumentClick)
    return () => document.removeEventListener('click', onDocumentClick)
  }, [])

  function toggle(name: string) {
    if (name === pinned) return // pinned column cannot be hidden
    const next = new Set(visible)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    onVisibleChange(next)
  }

  const lower = needle.trim().toLowerCase()
  const matches = (name: string) => name.toLowerCase().includes(lower)

  return (
    <div ref={host} style={{ display: 'contents' }}>
      <button
        type="button"
        className="btn-ghost"
        onClick={() => setOpen((was) => !was)}
      >
        <Icon name="grid" />
        <span className="micro-label" style={{ color: 'inherit' }}>Columns</span>
        <span className="mono muted">{visible.size} / {allColumns.length} shown</span>
        <Icon name="chevron-down" />
      </button>

      {open && (
        <div className="picker">
          <div className="picker-head">
            <div className="picker-search">
              <Icon name="search" className="muted" />
              <input
                placeholder="filter columns…"
                autoComplete="off"
                value={needle}
                onChange={(event) => setNeedle(event.target.value)}
              />
            </div>
            <button type="button" className="btn-text"
              onClick={() => onVisibleChange(new Set(allColumns))}>All</button>
            <span className="divider" />
            <button type="button" className="btn-text"
              onClick={() => onVisibleChange(new Set(defaultColumns))}>Default</button>
            <span className="divider" />
            <button type="button" className="btn-text"
              onClick={() => onVisibleChange(new Set([pinned]))}>None</button>
          </div>

          {groups.map((group) => {
            const shown = group.columns.filter(matches)
            if (shown.length === 0) return null
            return (
              <div className="picker-group" key={group.title}>
                <div className="picker-group-head">
                  <span className="micro-label">{group.title}</span>
                </div>
                <div className="picker-grid">
                  {shown.map((name) => {
                    const locked = name === pinned
                    return (
                      <div
                        key={name}
                        className={`picker-item${locked ? ' locked' : ''}`}
                        onClick={() => toggle(name)}
                      >
                        <span className={`checkbox${visible.has(name) ? ' checked' : ''}`}>
                          <Icon name="tick" style={{ width: '9px', height: '9px' }} />
                        </span>
                        <span className="picker-name">{name}</span>
                        {locked && <span className="pin">pinned</span>}
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
