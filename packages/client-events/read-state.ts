export interface SessionReadState {
  generation: string
  latest: number
  read: number
}

export interface SessionReadObservation {
  generation: string
  cursor: number
}

export function isReadPosition(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}

export function parseSessionReadState(value: unknown): SessionReadState | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  if (typeof row.generation !== "string" || !row.generation.trim()
    || !isReadPosition(row.latest) || !isReadPosition(row.read) || row.read > row.latest) return null
  return { generation: row.generation, latest: row.latest, read: row.read }
}

/** Merge progress without regression; only authoritative snapshots may replace an opaque generation. */
export function mergeSessionReadState(
  current: SessionReadState | undefined,
  incoming: SessionReadState,
): SessionReadState {
  if (!current || current.generation !== incoming.generation) return incoming
  const latest = Math.max(current.latest, incoming.latest)
  const read = Math.max(current.read, incoming.read)
  return latest === current.latest && read === current.read ? current : { ...incoming, latest, read }
}

/** Only the completed results actually supplied with a rendered page/event are observable. */
export function sessionReadObservation(
  state: SessionReadState | undefined,
  cursor: unknown,
): SessionReadObservation | null {
  return state && isReadPosition(cursor) && cursor > 0 && cursor <= state.latest
    ? { generation: state.generation, cursor }
    : null
}
