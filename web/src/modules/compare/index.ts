import { lazy } from 'react'
import { GitCompareArrows } from 'lucide-react'

import type { ModuleDefinition } from '../types'

export const compareModule: ModuleDefinition = {
  id: 'compare',
  title: 'Official vs modeled',
  description: 'One case: the official route and ours on one map, with times, roads, steps, warnings and the score.',
  icon: GitCompareArrows,
  path: '/compare',
  nav: { section: 'Review', order: 20 },
  fullBleed: true,
  component: lazy(() => import('./ComparePage')),
  endpoints: ['GET /api/cases', 'GET /api/cases/<id>', 'POST /api/cases/<id>/rerun'],
}
