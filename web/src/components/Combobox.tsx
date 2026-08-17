import { useEffect, useRef, useState } from 'react'
import { getDistinct } from '../api/client'
import { fmt } from '../utils/format'
import Icon from './Icon'

/** 2,405 options would be pointless to paint; the search narrows it. */
const MAX_SHOWN = 200

interface Props {
  column: string
  suggest: boolean
  placeholder: string
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
}

export default function Combobox({
  column, suggest, placeholder, value, onChange, onSubmit,
}: Props) {
  const [values, setValues] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  // A ref, not state: this must gate the fetch without triggering a re-render,
  // and it must survive across focus cycles.
  const requested = useRef(false)
  const host = useRef<HTMLDivElement>(null)

  /* Fetched on first focus, not at boot: each DISTINCT is a several-second
     query against a slow view, and most searches touch one or two fields. */
  async function ensureValues() {
    if (requested.current || !suggest) return
    requested.current = true
    setLoading(true)
    try {
      const data = await getDistinct(column)
      setValues(data.values)
    } catch {
      setValues([]) // not fatal: the field still takes free text
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    function onDocumentClick(event: MouseEvent) {
      if (!host.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onDocumentClick)
    return () => document.removeEventListener('click', onDocumentClick)
  }, [])

  const needle = value.trim().toUpperCase()
  const matches = values.filter((v) => v.toUpperCase().includes(needle))
  const shown = matches.slice(0, MAX_SHOWN)

  return (
    <div className="combo" ref={host}>
      <div className="combo-field">
        <Icon name="search" className="muted" />
        <input
          autoComplete="off"
          placeholder={placeholder}
          value={value}
          onFocus={() => { void ensureValues(); setOpen(true) }}
          onChange={(event) => { setOpen(true); onChange(event.target.value) }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') { setOpen(false); onSubmit() }
            if (event.key === 'Escape') setOpen(false)
          }}
        />
        <Icon name="chevron-down" className="muted" />
      </div>
      {open && (
        <div className="combo-list">
          {loading ? (
            <div className="combo-note">loading values…</div>
          ) : shown.length === 0 ? (
            <div className="combo-note">no match — free text is still accepted</div>
          ) : (
            <>
              {shown.map((option) => (
                <div
                  key={option}
                  onClick={() => { setOpen(false); onChange(option) }}
                >
                  {option}
                </div>
              ))}
              {matches.length > shown.length && (
                <div className="combo-note">
                  {fmt(matches.length - shown.length)} more — keep typing
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
