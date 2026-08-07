import type { ChatSummary } from "./types";

const WEBSOCKET_SESSION_KEY_PREFIX = "websocket:";

export function createTemporaryChatSession(chatId: string): ChatSummary {
  const now = new Date().toISOString();
  return {
    key: `${WEBSOCKET_SESSION_KEY_PREFIX}${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: now,
    updatedAt: now,
    preview: "",
  };
}
