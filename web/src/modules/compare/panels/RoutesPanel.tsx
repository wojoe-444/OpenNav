import { formatDistance, formatDuration } from '@/lib/format'
import { cn } from '@/lib/utils'

import { Empty, Section, Swatch } from '../bits'
import { routeLabel, SIDE_LABEL, SIDES } from '../sides'
import type { PanelProps } from './types'

/** Every route on both sides (best and alternates), and how they pair up. */
export function RoutesPanel({ data, focus, setFocus, zoomTo }: PanelProps) {
  return (
    <div className="flex flex-col gap-6">
      {SIDES.map((side) => {
        const res = side === 'official' ? data.official : data.modeled
        return (
          <Section key={side} title={`${SIDE_LABEL[side]} routes`}>
            {!res ? (
              <Empty>Not available.</Empty>
            ) : (
              <ul className="flex flex-col gap-2">
                {res.routes.map((r, i) => {
                  const on = focus?.side === side && focus.route === i && focus.step === undefined
                  return (
                    <li key={i}>
                      <button
                        type="button"
                        onClick={() => {
                          setFocus(on ? null : { side, route: i })
                          if (!on) zoomTo(r.geometry)
                        }}
                        className={cn(
                          'flex w-full flex-col gap-1 rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60',
                          on && 'border-primary ring-2 ring-primary/30',
                        )}
                      >
                        <span className="flex items-center gap-2">
                          <Swatch side={side} alt={i > 0} />
                          <span className="text-xs font-medium text-muted-foreground">{routeLabel(i)}</span>
                          <span className="flex-1 truncate font-medium">{r.summary || '–'}</span>
                          <span className="font-semibold tabular-nums">{formatDuration(r.duration_s)}</span>
                        </span>
                        <span className="flex gap-3 pl-7 text-xs text-muted-foreground tabular-nums">
                          <span>{formatDistance(r.distance_m)}</span>
                          <span>free-flow {formatDuration(r.static_duration_s)}</span>
                          <span>{r.steps.length} steps</span>
                          {r.warnings.length > 0 && <span className="text-warning-soft-foreground">{r.warnings.length} warning(s)</span>}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </Section>
        )
      })}

      <Section title="Pairing (by path overlap)">
        {!data.score ? (
          <Empty>Run the model to pair routes.</Empty>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="pb-2 font-medium">Official</th>
                <th className="pb-2 font-medium">Modeled</th>
                <th className="pb-2 text-right font-medium">Overlap</th>
                <th className="pb-2 text-right font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {data.score.matches.map((m) => (
                <tr key={m.truth_index} className="border-t">
                  <td className="py-2 pr-2">
                    {routeLabel(m.truth_index)} <span className="text-muted-foreground">{m.truth_summary}</span>
                  </td>
                  <td className="py-2 pr-2">
                    {m.ours_index === null ? (
                      <span className="text-destructive">not found</span>
                    ) : (
                      <>
                        {routeLabel(m.ours_index)} <span className="text-muted-foreground">{m.ours_summary}</span>
                      </>
                    )}
                  </td>
                  <td className="py-2 text-right tabular-nums">{Math.round(m.overlap * 100)}%</td>
                  <td className="py-2 text-right tabular-nums">
                    {m.duration_err === null ? '–' : `${m.duration_err > 0 ? '+' : ''}${Math.round(m.duration_err * 100)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  )
}
