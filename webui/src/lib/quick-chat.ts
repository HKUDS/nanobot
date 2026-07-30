import type { ChatSummary } from "@/lib/types";

export const QUICK_CHAT_ID = "quick-chat";
export const QUICK_CHAT_KEY = `websocket:${QUICK_CHAT_ID}`;
export const TEMPORARY_CHAT_ID_PREFIX = "temporary-";

export function isQuickChatKey(key: string | null): boolean {
  return key === QUICK_CHAT_KEY;
}

export function quickChatSession(persisted?: ChatSummary): ChatSummary {
  return {
    key: QUICK_CHAT_KEY,
    channel: "websocket",
    chatId: QUICK_CHAT_ID,
    createdAt: persisted?.createdAt ?? null,
    updatedAt: persisted?.updatedAt ?? null,
    preview: persisted?.preview ?? "",
    modelPreset: persisted?.modelPreset ?? null,
    runStartedAt: persisted?.runStartedAt ?? null,
    workspaceScope: persisted?.workspaceScope ?? null,
  };
}

export function createTemporaryChatSession(): ChatSummary {
  const chatId = `${TEMPORARY_CHAT_ID_PREFIX}${crypto.randomUUID()}`;
  return {
    key: `websocket:${chatId}`,
    channel: "websocket",
    chatId,
    createdAt: null,
    updatedAt: null,
    preview: "",
    modelPreset: null,
    runStartedAt: null,
    workspaceScope: null,
  };
}
