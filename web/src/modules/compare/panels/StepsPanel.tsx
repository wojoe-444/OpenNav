import { useState } from 'react'

import { NativeSelect } from '@/components/ui/native-select'
import type { Route, Step } from '@/lib/api'
import { formatDistance, formatStepDuration } from '@/lib/format'
import { cn } from '@/lib/utils'

import { Empty, Swatch } from '../bits'
import { routeLabel, SIDE_LABEL, SIDES, type Side } from '../sides'
import type { PanelProps } from './types'

/** Turn-by-turn steps of one route per side, in two aligned columns. Click a step to see it on the map. */
export function StepsPanel({ data, focus, setFocus, zoomTo }: PanelProps) {
  const [chosen, setChosen] = useState<Record<Side, number>>({ official: 0, modeled: 0 })
  const routes: Record<Side, Route[]> = {
    official: data.official?.routes ?? [],
    modeled: data.modeled?.routes ?? [],
  }
  const picked: Record<Side, Route | undefined> = {
    official: routes.official[chosen.official],
    modeled: routes.modeled[chosen.modeled],
  }
  const n = Math.max(picked.official?.steps.length ?? 0, picked.modeled?.steps.length ?? 0)
  const starts: Record<Side, number[]> = { official: cumulative(picked.official), modeled: cumulative(picked.modeled) }

  const cell = (side: Side, i: number) => {
    const s: Step | undefined = picked[side]?.steps[i]
    if (!s) return <td key={side} className="border-t" />
    const on = focus?.side === side && focus.route === chosen[side] && focus.step === i
    return (
      <td key={side} className="border-t p-0 align-top">
        <button
          type="button"
          onClick={() => {
            if (on) return setFocus(null)
            setFocus({ side, route: chosen[side], step: i })
            if (s.geometry.length) zoomTo(s.geometry)
          }}
          className={cn(
            'flex w-full flex-col gap-0.5 px-2 py-2 text-left text-sm transition-colors hover:bg-muted/60',
            on && 'bg-highlight-soft text-highlight-soft-foreground',
          )}
        >
          <span>{s.instruction}</span>
          {s.notes.map((note) => (
            <span key={note} className="text-xs text-warning-soft-foreground">
              {note}
            </span>
          ))}
          <span className="text-xs text-muted-foreground tabular-nums">
            {formatDistance(s.distance_m)} · {formatStepDuration(s.duration_s)} · at {formatDistance(starts[side][i])}
          </span>
        </button>
      </td>
    )
  }

  if (!data.official && !data.modeled) return <Empty>No routes.</Empty>
  return (
    <table className="w-full table-fixed">
      <thead className="sticky top-0 z-[1] bg-card">
        <tr>
          <th className="w-8" />
          {SIDES.map((side) => (
            <th key={side} className="px-2 pb-2 text-left">
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Swatch side={side} />
                {SIDE_LABEL[side]}
                <NativeSelect
                  aria-label={`${SIDE_LABEL[side]} route`}
                  className="min-w-0 flex-1 font-normal"
                  value={chosen[side]}
                  onChange={(e) => setChosen({ ...chosen, [side]: Number(e.target.value) })}
                  disabled={routes[side].length < 2}
                >
                  {routes[side].map((r, i) => (
                    <option key={i} value={i}>
                      {routeLabel(i)}: {r.summary}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: n }, (_, i) => (
          <tr key={i}>
            <td className="border-t pt-2 pr-1 text-right align-top text-xs text-muted-foreground tabular-nums">{i + 1}</td>
            {SIDES.map((side) => cell(side, i))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function cumulative(r: Route | undefined): number[] {
  const out: number[] = []
  let d = 0
  for (const s of r?.steps ?? []) {
    out.push(d)
    d += s.distance_m
  }
  return out
}
