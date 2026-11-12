import { toolTraceLinesFromEvents } from "@/lib/tool-traces";
import type {
  ToolProgressEvent,
  UIFileEdit,
  UIMessage,
  UITurnPhase,
} from "@/lib/types";

export type UIMessageTurnFields = Pick<UIMessage, "turnId" | "turnPhase" | "turnSeq">;

const FILE_EDIT_TOOL_NAMES = new Set(["write_file", "edit_file", "apply_patch"]);

/**
 * PR3 projection seam: replay can share these folds once GatewayContext exposes
 * an ordered canonical-event sequence and a monotonic per-thread revision.
 * Snapshot acceptance and revision comparison stay outside this projection;
 * until then, history continues to consume server-projected UIMessage snapshots.
 */

export function turnFieldsFromEvent(
  ev: { turn_id?: string; turn_phase?: UITurnPhase; turn_seq?: number },
  fallbackPhase?: UITurnPhase,
): UIMessageTurnFields {
  const fields: UIMessageTurnFields = {};
  if (typeof ev.turn_id === "string" && ev.turn_id.length > 0) {
    fields.turnId = ev.turn_id;
  }
  const phase = ev.turn_phase ?? fallbackPhase;
  if (phase) fields.turnPhase = phase;
  if (typeof ev.turn_seq === "number" && Number.isFinite(ev.turn_seq)) {
    fields.turnSeq = ev.turn_seq;
  }
  return fields;
}

export function matchesTurn(message: UIMessage, turn: UIMessageTurnFields): boolean {
  return !turn.turnId || !message.turnId || message.turnId === turn.turnId;
}

/** Find a still-open streamed assistant turn. Closed stream segments stay visible
 * as streaming until ``turn_end`` for visual continuity, but they must not
 * receive later delta segments. */
export function findStreamingAssistantIndex(
  prev: UIMessage[],
  closedStreamIds: ReadonlySet<string>,
  turn: UIMessageTurnFields = {},
): number | null {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const m = prev[i];
    if (m.kind === "trace") continue;
    if (
      m.role === "assistant"
      && m.isStreaming
      && !closedStreamIds.has(m.id)
      && matchesTurn(m, turn)
    ) return i;
    if (m.role === "user") break;
  }
  return null;
}

/**
 * Find the most recent assistant placeholder that an incoming answer
 * delta should adopt instead of spawning a parallel row.
 */
export function findActiveAssistantPlaceholderIndex(
  prev: UIMessage[],
  turn: UIMessageTurnFields = {},
): number | null {
  const last = prev[prev.length - 1];
  if (!last) return null;
  if (last.role !== "assistant" || last.kind === "trace") return null;
  if (last.content.length > 0) return null;
  if (!last.isStreaming) return null;
  if (!matchesTurn(last, turn)) return null;
  return prev.length - 1;
}

export function replaceMessageAt(
  prev: UIMessage[],
  index: number,
  message: UIMessage,
): UIMessage[] {
  const next = prev.slice();
  next[index] = message;
  return next;
}

/** Close the active reasoning stream segment. ``now`` is supplied by the caller
 * so the projection remains deterministic for replay and fixture tests. */
export function closeReasoningStream(prev: UIMessage[], now: number): UIMessage[] {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const candidate = prev[i];
    if (!candidate.reasoningStreaming) continue;
    const latencyMs =
      candidate.latencyMs === undefined
      && Number.isFinite(candidate.createdAt)
      && candidate.createdAt > 1_000_000_000_000
        ? Math.max(0, Math.round(now - candidate.createdAt))
        : candidate.latencyMs;
    const merged: UIMessage = {
      ...candidate,
      reasoningStreaming: false,
      ...(latencyMs !== undefined ? { latencyMs } : {}),
    };
    return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
  }
  return prev;
}

export function isReasoningOnlyPlaceholder(message: UIMessage): boolean {
  return (
    message.role === "assistant"
    && message.kind !== "trace"
    && message.content.trim().length === 0
    && !!message.reasoning
    && !message.reasoningStreaming
    && !message.media?.length
  );
}

