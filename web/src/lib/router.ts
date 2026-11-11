import { useCallback, useSyncExternalStore } from 'react'

/**
 * Minimal hash router. Hash routing works with Electron's file:// loading and
 * needs no server config. Paths look like "/claude-stats" (URL "#/claude-stats").
 */

/** Current route path, e.g. "/claude-stats" or "/apps/github-plus/repo/tree?ref=main". */
export function currentPath(): string {
  const raw = window.location.hash.replace(/^#/, '')
  if (!raw || raw === '/') return '/'
  return raw.startsWith('/') ? raw.replace(/\/+$/, '') : `/${raw}`
}

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

export function navigate(path: string) {
  const next = path.startsWith('/') ? path : `/${path}`
  if (currentPath() !== next) window.location.hash = next
}

/** Current route path and a navigate function. */
export function useRoute(): [string, (path: string) => void] {
  const path = useSyncExternalStore(subscribe, currentPath, () => '/')
  const go = useCallback((p: string) => navigate(p), [])
  return [path, go]
}

/** Query parameters of a route path ("/compare?case=x" -> {case: "x"}). */
export function routeParams(path: string): URLSearchParams {
  const i = path.indexOf('?')
  return new URLSearchParams(i === -1 ? '' : path.slice(i + 1))
}

/** Build a route path with query parameters, dropping empty ones. */
export function withParams(path: string, params: Record<string, string | undefined | null>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v)
  const s = q.toString()
  return s ? `${path}?${s}` : path
}
