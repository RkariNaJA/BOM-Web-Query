import type { DateFilterSpec } from '../api/types'

interface Props {
  spec: DateFilterSpec
  from: string
  to: string
  onChange: (param: string, value: string) => void
  onSubmit: () => void
}

export default function DateRange({ spec, from, to, onChange, onSubmit }: Props) {
  const bounds = spec.bounds
  const fields: Array<{ param: string; value: string; edge: 'from' | 'to' }> = [
    { param: spec.param_from, value: from, edge: 'from' },
    { param: spec.param_to, value: to, edge: 'to' },
  ]

  return (
    <div className="date-range">
      {fields.map((field, index) => (
        <span key={field.param} style={{ display: 'contents' }}>
          {index === 1 && <span className="mono muted">→</span>}
          <div className="combo-field">
            <input
              type="date"
              aria-label={`${spec.column} ${field.edge}`}
              // Absent until the background warm-up finishes; the inputs simply
              // go unbounded until then rather than blocking on it.
              min={bounds?.min}
              max={bounds?.max}
              value={field.value}
              onChange={(event) => onChange(field.param, event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') onSubmit() }}
            />
          </div>
        </span>
      ))}
    </div>
  )
}
