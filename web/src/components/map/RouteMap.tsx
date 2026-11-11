import { useEffect, useLayoutEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { maplibreGL } from '@maplibre/maplibre-gl-leaflet'
import { setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

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
  basemap?: BasemapId
  className?: string
}

// Ship MapLibre's worker as its own asset (Vite does not follow the library's own lookup).
setWorkerUrl(maplibreWorkerUrl)

/**
 * Background maps. All are OpenStreetMap data and need no API key:
 * OpenFreeMap (https://openfreemap.org) serves vector tiles with styles drawn
 * by MapLibre GL; "osm" is OpenStreetMap's own raster tiles
 * (https://operations.osmfoundation.org/policies/tiles/). Add a style here and
 * it shows up in the Layers card.
 */
export const BASEMAPS = {
  muted: { label: 'Muted', light: 'https://tiles.openfreemap.org/styles/positron', dark: 'https://tiles.openfreemap.org/styles/dark' },
  detailed: { label: 'Detailed', light: 'https://tiles.openfreemap.org/styles/liberty', dark: 'https://tiles.openfreemap.org/styles/liberty' },
  osm: { label: 'OSM standard', light: 'raster:https://tile.openstreetmap.org/{z}/{x}/{y}.png', dark: 'raster:https://tile.openstreetmap.org/{z}/{x}/{y}.png' },
} as const
export type BasemapId = keyof typeof BASEMAPS

// Dark mode for styles without a dark variant: invert and dim, so routes keep their contrast.
const DARK_FILTER = 'invert(1) hue-rotate(180deg) brightness(0.9) contrast(0.9) saturate(0.4)'

/** Fit without animation: a zoom animation racing the GL layer's start leaves it blank. */
function refit(m: L.Map, b: L.LatLngBounds) {
  if (m.getSize().x > 0 && m.getSize().y > 0) m.fitBounds(b, { padding: [40, 40], maxZoom: 17, animate: false })
}

/** Resolve "var(--series-1)" to a color Leaflet's SVG renderer accepts. */
function cssColor(c: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(c)
  return m ? getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || '#888' : c
}

/**
 * A Leaflet map of route polylines on an OpenStreetMap basemap (see BASEMAPS),
 * light or dark with the app theme. Imperative Leaflet inside one component, so pages just pass data.
 */
export function RouteMap({ lines, pins = [], fit, fitKey, sync, syncId = 'map', basemap = 'muted', className }: RouteMapProps) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const tiles = useRef<L.Layer | null>(null)
  const group = useRef<L.LayerGroup | null>(null)
  // Last programmatic fit, re-applied when the container resizes (e.g. the
  // first layout after a reload) until the reviewer pans or zooms by hand.
  const lastFit = useRef<L.LatLngBounds | null>(null)
  const userMoved = useRef(false)
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
    const markUser = () => {
      userMoved.current = true
    }
    const node = el.current
    for (const ev of ['mousedown', 'wheel', 'touchstart', 'keydown'] as const) node.addEventListener(ev, markUser, { passive: true })
    const ro = new ResizeObserver(() => {
      m.invalidateSize({ animate: false })
      if (lastFit.current && !userMoved.current) refit(m, lastFit.current)
    })
    ro.observe(node)
    return () => {
      ro.disconnect()
      for (const ev of ['mousedown', 'wheel', 'touchstart', 'keydown'] as const) node.removeEventListener(ev, markUser)
      m.remove()
      map.current = null
    }
  }, [syncId])

  useEffect(() => {
    const m = map.current
    if (!m) return
    tiles.current?.remove()
    const b = BASEMAPS[basemap]
    const dark = theme === 'dark'
    const url: string = dark ? b.dark : b.light
    if (url.startsWith('raster:')) {
      tiles.current = L.tileLayer(url.slice(7), {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(m)
    } else {
      const gl = maplibreGL({ style: url } as never)
      tiles.current = gl.addTo(m)
      // The GL map can come up blank when it starts during the first layout or a
      // zoom animation; once its style is in, resync it with Leaflet's view.
      gl.getMaplibreMap().once('load', () => {
        if (map.current !== m || tiles.current !== gl) return
        m.invalidateSize({ animate: false })
        gl.getMaplibreMap().resize()
        ;(gl as unknown as { _update(): void })._update()
      })
    }
    // A fresh attribution control, so a removed basemap's credit goes with it.
    m.attributionControl?.remove()
    m.attributionControl = L.control.attribution().addTo(m)
    // Invert only when the style has no dark variant of its own.
    const pane = m.getPane('tilePane')
    if (pane) pane.style.filter = dark && b.dark === b.light ? DARK_FILTER : ''
  }, [theme, basemap])

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
    lastFit.current = L.latLngBounds(fit)
    userMoved.current = false
    refit(m, lastFit.current)
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