export function stampLastAssistantCompletion(
  prev: UIMessage[],
  completion: Pick<
    UIMessage,
    "latencyMs" | "completedAt" | "usage" | "roundUsages" | "contextWindowTokens"
  >,
  turnId?: string,
): UIMessage[] {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const m = prev[i];
    if (
      m.role === "assistant"
      && m.kind !== "trace"
      && (!turnId || !m.turnId || m.turnId === turnId)
    ) {
      const merged: UIMessage = { ...m, ...completion, isStreaming: false };
      return [...prev.slice(0, i), merged, ...prev.slice(i + 1)];
    }
  }
  return prev;
}

function fileEditKey(edit: Pick<UIFileEdit, "call_id" | "tool" | "path">): string {
  if (edit.call_id && edit.path) return `${edit.call_id}|${edit.tool}|${edit.path}`;
  if (edit.call_id) return `${edit.call_id}|${edit.tool}`;
  return `${edit.tool}|${edit.path}`;
}

function fileEditToolEventKey(
  edit: Pick<UIFileEdit, "call_id" | "tool" | "path">,
): string {
  if (edit.call_id) return `${edit.call_id}|${edit.tool}`;
  return fileEditKey(edit);
}

function toolEventFileEditKey(event: ToolProgressEvent): string | null {
  const fn = (event as { function?: { name?: unknown } }).function;
  const name = typeof event.name === "string"
    ? event.name
    : typeof fn?.name === "string"
      ? fn.name
      : "";
  const callId = typeof event.call_id === "string" ? event.call_id : "";
  if (!name || !callId || !FILE_EDIT_TOOL_NAMES.has(name)) return null;
  return `${callId}|${name}`;
}

function hasFileEditForToolEvent(messages: UIMessage[], event: ToolProgressEvent): boolean {
  const key = toolEventFileEditKey(event);
  if (!key) return false;
  return messages.some((message) =>
    message.fileEdits?.some((edit) => fileEditToolEventKey(edit) === key),
  );
}

export function filterCoveredFileEditToolEvents(
  messages: UIMessage[],
  events: ToolProgressEvent[],
): ToolProgressEvent[] {
  if (events.length === 0) return events;
  return events.filter((event) => !hasFileEditForToolEvent(messages, event));
}

function stripCoveredFileEditToolHints(message: UIMessage, edits: UIFileEdit[]): UIMessage {
  const incomingKeys = new Set(edits.map(fileEditToolEventKey));
  const events = message.toolEvents ?? [];
  if (!events.length || incomingKeys.size === 0) return message;

  const removedTraceLines = new Set<string>();
  const keptEvents: ToolProgressEvent[] = [];
  let changed = false;
  for (const event of events) {
    const key = toolEventFileEditKey(event);
    if (key && incomingKeys.has(key)) {
      changed = true;
      for (const line of toolTraceLinesFromEvents([event])) {
        removedTraceLines.add(line);
      }
      continue;
    }
    keptEvents.push(event);
  }
  if (!changed) return message;

  const previousTraces = message.traces?.length
    ? message.traces
    : message.content
      ? [message.content]
      : [];
  const nextTraces = previousTraces.filter((line) => !removedTraceLines.has(line));
  return {
    ...message,
    traces: nextTraces,
    content: nextTraces[nextTraces.length - 1] ?? "",
    toolEvents: keptEvents.length ? keptEvents : undefined,
  };
}

function traceMessageIsEmpty(message: UIMessage): boolean {
  const traces = message.traces;
  const hasTrace = traces?.length
    ? traces.some((line) => line.trim().length > 0)
    : (message.content ?? "").trim().length > 0;
  return (
    message.kind === "trace"
    && !hasTrace
    && !message.toolEvents?.length
    && !message.fileEdits?.length
    && !message.media?.length
  );
}

