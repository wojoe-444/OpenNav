import { useCallback, useMemo, useState } from 'react'
import { Layers, Loader2, RefreshCw } from 'lucide-react'

import { BASEMAPS, RouteMap, type BasemapId, type MapLine, type MapPin, type MapSync } from '@/components/map/RouteMap'
import { Button } from '@/components/ui/button'
import { NativeSelect } from '@/components/ui/native-select'
import { Segmented } from '@/components/ui/segmented'
import { Switch } from '@/components/ui/switch'
import { api, type Comparison, type LatLon } from '@/lib/api'
import { formatDistance, formatDuration } from '@/lib/format'
import { navigate, routeParams, useRoute, withParams } from '@/lib/router'
import { cn } from '@/lib/utils'
import { useQuery } from '@/modules/client'

import { ScoreBadge, Swatch } from './bits'
import { routeLabel, SIDE_COLOR, SIDE_LABEL, SIDES, type Focus, type Side } from './sides'
import { PANELS } from './panels'

type LayerKey = 'official' | 'officialAlts' | 'modeled' | 'modeledAlts' | 'divergence'
const LAYER_LABEL: Record<LayerKey, string> = {
  official: 'Official best',
  officialAlts: 'Official alternates',
  modeled: 'Modeled best',
  modeledAlts: 'Modeled alternates',
  divergence: 'Where they split',
}
type MapMode = 'overlay' | 'split'

/**
 * Official vs modeled for one case: the map (both answers overlaid, or two
 * synced maps side by side) and a side panel whose tabs come from ./panels.
 * Page state lives in the URL (#/compare?case=...&tab=...) so a view can be
 * bookmarked or shared in a note.
 */
