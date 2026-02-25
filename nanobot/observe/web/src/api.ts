import type { TraceFile, TraceSummary } from "./types"

export async function fetchTraceList(signal?: AbortSignal): Promise<TraceSummary[]> {
  const r = await fetch("/api/traces", { signal })
  if (!r.ok) {
    throw new Error(`failed to load traces: ${r.status}`)
  }
  const payload = (await r.json()) as { traces?: TraceSummary[] }
  return payload.traces ?? []
}

export async function fetchTrace(traceId: string, signal?: AbortSignal): Promise<TraceFile> {
  const r = await fetch(`/api/traces/${encodeURIComponent(traceId)}`, { signal })
  if (!r.ok) {
    throw new Error(`failed to load trace: ${r.status}`)
  }
  return (await r.json()) as TraceFile
}
