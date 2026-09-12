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

interface PreparedMessage {
  message: UIMessage;
  hidden: boolean;
  compact: boolean;
}

const preparedMessages = new WeakMap<UIMessage, PreparedMessage>();
const completionMessages = new WeakMap<UIMessage, { completedAt: number; message: UIMessage }>();

function prepareMessage(original: UIMessage): PreparedMessage {
  const cached = preparedMessages.get(original);
  if (cached) return cached;
  const message = scrubSubagentUiMessages(normalizeLegacyLongTaskMessages([original]))[0];
  const prepared = {
    message,
    hidden: isSystemCommandTurnId(message.turnId)
      || (message.role === "user" && isModelCommandText(message.content))
      || (message.role === "assistant" && isModelCommandResponseText(message.content)),
    compact: message.role === "user" && message.content.trim().toLowerCase() === "/compact",
  };
  preparedMessages.set(original, prepared);
  return prepared;
}

export function projectWebuiThreadMessages(messages: UIMessage[]): UIMessage[] {
  const hiddenTurns = new Set<string>();
  const compactTurns = new Set<string>();
  for (const original of messages) {
    const { message, hidden, compact } = prepareMessage(original);
    if (message.role !== "user" || !message.turnId) continue;
    if (hidden && isModelCommandText(message.content)) hiddenTurns.add(message.turnId);
    if (compact && !hidden) compactTurns.add(message.turnId);
  }
  const visible: UIMessage[] = [];
  const starts = new Map<string, number>();
  let latestStart: number | undefined;
  for (const original of messages) {
    const prepared = prepareMessage(original);
    let message = prepared.message;
    if (prepared.hidden || (message.turnId && hiddenTurns.has(message.turnId))) continue;
    if (message.role === "user" && Number.isFinite(message.createdAt)) {
      latestStart = message.createdAt;
      if (message.turnId) starts.set(message.turnId, message.createdAt);
    }
    if (message.role === "assistant" && !message.kind && !message.isStreaming
      && message.turnId && compactTurns.has(message.turnId)) {
      if (message.content === "Nothing to compact.") message = { ...message, compactReply: "empty" };
      if (message.content === "Unable to compact context. Check the logs and try again.") {
        message = { ...message, compactReply: "failed" };
      }
    }
    // Replay latency starts at the user prompt, not the first assistant output.
    if (message.role === "assistant" && message.kind !== "trace"
      && message.completedAt === undefined && message.latencyMs !== undefined
      && Number.isFinite(message.latencyMs) && message.latencyMs >= 0) {
      const start = message.turnId ? starts.get(message.turnId) : message.source ? undefined : latestStart;
      if (start !== undefined) {
        const completedAt = start + message.latencyMs;
        const cached = completionMessages.get(message);
        if (cached?.completedAt === completedAt) message = cached.message;
        else {
          const completed = { ...message, completedAt };
          completionMessages.set(message, { completedAt, message: completed });
          message = completed;
        }
      }
    }
    visible.push(message);
  }
  return visible;
}
