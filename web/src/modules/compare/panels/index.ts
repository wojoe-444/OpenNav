import { OverviewPanel } from './OverviewPanel'
import { RoutesPanel } from './RoutesPanel'
import { ScorePanel } from './ScorePanel'
import { StepsPanel } from './StepsPanel'
import type { PanelDefinition } from './types'

/** Tabs of the compare page's side panel, in order. Add a review view here. */
export const PANELS: PanelDefinition[] = [
  { id: 'overview', label: 'Overview', component: OverviewPanel },
  { id: 'routes', label: 'Routes', component: RoutesPanel },
  { id: 'steps', label: 'Steps', component: StepsPanel },
  { id: 'score', label: 'Score', component: ScorePanel },
]
