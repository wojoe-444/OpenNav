import { useId } from 'react'

import { cn } from '@/lib/utils'

/*
 * The OpenNav logo: two routes (solid and dotted) between an origin and a
 * destination pin, on a blue tile. Same art as public/favicon.svg; keep the
 * two in step. Brand art keeps its colors in every palette.
 */
export function BrandTile({ className }: { className?: string }) {
  const id = useId().replace(/:/g, '')
  return (
    <span className={cn('flex shrink-0', className)}>
      <svg viewBox="0 0 64 64" className="size-full" aria-hidden>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4f86c6" />
            <stop offset="1" stopColor="#2a4f86" />
          </linearGradient>
        </defs>
        <rect width="64" height="64" rx="15" fill={`url(#${id})`} />
        <path d="M16 48c10-2 8-14 17-16s14-10 15-16" fill="none" stroke="#fbf6e8" strokeWidth="5" strokeLinecap="round" />
        <path
          d="M16 48c8-6 16-4 22-10s7-14 10-22"
          fill="none"
          stroke="#ffb35c"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray="1 6"
        />
        <circle cx="16" cy="48" r="5" fill="#fbf6e8" />
        <circle cx="48" cy="16" r="5" fill="#ffcf7a" />
      </svg>
    </span>
  )
}
