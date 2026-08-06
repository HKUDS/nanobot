import type { ChatSummary } from "./types";

export const TEMPORARY_CHAT_ID_PREFIX = "temporary-";
const WEBSOCKET_SESSION_KEY_PREFIX = "websocket:";

export function isTemporaryChatId(value: string): boolean {
  return value.startsWith(TEMPORARY_CHAT_ID_PREFIX);
}

export function temporaryChatIdFromSessionKey(value: string | null): string | null {
  if (!value?.startsWith(WEBSOCKET_SESSION_KEY_PREFIX)) return null;
  const chatId = value.slice(WEBSOCKET_SESSION_KEY_PREFIX.length);
  return isTemporaryChatId(chatId) ? chatId : null;
}

export function createTemporaryChatSession(): ChatSummary {
  const chatId = `${TEMPORARY_CHAT_ID_PREFIX}${crypto.randomUUID()}`;
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