export default function ComparePage() {
  const [path] = useRoute()
  const params = routeParams(path)
  const cases = useQuery('cases', api.cases)
  const caseId = params.get('case') || (cases.data?.find((c) => c.has_truth)?.id ?? cases.data?.[0]?.id ?? null)
  const tab = params.get('tab') ?? PANELS[0].id
  const mode: MapMode = params.get('map') === 'split' ? 'split' : 'overlay'
  const setParam = (k: string, v: string | null) =>
    navigate(withParams('/compare', { ...Object.fromEntries(params), case: caseId, [k]: v }))

  const cmp = useQuery(caseId, () => api.compare(caseId!))
  const [rerunning, setRerunning] = useState(false)
  const rerun = async () => {
    if (!caseId) return
    setRerunning(true)
    try {
      cmp.set(await api.rerun(caseId))
      void cases.refresh()
    } finally {
      setRerunning(false)
    }
  }

  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    official: true,
    officialAlts: true,
    modeled: true,
    modeledAlts: true,
    divergence: true,
  })
  const [basemap, setBasemapState] = useState<BasemapId>(() => {
    const v = localStorage.getItem('opennav.basemap')
    return v && v in BASEMAPS ? (v as BasemapId) : 'muted'
  })
  const setBasemap = (b: BasemapId) => {
    localStorage.setItem('opennav.basemap', b)
    setBasemapState(b)
  }
  const [focus, setFocus] = useState<Focus | null>(null)
  const [zoom, setZoom] = useState<{ points: LatLon[]; key: string } | null>(null)
  const zoomTo = useCallback((points: LatLon[]) => setZoom({ points, key: `${Date.now()}` }), [])
  const [view, setView] = useState<MapSync['view']>()
  const sync: MapSync = useMemo(() => ({ view, set: setView }), [view])

  const data = cmp.data && cmp.data.case.id === caseId ? cmp.data : undefined
  const fitAll = useMemo(() => (data ? allPoints(data) : []), [data])
  const fit = zoom?.points ?? fitAll
  const fitKey = zoom?.key ?? `case:${caseId}:${data ? 'loaded' : 'none'}`

  const linesFor = useCallback(
    (sides: Side[]) => (data ? buildLines(data, sides, layers, focus, setFocus) : []),
    [data, layers, focus],
  )
  const pins = useMemo(() => (data ? buildPins(data) : []), [data])
  const Panel = (PANELS.find((p) => p.id === tab) ?? PANELS[0]).component

  return (
    <div className="flex h-full min-h-0">
      {/* Map area */}
      <div className="relative flex min-w-0 flex-1">
        {mode === 'split' ? (
          SIDES.map((s) => (
            <div key={s} className="relative flex min-w-0 flex-1 border-r last:border-r-0">
              <RouteMap
                className="h-full w-full"
                lines={linesFor([s])}
                pins={pins}
                fit={fit}
                fitKey={fitKey}
                sync={sync}
                syncId={s}
                basemap={basemap}
              />
              <div className="pointer-events-none absolute top-3 left-14 z-[500] flex items-center gap-2 rounded-md bg-card/90 px-2.5 py-1 text-xs font-medium shadow-elevation-1">
                <Swatch side={s} />
                {SIDE_LABEL[s]}
              </div>
            </div>
          ))
        ) : (
          <RouteMap className="h-full w-full" lines={linesFor(SIDES)} pins={pins} fit={fit} fitKey={fitKey} basemap={basemap} />
        )}

        <LayerCard layers={layers} setLayers={setLayers} basemap={basemap} setBasemap={setBasemap} />
        {(cmp.fetching || rerunning) && (
          <div className="absolute top-3 left-1/2 z-[500] flex -translate-x-1/2 items-center gap-2 rounded-full bg-card px-3 py-1.5 text-sm shadow-elevation-2">
            <Loader2 className="size-4 animate-spin" />
            {data ? 'Re-running the model…' : 'Running the model (the first run loads the road graph)…'}
          </div>
        )}
      </div>

      {/* Side panel */}
      <aside className="flex w-[min(44rem,48vw)] shrink-0 flex-col border-l bg-card">
        <div className="flex flex-col gap-3 border-b p-4">
          <div className="flex items-center gap-2">
            <NativeSelect
              aria-label="Case"
              className="min-w-0 flex-1"
              value={caseId ?? ''}
              onChange={(e) => {
                setFocus(null)
                setZoom(null)
                navigate(withParams('/compare', { ...Object.fromEntries(params), case: e.target.value }))
              }}
            >
              {cases.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.id}
                  {c.has_truth ? '' : ' (no official answer)'}
                </option>
              ))}
            </NativeSelect>
            <Button variant="outline" size="sm" onClick={() => void rerun()} disabled={!data || rerunning} title="Run the model again (after changing the engine or params)">
              <RefreshCw className={cn(rerunning && 'animate-spin')} />
              Re-run model
            </Button>
          </div>
          {data && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>
                {data.case.origin} → {data.case.destination}
              </span>
              <span>Departs {formatDeparture(data)}</span>
              {data.score && <ScoreBadge total={data.score.total} />}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Segmented
              aria-label="Panel"
              value={tab}
              onChange={(v) => setParam('tab', v)}
              options={PANELS.map((p) => ({ value: p.id, label: p.label }))}
            />
            <Segmented
              aria-label="Map layout"
              value={mode}
              onChange={(v) => setParam('map', v === 'overlay' ? null : v)}
              options={[
                { value: 'overlay', label: 'Overlay' },
                { value: 'split', label: 'Side by side' },
              ]}
            />
          </div>
          {focus && data && <FocusBar data={data} focus={focus} clear={() => setFocus(null)} />}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {cases.error && <ErrorBox title="Could not load cases" message={cases.error.message} />}
          {cmp.error && <ErrorBox title="Could not load this case" message={cmp.error.message} />}
          {data?.official_error && <ErrorBox tone="warning" title="No official answer" message={data.official_error} />}
          {data?.modeled_error && (
            <ErrorBox title="The model failed" message={data.modeled_error} detail={data.modeled_traceback} />
          )}
          {!data && !cmp.error && <p className="text-sm text-muted-foreground">Loading…</p>}
          {data && (data.official || data.modeled) && (
            <Panel data={data} focus={focus} setFocus={setFocus} zoomTo={zoomTo} />
          )}
        </div>
      </aside>
    </div>
  )
}

