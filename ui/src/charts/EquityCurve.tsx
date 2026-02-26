import { useMemo } from 'react'
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'
import { colors } from '../theme/colors'
import type { EquityPoint } from '../api/client'

interface Props {
  data: EquityPoint[]
}

export function EquityCurve({ data }: Props) {
  const chartData = useMemo(() => {
    if (data.length === 0) return []

    let peak = data[0]?.equity || 100000
    return data.map((p) => {
      if (p.equity > peak) peak = p.equity
      const drawdown = ((p.equity - peak) / peak) * 100
      return {
        ts: p.timestamp_ns / 1_000_000, // ms
        equity: p.equity,
        drawdown,
      }
    })
  }, [data])

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-dim text-xs">
        No equity data. Run a backtest to populate.
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={colors.border} />
        <XAxis
          dataKey="ts"
          tick={{ fontSize: 9, fill: colors.textDim }}
          tickFormatter={(v) => new Date(v).toLocaleDateString()}
          stroke={colors.border}
        />
        <YAxis
          yAxisId="equity"
          tick={{ fontSize: 9, fill: colors.textDim }}
          tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
          stroke={colors.border}
          orientation="left"
        />
        <YAxis
          yAxisId="dd"
          tick={{ fontSize: 9, fill: colors.textDim }}
          tickFormatter={(v) => `${v.toFixed(1)}%`}
          stroke={colors.border}
          orientation="right"
        />
        <Tooltip
          contentStyle={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 4,
            fontSize: 11,
            color: colors.text,
          }}
          formatter={(value, name) => {
            const v = Number(value)
            if (name === 'equity') return [`$${v.toLocaleString()}`, 'Equity']
            return [`${v.toFixed(2)}%`, 'Drawdown']
          }}
          labelFormatter={(v) => new Date(v).toLocaleString()}
        />
        <Area
          yAxisId="dd"
          dataKey="drawdown"
          fill={colors.red}
          fillOpacity={0.15}
          stroke="none"
        />
        <Line
          yAxisId="equity"
          dataKey="equity"
          stroke={colors.green}
          strokeWidth={1.5}
          dot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
