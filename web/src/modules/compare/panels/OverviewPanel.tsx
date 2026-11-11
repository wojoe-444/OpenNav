import type { ReactNode } from 'react'
import { AlertTriangle, MapPinned } from 'lucide-react'

import type { Route } from '@/lib/api'
import { formatDistance, formatDuration } from '@/lib/format'
import { cn } from '@/lib/utils'

import { Delta, Empty, ScoreBadge, Section, Swatch } from '../bits'
import { SIDE_LABEL, SIDES, type Side } from '../sides'
import type { PanelProps } from './types'

const minutes = (s: number) => formatDuration(s)
const miles = (m: number) => formatDistance(m)

/** Best route of each side, field by field, with the difference. */
export function OverviewPanel({ data, setFocus, zoomTo }: PanelProps) {
  const best: Record<Side, Route | undefined> = {
    official: data.official?.routes[0],
    modeled: data.modeled?.routes[0] ?? undefined,
  }
  const rows: { label: string; value: (r: Route) => ReactNode; delta?: ReactNode }[] = [
    {
      label: 'Time with traffic',
      value: (r) => formatDuration(r.duration_s),
      delta: <Delta official={best.official?.duration_s} modeled={best.modeled?.duration_s} format={minutes} />,
    },
    {
      label: 'Free-flow time',
      value: (r) => formatDuration(r.static_duration_s),
      delta: <Delta official={best.official?.static_duration_s} modeled={best.modeled?.static_duration_s} format={minutes} />,
    },
    { label: 'Traffic delay', value: (r) => formatDuration(r.traffic_delay_s) },
    {
      label: 'Distance',
      value: (r) => formatDistance(r.distance_m),
      delta: <Delta official={best.official?.distance_m} modeled={best.modeled?.distance_m} format={miles} warnAt={0.01} />,
    },
    { label: 'Via', value: (r) => <span className="font-medium">{r.summary || '–'}</span> },
    { label: 'Steps', value: (r) => r.steps.length },
  ]
  const div = data.divergence
  return (
    <div className="flex flex-col gap-6">
      {data.score && (
        <div className="flex items-center gap-3 rounded-lg border bg-muted/40 px-4 py-3 text-sm">
          <span className="font-medium">Score</span>
          <ScoreBadge total={data.score.total} />
          <span className="text-muted-foreground">
            Best routes overlap {Math.round((data.score.metrics.route_overlap ?? 0) * 100)}%
          </span>
        </div>
      )}

      <Section title="Recommended route">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="pb-2 font-medium" />
              {SIDES.map((s) => (
                <th key={s} className="pb-2 font-medium">
                  <span className="inline-flex items-center gap-2">
                    <Swatch side={s} />
                    {SIDE_LABEL[s]}
                  </span>
                </th>
              ))}
              <th className="pb-2 font-medium">Difference</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t align-top">
                <td className="py-2 pr-3 text-muted-foreground">{row.label}</td>
                {SIDES.map((s) => (
                  <td key={s} className="py-2 pr-3 tabular-nums">
                    {best[s] ? row.value(best[s]) : '–'}
                  </td>
                ))}
                <td className="py-2">{row.delta ?? null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Where the routes split">
        {!div ? (
          <Empty>{data.official ? "Run the model to see where the paths differ." : "No official answer to compare against."}</Empty>
        ) : div.modeled_only.length + div.official_only.length === 0 ? (
          <Empty>The recommended paths match end to end (within 25 m).</Empty>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {(['official_only', 'modeled_only'] as const).flatMap((k) =>
              div[k].map((d, i) => (
                <li key={`${k}${i}`}>
                  <button
                    type="button"
                    onClick={() => {
                      setFocus(null)
                      zoomTo(d.geometry)
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted"
                  >
                    <MapPinned className="size-4 text-destructive" />
                    <Swatch side={k === 'official_only' ? 'official' : 'modeled'} />
                    <span className="flex-1">
                      {k === 'official_only' ? 'Only official drives' : 'Only modeled drives'} {formatDistance(d.length_m)}
                    </span>
                    <span className="text-xs text-muted-foreground">zoom</span>
                  </button>
                </li>
              )),
            )}
          </ul>
        )}
      </Section>

      <Section title="Warnings and traffic">
        <div className="grid grid-cols-2 gap-4 text-sm">
          {SIDES.map((s) => {
            const r = best[s]
            const res = s === 'official' ? data.official : data.modeled
            return (
              <div key={s} className="flex flex-col gap-2">
                <span className="inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Swatch side={s} />
                  {SIDE_LABEL[s]}
                </span>
                {!r ? (
                  <Empty>–</Empty>
                ) : (
                  <>
                    {r.warnings.length === 0 && <Empty>No warnings</Empty>}
                    {r.warnings.map((w) => (
                      <p key={w} className="flex gap-2">
                        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
                        {w}
                      </p>
                    ))}
                    {r.traffic_note && <p className="text-muted-foreground">{r.traffic_note}</p>}
                    {res?.comparison_note && <p className="text-muted-foreground">{res.comparison_note}</p>}
                    {r.congestion.length > 0 && (
                      <ul className="flex flex-col gap-1">
                        {r.congestion.map((c, i) => (
                          <li key={i} className="flex items-center gap-2">
                            <span
                              className={cn(
                                'size-2 rounded-full',
                                c.level === 'TRAFFIC_JAM' ? 'bg-destructive' : 'bg-warning',
                              )}
                            />
                            {c.level === 'TRAFFIC_JAM' ? 'Jam' : 'Slow'} on {c.road ?? 'unnamed road'},{' '}
                            {formatDistance(c.distance_m)}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </div>
            )
          })}
        </div>
      </Section>
    </div>
  )
}
