export function formatIso(iso?: string | null): string {
  if (!iso) return ""
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  } catch {
    return iso
  }
}

export function shortId(id: string, n: number = 10): string {
  if (id.length <= n) return id
  return `${id.slice(0, Math.max(4, n - 6))}…${id.slice(-5)}`
}

export function truncateText(s: string, n: number): string {
  if (s.length <= n) return s
  return `${s.slice(0, n)}...`
}

export function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0
}
