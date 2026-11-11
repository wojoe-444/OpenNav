import { lazy } from 'react'
import { ListChecks } from 'lucide-react'

import type { ModuleDefinition } from '../types'

export const casesModule: ModuleDefinition = {
  id: 'cases',
  title: 'Cases',
  description: 'Every test case, whether it has official ground truth, and its latest score.',
  icon: ListChecks,
  path: '/cases',
  nav: { section: 'Review', order: 10 },
  component: lazy(() => import('./CasesPage')),
  endpoints: ['GET /api/cases'],
}
