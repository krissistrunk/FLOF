import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts'
import { gradeColors, colors } from '../theme/colors'

interface Props {
  distribution: Record<string, number>
}

export function GradeDistribution({ distribution }: Props) {
  const data = Object.entries(distribution)
    .filter(([, v]) => v > 0)
    .map(([grade, count]) => ({
      name: grade,
      value: count,
      color: gradeColors[grade] || colors.textDim,
    }))

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-dim text-xs">
        No trades yet
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius="50%"
          outerRadius="80%"
          dataKey="value"
          strokeWidth={0}
        >
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.color} />
          ))}
        </Pie>
        <Tooltip
          contentStyle={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            borderRadius: 4,
            fontSize: 11,
            color: colors.text,
          }}
        />
        <Legend
          wrapperStyle={{ fontSize: 10, color: colors.textDim }}
          iconType="circle"
          iconSize={8}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}