function LayerCard({
  layers,
  setLayers,
  basemap,
  setBasemap,
}: {
  layers: Record<LayerKey, boolean>
  setLayers: (l: Record<LayerKey, boolean>) => void
  basemap: BasemapId
  setBasemap: (b: BasemapId) => void
}) {
  // Starts collapsed so it doesn't cover the route; remembered per browser.
  const [open, setOpenState] = useState(() => localStorage.getItem('opennav.layersOpen') === '1')
  const setOpen = (v: boolean) => {
    localStorage.setItem('opennav.layersOpen', v ? '1' : '0')
    setOpenState(v)
  }
  return (
    <div className="absolute right-3 bottom-6 z-[500] rounded-lg border bg-card/95 text-sm shadow-elevation-2 backdrop-blur">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className={cn('flex items-center gap-2 px-3 py-2 font-medium', open ? 'w-64' : 'w-auto')}
      >
        <Layers className="size-4" />
        Layers
      </button>
      {open && (
        <ul className="flex w-64 flex-col gap-2 border-t px-3 py-2">
          {(Object.keys(LAYER_LABEL) as LayerKey[]).map((k) => (
            <li key={k} className="flex items-center gap-2">
              {k === 'divergence' ? (
                <span className="inline-block h-1.5 w-5 rounded-full bg-destructive/50" />
              ) : (
                <Swatch side={k.startsWith('official') ? 'official' : 'modeled'} alt={k.endsWith('Alts')} />
              )}
              <label htmlFor={`layer-${k}`} className="flex-1">
                {LAYER_LABEL[k]}
              </label>
              <Switch id={`layer-${k}`} checked={layers[k]} onCheckedChange={(v) => setLayers({ ...layers, [k]: v })} />
            </li>
          ))}
          <li className="flex items-center gap-2 border-t pt-2">
            <label htmlFor="basemap" className="flex-1 text-muted-foreground">
              Background
            </label>
            <NativeSelect
              id="basemap"
              className="w-32"
              value={basemap}
              onChange={(e) => setBasemap(e.target.value as BasemapId)}
            >
              {(Object.keys(BASEMAPS) as BasemapId[]).map((b) => (
                <option key={b} value={b}>
                  {BASEMAPS[b].label}
                </option>
              ))}
            </NativeSelect>
          </li>
        </ul>
      )}
    </div>
  )
}

function FocusBar({ data, focus, clear }: { data: Comparison; focus: Focus; clear: () => void }) {
  const res = focus.side === 'official' ? data.official : data.modeled
  const r = res?.routes[focus.route]
  if (!r) return null
  const s = focus.step !== undefined ? r.steps[focus.step] : undefined
  return (
    <div className="flex items-center gap-2 rounded-md bg-highlight-soft px-3 py-1.5 text-sm text-highlight-soft-foreground">
      <Swatch side={focus.side} alt={focus.route > 0} />
      <span className="min-w-0 flex-1 truncate">
        {SIDE_LABEL[focus.side]} {routeLabel(focus.route).toLowerCase()}
        {s ? `, step ${focus.step! + 1}: ${s.instruction}` : `: ${r.summary}, ${formatDuration(r.duration_s)}, ${formatDistance(r.distance_m)}`}
      </span>
      <button type="button" onClick={clear} className="text-xs underline">
        clear
      </button>
    </div>
  )
}

function ErrorBox({
  title,
  message,
  detail,
  tone = 'error',
}: {
  title: string
  message: string
  detail?: string
  tone?: 'error' | 'warning'
}) {
  return (
    <div
      className={cn(
        'mb-4 rounded-lg border p-3 text-sm',
        tone === 'warning'
          ? 'border-warning/40 bg-warning-soft text-warning-soft-foreground'
          : 'border-destructive/30 bg-destructive-soft text-destructive-soft-foreground',
      )}
    >
      <div className="font-medium">{title}</div>
      <div className="mt-1 break-words">{message}</div>
      {detail && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs">Traceback</summary>
          <pre className="mt-1 overflow-x-auto text-xs whitespace-pre">{detail}</pre>
        </details>
      )}
    </div>
  )
}

