type HistorySourceKind = "stream" | "sequence" | "id";

export interface HistoryRowSource {
  kind: HistorySourceKind;
  key: string;
}

export interface HistoryRowIdentity {
  sources: HistoryRowSource[];
  fallback?: string;
}

export function sameHistoryRowIdentity(left: HistoryRowIdentity, right: HistoryRowIdentity): boolean {
  return left.fallback === right.fallback && left.sources.length === right.sources.length
    && left.sources.every((source, index) => source.key === right.sources[index].key);
}

function sourcesDisagree(left: HistoryRowIdentity, right: HistoryRowIdentity, kind: HistorySourceKind): boolean {
  const leftKeys = left.sources.filter((source) => source.kind === kind);
  const rightKeys = right.sources.filter((source) => source.kind === kind);
  return leftKeys.length > 0 && rightKeys.length > 0
    && !leftKeys.some((source) => rightKeys.some((other) => source.key === other.key));
}

export function matchHistoryRow(
  anchor: HistoryRowIdentity, candidates: Iterable<HTMLElement>, rows: WeakMap<HTMLElement, HistoryRowIdentity>,
): HTMLElement | undefined {
  const bySource = new Map<string, { element: HTMLElement; identity: HistoryRowIdentity }>();
  let fallback: HTMLElement | undefined;
  for (const element of candidates) {
    const identity = rows.get(element);
    if (!identity) continue;
    for (const source of identity.sources) bySource.set(source.key, { element, identity });
    if (!fallback && anchor.fallback && anchor.fallback === identity.fallback) fallback = element;
  }
  for (const source of anchor.sources) {
    const candidate = bySource.get(source.key);
    if (!candidate) continue;
    // A replay-generated row id may be reused for a different message.
    if (source.kind !== "stream" && sourcesDisagree(anchor, candidate.identity, "stream")) continue;
    if (source.kind === "id" && sourcesDisagree(anchor, candidate.identity, "sequence")) continue;
    return candidate.element;
  }
  return fallback;
}
