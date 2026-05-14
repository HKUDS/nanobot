import type { UIMessage } from "@/lib/types";

function userBoundaryIndices(messages: UIMessage[]): number[] {
  const idx: number[] = [];
  for (let i = 0; i < messages.length; i++) {
    if (messages[i]!.role === "user") idx.push(i);
  }
  return idx;
}

/** Trace rows only (deduped by id) in ``messages[start..end)``. */
function traceMessagesInRange(messages: UIMessage[], start: number, end: number): UIMessage[] {
  const seen = new Set<string>();
  const out: UIMessage[] = [];
  for (let i = Math.max(0, start); i < end && i < messages.length; i++) {
    const m = messages[i]!;
    if (m.kind !== "trace") continue;
    if (seen.has(m.id)) continue;
    seen.add(m.id);
    out.push(m);
  }
  return out;
}

/** Strip canonical trace rows that we replace from disk/prev; insert *traces* before last assistant text row in *tail*. */
function insertTracesBeforeLastAssistant(tail: UIMessage[], traces: UIMessage[]): UIMessage[] {
  if (traces.length === 0) return tail;
  const traceIds = new Set(traces.map((t) => t.id));
  const base = tail.filter((m) => !(m.kind === "trace" && traceIds.has(m.id)));
  let insertAt = base.length;
  for (let i = base.length - 1; i >= 0; i--) {
    if (base[i]!.role === "assistant" && base[i]!.kind !== "trace") {
      insertAt = i;
      break;
    }
  }
  return [...base.slice(0, insertAt), ...traces, ...base.slice(insertAt)];
}

/**
 * Legacy behaviour: only traces after the *last* user message in ``prev`` —
 * used when user-turn counts disagree (compaction / partial hydrate).
 */
function mergeFallbackLastTurnOnly(prev: UIMessage[], historical: UIMessage[]): UIMessage[] {
  const users = userBoundaryIndices(prev);
  if (users.length === 0) return historical;
  const lastUser = users[users.length - 1]!;
  const traces = traceMessagesInRange(prev, lastUser + 1, prev.length);
  if (traces.length === 0) return historical;

  const traceIds = new Set(traces.map((t) => t.id));
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
  return [...base.slice(0, insertAt), ...traces, ...base.slice(insertAt)];
}

/**
 * After ``turn_end`` the session history API returns canonical assistant rows but
 * does not yet persist every ephemeral WebSocket row. Re-insert in-flight
 * ``trace`` rows from the pre-refresh client state (or on-disk snapshot).
 *
 * **Per user turn:** traces from ``prev`` between user ``k`` and user ``k+1``
 * are merged only into that turn's tail — never into a later turn's assistant
 * reply (fixes inflated ``tool calls`` after refresh / session switch).
 */
export function mergeCanonicalHistoryPreservingLongTasks(
  prev: UIMessage[],
  historical: UIMessage[],
): UIMessage[] {
  const pUsers = userBoundaryIndices(prev);
  const hUsers = userBoundaryIndices(historical);
  if (pUsers.length === 0 || hUsers.length === 0 || pUsers.length !== hUsers.length) {
    return mergeFallbackLastTurnOnly(prev, historical);
  }

  const out: UIMessage[] = [];
  for (let k = 0; k < hUsers.length; k++) {
    const hStart = hUsers[k]!;
    const hEnd = k + 1 < hUsers.length ? hUsers[k + 1]! : historical.length;
    const userRow = historical[hStart]!;
    const tail = historical.slice(hStart + 1, hEnd);

    const pStart = pUsers[k]! + 1;
    const pEnd = k + 1 < pUsers.length ? pUsers[k + 1]! : prev.length;
    const traces = traceMessagesInRange(prev, pStart, pEnd);

    out.push(userRow, ...insertTracesBeforeLastAssistant(tail, traces));
  }
  return out;
}
