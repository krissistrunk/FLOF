import { useEffect } from 'react'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { Card } from '../components/common/Card'
import { Metric } from '../components/common/Metric'
import { Badge } from '../components/common/Badge'
import { EquityCurve } from '../charts/EquityCurve'
import { PnLHistogram } from '../charts/PnLHistogram'
import { colors, predatorColors } from '../theme/colors'

export function FleetHealth() {
  const {
    dashboard,
    equityCurve,
    setEquityCurve,
    trades,
    setTrades,
    positions,
    setPositions,
  } = useStore()

  useEffect(() => {
    api.getEquityCurve().then(setEquityCurve).catch(() => {})
    api.getTrades().then(setTrades).catch(() => {})
    api.getPositions().then(setPositions).catch(() => {})
  }, [setEquityCurve, setTrades, setPositions])

  const d = dashboard

  const equityChange = d && d.peak_equity > 0
    ? ((d.equity - d.peak_equity) / d.peak_equity) * 100
    : 0

  const closedTrades = trades.filter((t) => t.exit_price !== 0)
  const wins = closedTrades.filter((t) => t.pnl_dollars > 0).length
  const losses = closedTrades.filter((t) => t.pnl_dollars < 0).length

  return (
    <div className="flex flex-col gap-4">
      {/* Top row: Key metrics */}
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <Metric
            label="Equity"
            value={d ? `$${d.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '--'}
            sub={d ? `Peak: $${d.peak_equity.toLocaleString(undefined, { maximumFractionDigits: 0 })} (${equityChange >= 0 ? '+' : ''}${equityChange.toFixed(2)}%)` : undefined}
            color={d && d.equity >= d.peak_equity ? colors.green : colors.text}
          />
        </Card>
        <Card>
          <Metric
            label="Win Rate"
            value={d ? `${(d.win_rate * 100).toFixed(1)}%` : '--'}
            sub={`${wins}W / ${losses}L`}
            color={d && d.win_rate >= 0.5 ? colors.green : d && d.win_rate > 0 ? colors.amber : colors.textDim}
          />
        </Card>
        <Card>
          <Metric
            label="Max Drawdown"
            value={d ? `$${d.max_drawdown.toFixed(0)}` : '--'}
            sub={d ? `${(d.max_drawdown_pct * 100).toFixed(2)}%` : undefined}
            color={d && d.max_drawdown > 0 ? colors.red : colors.textDim}
          />
        </Card>
        <Card>
          <Metric
            label="Profit Factor"
            value={d ? (d.profit_factor === Infinity ? '\u221E' : d.profit_factor.toFixed(2)) : '--'}
            sub={d ? `PnL: ${d.total_pnl >= 0 ? '+' : ''}$${d.total_pnl.toFixed(0)}` : undefined}
            color={d && d.profit_factor > 1 ? colors.green : d && d.profit_factor > 0 ? colors.amber : colors.textDim}
          />
        </Card>
      </div>

      {/* Middle row: Charts */}
      <div className="grid grid-cols-2 gap-4">
        <Card title="Equity Curve" className="h-72">
          <div className="h-56">
            <EquityCurve data={equityCurve} />
          </div>
        </Card>
        <Card title="Trade PnL" className="h-72">
          <div className="h-56">
            <PnLHistogram trades={trades} />
          </div>
        </Card>
      </div>

      {/* Bottom row: Status */}
      <div className="grid grid-cols-3 gap-4">
        <Card title="Predator State">
          <div className="flex items-center gap-3">
            <Badge
              label={d?.predator_state || 'DORMANT'}
              color={predatorColors[d?.predator_state || 'DORMANT']}
              pulse={d?.predator_state === 'KILL'}
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-xs text-text-dim">
                Bias: <span className="text-text">{d?.macro_bias || 'None'}</span>
              </span>
              <span className="text-xs text-text-dim">
                Regime: <span className="text-text">{d?.regime || 'neutral'}</span>
              </span>
            </div>
          </div>
        </Card>
        <Card title="Open Positions">
          <div className="flex flex-col gap-1">
            <span className="text-2xl font-bold tabular-nums">{positions.length}</span>
            {positions.length > 0 && (
              <div className="flex flex-col gap-0.5">
                {positions.map((p) => (
                  <div key={p.position_id} className="flex items-center gap-2 text-xs">
                    <Badge
                      label={p.direction}
                      color={p.direction === 'LONG' ? colors.green : colors.red}
                    />
                    <span className="text-text-dim">{p.grade}</span>
                    <span className="tabular-nums">{p.entry_price.toFixed(2)}</span>
                    <span
                      className="tabular-nums"
                      style={{ color: p.pnl_dollars >= 0 ? colors.green : colors.red }}
                    >
                      {p.pnl_dollars >= 0 ? '+' : ''}${p.pnl_dollars.toFixed(0)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
        <Card title="Infrastructure">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs">
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: d?.state === 'active' ? colors.green : colors.textDim }}
              />
              <span>Strategy: {d?.state || 'idle'}</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full bg-green" />
              <span>API: online</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-text-dim">
              <span>Trades processed: {d?.trade_count || 0}</span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
