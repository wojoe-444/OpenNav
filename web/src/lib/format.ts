const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const full = new Intl.NumberFormat('en-US')

/** 1,284 / 12.9K / 4.2M */
export function formatCount(n: number): string {
  return Math.abs(n) < 10_000 ? full.format(Math.round(n)) : compact.format(n)
}

/** $0.42 / $12.30 / $1,284 / $12.9K */
export function formatUSD(n: number | undefined, opts: { compact?: boolean } = {}): string {
  if (n === undefined || !Number.isFinite(n)) return '–'
  if (opts.compact && Math.abs(n) >= 10_000) return `$${compact.format(n)}`
  const digits = Math.abs(n) >= 1000 ? 0 : 2
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

export function formatPercent(n: number | undefined, digits = 0): string {
  if (n === undefined || !Number.isFinite(n)) return '–'
  return `${(n * 100).toFixed(digits)}%`
}

/** +12% / −3.4% (true minus sign) */
export function formatSignedPercent(n: number): string {
  const v = Math.abs(n * 100).toFixed(Math.abs(n) < 0.1 ? 1 : 0)
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${v}%`
}

/** "Nov 3" from YYYY-MM-DD, local time. */
export function formatShortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatRelative(iso: string, now = Date.now()): string {
  const s = Math.round((now - Date.parse(iso)) / 1000)
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

/** "in 12 min" / "in 1 h" for a time in the future ("now" if it has passed). */
export function formatIn(iso: string, now = Date.now()): string {
  const s = Math.round((Date.parse(iso) - now) / 1000)
  if (s <= 30) return 'now'
  const m = Math.round(s / 60)
  if (m < 60) return `in ${Math.max(1, m)} min`
  const h = Math.round(m / 60)
  if (h < 24) return `in ${h} h`
  return `in ${Math.round(h / 24)} d`
}

/** 512 B / 4.2 KB / 38 MB / 1.4 GB / 2.1 TB (powers of 1024, as Explorer shows them) */
export function formatBytes(n: number | undefined): string {
  if (n === undefined || !Number.isFinite(n)) return '–'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = Math.max(0, n)
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${i === 0 ? Math.round(v) : v.toFixed(v < 10 ? 1 : 0)} ${units[i]}`
}

/** "36 min" / "1 hr 5 min" */
export function formatDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '–'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min`
  return `${Math.floor(m / 60)} hr${m % 60 ? ` ${m % 60} min` : ''}`
}

/** Step-scale durations: "45 s" under a minute. */
export function formatStepDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '–'
  return s < 60 ? `${Math.round(s)} s` : formatDuration(s)
}

/** Miles, or feet under 0.1 mi, like a maps app. */
export function formatDistance(m: number | null | undefined): string {
  if (m === null || m === undefined || !Number.isFinite(m)) return '–'
  const mi = m / 1609.344
  if (mi < 0.1) return `${Math.round(m * 3.28084)} ft`
  return `${mi < 100 ? mi.toFixed(1) : Math.round(mi)} mi`
}
