import type { CanonicalRunSnapshot } from "./nanobot-client";
import { projectThreadEvents } from "./thread-event-projection";
import type { UIMessage, WebuiThreadPersistedPayload } from "./types";

export function completedAssistantTurnIds(messages: UIMessage[]): string[] {
  return Array.from(new Set(messages.flatMap((message) => (
    message.role === "assistant" && message.turnId ? [message.turnId] : []
  ))));
}

export function canonicalRunSnapshot(
  messages: UIMessage[],
  hasPendingToolCalls: boolean,
  activeTurnId: string | null,
  completionIdsProvided = false,
): CanonicalRunSnapshot {
  return {
    observedTurnIds: Array.from(new Set(messages.flatMap((message) => (
      message.role === "user" && message.turnId ? [message.turnId] : []
    )))),
    hasPendingToolCalls,
    activeTurnId,
    completionIdsProvided,
  };
}

export function persistedCanonicalRunState(body: WebuiThreadPersistedPayload): {
  completedTurnIds: string[];
  snapshot: CanonicalRunSnapshot;
} {
  const messages = projectThreadEvents(body.events);
  const suppliedCompletionIds = Array.isArray(body.completed_turn_ids) ? body.completed_turn_ids : null;
  // The older protocol-1 host may omit active_turn_id. Its explicit pending
  // flag still confirms idle; a missing flag cannot establish completion.
  const snapshot = canonicalRunSnapshot(
    messages,
    body.has_pending_tool_calls !== false,
    typeof body.active_turn_id === "string" ? body.active_turn_id : null,
    suppliedCompletionIds !== null,
  );
  const completedTurnIds = suppliedCompletionIds?.filter(
    (turnId) => typeof turnId === "string" && turnId.length > 0,
  ) ?? [];
  // The gateway excludes incomplete transcript turns even when their display
  // projection contains turn_end. Only older hosts need idle-state inference.
  if (suppliedCompletionIds === null && !snapshot.hasPendingToolCalls && !snapshot.activeTurnId) {
    completedTurnIds.push(...body.events.flatMap((event) => (
      event.event === "turn_end" && event.turn_id ? [event.turn_id] : []
    )));
    completedTurnIds.push(...completedAssistantTurnIds(messages));
  }
  return { completedTurnIds: Array.from(new Set(completedTurnIds)), snapshot };
}
