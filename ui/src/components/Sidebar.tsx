import { useStore } from '../store/useStore'

const panels = [
  { id: 'fleet-health' as const, label: 'Fleet Health', icon: '\u25C9' },
  { id: 'toggle-board' as const, label: 'Toggle Board', icon: '\u2699' },
  { id: 'glass-box' as const, label: 'Glass Box', icon: '\u25A3' },
  { id: 'backtest-lab' as const, label: 'Backtest Lab', icon: '\u25B6' },
]

export function Sidebar() {
  const { activePanel, setActivePanel } = useStore()

  return (
    <nav className="w-48 bg-surface border-r border-border flex flex-col shrink-0">
      <div className="p-4 border-b border-border">
        <h1 className="text-sm font-bold text-blue tracking-wide">FLOF MATRIX</h1>
        <p className="text-[10px] text-text-dim mt-0.5">Command Center</p>
      </div>
      <div className="flex flex-col gap-0.5 p-2 flex-1">
        {panels.map((p) => (
          <button
            key={p.id}
            onClick={() => setActivePanel(p.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded text-xs text-left transition-colors ${
              activePanel === p.id
                ? 'bg-blue/15 text-blue border-none'
                : 'text-text-dim hover:text-text hover:bg-border/30 border-none'
            }`}
          >
            <span className="text-sm">{p.icon}</span>
            {p.label}
          </button>
        ))}
      </div>
    </nav>
  )
}
