import { Empty, ScoreBadge, Section } from '../bits'
import type { PanelProps } from './types'

const LABELS: Record<string, string> = {
  route_overlap: 'Path overlap (best routes)',
  duration: 'Time with traffic',
  static_duration: 'Free-flow time',
  distance: 'Distance',
  summary: 'Road summary',
  steps: 'Steps',
  warnings: 'Warnings',
  alternates: 'Alternates found',
  ranking: 'Route ranking',
  steps_roads: 'Roads named, in order',
  steps_count: 'Step count',
  steps_maneuvers: 'Maneuvers',
}

/** The 0-100 score from opennav/scoring.py, metric by metric. */
export function ScorePanel({ data }: PanelProps) {
  const s = data.score
  if (!s) return <Empty>{data.modeled_error ? 'The model failed, so there is no score.' : 'No score yet.'}</Empty>
  const weights = data.score_weights ?? {}
  const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1
  const top = Object.keys(weights)
  const sub = Object.keys(s.metrics).filter((k) => !(k in weights))
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <span className="text-4xl font-semibold tracking-tight tabular-nums">{s.total.toFixed(1)}</span>
        <ScoreBadge total={s.total} />
      </div>
      <Section title="Metrics (weight, points earned)">
        <ul className="flex flex-col gap-3 text-sm">
          {top.map((k) => (
            <Bar key={k} label={LABELS[k] ?? k} value={s.metrics[k] ?? 0} note={`${weights[k]} pts, earns ${((100 * weights[k] * (s.metrics[k] ?? 0)) / total).toFixed(1)}`} />
          ))}
        </ul>
      </Section>
      {sub.length > 0 && (
        <Section title="Step detail">
          <ul className="flex flex-col gap-3 text-sm">
            {sub.map((k) => (
              <Bar key={k} label={LABELS[k] ?? k} value={s.metrics[k]} />
            ))}
          </ul>
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        Each metric is 0 to 1 (1 = same as official). See opennav/scoring.py for how each is measured.
        {data.model_seconds !== undefined && ` Model ran in ${data.model_seconds} s.`}
      </p>
    </div>
  )
}

function Bar({ label, value, note }: { label: string; value: number; note?: string }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  const color = value >= 0.85 ? 'bg-success' : value >= 0.6 ? 'bg-warning' : 'bg-destructive'
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span>{label}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {note && <span className="mr-2">{note}</span>}
          {value.toFixed(2)}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </li>
  )
}
