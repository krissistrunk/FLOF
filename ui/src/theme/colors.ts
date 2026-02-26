export const colors = {
  bg: '#0a0a0f',
  surface: '#12121a',
  border: '#1e1e2e',
  text: '#e0e0e8',
  textDim: '#6b6b7b',
  green: '#00d084',
  red: '#ff4757',
  blue: '#4a9eff',
  amber: '#ffb347',
  gradeAPlus: '#00d084',
  gradeA: '#4a9eff',
  gradeB: '#ffb347',
  gradeC: '#6b6b7b',
} as const

export const predatorColors: Record<string, string> = {
  DORMANT: colors.textDim,
  SCOUTING: colors.blue,
  STALKING: colors.amber,
  KILL: colors.red,
}

export const gradeColors: Record<string, string> = {
  'A+': colors.gradeAPlus,
  A: colors.gradeA,
  B: colors.gradeB,
  C: colors.gradeC,
}
