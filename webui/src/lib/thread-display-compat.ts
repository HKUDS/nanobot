import { isModelCommandResponseText, isModelCommandText } from "@/lib/format";
import { isSystemCommandTurnId } from "@/lib/nanobot-client";
import { scrubSubagentUiMessages } from "@/lib/subagent-channel-display";
import type { UIMessage } from "@/lib/types";

/**
 * Older WebUI disk snapshots and historical sessions may still contain
 * ``kind: "long_task"`` rows from the retired orchestrator UI. Map them to
 * ordinary trace rows so the thread stays readable without bespoke cards.
 */
export function normalizeLegacyLongTaskMessages(messages: UIMessage[]): UIMessage[] {
  return messages.map((m) => {
    const kind = (m as { kind?: string }).kind;
    if (kind !== "long_task") return m;
    const text = (m.content ?? "").trim() || "(legacy thread activity)";
    return {
      id: m.id,
      role: "tool",
      kind: "trace",
      content: text,
      traces: [text],
      createdAt: m.createdAt,
    };
  });
}

/**
 * Replay timestamps an assistant row when its first output is recorded, while
 * latency covers the whole turn. Derive the end from the matching user start
 * so the displayed time cannot double-count the pre-output interval.
 */
function deriveAssistantCompletionTimes(messages: UIMessage[]): UIMessage[] {
  const userStartedAtByTurn = new Map<string, number>();
  let latestUserStartedAt: number | undefined;

  return messages.map((message) => {
    if (message.role === "user") {
      if (Number.isFinite(message.createdAt)) {
        latestUserStartedAt = message.createdAt;
        if (message.turnId) userStartedAtByTurn.set(message.turnId, message.createdAt);
      }
      return message;
    }
    if (
      message.role !== "assistant"
      || message.kind === "trace"
      || message.completedAt !== undefined
      || message.latencyMs === undefined
      || !Number.isFinite(message.latencyMs)
      || message.latencyMs < 0
    ) {
      return message;
    }

    const startedAt = message.turnId
      ? userStartedAtByTurn.get(message.turnId)
      : message.source
        ? undefined
        : latestUserStartedAt;
    if (startedAt === undefined) return message;
    return { ...message, completedAt: startedAt + message.latencyMs };
  });
}

export function projectWebuiThreadMessages(messages: UIMessage[]): UIMessage[] {
  const normalized = scrubSubagentUiMessages(normalizeLegacyLongTaskMessages(messages));
  const hiddenTurns = new Set(normalized.flatMap((message) => (
    message.role === "user" && isModelCommandText(message.content) && message.turnId
      ? [message.turnId]
      : []
  )));
  const visible = normalized.filter((message) => (
    !isSystemCommandTurnId(message.turnId)
    && (!message.turnId || !hiddenTurns.has(message.turnId))
    && !(message.role === "user" && isModelCommandText(message.content))
    && !(message.role === "assistant" && isModelCommandResponseText(message.content))
  ));
  return deriveAssistantCompletionTimes(visible);
}
