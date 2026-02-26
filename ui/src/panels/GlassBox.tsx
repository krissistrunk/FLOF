import { useEffect, useState } from 'react'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { Card } from '../components/common/Card'
import { Badge } from '../components/common/Badge'
import { DataTable } from '../components/common/DataTable'
import { GradeDistribution } from '../charts/GradeDistribution'
import { colors, gradeColors } from '../theme/colors'
import type { Trade, POI } from '../api/client'

export function GlassBox() {
  const { scoring, setScoring, pois, setPois } = useStore()
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)

  useEffect(() => {
    api.getScoring().then(setScoring).catch(() => {})
    api.getPois().then(setPois).catch(() => {})
  }, [setScoring, setPois])

  const tradeColumns = [
    {
      key: 'direction',
      label: 'Dir',
      width: '50px',
      render: (t: Trade) => (
        <Badge
          label={t.direction === 'LONG' ? 'L' : 'S'}
          color={t.direction === 'LONG' ? colors.green : colors.red}
        />
      ),
    },
    {
      key: 'grade',
      label: 'Grade',
      width: '50px',
      render: (t: Trade) => (
        <span style={{ color: gradeColors[t.grade] || colors.textDim, fontWeight: 'bold' }}>
          {t.grade}
        </span>
      ),
    },
    {
      key: 'score_total',
      label: 'Score',
      align: 'center' as const,
      width: '80px',
      render: (t: Trade) => (
        <span className="text-text-dim">
          <span className="text-text">{t.score_tier1}</span>/
          <span className="text-text">{t.score_tier2}</span>/
          <span className="text-text">{t.score_tier3}</span>
          {' = '}
          <span className="text-text font-bold">{t.score_total}</span>
        </span>
      ),
    },
    { key: 'entry_price', label: 'Entry', align: 'right' as const, render: (t: Trade) => t.entry_price.toFixed(2) },
    {
      key: 'exit_price',
      label: 'Exit',
      align: 'right' as const,
      render: (t: Trade) => (t.exit_price ? t.exit_price.toFixed(2) : '--'),
    },
    {
      key: 'pnl_dollars',
      label: 'PnL',
      align: 'right' as const,
      render: (t: Trade) => (
        <span style={{ color: t.pnl_dollars >= 0 ? colors.green : colors.red }}>
          {t.pnl_dollars >= 0 ? '+' : ''}${t.pnl_dollars.toFixed(0)}
        </span>
      ),
    },
    {
      key: 'pnl_r_multiple',
      label: 'R',
      align: 'right' as const,
      render: (t: Trade) => (
        <span style={{ color: t.pnl_r_multiple >= 0 ? colors.green : colors.red }}>
          {t.pnl_r_multiple >= 0 ? '+' : ''}{t.pnl_r_multiple.toFixed(2)}R
        </span>
      ),
    },
    { key: 'exit_reason', label: 'Reason', render: (t: Trade) => t.exit_reason || '--' },
  ]

  const rejectionColumns = [
    { key: 'gate', label: 'Gate', width: '60px' },
    { key: 'reason', label: 'Reason' },
    { key: 'direction', label: 'Dir', width: '50px' },
    { key: 'score', label: 'Score', align: 'right' as const },
  ]

  const poiColumns = [
    {
      key: 'type',
      label: 'Type',
      render: (p: POI) => (
        <span className="text-blue">{p.type.replace(/_/g, ' ')}</span>
      ),
    },
    { key: 'price', label: 'Price', align: 'right' as const, render: (p: POI) => p.price.toFixed(2) },
    { key: 'direction', label: 'Dir', width: '50px' },
    { key: 'timeframe', label: 'TF', width: '40px' },
    {
      key: 'flags',
      label: 'Flags',
      render: (p: POI) => {
        const flags: string[] = []
        if (p.is_fresh) flags.push('Fresh')
        if (p.is_flip_zone) flags.push('Flip')
        if (p.is_unicorn) flags.push('Unicorn')
        if (p.is_extreme) flags.push('Extreme')
        if (p.is_sweep_zone) flags.push('Sweep')
        return <span className="text-text-dim text-[9px]">{flags.join(', ') || '--'}</span>
      },
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-bold">Glass Box \u2014 Trade Forensics</h2>

      <div className="grid grid-cols-3 gap-4">
        {/* Trade table - 2 cols */}
        <Card title="Recent Trades" className="col-span-2">
          <DataTable<Trade>
            columns={tradeColumns}
            data={scoring?.trades || []}
            onRowClick={(t) => setSelectedTrade(t)}
            maxHeight="300px"
          />
        </Card>

        {/* Grade distribution */}
        <Card title="Grade Distribution" className="h-72">
          <div className="h-56">
            <GradeDistribution distribution={scoring?.grade_distribution || {}} />
          </div>
        </Card>
      </div>

      {/* Selected trade detail */}
      {selectedTrade && (
        <Card title={`Trade Detail: ${selectedTrade.position_id}`}>
          <div className="grid grid-cols-4 gap-4 text-xs">
            <div>
              <span className="text-text-dim">Direction: </span>
              <Badge
                label={selectedTrade.direction}
                color={selectedTrade.direction === 'LONG' ? colors.green : colors.red}
              />
            </div>
            <div>
              <span className="text-text-dim">Grade: </span>
              <span style={{ color: gradeColors[selectedTrade.grade], fontWeight: 'bold' }}>
                {selectedTrade.grade}
              </span>
            </div>
            <div>
              <span className="text-text-dim">POI: </span>
              <span>{selectedTrade.poi_type}</span>
            </div>
            <div>
              <span className="text-text-dim">Contracts: </span>
              <span>{selectedTrade.contracts}</span>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-4">
            <div className="bg-bg rounded p-3">
              <div className="text-[10px] text-text-dim uppercase mb-1">Tier 1 (Core SMC)</div>
              <div className="text-lg font-bold tabular-nums">{selectedTrade.score_tier1}/10</div>
            </div>
            <div className="bg-bg rounded p-3">
              <div className="text-[10px] text-text-dim uppercase mb-1">Tier 2 (Velez)</div>
              <div className="text-lg font-bold tabular-nums">{selectedTrade.score_tier2}/4</div>
            </div>
            <div className="bg-bg rounded p-3">
              <div className="text-[10px] text-text-dim uppercase mb-1">Tier 3 (VWAP+Liq)</div>
              <div className="text-lg font-bold tabular-nums">{selectedTrade.score_tier3}/3</div>
            </div>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4">
        {/* Rejections */}
        <Card title="Signal Rejections">
          <DataTable
            columns={rejectionColumns}
            data={scoring?.rejections || []}
            maxHeight="200px"
          />
        </Card>

        {/* Active POIs */}
        <Card title="Active POIs">
          <DataTable<POI>
            columns={poiColumns}
            data={pois || []}
            maxHeight="200px"
          />
        </Card>
      </div>
    </div>
  )
}
