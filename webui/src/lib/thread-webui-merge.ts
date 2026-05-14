import type { UIMessage } from "@/lib/types";

import { mergeCanonicalHistoryPreservingLongTasks } from "@/lib/thread-history-merge";

/**
 * Merge on-disk WebUI display messages with API session history.
 * Prefer disk when it has more rows (session may have compacted); inject
 * ``trace`` rows from disk into the canonical server ordering when present.
 */
export function mergeWebuiDiskSnapshotWithHistorical(
  disk: UIMessage[],
  historical: UIMessage[],
): UIMessage[] {
  if (disk.length === 0) return historical;
  const hasEphemeral = disk.some((m) => m.kind === "trace");
  if (hasEphemeral) return mergeCanonicalHistoryPreservingLongTasks(disk, historical);
  return disk.length >= historical.length ? disk : historical;
}
