import type { UIMessage } from "@/lib/types";

type ComposerUsageSnapshot = Pick<UIMessage,
  "id" | "turnId" | "createdAt" | "completedAt" | "usage" | "roundUsages" | "contextWindowTokens"
> & { compacted?: boolean };

/** Select one authoritative usage snapshot per turn, independent of text rows. */
export function composerUsageSnapshots(messages: UIMessage[]): ComposerUsageSnapshot[] {
  const snapshots = new Map<string, NonNullable<UIMessage["modelRequest"]>>();
  const lastRows = new Map<string, number>();
  const compactions = new Map<string, number | undefined>();
  messages.forEach((row, index) => {
    if (!row.turnId) return;
    lastRows.set(row.turnId, index);
    if (row.modelRequest) snapshots.set(row.turnId, row.modelRequest);
    if (row.kind === "compaction" && row.compaction?.phase === "succeeded") {
      compactions.set(row.turnId, row.compaction.turnSeq);
    }
  });
  return messages.flatMap((row, index): ComposerUsageSnapshot[] => {
    const snapshot = row.turnId ? snapshots.get(row.turnId) : undefined;
    if (snapshot) {
      if (lastRows.get(row.turnId!) !== index) return [];
      const compactionSeq = compactions.get(row.turnId!);
      const compacted = compactions.has(row.turnId!) && !(snapshot.usageTurnSeq !== undefined
        && compactionSeq !== undefined && snapshot.usageTurnSeq > compactionSeq);
      return [{ id: row.id, turnId: row.turnId, createdAt: row.createdAt, compacted,
        completedAt: row.completedAt, usage: snapshot.usage,
        roundUsages: snapshot.roundUsages, contextWindowTokens: snapshot.contextWindowTokens }];
    }
    if (row.kind === "compaction" && row.compaction?.phase === "succeeded") {
      return [{ id: row.id, createdAt: row.createdAt, compacted: true }];
    }
    if (row.role !== "assistant" || row.kind === "trace" || row.isStreaming) return [];
    return [row];
  });
}
