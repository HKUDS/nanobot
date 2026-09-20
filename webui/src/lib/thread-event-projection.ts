import { toMediaAttachment } from "@/lib/media";
import {
  mergeToolProgressEvents,
  mergeToolProgressTraceLines,
  normalizeToolProgressEvents,
  toolTraceLinesFromEvents,
} from "@/lib/tool-traces";
import type {
  ThreadProjectionEvent,
  ToolProgressEvent,
  UIFileEdit,
  UIMessage,
  UITurnPhase,
} from "@/lib/types";

export type { ThreadProjectionEvent } from "@/lib/types";

export type UIMessageTurnFields = Pick<UIMessage, "turnId" | "turnPhase" | "turnSeq">;

const FILE_EDIT_TOOL_NAMES = new Set(["write_file", "edit_file", "apply_patch"]);

export interface ThreadProjectionState {
  messages: UIMessage[];
  activeAssistantId: string | null;
  closedAssistantIds: Set<string>;
  mergeReasoning: boolean;
  activitySegmentId: string | null;
  fileEditSegmentId: string | null;
  activitySegmentCounter: number;
  suppressUntilTurnEnd: boolean;
  closedTurnIds: Set<string>;
  turnAliases: Map<string, string>;
}

export interface ThreadProjectionOptions {
  createId: () => string;
  now: number;
  persisted?: boolean;
  sideChannel?: boolean;
}

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
export function closeReasoningStream(prev: UIMessage[], now?: number): UIMessage[] {
  for (let i = prev.length - 1; i >= 0; i -= 1) {
    const candidate = prev[i];
    if (!candidate.reasoningStreaming) continue;
    const latencyMs =
      now !== undefined
      && candidate.latencyMs === undefined
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

export function createThreadProjectionState(
  messages: UIMessage[] = [],
): ThreadProjectionState {
  return {
    messages,
    activeAssistantId: null,
    closedAssistantIds: new Set(),
    mergeReasoning: false,
    activitySegmentId: null,
    fileEditSegmentId: null,
    activitySegmentCounter: 0,
    suppressUntilTurnEnd: false,
    closedTurnIds: new Set(),
    turnAliases: new Map(),
  };
}

export function resetThreadProjectionCursor(
  state: ThreadProjectionState,
  messages: UIMessage[] = state.messages,
): ThreadProjectionState {
  return {
    ...createThreadProjectionState(messages),
    activitySegmentCounter: state.activitySegmentCounter,
    closedTurnIds: new Set(state.closedTurnIds),
    turnAliases: new Map(state.turnAliases),
  };
}

export function clearThreadProjectionActivity(
  state: ThreadProjectionState,
): ThreadProjectionState {
  return {
    ...state,
    activitySegmentId: null,
    fileEditSegmentId: null,
  };
}

export function closeThreadProjectionAnswer(
  state: ThreadProjectionState,
): ThreadProjectionState {
  if (!state.activeAssistantId) return state;
  const closedAssistantIds = new Set(state.closedAssistantIds);
  closedAssistantIds.add(state.activeAssistantId);
  return {
    ...state,
    activeAssistantId: null,
    closedAssistantIds,
    mergeReasoning: false,
  };
}

function projectionCreatedAt(event: ThreadProjectionEvent, options: ThreadProjectionOptions): number {
  return typeof event.created_at_ms === "number" && Number.isFinite(event.created_at_ms)
    ? event.created_at_ms
    : options.now;
}

function projectionMessageId(
  event: ThreadProjectionEvent,
  options: ThreadProjectionOptions,
): string {
  return typeof event.projection_id === "string" && event.projection_id.length > 0
    ? event.projection_id
    : options.createId();
}

function turnFieldsForProjection(
  state: ThreadProjectionState,
  event: ThreadProjectionEvent,
  fallbackPhase?: UITurnPhase,
): UIMessageTurnFields {
  const fields = turnFieldsFromEvent(event, fallbackPhase);
  const rawTurnId = fields.turnId;
  if (!rawTurnId || !state.closedTurnIds.has(rawTurnId)) return fields;
  let alias = state.turnAliases.get(rawTurnId);
  if (!alias) {
    const suffix = event.projection_id || event.created_at_ms || state.messages.length;
    alias = `${rawTurnId}:replay:${suffix}`;
    state.turnAliases.set(rawTurnId, alias);
  }
  return { ...fields, turnId: alias };
}

function ensureProjectionActivitySegment(state: ThreadProjectionState): string {
  if (state.activitySegmentId) return state.activitySegmentId;
  state.activitySegmentCounter += 1;
  state.activitySegmentId = `activity-${state.activitySegmentCounter}`;
  return state.activitySegmentId;
}

function detachedProjectionActivitySegment(state: ThreadProjectionState): string {
  state.activitySegmentCounter += 1;
  return `activity-${state.activitySegmentCounter}`;
}

function activeAssistantIndex(
  state: ThreadProjectionState,
  turn: UIMessageTurnFields,
): number | null {
  if (!state.activeAssistantId) return null;
  const index = state.messages.findIndex((message) => message.id === state.activeAssistantId);
  if (index < 0) {
    state.activeAssistantId = null;
    state.mergeReasoning = false;
    return null;
  }
  const message = state.messages[index];
  if (
    message.role !== "assistant"
    || message.kind === "trace"
    || !message.isStreaming
    || !matchesTurn(message, turn)
  ) {
    state.activeAssistantId = null;
    state.mergeReasoning = false;
    return null;
  }
  return index;
}

function appendAnswerText(
  state: ThreadProjectionState,
  event: Extract<ThreadProjectionEvent, { event: "delta" }>,
  options: ThreadProjectionOptions,
): void {
  const turn = turnFieldsForProjection(state, event, "answer");
  let targetIndex = activeAssistantIndex(state, turn);
  if (targetIndex === null) targetIndex = findActiveAssistantPlaceholderIndex(state.messages, turn);
  if (targetIndex === null) {
    targetIndex = findStreamingAssistantIndex(state.messages, state.closedAssistantIds, turn);
  }
  if (targetIndex === null) {
    const id = projectionMessageId(event, options);
    state.messages = [
      ...state.messages,
      {
        id,
        role: "assistant",
        content: "",
        isStreaming: true,
        createdAt: projectionCreatedAt(event, options),
      },
    ];
    targetIndex = state.messages.length - 1;
  }
  const target = state.messages[targetIndex];
  const merged: UIMessage = {
    ...target,
    content: target.content + event.text,
    isStreaming: true,
    ...turn,
    ...(event.source ? { source: event.source } : {}),
    ...(event.response_sources !== undefined ? { responseSources: event.response_sources } : {}),
  };
  state.closedAssistantIds.delete(merged.id);
  state.activeAssistantId = merged.id;
  state.mergeReasoning = false;
  state.messages = replaceMessageAt(state.messages, targetIndex, merged);
}

function attachProjectedReasoning(
  state: ThreadProjectionState,
  event: Extract<ThreadProjectionEvent, { event: "reasoning_delta" | "reasoning_end" }>,
  text: string,
  options: ThreadProjectionOptions,
): void {
  const turn = turnFieldsForProjection(state, event, "reasoning");
  const activeAssistantBeforeContinuation = state.activeAssistantId;
  const continuationIndex = state.mergeReasoning
    ? activeAssistantIndex(state, turn)
    : null;
  if (continuationIndex !== null) {
    const target = state.messages[continuationIndex];
    const separator = target.reasoning && !target.reasoningStreaming ? "\n\n" : "";
    state.messages = replaceMessageAt(state.messages, continuationIndex, {
      ...target,
      reasoning: (target.reasoning ?? "") + separator + text,
      reasoningStreaming: true,
    });
    return;
  }

  if (state.fileEditSegmentId || activeAssistantBeforeContinuation) {
    if (activeAssistantBeforeContinuation && !state.activeAssistantId) {
      state.closedAssistantIds.add(activeAssistantBeforeContinuation);
    }
    const closed = closeThreadProjectionAnswer(state);
    Object.assign(state, clearThreadProjectionActivity(closed));
  }
  for (let index = state.messages.length - 1; index >= 0; index -= 1) {
    const candidate = state.messages[index];
    if (candidate.role === "user" || candidate.kind === "trace") break;
    if (candidate.role !== "assistant") continue;
    if (!matchesTurn(candidate, turn) || candidate.content.length > 0) break;
    if (candidate.reasoningStreaming || (candidate.isStreaming && candidate.reasoning === undefined)) {
      const activitySegmentId = candidate.activitySegmentId
        ?? ensureProjectionActivitySegment(state);
      state.messages = replaceMessageAt(state.messages, index, {
        ...candidate,
        reasoning: (candidate.reasoning ?? "") + text,
        reasoningStreaming: true,
        activitySegmentId,
        ...turn,
      });
      return;
    }
    break;
  }

  const activitySegmentId = ensureProjectionActivitySegment(state);
  state.messages = [
    ...state.messages,
    {
      id: projectionMessageId(event, options),
      role: "assistant",
      content: "",
      isStreaming: true,
      reasoning: text,
      reasoningStreaming: true,
      activitySegmentId,
      ...turn,
      createdAt: projectionCreatedAt(event, options),
    },
  ];
}

function absorbProjectedAssistantMessage(
  state: ThreadProjectionState,
  event: Extract<ThreadProjectionEvent, { event: "message" }>,
  message: Omit<UIMessage, "id" | "role" | "createdAt">,
  options: ThreadProjectionOptions,
): void {
  const last = state.messages[state.messages.length - 1];
  if (last && isReasoningOnlyPlaceholder(last) && matchesTurn(last, message)) {
    state.messages = [
      ...state.messages.slice(0, -1),
      {
        ...last,
        ...message,
        isStreaming: false,
        reasoningStreaming: false,
      },
    ];
    return;
  }
  state.messages = [
    ...state.messages,
    {
      id: projectionMessageId(event, options),
      role: "assistant",
      createdAt: projectionCreatedAt(event, options),
      ...message,
    },
  ];
}

function projectToolActivity(
  state: ThreadProjectionState,
  event: Extract<ThreadProjectionEvent, { event: "message" }>,
  options: ThreadProjectionOptions,
): void {
  Object.assign(state, closeThreadProjectionAnswer(state));
  const structuredEvents = normalizeToolProgressEvents(event.tool_events);
  const visibleEvents = filterCoveredFileEditToolEvents(state.messages, structuredEvents);
  const structuredLines = toolTraceLinesFromEvents(visibleEvents);
  const lines = structuredLines.length > 0
    ? structuredLines
    : structuredEvents.length > 0
      ? []
      : event.text
        ? [event.text]
        : [];
  if (lines.length === 0) return;

  const segmentId = ensureProjectionActivitySegment(state);
  const turn = turnFieldsForProjection(state, event, "activity");
  const last = state.messages[state.messages.length - 1];
  if (
    last
    && last.kind === "trace"
    && !last.isStreaming
    && (!last.activitySegmentId || last.activitySegmentId === segmentId)
  ) {
    const previousTraces = last.traces?.length
      ? last.traces
      : last.content
        ? [last.content]
        : [];
    const mergedEvents = visibleEvents.length > 0
      ? mergeToolProgressEvents(last.toolEvents, visibleEvents)
      : last.toolEvents;
    const mergedLines = visibleEvents.length > 0
      ? mergeToolProgressTraceLines(
          previousTraces,
          last.toolEvents,
          structuredLines,
          visibleEvents,
        )
      : null;
    state.messages = [
      ...state.messages.slice(0, -1),
      {
        ...last,
        traces: mergedLines ?? [...previousTraces, ...lines],
        content: mergedLines
          ? mergedLines[mergedLines.length - 1]
          : lines[lines.length - 1],
        toolEvents: mergedEvents,
        activitySegmentId: last.activitySegmentId ?? segmentId,
        ...turn,
      },
    ];
    return;
  }
  state.messages = [
    ...state.messages,
    {
      id: projectionMessageId(event, options),
      role: "tool",
      kind: "trace",
      content: lines[lines.length - 1],
      traces: lines,
      ...(visibleEvents.length ? { toolEvents: visibleEvents } : {}),
      activitySegmentId: segmentId,
      ...turn,
      createdAt: projectionCreatedAt(event, options),
    },
  ];
}

function projectFileEdits(
  state: ThreadProjectionState,
  event: Extract<ThreadProjectionEvent, { event: "file_edit" }>,
  options: ThreadProjectionOptions,
): void {
  Object.assign(state, closeThreadProjectionAnswer(state));
  const normalized = mergeFileEdits(undefined, event.edits);
  if (normalized.length === 0) return;
  const turn = turnFieldsForProjection(state, event, "activity");
  const opensPhase = normalized.some(
    (edit) => edit.status === "editing" || edit.phase === "start",
  );
  let segmentId = state.fileEditSegmentId;
  if (!segmentId && opensPhase) {
    segmentId = detachedProjectionActivitySegment(state);
    state.fileEditSegmentId = segmentId;
  }
  const base = stripCoveredFileEditToolHintsFromMessages(state.messages, normalized, turn);
  const targetIndex = findFileEditTraceIndex(base, segmentId, normalized);
  if (targetIndex !== null) {
    const target = base[targetIndex];
    segmentId = target.activitySegmentId ?? segmentId ?? detachedProjectionActivitySegment(state);
    if (opensPhase) state.fileEditSegmentId = segmentId;
    state.messages = replaceMessageAt(base, targetIndex, {
      ...target,
      fileEdits: mergeFileEdits(target.fileEdits, normalized),
      activitySegmentId: segmentId,
      ...turn,
    });
    return;
  }
  segmentId = segmentId ?? detachedProjectionActivitySegment(state);
  if (opensPhase) state.fileEditSegmentId = segmentId;
  state.messages = [
    ...base,
    {
      id: projectionMessageId(event, options),
      role: "tool",
      kind: "trace",
      content: "",
      traces: [],
      fileEdits: normalized,
      activitySegmentId: segmentId,
      ...turn,
      createdAt: projectionCreatedAt(event, options),
    },
  ];
}

/** Canonical UI-message reducer shared by WebSocket delivery and transcript replay. */
export function projectThreadEvent(
  previous: ThreadProjectionState,
  event: ThreadProjectionEvent,
  options: ThreadProjectionOptions,
): ThreadProjectionState {
  const state: ThreadProjectionState = {
    ...previous,
    closedAssistantIds: new Set(previous.closedAssistantIds),
    closedTurnIds: new Set(previous.closedTurnIds),
    turnAliases: new Map(previous.turnAliases),
  };

  if (event.event === "user_message") {
    if (event.provenance?.session_message) {
      const messageId = event.provenance.session_message.message_id?.trim();
      if (!messageId || state.messages.some(
        (message) => message.sessionMessage?.message_id === messageId,
      )) return state;
    } else if (event.turn_id && state.messages.some(
      (message) => message.role === "user" && message.turnId === event.turn_id,
    )) return state;
    if (state.activeAssistantId) {
      state.messages = state.messages.map((message) => (
        message.id === state.activeAssistantId ? { ...message, isStreaming: false } : message
      ));
    }
    state.messages = closeReasoningStream(
      state.messages,
      options.persisted ? undefined : options.now,
    );
    Object.assign(state, resetThreadProjectionCursor(state, state.messages));
    const media = event.media_urls?.map((item) => toMediaAttachment(item));
    const turn = turnFieldsForProjection(state, event, "user");
    const row: UIMessage = {
      id: projectionMessageId(event, options),
      role: "user",
      content: event.text,
      createdAt: projectionCreatedAt(event, options),
      ...turn,
      ...(!options.persisted ? { deliveryStatus: "accepted" as const } : {}),
      ...(media?.length ? { media } : {}),
      ...(event.cli_apps?.length ? { cliApps: event.cli_apps } : {}),
      ...(event.mcp_presets?.length ? { mcpPresets: event.mcp_presets } : {}),
      ...(event.session_mentions?.length ? { sessionMentions: event.session_mentions } : {}),
      ...(event.provenance?.session_message
        ? { sessionMessage: event.provenance.session_message }
        : {}),
    };
    if (media?.length && media.every((item) => item.kind === "image")) {
      row.images = media.map(({ url, name }) => ({ url, name }));
    }
    state.messages = [...state.messages, row];
    return state;
  }

  if (event.event === "delta") {
    if (!state.suppressUntilTurnEnd && event.text) {
      state.activitySegmentId = null;
      state.fileEditSegmentId = null;
      appendAnswerText(state, event, options);
    }
    return state;
  }

  if (event.event === "stream_end") {
    if (state.suppressUntilTurnEnd) return state;
    const turn = turnFieldsForProjection(state, event, "answer");
    const mergeNext = event.resuming === true && event.merge_next === true;
    let targetIndex = activeAssistantIndex(state, turn);
    if (targetIndex === null) {
      targetIndex = findStreamingAssistantIndex(state.messages, state.closedAssistantIds, turn);
    }
    if (typeof event.text === "string") {
      if (targetIndex === null) {
        const id = projectionMessageId(event, options);
        state.messages = [
          ...state.messages,
          {
            id,
            role: "assistant",
            content: event.text,
            isStreaming: true,
            ...turn,
            ...(event.source ? { source: event.source } : {}),
            ...(event.response_sources !== undefined ? { responseSources: event.response_sources } : {}),
            createdAt: projectionCreatedAt(event, options),
          },
        ];
        targetIndex = state.messages.length - 1;
      } else {
        const target = state.messages[targetIndex];
        state.messages = replaceMessageAt(state.messages, targetIndex, {
          ...target,
          content: event.text,
          isStreaming: true,
          ...turn,
          ...(event.source ? { source: event.source } : {}),
          ...(event.response_sources !== undefined ? { responseSources: event.response_sources } : {}),
        });
      }
    } else if ((event.source || event.response_sources !== undefined) && targetIndex !== null) {
      state.messages = replaceMessageAt(state.messages, targetIndex, {
        ...state.messages[targetIndex],
        ...turn,
        ...(event.source ? { source: event.source } : {}),
        ...(event.response_sources !== undefined ? { responseSources: event.response_sources } : {}),
      });
    }
    if (targetIndex !== null) state.activeAssistantId = state.messages[targetIndex].id;
    state.mergeReasoning = mergeNext && state.activeAssistantId !== null;
    if (!mergeNext) Object.assign(state, closeThreadProjectionAnswer(state));
    return state;
  }

  if (event.event === "reasoning_delta") {
    if (!state.suppressUntilTurnEnd && event.text) {
      attachProjectedReasoning(state, event, event.text, options);
    }
    return state;
  }

  if (event.event === "reasoning_end") {
    if (state.suppressUntilTurnEnd) return state;
    if (event.text) attachProjectedReasoning(state, event, event.text, options);
    state.messages = closeReasoningStream(
      state.messages,
      options.persisted ? undefined : options.now,
    );
    return state;
  }

  if (event.event === "context_compaction") {
    Object.assign(state, closeThreadProjectionAnswer(state));
    const id = `compaction-${event.compaction_id}`;
    const existing = state.messages.findIndex((message) => message.id === id);
    const message: UIMessage = {
      id,
      role: "assistant",
      content: "",
      kind: "compaction",
      createdAt: projectionCreatedAt(event, options),
      compaction: {
        id: event.compaction_id,
        phase: event.phase,
        ...(!options.persisted ? { announce: true } : {}),
      },
      ...turnFieldsForProjection(state, event, "activity"),
    };
    if (existing < 0) state.messages = [...state.messages, message];
    else state.messages = replaceMessageAt(state.messages, existing, {
      ...message,
      createdAt: state.messages[existing].createdAt,
    });
    state.activitySegmentId = null;
    state.fileEditSegmentId = null;
    return state;
  }

  if (event.event === "message") {
    if (
      state.suppressUntilTurnEnd
      && (event.kind === "tool_hint" || event.kind === "progress" || event.kind === "reasoning")
    ) return state;
    if (event.kind === "reasoning") {
      if (event.text) {
        attachProjectedReasoning(state, {
          ...event,
          event: "reasoning_delta",
        }, event.text, options);
        state.messages = closeReasoningStream(
          state.messages,
          options.persisted ? undefined : options.now,
        );
      }
      return state;
    }
    if (event.kind === "tool_hint" || event.kind === "progress") {
      projectToolActivity(state, event, options);
      return state;
    }

    const media = event.media_urls?.map((item) => toMediaAttachment(item))
      ?? event.media?.map((url) => toMediaAttachment({ url }));
    const latencyMs = typeof event.latency_ms === "number" && event.latency_ms >= 0
      ? Math.round(event.latency_ms)
      : undefined;
    const projected = {
      content: event.text,
      ...(media?.length ? { media } : {}),
      ...(latencyMs !== undefined ? { latencyMs } : {}),
      ...(event.source ? { source: event.source } : {}),
      ...(event.response_sources !== undefined ? { responseSources: event.response_sources } : {}),
      ...turnFieldsForProjection(state, event, "answer"),
    };
    if (options.sideChannel) {
      absorbProjectedAssistantMessage(state, event, projected, options);
      return state;
    }
    const activeId = state.activeAssistantId;
    Object.assign(state, closeThreadProjectionAnswer(state));
    if (activeId) state.messages = state.messages.filter((message) => message.id !== activeId);
    absorbProjectedAssistantMessage(state, event, projected, options);
    state.activitySegmentId = null;
    state.fileEditSegmentId = null;
    if (media?.length) state.suppressUntilTurnEnd = true;
    return state;
  }

  if (event.event === "file_edit") {
    projectFileEdits(state, event, options);
    return state;
  }

  const turn = turnFieldsForProjection(state, event, "complete");
  state.suppressUntilTurnEnd = false;
  state.activitySegmentId = null;
  state.fileEditSegmentId = null;
  state.messages = finalizeStreamedTurn(state.messages);
  const latencyMs = typeof event.latency_ms === "number" && event.latency_ms >= 0
    ? Math.round(event.latency_ms)
    : undefined;
  state.messages = stampLastAssistantCompletion(
    state.messages,
    {
      ...(latencyMs !== undefined ? { latencyMs } : {}),
      ...(event.usage ? { usage: event.usage } : {}),
      ...(event.round_usages?.length ? { roundUsages: event.round_usages } : {}),
      ...(typeof event.context_window_tokens === "number"
        ? { contextWindowTokens: event.context_window_tokens }
        : {}),
      ...(!options.persisted ? { completedAt: options.now } : {}),
    },
    turn.turnId,
  );
  state.activeAssistantId = null;
  state.closedAssistantIds.clear();
  state.mergeReasoning = false;
  if (event.turn_id) {
    if (state.turnAliases.has(event.turn_id)) state.turnAliases.delete(event.turn_id);
    else state.closedTurnIds.add(event.turn_id);
  }
  return state;
}

export function projectThreadEvents(events: ThreadProjectionEvent[]): UIMessage[] {
  let state = createThreadProjectionState();
  const fallbackNow = Date.now();
  events.forEach((event, index) => {
    state = projectThreadEvent(state, event, {
      createId: () => `history-${index}`,
      now: typeof event.created_at_ms === "number"
        ? event.created_at_ms
        : fallbackNow + index,
      persisted: true,
    });
  });
  return state.messages.map((row) => {
    const message = { ...row };
    delete message.isStreaming;
    delete message.reasoningStreaming;
    return message;
  });
}
