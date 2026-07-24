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

export function projectWebuiThreadMessages(messages: UIMessage[]): UIMessage[] {
  const normalized = scrubSubagentUiMessages(normalizeLegacyLongTaskMessages(messages));
  const hiddenTurns = new Set(normalized.flatMap((message) => (
    message.role === "user" && isModelCommandText(message.content) && message.turnId
      ? [message.turnId]
      : []
  )));
  return normalized.filter((message) => (
    !isSystemCommandTurnId(message.turnId)
    && (!message.turnId || !hiddenTurns.has(message.turnId))
    && !(message.role === "user" && isModelCommandText(message.content))
    && !(message.role === "assistant" && isModelCommandResponseText(message.content))
  ));
}
