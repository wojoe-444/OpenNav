import { useCallback, useSyncExternalStore } from 'react'

import { DEFAULT_PALETTE, findPalette, tokens } from './palettes'

/**
 * Appearance for the whole app, apps included: a color scheme (palette, see
 * `palettes.ts`) plus light / dark mode. Light mode and "Sand & Ink" are the
 * defaults. Both are remembered in localStorage (inside the app's AppData
 * folder in Electron). Mode is applied as the `dark` class on <html>, which
 * the Tailwind tokens and app stylesheets key off; the palette is applied by
 * writing its tokens as CSS variables on <html>.
 */
export type Theme = 'light' | 'dark'

const MODE_KEY = 'opennav.theme'
const PALETTE_KEY = 'opennav.palette'
const listeners = new Set<() => void>()

function readItem(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeItem(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable: keep it for this session */
  }
}

let theme: Theme = readItem(MODE_KEY) === 'dark' ? 'dark' : 'light'
let palette: string = findPalette(readItem(PALETTE_KEY) ?? DEFAULT_PALETTE).id

function apply() {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.dataset.palette = palette
  const p = findPalette(palette)
  if (p.shape) root.dataset.shape = p.shape
  else delete root.dataset.shape
  if (p.texture) root.dataset.texture = p.texture
  else delete root.dataset.texture
  for (const [k, v] of Object.entries(tokens(p, theme === 'dark'))) {
    root.style.setProperty(`--${k}`, v)
  }
}
apply()

function emit() {
  apply()
  listeners.forEach((l) => l())
}

export function setTheme(next: Theme) {
  theme = next
  writeItem(MODE_KEY, next)
  emit()
}

export function setPalette(id: string) {
  palette = findPalette(id).id
  writeItem(PALETTE_KEY, palette)
  emit()
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Current mode and a toggle. */
export function useTheme(): [Theme, () => void] {
  const t = useSyncExternalStore(subscribe, () => theme, () => 'light' as Theme)
  const toggle = useCallback(() => setTheme(theme === 'dark' ? 'light' : 'dark'), [])
  return [t, toggle]
}

/** Current palette id and a setter. */
export function usePalette(): [string, (id: string) => void] {
  const p = useSyncExternalStore(subscribe, () => palette, () => DEFAULT_PALETTE)
  return [p, setPalette]
}
