import { create } from 'zustand'
import type { DashboardData, Trade, Toggle, EquityPoint, Position, ScoringData, RiskData, POI, BacktestStatus } from '../api/client'

type Panel = 'fleet-health' | 'toggle-board' | 'glass-box' | 'backtest-lab'

interface Store {
  // Navigation
  activePanel: Panel
  setActivePanel: (panel: Panel) => void

  // Dashboard data
  dashboard: DashboardData | null
  setDashboard: (data: DashboardData) => void

  // Positions
  positions: Position[]
  setPositions: (data: Position[]) => void

  // Trades
  trades: Trade[]
  setTrades: (data: Trade[]) => void

  // Toggles
  toggles: Toggle[]
  setToggles: (data: Toggle[]) => void

  // Equity curve
  equityCurve: EquityPoint[]
  setEquityCurve: (data: EquityPoint[]) => void

  // Scoring
  scoring: ScoringData | null
  setScoring: (data: ScoringData) => void

  // Risk
  risk: RiskData | null
  setRisk: (data: RiskData) => void

  // POIs
  pois: POI[]
  setPois: (data: POI[]) => void

  // Backtest
  activeBacktest: BacktestStatus | null
  setActiveBacktest: (data: BacktestStatus | null) => void

  // Loading state
  loading: boolean
  setLoading: (loading: boolean) => void

  // Error
  error: string | null
  setError: (error: string | null) => void

  // Last update
  lastUpdate: number
  setLastUpdate: (ts: number) => void
}

export const useStore = create<Store>((set) => ({
  activePanel: 'fleet-health',
  setActivePanel: (panel) => set({ activePanel: panel }),

  dashboard: null,
  setDashboard: (data) => set({ dashboard: data }),

  positions: [],
  setPositions: (data) => set({ positions: data }),

  trades: [],
  setTrades: (data) => set({ trades: data }),

  toggles: [],
  setToggles: (data) => set({ toggles: data }),

  equityCurve: [],
  setEquityCurve: (data) => set({ equityCurve: data }),

  scoring: null,
  setScoring: (data) => set({ scoring: data }),

  risk: null,
  setRisk: (data) => set({ risk: data }),

  pois: [],
  setPois: (data) => set({ pois: data }),

  activeBacktest: null,
  setActiveBacktest: (data) => set({ activeBacktest: data }),

  loading: false,
  setLoading: (loading) => set({ loading }),

  error: null,
  setError: (error) => set({ error }),

  lastUpdate: 0,
  setLastUpdate: (ts) => set({ lastUpdate: ts }),
}))
