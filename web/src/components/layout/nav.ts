import { modules } from '@/modules/registry'
import type { IconComponent } from '@/modules/types'

export interface NavItem {
  /** Route path, e.g. "/compare". Also the item's identity. */
  path: string
  label: string
  icon: IconComponent
  badge?: string
  /** Subpages, drawn as a collapsible tree under this item. One level deep. */
  children?: NavItem[]
}

export interface NavSection {
  heading?: string
  items: NavItem[]
}

/** Nav built from the module registry (src/modules/registry.ts), as in MonoRail. */
export function buildNavSections(): NavSection[] {
  const sections: NavSection[] = [{ heading: 'Review', items: [] }]
  const sorted = [...modules].sort((a, b) => (a.nav.order ?? 100) - (b.nav.order ?? 100))
  for (const m of sorted) {
    if (m.nav.hidden) continue
    const item: NavItem = { path: m.path, label: m.title, icon: m.icon, badge: m.nav.badge }
    const parent = m.nav.parent ? findNavItem(sections, m.nav.parent)?.item : undefined
    if (parent) {
      parent.children = [...(parent.children ?? []), item]
      continue
    }
    let section = sections.find((s) => s.heading === m.nav.section)
    if (!section) {
      section = { heading: m.nav.section, items: [] }
      sections.push(section)
    }
    section.items.push(item)
  }
  return sections.filter((s) => s.items.length > 0)
}

const SECTIONS = buildNavSections()

/** Every item, subpages included, in drawer order. */
export function flattenNav(sections: NavSection[]): NavItem[] {
  return sections.flatMap((s) => s.items.flatMap((i) => [i, ...(i.children ?? [])]))
}

/** Find an item (or subpage) by path, with its section and parent item. Query strings are ignored. */
export function findNavItem(
  sections: NavSection[],
  path: string,
): { item: NavItem; section: NavSection; parent?: NavItem } | undefined {
  const bare = path.split('?')[0]
  for (const section of sections) {
    for (const item of section.items) {
      if (item.path === bare) return { item, section }
      const child = item.children?.find((c) => c.path === bare)
      if (child) return { item: child, section, parent: item }
    }
  }
  return undefined
}

export function useNavSections(): NavSection[] {
  return SECTIONS
}
