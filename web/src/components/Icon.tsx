export type IconName =
  | 'search' | 'chevron-down' | 'chevron-left' | 'chevron-right'
  | 'grid' | 'download' | 'tick' | 'x'

interface Props {
  name: IconName
  className?: string
  style?: React.CSSProperties
}

export default function Icon({ name, className = '', style }: Props) {
  return (
    <svg className={`icon ${className}`.trim()} style={style} aria-hidden="true">
      <use href={`#i-${name}`} />
    </svg>
  )
}
