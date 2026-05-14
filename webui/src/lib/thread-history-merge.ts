import type { UIMessage } from "@/lib/types";

/**
 * After ``turn_end`` the session history API returns canonical assistant rows but
 * does not yet persist ``long_task`` WebSocket metadata. Re-insert ephemeral
 * long-task cards from the pre-refresh client state so they remain visible.
 *
 * Placement: immediately before the **last** assistant row after the last user
 * message (final reply of the turn), so the card stays below reasoning / tool trace rows.
 */
export function mergeCanonicalHistoryPreservingLongTasks(
  prev: UIMessage[],
  historical: UIMessage[],
): UIMessage[] {
  const longTasks = prev.filter((m) => m.kind === "long_task" && m.longTask?.run_id);
  if (longTasks.length === 0) return historical;

  const seen = new Set<string>();
  const deduped: UIMessage[] = [];
  for (const m of longTasks) {
    const rid = m.longTask?.run_id;
    if (!rid || seen.has(rid)) continue;
    seen.add(rid);
    deduped.push(m);
  }

  /** Anchor long_task just before this turn's final assistant reply, not before the first
   *  reasoning-only row — otherwise the card sits above Thinking / tool traces (“pinned”). */
  let insertAt = historical.length;
  for (let i = historical.length - 1; i >= 0; i--) {
    if (historical[i]!.role !== "user") continue;
    let lastAssistant = -1;
    for (let j = i + 1; j < historical.length; j++) {
      const m = historical[j]!;
      if (m.role === "assistant" && m.kind !== "trace" && m.kind !== "long_task") {
        lastAssistant = j;
      }
    }
    if (lastAssistant >= 0) insertAt = lastAssistant;
    break;
  }

  return [...historical.slice(0, insertAt), ...deduped, ...historical.slice(insertAt)];
}
