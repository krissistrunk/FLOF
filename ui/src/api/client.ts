const BASE = '/api'

async function fetchJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }
  return res.json()
}

export const api = {
  getDashboard: () => fetchJSON<DashboardData>('/dashboard'),
  getPositions: () => fetchJSON<Position[]>('/positions'),
  getTrades: () => fetchJSON<Trade[]>('/trades'),
  getScoring: () => fetchJSON<ScoringData>('/scoring'),
  getRisk: () => fetchJSON<RiskData>('/risk'),
  getConfig: () => fetchJSON<Record<string, unknown>>('/config'),
  getToggles: () => fetchJSON<Toggle[]>('/config/toggles'),
  getEquityCurve: () => fetchJSON<EquityPoint[]>('/equity-curve'),
  getPois: () => fetchJSON<POI[]>('/pois'),
  setToggle: (id: string, enabled: boolean) =>
    postJSON<{ toggle_id: string; enabled: boolean }>(`/toggles/${id}`, { enabled }),
  nuclearFlatten: () => postJSON<{ status: string }>('/nuclear-flatten'),
  runBacktest: (params: BacktestParams) =>
    postJSON<{ job_id: string; status: string }>('/backtest/run', params),
  getBacktestStatus: (jobId: string) =>
    fetchJSON<BacktestStatus>(`/backtest/status/${jobId}`),
  getBacktestJobs: () => fetchJSON<BacktestJobSummary[]>('/backtest/jobs'),
}

// Types
export interface DashboardData {
  state: string
  equity: number
  peak_equity: number
  max_drawdown: number
  max_drawdown_pct: number
  current_price: number
  atr: number
  trade_count: number
  open_positions: number
  predator_state: string
  macro_bias: string | null
  regime: string
  win_rate: number
  profit_factor: number
  total_pnl: number
}

export interface Position {
  position_id: string
  direction: string
  grade: string
  entry_price: number
  stop_price: number
  target_price: number
  total_contracts: number
  remaining_contracts: number
  phase: string
  partial_filled: boolean
  breakeven_set: boolean
  highest_favorable: number
  entry_time_ns: number
  pnl_dollars: number
  pnl_r_multiple: number
  partial_pnl_dollars: number
}

export interface Trade {
  position_id: string
  direction: string
  grade: string
  score_total: number
  score_tier1: number
  score_tier2: number
  score_tier3: number
  entry_price: number
  stop_price: number
  target_price: number
  exit_price: number
  contracts: number
  pnl_dollars: number
  pnl_r_multiple: number
  exit_reason: string
  poi_type: string
  timestamp_ns: number
  exit_time_ns: number
}

export interface ScoringData {
  trades: Trade[]
  rejections: Rejection[]
  grade_distribution: Record<string, number>
}

export interface Rejection {
  reason: string
  gate: string
  timestamp_ns: number
  direction: string
  score: number
}

export interface RiskData {
  pillars: Record<string, Record<string, unknown>>
  gates: Record<string, Record<string, unknown>>
  is_flattened: boolean
  consecutive_losses: number
}

export interface Toggle {
  id: string
  name: string
  category: string
  enabled: boolean
  raw_value: boolean
  is_safety: boolean
  parents: string[]
  key: string
}

export interface EquityPoint {
  timestamp_ns: number
  equity: number
}

export interface POI {
  type: string
  price: number
  zone_high: number
  zone_low: number
  timeframe: string
  direction: string
  is_extreme: boolean
  is_decisional: boolean
  is_flip_zone: boolean
  is_sweep_zone: boolean
  is_unicorn: boolean
  has_inducement: boolean
  is_fresh: boolean
}

export interface BacktestParams {
  instrument?: string
  profile?: string
  fill_level?: number
  engine?: string
  data_file?: string
}

export interface BacktestStatus {
  job_id: string
  status: string
  progress: number
  total_bars: number
  params: Record<string, unknown>
  summary?: {
    trade_count: number
    total_pnl: number
    final_equity: number
    win_rate: number
    max_drawdown: number
    max_drawdown_pct: number
  }
  error?: string
}

export interface BacktestJobSummary {
  job_id: string
  status: string
  progress: number
  total_bars: number
  params: Record<string, unknown>
}
