interface BadgeProps {
  label: string
  color: string
  pulse?: boolean
}

export function Badge({ label, color, pulse = false }: BadgeProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wide"
      style={{ color, borderColor: color, border: '1px solid' }}
    >
      {pulse && (
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ backgroundColor: color }}
        />
      )}
      {label}
    </span>
  )
}
