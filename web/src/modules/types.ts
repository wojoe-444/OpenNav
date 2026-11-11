import type { ComponentType, LazyExoticComponent } from 'react'

/** A nav/header icon: any Lucide icon. */
export type IconComponent = ComponentType<{ className?: string }>

/**
 * The module contract, the same as MonoRail's (wojoe-444/MonoRail).
 *
 * A module is one review view: it owns one nav entry, one route and one page,
 * and reads its data from the local Python API (`opennav serve`). Adding one:
 *
 *   1. Create `src/modules/<id>/index.ts` exporting a `ModuleDefinition`.
 *   2. Add it to the list in `src/modules/registry.ts`.
 *   3. If it needs new data, add an endpoint in `opennav/viewer/server.py`
 *      (method on `Api` + a line in `ROUTES`) and a typed call in `src/lib/api.ts`.
 *
 * The nav, router and top bar read from the registry, so nothing else changes.
 */
export interface ModuleDefinition {
  /** Stable kebab-case id. */
  id: string
  /** Label used in the nav and the top bar. */
  title: string
  /** One-line summary, shown in page headers. */
  description: string
  icon: IconComponent
  /** Route path, e.g. "/compare". Must be unique. Query strings (?case=...) are page state. */
  path: string
  nav: {
    /** Nav section heading. Sections are created on demand, in registry order. */
    section: string
    /** Lower sorts first within the section. Defaults to 100. */
    order?: number
    badge?: string
    /** Path of a nav item to nest under as a subpage. */
    parent?: string
    /** Hidden from the nav (reached by links only). */
    hidden?: boolean
  }
  /** The page owns the whole body (no max width or padding), e.g. a map view. */
  fullBleed?: boolean
  /** The page. Use `lazy(() => import(...))` so modules load on demand. */
  component: LazyExoticComponent<ComponentType> | ComponentType
  /** API endpoints the page uses, listed so the page/backend contract is visible in one place. */
  endpoints?: readonly string[]
}
