import { useStore } from '../store/useStore'
import { Badge } from './common/Badge'
import { predatorColors } from '../theme/colors'
import { colors } from '../theme/colors'

export function StatusBar() {
  const { dashboard, lastUpdate } = useStore()

  const d = dashboard
  const predatorState = d?.predator_state || 'DORMANT'
  const predatorColor = predatorColors[predatorState] || colors.textDim

  const formatTime = (ts: number) => {
    if (!ts) return '--:--:--'
    return new Date(ts).toLocaleTimeString()
  }

  const healthColor = d?.state === 'active' ? colors.green : colors.textDim

  return (
    <div className="h-8 bg-surface border-t border-border flex items-center px-4 text-[10px] shrink-0">
      {/* Left */}
      <div className="flex items-center gap-4 flex-1">
        <Badge label={predatorState} color={predatorColor} pulse={predatorState === 'KILL'} />
        {d && d.state !== 'idle' && (
          <>
            <span className="text-text-dim">
              Price <span className="text-text tabular-nums">{d.current_price.toFixed(2)}</span>
            </span>
            <span className="text-text-dim">
              ATR <span className="text-text tabular-nums">{d.atr.toFixed(2)}</span>
            </span>
          </>
        )}
      </div>

      {/* Center */}
      <div className="flex items-center gap-4 flex-1 justify-center">
        {d && d.state !== 'idle' && (
          <>
            <span className="text-text-dim">
              Equity{' '}
              <span className="text-text tabular-nums font-medium">
                ${d.equity.toLocaleString(undefined, { minimumFractionDigits: 0 })}
              </span>
            </span>
            <span className="text-text-dim">
              PnL{' '}
              <span
                className="tabular-nums font-medium"
                style={{ color: d.total_pnl >= 0 ? colors.green : colors.red }}
              >
                {d.total_pnl >= 0 ? '+' : ''}${d.total_pnl.toFixed(0)}
              </span>
            </span>
            <span className="text-text-dim">
              Open <span className="text-text tabular-nums">{d.open_positions}</span>
            </span>
          </>
        )}
      </div>

      {/* Right */}
      <div className="flex items-center gap-3 flex-1 justify-end">
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: healthColor }} />
          <span className="text-text-dim">{d?.state === 'active' ? 'ONLINE' : 'IDLE'}</span>
        </span>
        <span className="text-text-dim tabular-nums">{formatTime(lastUpdate)}</span>
      </div>
    </div>
  )
}
