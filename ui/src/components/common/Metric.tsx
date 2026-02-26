interface MetricProps {
  label: string
  value: string | number
  sub?: string
  color?: string
}

export function Metric({ label, value, sub, color }: MetricProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-text-dim text-[10px] uppercase tracking-wider">{label}</span>
      <span className="text-xl font-bold tabular-nums" style={color ? { color } : undefined}>
        {value}
      </span>
      {sub && <span className="text-text-dim text-xs tabular-nums">{sub}</span>}
    </div>
  )
}
