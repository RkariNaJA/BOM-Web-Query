interface Props<T> {
  values: readonly T[]
  value: T
  label: (value: T) => string
  onPick: (value: T) => void
}

/** Replaces buildSegmented(). Active state is derived from `value` rather than
 *  held in the DOM, so the row-limit and page-size controls stay in sync with
 *  the reducer even when something else changes them (e.g. Reset). */
export default function Segmented<T extends string | number>({
  values, value, label, onPick,
}: Props<T>) {
  return (
    <div className="segmented">
      {values.map((candidate) => (
        <button
          key={String(candidate)}
          type="button"
          className={candidate === value ? 'active' : ''}
          onClick={() => onPick(candidate)}
        >
          {label(candidate)}
        </button>
      ))}
    </div>
  )
}
