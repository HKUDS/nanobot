import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteSession,
  fetchSessionMessages,
  listSessions,
  listSlashCommands,
  updateProviderSettings,
  updateSettings,
} from "@/lib/api";

describe("webui API helpers", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ deleted: true, key: "websocket:chat-1", messages: [] }),
      }),
    );
  });

  it("percent-encodes websocket keys when fetching session history", async () => {
    await fetchSessionMessages("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/messages",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("percent-encodes websocket keys when deleting a session", async () => {
    await deleteSession("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/delete",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("serializes settings updates as a narrow query string", async () => {
    await updateSettings("tok", {
      model: "openrouter/test",
      provider: "openrouter",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/settings/update?model=openrouter%2Ftest&provider=openrouter",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("serializes provider settings updates without returning secrets", async () => {
    await updateProviderSettings("tok", {
      provider: "openrouter",
      apiKey: "sk-or-test",
      apiBase: "https://openrouter.ai/api/v1",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/settings/provider/update?provider=openrouter&api_key=sk-or-test&api_base=https%3A%2F%2Fopenrouter.ai%2Fapi%2Fv1",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("maps generated session titles from the sessions list", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        sessions: [
          {
            key: "websocket:chat-1",
            created_at: "2026-05-01T10:00:00",
            updated_at: "2026-05-01T10:01:00",
            title: "优化 WebUI 标题",
          },
        ],
      }),
    } as Response);

    await expect(listSessions("tok")).resolves.toMatchObject([
      {
        key: "websocket:chat-1",
        title: "优化 WebUI 标题",
        preview: "",
      },
    ]);
  });

  it("maps slash command metadata from the commands endpoint", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        commands: [
          {
            command: "/stop",
            title: "Stop current task",
            description: "Cancel the active task.",
            icon: "square",
          },
          {
            command: "/restart",
            title: "Restart nanobot",
            description: "Restart the bot process.",
            icon: "rotate-cw",
          },
          {
            command: "/history",
            title: "Show conversation history",
            description: "Print the last N messages.",
            icon: "history",
            arg_hint: "[n]",
          },
        ],
      }),
    } as Response);

    await expect(listSlashCommands("tok")).resolves.toEqual([
      {
        command: "/history",
        title: "Show conversation history",
        description: "Print the last N messages.",
        icon: "history",
        argHint: "[n]",
      },
    ]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/commands",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });
});
