import type { ComponentType } from 'react'

import type { Comparison } from '@/lib/api'

import type { Focus } from '../sides'

export interface PanelProps {
  data: Comparison
  focus: Focus | null
  setFocus: (f: Focus | null) => void
  /** Zoom the map to these points. */
  zoomTo: (points: [number, number][]) => void
}

/**
 * A tab in the compare page's side panel. Add a review view by writing a
 * component and adding it to PANELS in ./index.ts.
 */
export interface PanelDefinition {
  id: string
  label: string
  component: ComponentType<PanelProps>
}
