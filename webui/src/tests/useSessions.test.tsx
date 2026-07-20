import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { sessionTitle, useSessionHistory, useSessions } from "@/hooks/useSessions";
import * as api from "@/lib/api";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listSessions: vi.fn(),
    deleteSession: vi.fn(),
    fetchWebuiThread: vi.fn(),
  };
});

function fakeClient() {
  const sessionUpdateHandlers = new Set<(chatId: string, scope?: string) => void>();
  return {
    status: "open" as const,
    defaultChatId: null as string | null,
    onStatus: () => () => {},
    onError: () => () => {},
    onChat: () => () => {},
    getRunStartedAt: () => null,
    onSessionUpdate: (handler: (chatId: string, scope?: string) => void) => {
      sessionUpdateHandlers.add(handler);
      return () => sessionUpdateHandlers.delete(handler);
    },
    emitSessionUpdate: (chatId: string, scope?: string) => {
      for (const handler of sessionUpdateHandlers) handler(chatId, scope);
    },
    sendMessage: vi.fn(),
    newChat: vi.fn(),
    forkChat: vi.fn(),
    attach: vi.fn(),
    connect: vi.fn(),
    close: vi.fn(),
    updateUrl: vi.fn(),
  };
}

function wrap(client: ReturnType<typeof fakeClient>) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ClientProvider
        client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
        token="tok"
      >
        {children}
      </ClientProvider>
    );
  };
}

