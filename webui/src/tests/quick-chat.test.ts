import { describe, expect, it } from "vitest";

import {
  isQuickChatKey,
  QUICK_CHAT_ID,
  QUICK_CHAT_KEY,
  quickChatSession,
} from "@/lib/quick-chat";

describe("Quick Chat identity", () => {
  it("uses one stable websocket session", () => {
    expect(QUICK_CHAT_ID).toBe("quick-chat");
    expect(QUICK_CHAT_KEY).toBe("websocket:quick-chat");
    expect(isQuickChatKey(QUICK_CHAT_KEY)).toBe(true);
    expect(isQuickChatKey("websocket:another-chat")).toBe(false);
  });

  it("keeps persisted metadata behind the fixed identity", () => {
    expect(quickChatSession({
      key: "websocket:quick-chat",
      channel: "websocket",
      chatId: "quick-chat",
      createdAt: "2026-07-30T08:00:00Z",
      updatedAt: "2026-07-30T08:05:00Z",
      preview: "hello",
      modelPreset: "fast",
    })).toMatchObject({
      key: QUICK_CHAT_KEY,
      channel: "websocket",
      chatId: QUICK_CHAT_ID,
      createdAt: "2026-07-30T08:00:00Z",
      updatedAt: "2026-07-30T08:05:00Z",
      preview: "hello",
      modelPreset: "fast",
    });
  });
});
