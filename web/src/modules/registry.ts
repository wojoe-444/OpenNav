import { casesModule } from './cases'
import { compareModule } from './compare'
import { settingsModule } from './settings'

import type { ModuleDefinition } from './types'

/** Every module in the app, in nav order. Add new modules here. */
export const modules: ModuleDefinition[] = [casesModule, compareModule, settingsModule]

const ids = new Set<string>()
const paths = new Set<string>()
for (const m of modules) {
  if (ids.has(m.id)) throw new Error(`Duplicate module id: ${m.id}`)
  if (paths.has(m.path)) throw new Error(`Duplicate module path: ${m.path}`)
  ids.add(m.id)
  paths.add(m.path)
}

export function findModuleByPath(path: string): ModuleDefinition | undefined {
  const bare = path.split('?')[0]
  return modules.find((m) => m.path === bare)
}
