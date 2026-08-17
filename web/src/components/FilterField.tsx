import type { FilterSpec } from '../api/types'
import Combobox from './Combobox'
import DateRange from './DateRange'

/** Hint text only — purely cosmetic, falls back for any column not listed. */
const PLACEHOLDERS: Record<string, string> = {
  STYLE_NBR: 'e.g. AB1234',
  STYLE_SEASON: 'e.g. AB1234SU27',
  ITEM_NBR: 'e.g. 9000001',
  IM: 'e.g. FPLNI9000001',
}

interface Props {
  spec: FilterSpec
  values: Record<string, string>
  onChange: (param: string, value: string) => void
  onSubmit: () => void
}

export default function FilterField({ spec, values, onChange, onSubmit }: Props) {
  let note = spec.note
  let control

  if (spec.kind === 'date') {
    control = (
      <DateRange
        spec={spec}
        from={values[spec.param_from] ?? ''}
        to={values[spec.param_to] ?? ''}
        onChange={onChange}
        onSubmit={onSubmit}
      />
    )
    if (!note && spec.bounds) {
      note = `data spans ${spec.bounds.min} → ${spec.bounds.max}`
    }
  } else {
    control = (
      <Combobox
        column={spec.column}
        suggest={spec.suggest}
        placeholder={PLACEHOLDERS[spec.column] ?? `any ${spec.column}`}
        value={values[spec.param] ?? ''}
        onChange={(value) => onChange(spec.param, value)}
        onSubmit={onSubmit}
      />
    )
  }

  return (
    <label className="field">
      <span className="micro-label">{spec.column}</span>
      {control}
      {note && <span className="mono field-note">{note}</span>}
    </label>
  )
}
