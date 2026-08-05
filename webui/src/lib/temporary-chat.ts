import type { ChatSummary } from "./types";

export const TEMPORARY_CHAT_ID_PREFIX = "temporary-";
export const TEMPORARY_CHAT_ROUTE_KEY = "__temporary_chat__";

export function isTemporaryChatId(value: string): boolean {
  return value.startsWith(TEMPORARY_CHAT_ID_PREFIX);
}

export function createTemporaryChatSession(): ChatSummary {
  const chatId = `${TEMPORARY_CHAT_ID_PREFIX}${crypto.randomUUID()}`;
  const now = new Date().toISOString();
  return {
    key: `websocket:${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: now,
    updatedAt: now,
    preview: "",
  };
}
