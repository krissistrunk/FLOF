import { useEffect, useCallback } from 'react'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { wsManager } from '../api/websocket'
import { Sidebar } from './Sidebar'
import { StatusBar } from './StatusBar'
import { FleetHealth } from '../panels/FleetHealth'
import { ToggleBoard } from '../panels/ToggleBoard'
import { GlassBox } from '../panels/GlassBox'
import { BacktestLab } from '../panels/BacktestLab'
import type { DashboardData } from '../api/client'

const panelMap = {
  'fleet-health': FleetHealth,
  'toggle-board': ToggleBoard,
  'glass-box': GlassBox,
  'backtest-lab': BacktestLab,
} as const

export function Layout() {
  const { activePanel, setDashboard, setLastUpdate, setError } = useStore()
  const ActivePanel = panelMap[activePanel]

  const fetchAll = useCallback(async () => {
    try {
      const data = await api.getDashboard()
      setDashboard(data)
      setLastUpdate(Date.now())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Connection failed')
    }
  }, [setDashboard, setLastUpdate, setError])

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 2000)

    // WebSocket for real-time updates
    wsManager.connect()
    const handleDashboard = (data: unknown) => {
      setDashboard(data as DashboardData)
      setLastUpdate(Date.now())
    }
    wsManager.on('dashboard', handleDashboard)

    return () => {
      clearInterval(interval)
      wsManager.off('dashboard', handleDashboard)
    }
  }, [fetchAll, setDashboard, setLastUpdate])

  return (
    <div className="h-screen flex flex-col bg-bg">
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-auto p-4">
          <ActivePanel />
        </main>
      </div>
      <StatusBar />
    </div>
  )
}
