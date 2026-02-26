import { useEffect, useState } from 'react'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import type { BacktestParams, BacktestJobSummary } from '../api/client'
import { Card } from '../components/common/Card'
import { Metric } from '../components/common/Metric'
import { colors } from '../theme/colors'

export function BacktestLab() {
  const { activeBacktest, setActiveBacktest, setDashboard, setEquityCurve, setTrades } = useStore()
  const [params, setParams] = useState<BacktestParams>({
    instrument: 'ES',
    profile: 'futures',
    fill_level: 2,
    engine: 'manual',
    data_file: '',
  })
  const [jobs, setJobs] = useState<BacktestJobSummary[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Poll for job list
  useEffect(() => {
    api.getBacktestJobs().then(setJobs).catch(() => {})
  }, [activeBacktest])

  // Poll active backtest progress
  useEffect(() => {
    if (!activeBacktest || activeBacktest.status !== 'running') return

    const interval = setInterval(async () => {
      try {
        const status = await api.getBacktestStatus(activeBacktest.job_id)
        setActiveBacktest(status)

        if (status.status === 'completed' || status.status === 'failed') {
          setRunning(false)
          // Refresh data
          api.getDashboard().then(setDashboard).catch(() => {})
          api.getEquityCurve().then(setEquityCurve).catch(() => {})
          api.getTrades().then(setTrades).catch(() => {})
          api.getBacktestJobs().then(setJobs).catch(() => {})
        }
      } catch {
        // ignore
      }
    }, 500)

    return () => clearInterval(interval)
  }, [activeBacktest, setActiveBacktest, setDashboard, setEquityCurve, setTrades])

  const handleRun = async () => {
    setError(null)
    setRunning(true)
    try {
      const result = await api.runBacktest(params)
      setActiveBacktest({
        job_id: result.job_id,
        status: 'running',
        progress: 0,
        total_bars: 0,
        params: params as unknown as Record<string, unknown>,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start backtest')
      setRunning(false)
    }
  }

  const progressPct =
    activeBacktest && activeBacktest.total_bars > 0
      ? (activeBacktest.progress / activeBacktest.total_bars) * 100
      : 0

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-bold">Backtest Lab</h2>

      <div className="grid grid-cols-3 gap-4">
        {/* Parameters */}
        <Card title="Parameters" className="col-span-1">
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-text-dim">Instrument</span>
              <select
                value={params.instrument}
                onChange={(e) => setParams({ ...params, instrument: e.target.value })}
                className="bg-bg border border-border rounded px-2 py-1.5 text-text text-xs"
              >
                <option value="ES">ES (S&P 500)</option>
                <option value="NQ">NQ (Nasdaq)</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs">
              <span className="text-text-dim">Fill Level</span>
              <select
                value={params.fill_level}
                onChange={(e) => setParams({ ...params, fill_level: Number(e.target.value) })}
                className="bg-bg border border-border rounded px-2 py-1.5 text-text text-xs"
              >
                <option value={1}>1 - Optimistic</option>
                <option value={2}>2 - Standard</option>
                <option value={3}>3 - Conservative</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs">
              <span className="text-text-dim">Engine</span>
              <select
                value={params.engine}
                onChange={(e) => setParams({ ...params, engine: e.target.value })}
                className="bg-bg border border-border rounded px-2 py-1.5 text-text text-xs"
              >
                <option value="manual">Manual (Fast)</option>
                <option value="nautilus">NautilusTrader</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs">
              <span className="text-text-dim">Data File (optional)</span>
              <input
                type="text"
                value={params.data_file}
                onChange={(e) => setParams({ ...params, data_file: e.target.value })}
                placeholder="Auto-discover from data/"
                className="bg-bg border border-border rounded px-2 py-1.5 text-text text-xs"
              />
            </label>

            <button
              onClick={handleRun}
              disabled={running}
              className={`mt-2 px-4 py-2 rounded text-xs font-bold uppercase tracking-wide transition-colors border-none cursor-pointer ${
                running
                  ? 'bg-border text-text-dim cursor-not-allowed'
                  : 'bg-blue text-bg hover:bg-blue/80'
              }`}
            >
              {running ? 'Running...' : 'Run Backtest'}
            </button>

            {error && (
              <div className="text-red text-xs mt-1">{error}</div>
            )}
          </div>
        </Card>

        {/* Progress & Results */}
        <Card title="Progress" className="col-span-2">
          {activeBacktest ? (
            <div className="flex flex-col gap-4">
              {/* Progress bar */}
              <div>
                <div className="flex justify-between text-xs text-text-dim mb-1">
                  <span>Job: {activeBacktest.job_id}</span>
                  <span className="uppercase font-bold" style={{
                    color: activeBacktest.status === 'completed' ? colors.green
                      : activeBacktest.status === 'failed' ? colors.red
                      : colors.amber
                  }}>
                    {activeBacktest.status}
                  </span>
                </div>
                <div className="w-full h-2 bg-bg rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${progressPct}%`,
                      backgroundColor:
                        activeBacktest.status === 'completed' ? colors.green
                          : activeBacktest.status === 'failed' ? colors.red
                          : colors.blue,
                    }}
                  />
                </div>
                <div className="flex justify-between text-[10px] text-text-dim mt-1">
                  <span>{activeBacktest.progress.toLocaleString()} bars</span>
                  <span>{activeBacktest.total_bars.toLocaleString()} total</span>
                </div>
              </div>

              {/* Results summary */}
              {activeBacktest.summary && (
                <div className="grid grid-cols-3 gap-4 mt-2">
                  <Metric
                    label="Trades"
                    value={activeBacktest.summary.trade_count}
                  />
                  <Metric
                    label="Total PnL"
                    value={`$${activeBacktest.summary.total_pnl.toFixed(0)}`}
                    color={activeBacktest.summary.total_pnl >= 0 ? colors.green : colors.red}
                  />
                  <Metric
                    label="Win Rate"
                    value={`${(activeBacktest.summary.win_rate * 100).toFixed(1)}%`}
                    color={activeBacktest.summary.win_rate >= 0.5 ? colors.green : colors.amber}
                  />
                  <Metric
                    label="Final Equity"
                    value={`$${activeBacktest.summary.final_equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                  />
                  <Metric
                    label="Max Drawdown"
                    value={`$${activeBacktest.summary.max_drawdown.toFixed(0)}`}
                    color={colors.red}
                  />
                  <Metric
                    label="Max DD %"
                    value={`${(activeBacktest.summary.max_drawdown_pct * 100).toFixed(2)}%`}
                    color={colors.red}
                  />
                </div>
              )}

              {activeBacktest.error && (
                <div className="text-red text-xs bg-red/10 p-2 rounded">
                  {activeBacktest.error}
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center h-32 text-text-dim text-xs">
              Configure parameters and click "Run Backtest" to start
            </div>
          )}
        </Card>
      </div>

      {/* Job history */}
      {jobs.length > 0 && (
        <Card title="History">
          <div className="flex flex-col gap-1">
            {jobs.map((j) => (
              <div key={j.job_id} className="flex items-center gap-4 text-xs px-2 py-1">
                <span className="text-text-dim font-mono">{j.job_id}</span>
                <span
                  className="uppercase font-bold text-[10px]"
                  style={{
                    color: j.status === 'completed' ? colors.green
                      : j.status === 'failed' ? colors.red
                      : colors.amber,
                  }}
                >
                  {j.status}
                </span>
                <span className="text-text-dim">
                  {j.progress.toLocaleString()}/{j.total_bars.toLocaleString()} bars
                </span>
                <span className="text-text-dim">
                  {Object.entries(j.params)
                    .filter(([k]) => k !== 'data_file')
                    .map(([k, v]) => `${k}=${v}`)
                    .join(', ')}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