export function stripCoveredFileEditToolHintsFromMessages(
  messages: UIMessage[],
  edits: UIFileEdit[],
  turn: UIMessageTurnFields,
): UIMessage[] {
  if (edits.length === 0) return messages;
  let next = messages;
  for (let i = next.length - 1; i >= 0; i -= 1) {
    const candidate = next[i];
    if (candidate.role === "user") break;
    if (candidate.kind !== "trace") continue;
    if (!matchesTurn(candidate, turn)) continue;
    const cleaned = stripCoveredFileEditToolHints(candidate, edits);
    if (cleaned === candidate) continue;
    if (next === messages) next = [...messages];
    if (traceMessageIsEmpty(cleaned)) {
      next.splice(i, 1);
    } else {
      next[i] = cleaned;
    }
  }
  return next;
}

function normalizeFileEdit(edit: UIFileEdit): UIFileEdit | null {
  if (!edit || !edit.tool || (!edit.path && !edit.pending)) return null;
  const inferredStatus =
    edit.phase === "error"
      ? "error"
      : edit.phase === "end"
        ? "done"
        : "editing";
  const normalized: UIFileEdit = {
    ...edit,
    call_id: edit.call_id || `${edit.tool}:${edit.path}`,
    added: Number.isFinite(edit.added) ? Math.max(0, Math.round(edit.added)) : 0,
    deleted: Number.isFinite(edit.deleted) ? Math.max(0, Math.round(edit.deleted)) : 0,
    status: edit.status === "error" || edit.status === "done" || edit.status === "editing"
      ? edit.status
      : inferredStatus,
  };
  if (edit.pending && !edit.path) normalized.pending = true;
  return normalized;
}

export function mergeFileEdits(
  existing: UIFileEdit[] | undefined,
  incoming: UIFileEdit[],
): UIFileEdit[] {
  const next = [...(existing ?? [])];
  const indexByKey = new Map(next.map((edit, index) => [fileEditKey(edit), index]));
  for (const raw of incoming) {
    const edit = normalizeFileEdit(raw);
    if (!edit) continue;
    const key = fileEditKey(edit);
    let existingIndex = indexByKey.get(key);
    if (existingIndex === undefined && edit.path) {
      const eventKey = fileEditToolEventKey(edit);
      const pendingIndex = next.findIndex((existing) =>
        !existing.path && existing.pending && fileEditToolEventKey(existing) === eventKey,
      );
      if (pendingIndex >= 0) existingIndex = pendingIndex;
    }
    if (existingIndex === undefined) {
      indexByKey.set(key, next.length);
      next.push(edit);
      continue;
    }
    const merged = { ...next[existingIndex], ...edit };
    if (edit.path && !edit.pending) delete merged.pending;
    next[existingIndex] = merged;
    indexByKey.set(key, existingIndex);
  }
  return next;
}

export function findFileEditTraceIndex(
  prev: UIMessage[],
  segmentId: string | null,
  incoming: UIFileEdit[],
): number | null {
  const incomingKeys = new Set(incoming.map(fileEditKey));
  const incomingToolEventKeys = new Set(incoming.map(fileEditToolEventKey));
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const candidate = prev[i];
    if (candidate.role === "user") break;
    if (candidate.kind !== "trace") continue;
    if (segmentId && candidate.activitySegmentId === segmentId) return i;
    for (const existing of candidate.fileEdits ?? []) {
      if (
        incomingKeys.has(fileEditKey(existing))
        || (
          !existing.path
          && existing.pending
          && incomingToolEventKeys.has(fileEditToolEventKey(existing))
        )
      ) return i;
    }
  }
  return null;
}

export function finalizeStreamedTurn(
  prev: UIMessage[],
  turn: UIMessageTurnFields = {},
): UIMessage[] {
  return prev.map((m) =>
    m.isStreaming && matchesTurn(m, turn)
      ? { ...m, isStreaming: false, reasoningStreaming: false }
      : m,
  );
}
