import { useEffect, useState } from 'react'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { Card } from '../components/common/Card'
import { colors } from '../theme/colors'

const categoryLabels: Record<string, string> = {
  structure: 'Market Structure',
  execution: 'Execution',
  velez: 'Velez Momentum',
  risk: 'Risk Management',
  safety: 'Safety',
  multi_asset: 'Multi-Asset',
  options: 'Options',
}

const categoryOrder = ['structure', 'execution', 'velez', 'risk', 'safety', 'multi_asset', 'options']

export function ToggleBoard() {
  const { toggles, setToggles } = useStore()
  const [pending, setPending] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  useEffect(() => {
    api.getToggles().then(setToggles).catch(() => {})
  }, [setToggles])

  const handleToggle = async (id: string, current: boolean, isSafety: boolean) => {
    if (isSafety && current) {
      // Safety toggle — require double-click confirmation
      if (confirmId === id) {
        setConfirmId(null)
      } else {
        setConfirmId(id)
        setTimeout(() => setConfirmId(null), 3000)
        return
      }
    }

    setPending(id)
    try {
      await api.setToggle(id, !current)
      const updated = await api.getToggles()
      setToggles(updated)
    } catch (e) {
      // ignore
    }
    setPending(null)
  }

  const grouped = categoryOrder.map((cat) => ({
    category: cat,
    label: categoryLabels[cat] || cat,
    toggles: toggles.filter((t) => t.category === cat),
  }))

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold">Feature Toggles</h2>
        <span className="text-xs text-text-dim">
          {toggles.filter((t) => t.enabled).length}/{toggles.length} active
        </span>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {grouped.map(({ category, label, toggles: catToggles }) => (
          <Card key={category} title={label}>
            <div className="flex flex-col gap-1.5">
              {catToggles.map((t) => {
                const isDisabledByParent = t.raw_value && !t.enabled
                const isConfirming = confirmId === t.id
                const isPending = pending === t.id

                return (
                  <div
                    key={t.id}
                    className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${
                      isDisabledByParent ? 'opacity-40' : ''
                    }`}
                  >
                    {/* Toggle switch */}
                    <button
                      onClick={() => handleToggle(t.id, t.enabled, t.is_safety)}
                      disabled={isPending || isDisabledByParent}
                      className={`relative w-8 h-4 rounded-full transition-colors shrink-0 border-none cursor-pointer ${
                        isPending ? 'opacity-50' : ''
                      }`}
                      style={{
                        backgroundColor: t.enabled
                          ? t.is_safety
                            ? colors.red
                            : colors.green
                          : colors.border,
                      }}
                    >
                      <span
                        className="absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform"
                        style={{
                          transform: t.enabled ? 'translateX(16px)' : 'translateX(2px)',
                        }}
                      />
                    </button>

                    {/* ID */}
                    <span
                      className="font-mono text-text-dim w-7 shrink-0"
                      style={t.is_safety ? { color: colors.red } : undefined}
                    >
                      {t.id}
                    </span>

                    {/* Name */}
                    <span className="truncate flex-1">{t.name}</span>

                    {/* Parent indicator */}
                    {t.parents.length > 0 && (
                      <span className="text-text-dim text-[9px]">
                        \u2190 {t.parents.join(', ')}
                      </span>
                    )}

                    {/* Safety confirm */}
                    {isConfirming && (
                      <span className="text-red text-[9px] font-bold animate-pulse">
                        Click again to confirm
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
