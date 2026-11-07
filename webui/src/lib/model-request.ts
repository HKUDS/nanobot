import type { UIMessage, UIModelRequestSnapshot } from "@/lib/types";

export type ComposerUsageSnapshot = Pick<UIMessage,
  "id" | "turnId" | "createdAt" | "completedAt" | "usage" | "roundUsages" | "contextWindowTokens"
> & { compacted?: boolean; estimatedContextTokens?: number };

export function reconcileModelRequest(
  current: UIModelRequestSnapshot | undefined,
  incoming: UIModelRequestSnapshot,
): UIModelRequestSnapshot {
  if (!current) return incoming;
  if ((current.ended && !incoming.ended) || current.retiredRunIds.includes(incoming.runId)) return current;
  if (current.turnSeq !== undefined && incoming.turnSeq !== undefined) {
    if (incoming.turnSeq < current.turnSeq
      || (incoming.turnSeq === current.turnSeq && !(incoming.ended && !current.ended))) return current;
  } else if (current.runId === incoming.runId) {
    if (incoming.sequence < current.sequence
      || (incoming.sequence === current.sequence && !(incoming.ended && !current.ended))) return current;
  } else if (!incoming.retiredRunIds.includes(current.runId)) return current;
  return { ...incoming, retiredRunIds: Array.from(new Set([
    ...current.retiredRunIds, ...incoming.retiredRunIds,
    ...(current.runId !== incoming.runId ? [current.runId] : []),
  ])) };
}

/** Select one authoritative usage snapshot per turn, independent of text rows. */
export function composerUsageSnapshots(
  messages: UIMessage[],
  snapshots: ReadonlyMap<string, UIModelRequestSnapshot>,
): ComposerUsageSnapshot[] {
  const lastRows = new Map<string, number>();
  const compactions = new Map<string, number | undefined>();
  messages.forEach((row, index) => {
    if (!row.turnId) return;
    lastRows.set(row.turnId, index);
    if (row.kind === "compaction" && row.compaction?.phase === "succeeded") {
      compactions.set(row.turnId, row.compaction.turnSeq);
    }
  });
  const rows = messages.flatMap((row, index): ComposerUsageSnapshot[] => {
    const snapshot = row.turnId ? snapshots.get(row.turnId) : undefined;
    if (snapshot) {
      if (lastRows.get(row.turnId!) !== index) return [];
      const compactionSeq = compactions.get(row.turnId!);
      const compacted = compactions.has(row.turnId!) && !(snapshot.usageTurnSeq !== undefined
        && compactionSeq !== undefined && snapshot.usageTurnSeq > compactionSeq);
      if (compacted) {
        const baseline = messages.filter((message) => message.turnId === row.turnId
          && message.compaction?.phase === "succeeded").at(-1)?.compaction?.contextSnapshot;
        return [{ id: row.id, turnId: row.turnId, createdAt: row.createdAt, compacted: true,
          estimatedContextTokens: baseline?.estimatedTokens, contextWindowTokens: baseline?.contextWindowTokens }];
      }
      return [{ id: row.id, turnId: row.turnId, createdAt: row.createdAt, compacted,
        completedAt: snapshot.completedAt ?? row.completedAt, usage: snapshot.usage,
        roundUsages: snapshot.roundUsages, contextWindowTokens: snapshot.contextWindowTokens }];
    }
    if (row.kind === "compaction" && row.compaction?.phase === "succeeded") {
      return [{ id: row.id, createdAt: row.createdAt, compacted: true,
        estimatedContextTokens: row.compaction.contextSnapshot?.estimatedTokens,
        contextWindowTokens: row.compaction.contextSnapshot?.contextWindowTokens }];
    }
    if (row.role !== "assistant" || row.kind === "trace" || row.isStreaming) return [];
    return [row];
  });
  // Proactive requests can precede any body. They need usage, not placeholder rows.
  const unanchored = Array.from(snapshots, ([turnId, snapshot]) => ({
    id: `model-request:${turnId}`, turnId, ...snapshot,
  })).filter((snapshot) => !lastRows.has(snapshot.turnId))
    .sort((left, right) => left.createdAt - right.createdAt);
  if (!unanchored.length) return rows;
  const result: ComposerUsageSnapshot[] = [];
  let index = 0;
  for (const row of rows) {
    while (index < unanchored.length && unanchored[index].createdAt <= row.createdAt) {
      result.push(unanchored[index++]);
    }
    result.push(row);
  }
  return [...result, ...unanchored.slice(index)];
}
