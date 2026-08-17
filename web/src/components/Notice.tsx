interface Props {
  text: string
  onDismiss: () => void
}

export default function Notice({ text, onDismiss }: Props) {
  return (
    <div className="notice">
      <span className="glyph" />
      <span className="mono">{text}</span>
      <span className="spacer" />
      <button type="button" className="btn-text" onClick={onDismiss}>Dismiss</button>
    </div>
  )
}
