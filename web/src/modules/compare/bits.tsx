import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import { SIDE_COLOR, type Side } from './sides'

export function Swatch({ side, alt, className }: { side: Side; alt?: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('inline-block h-1 w-5 shrink-0 rounded-full', alt && 'opacity-50', className)}
      style={{ background: SIDE_COLOR[side] }}
    />
  )
}

export function ScoreBadge({ total, className }: { total: number; className?: string }) {
  const variant = total >= 85 ? 'success' : total >= 60 ? 'warning' : 'destructive'
  return (
    <Badge variant={variant} className={cn('tabular-nums', className)}>
      {total.toFixed(1)} / 100
    </Badge>
  )
}

/** Signed difference of modeled vs official, e.g. "+1 min (+3%)", tinted when large. */
export function Delta({
  official,
  modeled,
  format,
  warnAt = 0.05,
}: {
  official: number | null | undefined
  modeled: number | null | undefined
  format: (v: number) => string
  warnAt?: number
}) {
  if (official == null || modeled == null || !official) return <span className="text-muted-foreground">–</span>
  const d = modeled - official
  const rel = d / official
  const sign = d > 0 ? '+' : d < 0 ? '−' : '±'
  return (
    <span
      className={cn(
        'tabular-nums',
        Math.abs(rel) >= warnAt * 2 ? 'text-destructive' : Math.abs(rel) >= warnAt ? 'text-warning-soft-foreground' : 'text-success',
      )}
    >
      {sign}
      {format(Math.abs(d))} ({sign}
      {Math.abs(rel * 100).toFixed(Math.abs(rel) < 0.1 ? 1 : 0)}%)
    </span>
  )
}

export function Section({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
        {actions}
      </div>
      {children}
    </section>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}
