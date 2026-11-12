import type { CanonicalRunSnapshot } from "./nanobot-client";
import { projectThreadEvents } from "./thread-event-projection";
import type { UIMessage, WebuiThreadPersistedPayload } from "./types";

export function completedAssistantTurnIds(messages: UIMessage[]): string[] {
  return Array.from(new Set(messages.flatMap((message) => (
    message.role === "assistant" && message.turnId ? [message.turnId] : []
  ))));
}

export function persistedCanonicalRunState(body: WebuiThreadPersistedPayload): {
  completedTurnIds: string[];
  snapshot: CanonicalRunSnapshot;
} {
  const suppliedCompletionIds = Array.isArray(body.completed_turn_ids) ? body.completed_turn_ids : null;
  // User identities and explicit completion are wire facts, not rendered messages.
  const snapshot: CanonicalRunSnapshot = {
    observedTurnIds: Array.from(new Set(body.events.flatMap((event) => (
      event.event === "user_message" && event.turn_id ? [event.turn_id] : []
    )))),
    hasPendingToolCalls: body.has_pending_tool_calls !== false,
    activeTurnId: typeof body.active_turn_id === "string" ? body.active_turn_id : null,
    completionIdsProvided: suppliedCompletionIds !== null,
  };
  const completedTurnIds = suppliedCompletionIds?.filter(
    (turnId) => typeof turnId === "string" && turnId.length > 0,
  ) ?? [];
  // The gateway excludes incomplete transcript turns even when their display
  // projection contains turn_end. Only older hosts need idle-state inference.
  if (suppliedCompletionIds === null && !snapshot.hasPendingToolCalls && !snapshot.activeTurnId) {
    completedTurnIds.push(...body.events.flatMap((event) => (
      event.event === "turn_end" && event.turn_id ? [event.turn_id] : []
    )));
    completedTurnIds.push(...completedAssistantTurnIds(projectThreadEvents(body.events)));
  }
  return { completedTurnIds: Array.from(new Set(completedTurnIds)), snapshot };
}
