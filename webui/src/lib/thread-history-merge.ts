import type { UIMessage } from "@/lib/types";

/**
 * After ``turn_end`` the session history API returns canonical assistant rows but
 * does not yet persist every ephemeral WebSocket row. Re-insert in-flight
 * ``trace`` rows from the pre-refresh client state (or on-disk snapshot).
 *
 * Placement: immediately before the **last** assistant row after the last user
 * message (final reply of the turn), so traces stay below reasoning rows.
 */
export function mergeCanonicalHistoryPreservingLongTasks(
  prev: UIMessage[],
  historical: UIMessage[],
): UIMessage[] {
  const seenTrace = new Set<string>();
  const deduped: UIMessage[] = [];
  for (const m of prev) {
    if (m.kind !== "trace") continue;
    if (seenTrace.has(m.id)) continue;
    seenTrace.add(m.id);
    deduped.push(m);
  }
  if (deduped.length === 0) return historical;

  const traceIds = new Set(deduped.map((m) => m.id));
  const base = historical.filter((m) => !(m.kind === "trace" && traceIds.has(m.id)));

  let insertAt = base.length;
  for (let i = base.length - 1; i >= 0; i--) {
    if (base[i]!.role !== "user") continue;
    let lastAssistant = -1;
    for (let j = i + 1; j < base.length; j++) {
      const m = base[j]!;
      if (m.role === "assistant" && m.kind !== "trace") {
        lastAssistant = j;
      }
    }
    if (lastAssistant >= 0) insertAt = lastAssistant;
    break;
  }

  return [...base.slice(0, insertAt), ...deduped, ...base.slice(insertAt)];
}
