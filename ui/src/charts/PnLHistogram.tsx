import { useMemo } from 'react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell } from 'recharts'
import { colors } from '../theme/colors'
import type { Trade } from '../api/client'

interface Props {
  trades: Trade[]
}

export function PnLHistogram({ trades }: Props) {
  const data = useMemo(() => {
    return trades
      .filter((t) => t.exit_price !== 0)
      .map((t, i) => ({
        idx: i + 1,
        pnl: t.pnl_dollars,
        grade: t.grade,
      }))
  }, [trades])

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-dim text-xs">
        No closed trades
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
        <XAxis
          dataKey="idx"
          tick={{ fontSize: 9, fill: colors.textDim }}
          stroke={colors.border}
        />
        <YAxis
          tick={{ fontSize: 9, fill: colors.textDim }}
          tickFormatter={(v) => `$${v}`}
          stroke={colors.border}
        />
        <Tooltip
          contentStyle={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 4,
            fontSize: 11,
            color: colors.text,
          }}
          formatter={(value) => [`$${Number(value).toFixed(2)}`, 'PnL']}
        />
        <Bar dataKey="pnl" radius={[2, 2, 0, 0]}>
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.pnl >= 0 ? colors.green : colors.red} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
