/**
 * Typed calls to the local Python API (opennav/viewer/server.py). The shapes
 * mirror opennav/viewer/compare.py; keep the two in step.
 */

export type LatLon = [number, number]

export interface Step {
  instruction: string
  distance_m: number
  distance_mi: number
  duration_s: number
  static_duration_s: number | null
  maneuver: string | null
  road: string | null
  notes: string[]
  geometry: LatLon[]
}

export interface Congestion {
  road: string | null
  level: 'SLOW' | 'TRAFFIC_JAM' | string
  distance_m: number
}

export interface Route {
  summary: string
  duration_s: number
  static_duration_s: number | null
  traffic_delay_s: number | null
  distance_m: number
  distance_mi: number
  labels: string[]
  warnings: string[]
  traffic_note: string | null
  congestion: Congestion[]
  geometry: LatLon[]
  steps: Step[]
}

export interface RouteResult {
  provider: string
  departure: string | null
  origin_resolved: string | null
  destination_resolved: string | null
  fetched_at: string | null
  comparison_note: string | null
  routes: Route[]
}

export interface RouteMatch {
  truth_index: number
  ours_index: number | null
  overlap: number
  duration_err: number | null
  truth_summary: string
  ours_summary: string | null
}

export interface Score {
  total: number
  metrics: Record<string, number>
  details: Record<string, unknown>
  matches: RouteMatch[]
}

export interface Divergence {
  length_m: number
  geometry: LatLon[]
}

export interface CaseDef {
  id: string
  origin: string
  destination: string
  departure: string
  timezone: string
  notes: string
  observed: Record<string, unknown>
}

export interface Comparison {
  case: CaseDef
  model: string
  models: string[]
  official: RouteResult | null
  official_error?: string
  official_file?: string
  modeled?: RouteResult | null
  modeled_error?: string
  modeled_traceback?: string
  model_seconds?: number
  score?: Score
  /** Weight of each top-level metric in the 0-100 total (opennav/scoring.py WEIGHTS). */
  score_weights?: Record<string, number>
  divergence?: { modeled_only: Divergence[]; official_only: Divergence[] }
}

export interface CaseSummary {
  id: string
  origin: string
  destination: string
  departure: string
  has_truth: boolean
  truth_files: string[]
  scores: Record<string, number | null>
}

export interface Health {
  ok: boolean
  data_dir: string
  models: string[]
}

async function request<T>(method: 'GET' | 'POST', path: string): Promise<T> {
  const res = await fetch(`./api${path}`, { method })
  const text = await res.text()
  let body: unknown
  try {
    body = JSON.parse(text)
  } catch {
    throw new Error(`API ${res.status}: ${text.slice(0, 200) || 'no response (is `opennav serve` running?)'}`)
  }
  if (!res.ok) throw new Error((body as { error?: string }).error ?? `API error ${res.status}`)
  return body as T
}

export const api = {
  health: () => request<Health>('GET', '/health'),
  cases: () => request<CaseSummary[]>('GET', '/cases'),
  compare: (id: string, model = 'opennav') =>
    request<Comparison>('GET', `/cases/${encodeURIComponent(id)}?model=${encodeURIComponent(model)}`),
  rerun: (id: string, model = 'opennav') =>
    request<Comparison>('POST', `/cases/${encodeURIComponent(id)}/rerun?model=${encodeURIComponent(model)}`),
}
