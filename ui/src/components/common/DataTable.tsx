import { useState } from 'react'

interface Column<T> {
  key: string
  label: string
  render?: (row: T) => React.ReactNode
  align?: 'left' | 'right' | 'center'
  width?: string
}

interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  onRowClick?: (row: T) => void
  maxHeight?: string
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  onRowClick,
  maxHeight = '400px',
}: DataTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const sorted = sortKey
    ? [...data].sort((a, b) => {
        const av = a[sortKey]
        const bv = b[sortKey]
        if (typeof av === 'number' && typeof bv === 'number') {
          return sortDir === 'asc' ? av - bv : bv - av
        }
        return sortDir === 'asc'
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av))
      })
    : data

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  return (
    <div className="overflow-auto" style={{ maxHeight }}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-border">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-2 py-1.5 text-text-dim font-medium uppercase tracking-wider cursor-pointer hover:text-text"
                style={{ textAlign: col.align || 'left', width: col.width }}
                onClick={() => handleSort(col.key)}
              >
                {col.label}
                {sortKey === col.key && (sortDir === 'asc' ? ' \u25B2' : ' \u25BC')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr
              key={i}
              className={`border-b border-border/50 ${onRowClick ? 'cursor-pointer hover:bg-border/30' : ''}`}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className="px-2 py-1.5 tabular-nums"
                  style={{ textAlign: col.align || 'left' }}
                >
                  {col.render ? col.render(row) : String(row[col.key] ?? '')}
                </td>
              ))}
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-2 py-8 text-center text-text-dim"
              >
                No data
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
