import { Suspense, useEffect, useState } from 'react'

import { findNavItem, useNavSections } from '@/components/layout/nav'
import { SideNav } from '@/components/layout/SideNav'
import { TopBar } from '@/components/layout/TopBar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useRoute } from '@/lib/router'
import { cn } from '@/lib/utils'
import { findModuleByPath } from '@/modules/registry'

const HOME = '/cases'
const COLLAPSED_KEY = 'opennav.navCollapsed'

/** App shell from MonoRail: drawer, 64px top bar, and the current module's page. */
export default function App() {
  const [path, navigate] = useRoute()
  const navSections = useNavSections()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1')

  useEffect(() => {
    if (path === '/') navigate(HOME)
  }, [path, navigate])
  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  const mod = findModuleByPath(path)
  const found = findNavItem(navSections, path)
  const Page = mod?.component

  return (
    <TooltipProvider>
      <div className="flex h-full overflow-hidden">
        <SideNav current={found?.item.path ?? path.split('?')[0]} onNavigate={navigate} collapsed={collapsed} />
        <div className={cn('flex min-w-0 flex-1 flex-col', mod?.fullBleed ? 'overflow-hidden' : 'overflow-y-auto')}>
          <TopBar
            section={found?.section.heading}
            parent={found?.parent ? { label: found.parent.label, path: found.parent.path } : undefined}
            onNavigate={navigate}
            title={mod?.title ?? 'Not found'}
            collapsed={collapsed}
            onToggleCollapsed={() => setCollapsed((c) => !c)}
          />
          {mod?.fullBleed ? (
            <main className="min-h-0 flex-1 overflow-hidden">
              <Suspense fallback={null}>{Page && <Page />}</Suspense>
            </main>
          ) : (
            // Content container: max 1536px with 24/32px gutters
            <main className="mx-auto w-full max-w-[96rem] p-6 lg:p-8">
              <Suspense fallback={null}>
                {Page ? <Page /> : <p className="text-sm text-muted-foreground">No page at {path}.</p>}
              </Suspense>
            </main>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