describe("useSessions", () => {
  beforeEach(() => {
    vi.mocked(api.listSessions).mockReset();
    vi.mocked(api.deleteSession).mockReset();
    vi.mocked(api.fetchWebuiThread).mockReset();
  });

  it("does not use low-information greetings as fallback session titles", () => {
    expect(sessionTitle({
      key: "websocket:chat-hi",
      channel: "websocket",
      chatId: "chat-hi",
      createdAt: "2026-04-16T10:00:00Z",
      updatedAt: "2026-04-16T10:00:00Z",
      title: "",
      preview: "hi",
    })).toBe("New chat");

    expect(sessionTitle({
      key: "websocket:chat-work",
      channel: "websocket",
      chatId: "chat-work",
      createdAt: "2026-04-16T10:00:00Z",
      updatedAt: "2026-04-16T10:00:00Z",
      title: "",
      preview: "帮我优化 WebUI 性能",
    })).toBe("帮我优化 WebUI 性能");
  });

  it("removes a session from the local list after delete succeeds", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Alpha",
      },
      {
        key: "websocket:chat-b",
        channel: "websocket",
        chatId: "chat-b",
        createdAt: "2026-04-16T11:00:00Z",
        updatedAt: "2026-04-16T11:00:00Z",
        preview: "Beta",
      },
    ]);
    vi.mocked(api.deleteSession).mockResolvedValue({ deleted: true });

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(2));

    await act(async () => {
      await result.current.deleteChat("websocket:chat-a");
    });

    expect(api.deleteSession).toHaveBeenCalledWith("tok", "websocket:chat-a", undefined);
    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-b"]);
  });

  it("keeps a session when delete is blocked by bound automations", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Alpha",
      },
    ]);
    vi.mocked(api.deleteSession).mockResolvedValue({
      deleted: false,
      blocked_by_automations: true,
      automations: [],
    });

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(1));

    let deleteResult: Awaited<ReturnType<typeof result.current.deleteChat>> | undefined;
    await act(async () => {
      deleteResult = await result.current.deleteChat("websocket:chat-a");
    });

    expect(deleteResult?.blocked_by_automations).toBe(true);
    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-a"]);
  });

  it("refreshes sessions when the websocket reports a session update", async () => {
    vi.mocked(api.listSessions)
      .mockResolvedValueOnce([
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "",
      },
      ])
      .mockResolvedValueOnce([
        {
          key: "websocket:chat-a",
          channel: "websocket",
          chatId: "chat-a",
          createdAt: "2026-04-16T10:00:00Z",
          updatedAt: "2026-04-16T10:01:00Z",
          title: "生成的小标题",
          preview: "用户第一句话",
        },
      ]);
    const client = fakeClient();

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.sessions[0]?.title).toBeUndefined());

    act(() => {
      client.emitSessionUpdate("chat-a");
    });

    await waitFor(() => expect(result.current.sessions[0]?.title).toBe("生成的小标题"));
    expect(api.listSessions).toHaveBeenCalledTimes(2);
  });

  it("keeps a newly created chat visible until the server session list catches up", async () => {
    vi.mocked(api.listSessions)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          key: "websocket:chat-new",
          channel: "websocket",
          chatId: "chat-new",
          createdAt: "2026-05-20T10:00:00Z",
          updatedAt: "2026-05-20T10:01:00Z",
          title: "Generated title",
          preview: "First message",
        },
      ]);
    const client = fakeClient();
    client.newChat.mockResolvedValue("chat-new");

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.sessions).toEqual([]);

    await act(async () => {
      await result.current.createChat();
    });

    expect(client.newChat).toHaveBeenCalledWith(60_000, undefined);
    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-new"]);

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-new"]);
    expect(result.current.sessions[0]?.preview).toBe("");

    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-new"]);
    expect(result.current.sessions[0]?.preview).toBe("First message");
    expect(result.current.sessions[0]?.title).toBe("Generated title");
  });

  it("stores optimistic workspace scope when creating a chat", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([]);
    const client = fakeClient();
    client.newChat.mockResolvedValue("chat-workspace");
    const workspaceScope = {
      project_path: "/tmp/project",
      project_name: "project",
      access_mode: "restricted" as const,
      restrict_to_workspace: true,
    };

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.createChat(workspaceScope);
    });

    expect(client.newChat).toHaveBeenCalledWith(60_000, workspaceScope);
    expect(result.current.sessions[0]?.workspaceScope).toEqual(workspaceScope);
  });

  it("passes through WebUI transcript user media as images and media", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        {
          id: "u1",
          role: "user",
          content: "what's this?",
          createdAt: 1,
          images: [
            { url: "/api/media/sig-1/payload-1", name: "snap.png" },
            { url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
          ],
          media: [
            { kind: "image", url: "/api/media/sig-1/payload-1", name: "snap.png" },
            { kind: "image", url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
          ],
        },
        { id: "a1", role: "assistant", content: "it's a cat", createdAt: 2 },
        { id: "u2", role: "user", content: "follow-up without images", createdAt: 3 },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-media"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    const [first, second, third] = result.current.messages;
    expect(first.role).toBe("user");
    expect(first.images).toEqual([
      { url: "/api/media/sig-1/payload-1", name: "snap.png" },
      { url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
    ]);
    expect(first.media).toEqual([
      { kind: "image", url: "/api/media/sig-1/payload-1", name: "snap.png" },
      { kind: "image", url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
    ]);
    expect(second.role).toBe("assistant");
    expect(second.images).toBeUndefined();
    expect(third.role).toBe("user");
    expect(third.images).toBeUndefined();
  });

  it("passes through assistant video media from transcript replay", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        {
          id: "a1",
          role: "assistant",
          content: "clip ready",
          createdAt: 1,
          media: [{ kind: "video", url: "/api/media/sig-v/payload-v", name: "clip.mp4" }],
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-video"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages[0]!.role).toBe("assistant");
    expect(result.current.messages[0]!.images).toBeUndefined();
    expect(result.current.messages[0]!.media).toEqual([
      { kind: "video", url: "/api/media/sig-v/payload-v", name: "clip.mp4" },
    ]);
  });

  it("passes through assistant reasoning from transcript replay", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        {
          id: "a1",
          role: "assistant",
          content: "final answer",
          createdAt: 1,
          reasoning: "hidden but persisted reasoning",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-reasoning"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0]!.role).toBe("assistant");
    expect(result.current.messages[0]!.content).toBe("final answer");
    expect(result.current.messages[0]!.reasoning).toBe("hidden but persisted reasoning");
  });

  it("accepts transcript rows produced by the server replay reducer", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        { id: "u1", role: "user", content: "research this", createdAt: 1 },
        {
          id: "t1",
          role: "tool",
          kind: "trace",
          content: "web_fetch({})",
          traces: ["web_search({\"query\":\"agents\"})", "web_fetch({\"url\":\"https://example.com\"})"],
          createdAt: 2,
        },
        { id: "a1", role: "assistant", content: "summary", createdAt: 3 },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-tools"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "tool", "assistant"]);
    const trace = result.current.messages[1]!;
    expect(trace.kind).toBe("trace");
    expect(trace.traces).toEqual([
      "web_search({\"query\":\"agents\"})",
      "web_fetch({\"url\":\"https://example.com\"})",
    ]);
    expect(result.current.messages[2]!.content).toBe("summary");
  });

  it("flags transcript ending with a trace row as pending", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        {
          id: "t1",
          role: "tool",
          kind: "trace",
          content: "Using 2 tools",
          traces: ["Using 2 tools"],
          createdAt: 1,
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-pending"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPendingToolCalls).toBe(true);
  });

  it("uses the server pending flag for completed tails that still end with trace rows", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      has_pending_tool_calls: false,
      messages: [
        {
          id: "a1",
          role: "assistant",
          content: "Cron test",
          turnId: "cron:run",
          createdAt: 1,
        },
        {
          id: "t1",
          role: "tool",
          kind: "trace",
          content: "message({})",
          traces: ["message({})"],
          turnId: "cron:run",
          createdAt: 2,
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-cron-done"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages.at(-1)?.kind).toBe("trace");
    expect(result.current.hasPendingToolCalls).toBe(false);
  });

  it("does not flag transcript as pending when last row is not a trace", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        { id: "a1", role: "assistant", content: "All done", createdAt: 1 },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-done"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPendingToolCalls).toBe(false);
  });

  it("treats missing transcript (404) as empty history", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue(null);

    const { result } = renderHook(() => useSessionHistory("websocket:new-chat"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages).toEqual([]);
    expect(result.current.hasPendingToolCalls).toBe(false);
  });

  it("aborts the stale history request when switching sessions", async () => {
    let firstSignal: AbortSignal | undefined;
    vi.mocked(api.fetchWebuiThread).mockImplementation(
      async (_token, key, optionsOrBase) => {
        if (key === "websocket:first") {
          firstSignal = typeof optionsOrBase === "object" ? optionsOrBase.signal : undefined;
          await new Promise<never>((_resolve, reject) => {
            firstSignal?.addEventListener(
              "abort",
              () => reject(new DOMException("aborted", "AbortError")),
              { once: true },
            );
          });
        }
        return null;
      },
    );

    const { result, rerender } = renderHook(
      ({ sessionKey }) => useSessionHistory(sessionKey),
      {
        initialProps: { sessionKey: "websocket:first" },
        wrapper: wrap(fakeClient()),
      },
    );

    await waitFor(() => expect(firstSignal).toBeDefined());
    rerender({ sessionKey: "websocket:second" });

    expect(firstSignal?.aborted).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it("loads older transcript pages before the current history", async () => {
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "u2", role: "user", content: "new question", createdAt: 2 },
          { id: "a2", role: "assistant", content: "new answer", createdAt: 3 },
        ],
        page: {
          before_cursor: "cursor-2",
          has_more_before: true,
          loaded_message_count: 2,
          user_message_offset: 1,
        },
      })
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "u1", role: "user", content: "old question", createdAt: 0 },
          { id: "a1", role: "assistant", content: "old answer", createdAt: 1 },
        ],
        page: {
          before_cursor: null,
          has_more_before: false,
          loaded_message_count: 2,
          user_message_offset: 0,
        },
      });

    const { result } = renderHook(() => useSessionHistory("websocket:paged"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.fetchWebuiThread).toHaveBeenCalledWith(
      "tok",
      "websocket:paged",
      expect.objectContaining({
        limit: 160,
        direction: "latest",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result.current.hasMoreBefore).toBe(true);
    expect(result.current.userMessageOffset).toBe(1);

    await act(async () => {
      await result.current.loadOlder();
    });

    expect(api.fetchWebuiThread).toHaveBeenLastCalledWith("tok", "websocket:paged", {
      limit: 120,
      before: "cursor-2",
    });
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "old question",
      "old answer",
      "new question",
      "new answer",
    ]);
    expect(result.current.hasMoreBefore).toBe(false);
    expect(result.current.userMessageOffset).toBe(0);
  });

  it("keeps the session in the list when delete fails", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([
      {
        key: "websocket:chat-a",
        channel: "websocket",
        chatId: "chat-a",
        createdAt: "2026-04-16T10:00:00Z",
        updatedAt: "2026-04-16T10:00:00Z",
        preview: "Alpha",
      },
    ]);
    vi.mocked(api.deleteSession).mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(1));

    await expect(
      act(async () => {
        await result.current.deleteChat("websocket:chat-a");
      }),
    ).rejects.toThrow("boom");

    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-a"]);
  });
});