function allPoints(d: Comparison): LatLon[] {
  const out: LatLon[] = []
  for (const res of [d.official, d.modeled]) for (const r of res?.routes ?? []) out.push(...r.geometry)
  return out
}

function buildPins(d: Comparison): MapPin[] {
  const ll = (t: string | null | undefined): LatLon | null => {
    if (!t) return null
    const [a, b] = t.split(',').map(Number)
    return Number.isFinite(a) && Number.isFinite(b) ? [a, b] : null
  }
  const res = d.official ?? d.modeled
  const o = ll(res?.origin_resolved)
  const t = ll(res?.destination_resolved)
  return [
    ...(o ? [{ id: 'o', at: o, label: `Start: ${d.case.origin}`, color: 'var(--success)' }] : []),
    ...(t ? [{ id: 'd', at: t, label: `End: ${d.case.destination}`, color: 'var(--destructive)' }] : []),
  ]
}

function buildLines(
  d: Comparison,
  sides: Side[],
  layers: Record<LayerKey, boolean>,
  focus: Focus | null,
  setFocus: (f: Focus | null) => void,
): MapLine[] {
  const under: MapLine[] = []
  const alts: MapLine[] = []
  const bests: MapLine[] = []
  const top: MapLine[] = []
  if (layers.divergence && d.divergence) {
    for (const s of sides) {
      const key = s === 'official' ? 'official_only' : 'modeled_only'
      d.divergence[key].forEach((g, i) =>
        under.push({
          id: `div-${s}-${i}`,
          geometry: g.geometry,
          color: 'var(--destructive)',
          weight: 16,
          opacity: 0.28,
          tooltip: `Only ${SIDE_LABEL[s].toLowerCase()} drives this (${formatDistance(g.length_m)})`,
        }),
      )
    }
  }
  for (const s of sides) {
    const res = s === 'official' ? d.official : d.modeled
    res?.routes.forEach((r, i) => {
      const show = i === 0 ? layers[s] : layers[s === 'official' ? 'officialAlts' : 'modeledAlts']
      const focused = focus?.side === s && focus.route === i
      if (!show && !focused) return
      const dimmed = focus !== null && !focused
      const line: MapLine = {
        id: `${s}-${i}`,
        geometry: r.geometry,
        color: SIDE_COLOR[s],
        // Official drawn wider underneath so the modeled line reads on top of it.
        weight: (s === 'official' ? 8 : 4) + (focused ? 2 : 0),
        opacity: dimmed ? 0.25 : focused ? 1 : i === 0 ? 0.9 : 0.55,
        dash: i === 0 || focused ? undefined : s === 'official' ? '10 8' : '4 8',
        tooltip: `${SIDE_LABEL[s]} ${routeLabel(i).toLowerCase()}: ${r.summary}, ${formatDuration(r.duration_s)}, ${formatDistance(r.distance_m)}`,
        onClick: () => setFocus(focused && focus?.step === undefined ? null : { side: s, route: i }),
      }
      ;(focused ? top : i === 0 ? bests : alts).push(line)
      if (focused && focus?.step !== undefined) {
        const st = r.steps[focus.step]
        if (st?.geometry.length)
          top.push({ id: 'step', geometry: st.geometry, color: 'var(--highlight)', weight: 10, opacity: 0.95, tooltip: st.instruction })
      }
    })
  }
  // Official best under modeled best so both stay visible where they coincide.
  bests.sort((a, b) => (a.id.startsWith('official') ? -1 : 0) - (b.id.startsWith('official') ? -1 : 0))
  return [...under, ...alts.reverse(), ...bests, ...top]
}

/** Departure in the case's own time zone, e.g. "Wed, Nov 18, 8:00 AM EST". */
function formatDeparture(d: Comparison): string {
  const iso = d.official?.departure ?? d.modeled?.departure
  if (!iso) return d.case.departure
  return new Date(iso).toLocaleString('en-US', {
    timeZone: d.case.timezone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  })
}
