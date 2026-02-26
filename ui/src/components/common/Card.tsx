interface CardProps {
  title?: string
  children: React.ReactNode
  className?: string
}

export function Card({ title, children, className = '' }: CardProps) {
  return (
    <div className={`bg-surface border border-border rounded-lg p-4 ${className}`}>
      {title && (
        <h3 className="text-text-dim text-xs uppercase tracking-wider mb-3 font-medium">
          {title}
        </h3>
      )}
      {children}
    </div>
  )
}
