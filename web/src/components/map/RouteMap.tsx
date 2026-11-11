import { useEffect, useLayoutEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { useTheme } from '@/lib/theme'
import type { LatLon } from '@/lib/api'

/** One polyline on the map. Layers draw in array order (last on top). */
export interface MapLine {
  id: string
  geometry: LatLon[]
  color: string
  weight?: number
  opacity?: number
  dash?: string
  tooltip?: string
  onClick?: () => void
}

export interface MapPin {
  id: string
  at: LatLon
  label: string
  color: string
}

/** Shared view between maps (side-by-side mode keeps both in step). */
export interface MapSync {
  view?: { center: L.LatLng; zoom: number; from: string }
  set: (v: { center: L.LatLng; zoom: number; from: string }) => void
}

interface RouteMapProps {
  lines: MapLine[]
  pins?: MapPin[]
  /** Fit to these points when `fitKey` changes (e.g. a new case, or a focused step). */
  fit?: LatLon[]
  fitKey?: string
  sync?: MapSync
  syncId?: string
  className?: string
}

const TILES = {
  light: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  dark: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
}
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'

/** Resolve "var(--series-1)" to a color Leaflet's SVG renderer accepts. */
function cssColor(c: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(c)
  return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || '#888' : c
}

/**
 * A Leaflet map of route polylines on a CARTO basemap (light or dark with the
 * app theme). Imperative Leaflet inside one component, so pages just pass data.
 */
export function RouteMap({ lines, pins = [], fit, fitKey, sync, syncId = 'map', className }: RouteMapProps) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const tiles = useRef<L.TileLayer | null>(null)
  const group = useRef<L.LayerGroup | null>(null)
  const [theme] = useTheme()
  const syncRef = useRef(sync)
  useLayoutEffect(() => {
    syncRef.current = sync
  })

  useEffect(() => {
    if (!el.current) return
    const m = L.map(el.current, { zoomControl: true, preferCanvas: false })
    m.setView([33.75, -84.39], 10)
    group.current = L.layerGroup().addTo(m)
    m.on('moveend', () => {
      const s = syncRef.current
      if (s) s.set({ center: m.getCenter(), zoom: m.getZoom(), from: syncId })
    })
    map.current = m
    const ro = new ResizeObserver(() => m.invalidateSize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      m.remove()
      map.current = null
    }
  }, [syncId])

  useEffect(() => {
    const m = map.current
    if (!m) return
    tiles.current?.remove()
    tiles.current = L.tileLayer(theme === 'dark' ? TILES.dark : TILES.light, {
      attribution: ATTRIBUTION,
      subdomains: 'abcd',
      maxZoom: 20,
    }).addTo(m)
  }, [theme])

  useEffect(() => {
    const g = group.current
    if (!g) return
    g.clearLayers()
    for (const ln of lines) {
      if (ln.geometry.length < 2) continue
      const pl = L.polyline(ln.geometry, {
        color: cssColor(ln.color),
        weight: ln.weight ?? 5,
        opacity: ln.opacity ?? 0.9,
        dashArray: ln.dash,
        lineCap: 'round',
        lineJoin: 'round',
      })
      if (ln.tooltip) pl.bindTooltip(ln.tooltip, { sticky: true })
      if (ln.onClick) pl.on('click', ln.onClick)
      pl.addTo(g)
    }
    for (const p of pins) {
      L.circleMarker(p.at, { radius: 7, color: '#fff', weight: 2, fillColor: cssColor(p.color), fillOpacity: 1 })
        .bindTooltip(p.label)
        .addTo(g)
    }
  }, [lines, pins, theme])

  useEffect(() => {
    const m = map.current
    if (!m || !fit || fit.length === 0) return
    m.fitBounds(L.latLngBounds(fit), { padding: [40, 40], maxZoom: 17 })
  }, [fitKey]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const m = map.current
    const v = sync?.view
    if (!m || !v || v.from === syncId) return
    if (m.getCenter().distanceTo(v.center) < 1 && m.getZoom() === v.zoom) return
    m.setView(v.center, v.zoom, { animate: false })
  }, [sync?.view, syncId])

  return <div ref={el} className={className} />
}
