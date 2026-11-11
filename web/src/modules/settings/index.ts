import { lazy } from 'react'
import { Settings } from 'lucide-react'

import type { ModuleDefinition } from '../types'

export const settingsModule: ModuleDefinition = {
  id: 'settings',
  title: 'Settings',
  description: 'Appearance and where the viewer reads its data.',
  icon: Settings,
  path: '/settings',
  nav: { section: 'Configure', order: 900 },
  component: lazy(() => import('./SettingsPage')),
  endpoints: ['GET /api/health'],
}
