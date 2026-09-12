export interface CodexQuotaWindow {
  used_percent: number
  window_duration_mins: number | null
  resets_at: number | null
}

export interface CodexQuotaBucket {
  limit_id: string
  limit_name: string | null
  primary: CodexQuotaWindow | null
  secondary: CodexQuotaWindow | null
}

export interface CodexQuotaSnapshot {
  enabled: boolean
  state: "available" | "stale" | "unavailable" | "disabled"
  observed_at: number | null
  gateway_account_matches: boolean | null
  buckets: CodexQuotaBucket[]
  error: string | null
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid operation response")
  return value as Record<string, unknown>
}

function nullablePositive(value: unknown): number | null {
  if (value == null) return null
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) throw new Error("Invalid quota timestamp or duration")
  return value
}

function quotaWindow(value: unknown): CodexQuotaWindow | null {
  if (value == null) return null
  const row = record(value)
  if (typeof row.used_percent !== "number" || !Number.isFinite(row.used_percent) || row.used_percent < 0) {
    throw new Error("Invalid quota percentage")
  }
  return {
    used_percent: row.used_percent,
    window_duration_mins: nullablePositive(row.window_duration_mins),
    resets_at: nullablePositive(row.resets_at),
  }
}

export function parseCodexQuota(value: unknown): CodexQuotaSnapshot {
  const row = record(value)
  const state = row.state
  if (typeof row.enabled !== "boolean" || !["available", "stale", "unavailable", "disabled"].includes(String(state))) {
    throw new Error("Invalid quota status")
  }
  if (!Array.isArray(row.buckets)) throw new Error("Invalid quota buckets")
  return {
    enabled: row.enabled,
    state: state as CodexQuotaSnapshot["state"],
    observed_at: nullablePositive(row.observed_at),
    gateway_account_matches: typeof row.gateway_account_matches === "boolean" ? row.gateway_account_matches : null,
    error: typeof row.error === "string" ? row.error : null,
    buckets: row.buckets.map((value: unknown) => {
      const bucket = record(value)
      if (typeof bucket.limit_id !== "string" || !bucket.limit_id) throw new Error("Invalid quota bucket ID")
      return {
        limit_id: bucket.limit_id,
        limit_name: typeof bucket.limit_name === "string" ? bucket.limit_name : null,
        primary: quotaWindow(bucket.primary),
        secondary: quotaWindow(bucket.secondary),
      }
    }),
  }
}

export function quotaDuration(minutes: number | null): string {
  if (minutes === null) return "okno"
  if (minutes % 1440 === 0) return `${minutes / 1440}d`
  if (minutes % 60 === 0) return `${minutes / 60}h`
  return `${minutes}min`
}

export function quotaSummary(snapshot: CodexQuotaSnapshot | null): string {
  if (!snapshot?.enabled) return ""
  const bucket = snapshot.buckets.find((item) => item.limit_id === "codex") ?? snapshot.buckets[0]
  const windows = [bucket?.primary, bucket?.secondary].filter((item): item is CodexQuotaWindow => Boolean(item))
  const label = snapshot.gateway_account_matches === false ? "Codex CLI (inne konto)" : "Codex"
  if (!windows.length) return `${label}: brak danych`
  return `${label}: ${windows.map((item) => `${quotaDuration(item.window_duration_mins)} ${item.used_percent}%`).join(" · ")}${snapshot.state === "stale" ? " · nieaktualne" : ""}`
}
