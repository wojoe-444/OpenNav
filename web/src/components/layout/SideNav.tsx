import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { BrandTile } from '@/components/layout/BrandMark'
import { useHealth } from '@/modules/client'
import { cn } from '@/lib/utils'

import { useNavSections, type NavItem } from './nav'

interface SideNavProps {
  current: string
  onNavigate: (path: string) => void
  collapsed: boolean
}

/**
 * Permanent navigation drawer, taken from MonoRail (wojoe-444/MonoRail), which
 * styles it after the Bot Dashboard in wojoe-444/MC-Player: a 64px brand header aligned with the app bar, grouped
 * sections with overline labels, 40px items on soft pills, and the active
 * item filled with the drawer's primary color. Collapses to a 72px icon rail.
 * The toggle lives in the top bar.
 *
 * Items with subpages are collapsible groups drawn as a tree: the subpages
 * are plain text rows on a thin guide line under the parent's icon, the
 * current one tinted with a primary bar. Open/closed is remembered per group;
 * a closed group that holds the current page shows a dot. On the icon rail a
 * group's icon opens a menu with its pages.
 */
export function SideNav({ current, onNavigate, collapsed }: SideNavProps) {
  const navSections = useNavSections()
  const health = useHealth()
  return (
    <aside
      data-slot="sidebar"
      className={cn(
        'flex h-full shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200',
        collapsed ? 'w-[72px]' : 'w-[256px]',
      )}
    >
      {/* Brand header: height matches the 64px top bar */}
      <div
        className={cn(
          'flex h-16 shrink-0 items-center gap-3 border-b border-sidebar-border px-4',
          collapsed && 'justify-center px-0',
        )}
      >
        <BrandTile className="size-8" />
        {!collapsed && (
          <div className="flex min-w-0 flex-col leading-tight">
            <span className="truncate text-sm font-semibold text-sidebar-accent-foreground">OpenNav</span>
            <span className="truncate text-xs text-sidebar-muted-foreground">Route review</span>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-4 py-4" aria-label="Main">
        {navSections.map((section, i) => (
          <div key={section.heading ?? i} className={cn(i > 0 && 'mt-4')}>
            {section.heading && !collapsed && (
              <div className="flex h-8 items-center px-3 text-[11px] font-semibold tracking-wider text-sidebar-muted-foreground uppercase">
                {section.heading}
              </div>
            )}
            {section.heading && collapsed && <div className="mx-2 mb-3 h-px bg-sidebar-border" />}
            <ul className="flex flex-col gap-1">
              {section.items.map((item) => (
                <li key={item.path}>
                  {item.children && item.children.length > 0 ? (
                    <NavGroup item={item} current={current} collapsed={collapsed} onNavigate={onNavigate} />
                  ) : (
                    <NavButton item={item} current={current} collapsed={collapsed} onNavigate={onNavigate} />
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {!collapsed && (
        <div className="flex items-center justify-between border-t border-sidebar-border p-4 text-xs text-sidebar-muted-foreground">
          <span>Version {__APP_VERSION__}</span>
          {health.error ? (
            <Badge variant="destructive" title={health.error.message}>API offline</Badge>
          ) : (
            <Badge variant="success" title={health.data?.data_dir}>local</Badge>
          )}
        </div>
      )}
    </aside>
  )
}

function NavButton({
  item,
  current,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  current: string
  collapsed: boolean
  onNavigate: (path: string) => void
}) {
  const active = item.path === current
  const Icon = item.icon
  const button = (
    <button
      type="button"
      onClick={() => onNavigate(item.path)}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring',
        collapsed && 'justify-center px-0',
        active
          ? 'bg-sidebar-primary font-medium text-sidebar-primary-foreground shadow-md shadow-sidebar-primary/25'
          : 'bg-sidebar-accent/70 text-sidebar-accent-foreground hover:bg-sidebar-accent',
      )}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed && <span className="flex-1 truncate text-left">{item.label}</span>}
      {!collapsed && item.badge && (
        <span
          className={cn(
            'min-w-5 rounded-full px-1.5 text-center text-[11px] leading-5 font-semibold',
            active ? 'bg-sidebar-primary-foreground/20' : 'bg-warning text-black',
          )}
        >
          {item.badge}
        </span>
      )}
    </button>
  )
  if (!collapsed) return button
  return (
    <Tooltip>
      <TooltipTrigger asChild>{button}</TooltipTrigger>
      <TooltipContent side="right">{item.label}</TooltipContent>
    </Tooltip>
  )
}

const OPEN_KEY = 'opennav.navOpen'

function readOpenState(): Record<string, boolean> {
  try {
    const v = JSON.parse(localStorage.getItem(OPEN_KEY) ?? '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    return {}
  }
}

/** Open/closed state of one nav group, kept in localStorage. Groups start open. */
function useGroupOpen(path: string): [boolean, (open: boolean) => void] {
  const [open, setOpenState] = useState(() => readOpenState()[path] ?? true)
  const setOpen = (next: boolean) => {
    setOpenState(next)
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify({ ...readOpenState(), [path]: next }))
    } catch {
      // Storage unavailable: the state just isn't remembered.
    }
  }
  return [open, setOpen]
}

function NavGroup({
  item,
  current,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  current: string
  collapsed: boolean
  onNavigate: (path: string) => void
}) {
  const children = item.children ?? []
  const [open, setOpen] = useGroupOpen(item.path)
  const activeChild = children.find((c) => c.path === current)

  // Arriving on a subpage from elsewhere (a link, a handoff) opens its group.
  // Only when the current subpage changes, so the user can still close it.
  const activeChildPath = activeChild?.path
  const [seenChild, setSeenChild] = useState(activeChildPath)
  if (seenChild !== activeChildPath) {
    setSeenChild(activeChildPath)
    if (activeChildPath && !open) setOpen(true)
  }

  if (collapsed) return <RailGroup item={item} current={current} onNavigate={onNavigate} />

  const active = item.path === current
  const Icon = item.icon
  const Chevron = open ? ChevronDown : ChevronRight
  return (
    <div>
      <div
        className={cn(
          'flex h-10 w-full items-center rounded-md text-sm transition-colors',
          active
            ? 'bg-sidebar-primary font-medium text-sidebar-primary-foreground shadow-md shadow-sidebar-primary/25'
            : 'bg-sidebar-accent/70 text-sidebar-accent-foreground hover:bg-sidebar-accent',
          !active && activeChild && 'font-medium',
        )}
      >
        <button
          type="button"
          onClick={() => {
            onNavigate(item.path)
            if (!open) setOpen(true)
          }}
          aria-current={active ? 'page' : undefined}
          className="flex h-full min-w-0 flex-1 items-center gap-3 rounded-md pl-3 outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        >
          <Icon className="size-4 shrink-0" />
          <span className="flex-1 truncate text-left">{item.label}</span>
          {!open && activeChild && (
            <span
              className={cn('size-1.5 shrink-0 rounded-full', active ? 'bg-sidebar-primary-foreground' : 'bg-sidebar-primary')}
              aria-label={`${activeChild.label} is open`}
            />
          )}
        </button>
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={open ? `Collapse ${item.label}` : `Expand ${item.label}`}
          className="mr-1 flex size-8 shrink-0 items-center justify-center rounded-md opacity-60 outline-none hover:opacity-100 focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        >
          <Chevron className="size-4" />
        </button>
      </div>
      {open && (
        // Tree: a hairline guide under the parent's icon (12px padding + half of 16px).
        <ul className="mt-0.5 mb-1 ml-[19px] flex flex-col border-l border-sidebar-border" aria-label={`${item.label} pages`}>
          {children.map((child) => {
            const on = child.path === current
            return (
              <li key={child.path}>
                <button
                  type="button"
                  onClick={() => onNavigate(child.path)}
                  aria-current={on ? 'page' : undefined}
                  className={cn(
                    '-ml-px flex h-8 w-full items-center gap-2 rounded-r-md border-l-2 pr-3 pl-5 text-left text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring',
                    on
                      ? 'border-sidebar-primary bg-sidebar-primary/10 font-semibold text-sidebar-accent-foreground dark:text-sidebar-primary'
                      : 'border-transparent text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground',
                  )}
                >
                  <span className="flex-1 truncate">{child.label}</span>
                  {child.badge && (
                    <span className="min-w-5 rounded-full bg-warning px-1.5 text-center text-[11px] leading-5 font-semibold text-black">
                      {child.badge}
                    </span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** A group on the 72px icon rail: the icon opens a menu with the group's pages. */
function RailGroup({ item, current, onNavigate }: { item: NavItem; current: string; onNavigate: (path: string) => void }) {
  const children = item.children ?? []
  const active = item.path === current
  const holdsCurrent = children.some((c) => c.path === current)
  const Icon = item.icon
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label={`${item.label} pages`}
              className={cn(
                'relative flex h-10 w-full items-center justify-center rounded-md text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring',
                active || holdsCurrent
                  ? 'bg-sidebar-primary text-sidebar-primary-foreground shadow-md shadow-sidebar-primary/25'
                  : 'bg-sidebar-accent/70 text-sidebar-accent-foreground hover:bg-sidebar-accent',
              )}
            >
              <Icon className="size-4 shrink-0" />
              <ChevronRight className="absolute right-1 size-3 opacity-60" />
            </button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent side="right">{item.label}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent side="right" align="start" sideOffset={12}>
        <DropdownMenuLabel>{item.label}</DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => onNavigate(item.path)} className={cn(active && 'font-semibold')}>
          <Icon />
          Overview
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {children.map((child) => {
          const ChildIcon = child.icon
          return (
            <DropdownMenuItem
              key={child.path}
              onSelect={() => onNavigate(child.path)}
              className={cn(child.path === current && 'font-semibold')}
            >
              <ChildIcon />
              {child.label}
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
