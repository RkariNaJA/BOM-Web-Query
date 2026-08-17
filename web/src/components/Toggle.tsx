interface Props {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
}

/** A div rather than a checkbox because controls.css styles .toggle-track /
 *  .toggle-knob directly. role/aria-checked/tabIndex restore the semantics. */
export default function Toggle({ checked, onChange, label }: Props) {
  const flip = () => onChange(!checked)
  return (
    <div
      className={`toggle${checked ? ' on' : ''}`}
      role="switch"
      aria-checked={checked}
      tabIndex={0}
      onClick={flip}
      onKeyDown={(event) => {
        if (event.key === ' ' || event.key === 'Enter') {
          event.preventDefault()
          flip()
        }
      }}
    >
      <span className="toggle-track"><span className="toggle-knob" /></span>
      <span>{label}</span>
    </div>
  )
}
