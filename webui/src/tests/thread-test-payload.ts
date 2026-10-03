import type {
  ThreadProjectionEvent,
  UIMessage,
  WebuiThreadPersistedPayload,
} from "@/lib/types";

// UI-focused tests can describe their expected rows compactly here, but this
// builder always feeds the application the canonical event protocol. The HTTP
// boundary separately verifies that message-projected payloads are rejected.
type MessageFixturePayload = Omit<
  Partial<WebuiThreadPersistedPayload>,
  "events" | "projection"
> & {
  schemaVersion: number;
  messages: UIMessage[];
  fork_boundary_message_count?: number;
};

function eventBase(message: UIMessage, suffix = "") {
  return {
    chat_id: "test-history",
    projection_id: `${message.id}${suffix}`,
    created_at_ms: message.createdAt,
    ...(message.turnId ? { turn_id: message.turnId } : {}),
    ...(message.turnPhase ? { turn_phase: message.turnPhase } : {}),
    ...(message.turnSeq !== undefined ? { turn_seq: message.turnSeq } : {}),
  };
}

function completionEvent(message: UIMessage): ThreadProjectionEvent | null {
  if (
    message.latencyMs === undefined
    && message.usage === undefined
    && message.roundUsages === undefined
    && message.contextWindowTokens === undefined
  ) return null;
  return {
    event: "turn_end",
    ...eventBase(message, ":complete"),
    ...(message.latencyMs !== undefined ? { latency_ms: message.latencyMs } : {}),
    ...(message.usage ? { usage: message.usage } : {}),
    ...(message.roundUsages ? { round_usages: message.roundUsages } : {}),
    ...(message.contextWindowTokens !== undefined
      ? { context_window_tokens: message.contextWindowTokens }
      : {}),
  };
}

function messageEvents(message: UIMessage): ThreadProjectionEvent[] {
  const base = eventBase(message);
  if (message.role === "user") {
    return [{
      event: "user_message",
      ...base,
      text: message.content,
      starts_turn: true,
      ...(message.media?.length ? { media_urls: message.media } : {}),
      ...(message.cliApps?.length ? { cli_apps: message.cliApps } : {}),
      ...(message.mcpPresets?.length ? { mcp_presets: message.mcpPresets } : {}),
      ...(message.sessionMentions?.length
        ? { session_mentions: message.sessionMentions }
        : {}),
    }];
  }
  if (message.kind === "compaction" && message.compaction) {
    return [{
      event: "context_compaction",
      ...base,
      compaction_id: message.compaction.id,
      phase: message.compaction.phase,
    }];
  }
  if (message.kind === "trace" || message.role === "tool") {
    const events: ThreadProjectionEvent[] = [];
    const traces = message.traceDetail
      ? [message.content]
      : message.traces?.length
        ? message.traces
        : message.content
          ? [message.content]
          : [];
    traces.forEach((text, index) => {
      events.push({
        event: "message",
        ...eventBase(message, traces.length === 1 ? "" : `:trace:${index}`),
        text,
        kind: "progress",
        ...(index === traces.length - 1 && message.toolEvents?.length
          ? { tool_events: message.toolEvents }
          : {}),
        ...(index === 0 && message.traceDetail
          ? { trace_detail: message.traceDetail }
          : {}),
      });
    });
    if (message.fileEdits?.length) {
      events.push({
        event: "file_edit",
        ...eventBase(message, ":files"),
        edits: message.fileEdits,
      });
    }
    return events;
  }

  const events: ThreadProjectionEvent[] = [];
  if (message.reasoning) {
    events.push({
      event: "reasoning_delta",
      ...eventBase(message, ":reasoning"),
      text: message.reasoning,
    });
    events.push({
      event: "reasoning_end",
      ...eventBase(message, ":reasoning-end"),
    });
  }
  events.push({
    event: "message",
    ...base,
    text: message.content,
    ...(message.media?.length ? { media_urls: message.media } : {}),
    ...(message.latencyMs !== undefined ? { latency_ms: message.latencyMs } : {}),
  });
  const completion = completionEvent(message);
  if (completion) events.push(completion);
  return events;
}

export function canonicalThreadPayload(
  payload: WebuiThreadPersistedPayload | MessageFixturePayload | null,
): WebuiThreadPersistedPayload | null {
  if (payload === null || "events" in payload) return payload;
  const events = payload.messages.flatMap(messageEvents);
  const boundary = payload.fork_boundary_message_count;
  const forkBoundaryEventIndex = typeof boundary === "number"
    ? payload.messages.slice(0, boundary).flatMap(messageEvents).length
    : undefined;
  const rest = { ...payload } as Record<string, unknown>;
  delete rest.messages;
  delete rest.fork_boundary_message_count;
  const canonical = payload as unknown as Record<string, unknown>;
  delete canonical.messages;
  delete canonical.fork_boundary_message_count;
  Object.assign(canonical, {
    ...rest,
    projection: "events",
    events,
    ...(forkBoundaryEventIndex !== undefined
      ? { fork_boundary_event_index: forkBoundaryEventIndex }
      : {}),
  });
  return payload as unknown as WebuiThreadPersistedPayload;
}
