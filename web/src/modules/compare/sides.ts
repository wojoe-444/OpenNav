/** The two sides of every comparison, with their fixed colors (chart series 1 and 2). */
export type Side = 'official' | 'modeled'
export const SIDES: Side[] = ['official', 'modeled']
export const SIDE_LABEL: Record<Side, string> = { official: 'Official', modeled: 'Modeled' }
export const SIDE_COLOR: Record<Side, string> = { official: 'var(--series-1)', modeled: 'var(--series-2)' }

/** A route or step the reviewer clicked; the map highlights it. */
export interface Focus {
  side: Side
  route: number
  step?: number
}

export function routeLabel(i: number): string {
  return i === 0 ? 'Best' : `Alt ${i}`
}
