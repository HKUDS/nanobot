import { createThreadProjectionState, type ThreadProjectionState } from "./thread-event-projection";
import type { UIMessage } from "./types";

/** Resumable, memory-only state. Visible rows alone are not a projection cursor. */
export interface ThreadCheckpoint {
  projection: ThreadProjectionState;
  sideChannelTurnIds: Set<string>;
}

export function createThreadCheckpoint(messages: UIMessage[] = []): ThreadCheckpoint {
  return { projection: createThreadProjectionState(messages), sideChannelTurnIds: new Set() };
}

export function copyThreadCheckpoint(
  checkpoint: ThreadCheckpoint,
  messages = checkpoint.projection.messages,
): ThreadCheckpoint {
  return {
    projection: {
      ...checkpoint.projection,
      messages,
      closedAssistantIds: new Set(checkpoint.projection.closedAssistantIds),
      closedAnswerStreamIds: new Set(checkpoint.projection.closedAnswerStreamIds),
      closedTurnIds: new Set(checkpoint.projection.closedTurnIds),
      turnAliases: new Map(checkpoint.projection.turnAliases),
    },
    sideChannelTurnIds: new Set(checkpoint.sideChannelTurnIds),
  };
}
