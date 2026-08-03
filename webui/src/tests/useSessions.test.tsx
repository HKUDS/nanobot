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

function wrap(
  client: ReturnType<typeof fakeClient>,
  tokenSource: string | { current: string } = "tok",
) {
  return function Wrapper({ children }: { children: ReactNode }) {
    const token = typeof tokenSource === "string" ? tokenSource : tokenSource.current;
    return (
      <ClientProvider
        client={client as unknown as import("@/lib/nanobot-client").NanobotClient}
        token={token}
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
    })).toBe("New topic");

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

  it("coalesces a same-task burst of session updates into one refresh", async () => {
    vi.mocked(api.listSessions).mockResolvedValue([]);
    const client = fakeClient();

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.listSessions).toHaveBeenCalledTimes(1);

    await act(async () => {
      client.emitSessionUpdate("chat-a", "metadata");
      client.emitSessionUpdate("chat-a", "thread");
      client.emitSessionUpdate("chat-b", "metadata");
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.listSessions).toHaveBeenCalledTimes(2);
  });

  it("runs one trailing refresh when an update arrives during a session request", async () => {
    let resolveInFlight!: (rows: []) => void;
    vi.mocked(api.listSessions)
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveInFlight = resolve;
      }))
      .mockResolvedValueOnce([
        {
          key: "websocket:chat-a",
          channel: "websocket",
          chatId: "chat-a",
          createdAt: "2026-04-16T10:00:00Z",
          updatedAt: "2026-04-16T10:01:00Z",
          title: "Latest title",
          preview: "Latest preview",
        },
      ]);
    const client = fakeClient();

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(client),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      client.emitSessionUpdate("chat-a", "metadata");
      await Promise.resolve();
    });
    await waitFor(() => expect(api.listSessions).toHaveBeenCalledTimes(2));

    await act(async () => {
      client.emitSessionUpdate("chat-a", "thread");
      await Promise.resolve();
    });
    expect(api.listSessions).toHaveBeenCalledTimes(2);

    await act(async () => {
      resolveInFlight([]);
      await Promise.resolve();
    });

    await waitFor(() => expect(api.listSessions).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.sessions[0]?.title).toBe("Latest title");
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

  it("exposes turn ids backed by persisted completion events", async () => {
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      has_pending_tool_calls: false,
      completed_turn_ids: ["turn-empty", "", "turn-empty"],
      messages: [
        {
          id: "u1",
          role: "user",
          content: "stop",
          turnId: "turn-empty",
          createdAt: 1,
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-empty"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.completedTurnIds).toEqual(["turn-empty"]);
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

  it("does not reload history when only the auth token rotates", async () => {
    const tokenSource = { current: "tok-old" };
    vi.mocked(api.fetchWebuiThread).mockResolvedValue({
      schemaVersion: 3,
      messages: [
        { id: "a1", role: "assistant", content: "stable", createdAt: 1 },
      ],
    });

    const { result, rerender } = renderHook(
      () => useSessionHistory("websocket:token-rotation"),
      { wrapper: wrap(fakeClient(), tokenSource) },
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(api.fetchWebuiThread).toHaveBeenCalledTimes(1);
    expect(api.fetchWebuiThread).toHaveBeenLastCalledWith(
      "tok-old",
      "websocket:token-rotation",
      expect.any(Object),
    );

    tokenSource.current = "tok-new";
    rerender();
    await act(async () => Promise.resolve());
    expect(api.fetchWebuiThread).toHaveBeenCalledTimes(1);

    act(() => result.current.refresh());
    await waitFor(() => expect(api.fetchWebuiThread).toHaveBeenCalledTimes(2));
    expect(api.fetchWebuiThread).toHaveBeenLastCalledWith(
      "tok-new",
      "websocket:token-rotation",
      expect.any(Object),
    );
  });

  it("aborts a superseded latest-history request without surfacing an error", async () => {
    let firstSignal: AbortSignal | undefined;
    vi.mocked(api.fetchWebuiThread)
      .mockImplementationOnce((_token, _key, optionsOrBase) => new Promise((_resolve, reject) => {
        if (typeof optionsOrBase !== "string") firstSignal = optionsOrBase?.signal;
        firstSignal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      }))
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "a2", role: "assistant", content: "latest", createdAt: 2 },
        ],
      });

    const { result } = renderHook(
      () => useSessionHistory("websocket:superseded"),
      { wrapper: wrap(fakeClient()) },
    );

    await waitFor(() => expect(firstSignal).toBeDefined());
    act(() => result.current.refresh());

    await waitFor(() => expect(api.fetchWebuiThread).toHaveBeenCalledTimes(2));
    expect(firstSignal?.aborted).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.messages.map((message) => message.id)).toEqual(["a2"]);
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
        limit: 80,
        direction: "latest",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result.current.hasMoreBefore).toBe(true);
    expect(result.current.userMessageOffset).toBe(1);
    const latestVersion = result.current.version;
    const latestLineage = result.current.lineage;
    expect(result.current.continuity).toBe("initial");

    await act(async () => {
      await result.current.loadOlder();
    });

    expect(api.fetchWebuiThread).toHaveBeenLastCalledWith(
      "tok",
      "websocket:paged",
      expect.objectContaining({
        limit: 120,
        before: "cursor-2",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(result.current.messages.map((message) => message.content)).toEqual([
      "old question",
      "old answer",
      "new question",
      "new answer",
    ]);
    expect(result.current.hasMoreBefore).toBe(false);
    expect(result.current.userMessageOffset).toBe(0);
    expect(result.current.version).toBe(latestVersion);
    expect(result.current.lineage).toBe(latestLineage);
    expect(result.current.continuity).toBe("initial");
  });

  it("aborts an older-history request when the consumer unmounts", async () => {
    let olderSignal: AbortSignal | undefined;
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "u2", role: "user", content: "latest question", createdAt: 2 },
        ],
        page: {
          before_cursor: "cursor-2",
          has_more_before: true,
          loaded_message_count: 1,
          user_message_offset: 1,
        },
      })
      .mockImplementationOnce((_token, _key, optionsOrBase) => new Promise((_resolve, reject) => {
        if (typeof optionsOrBase !== "string") olderSignal = optionsOrBase?.signal;
        olderSignal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      }));

    const { result, unmount } = renderHook(
      () => useSessionHistory("websocket:unmount-older"),
      { wrapper: wrap(fakeClient()) },
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    let olderRequest!: Promise<void>;
    act(() => {
      olderRequest = result.current.loadOlder();
    });
    await waitFor(() => expect(olderSignal).toBeDefined());

    unmount();

    expect(olderSignal?.aborted).toBe(true);
    await expect(olderRequest).resolves.toBeUndefined();
  });

  it("preserves a loaded prefix when a canonical latest window overlaps its tail", async () => {
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        has_pending_tool_calls: true,
        messages: [
          { id: "u2", role: "user", content: "middle question", createdAt: 2 },
          { id: "a2", role: "assistant", content: "middle answer", createdAt: 3 },
        ],
        page: {
          before_cursor: "cursor-middle",
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
      })
      .mockResolvedValueOnce({
        schemaVersion: 3,
        has_pending_tool_calls: false,
        completed_turn_ids: ["turn-3"],
        messages: [
          { id: "a2-replayed", role: "assistant", content: "middle answer", createdAt: 3 },
          {
            id: "u3",
            role: "user",
            content: "latest question",
            turnId: "turn-3",
            createdAt: 4,
          },
          {
            id: "a3",
            role: "assistant",
            content: "latest answer",
            turnId: "turn-3",
            createdAt: 5,
          },
        ],
        page: {
          before_cursor: "cursor-shifted",
          has_more_before: true,
          loaded_message_count: 3,
          user_message_offset: 1,
        },
      });

    const { result } = renderHook(() => useSessionHistory("websocket:paged-refresh"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.loadOlder();
    });
    const loadedVersion = result.current.version;
    const loadedLineage = result.current.lineage;

    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.version).toBeGreaterThan(loadedVersion));

    expect(result.current.messages.map((message) => message.id)).toEqual([
      "u1",
      "a1",
      "u2",
      "a2-replayed",
      "u3",
      "a3",
    ]);
    expect(result.current.hasMoreBefore).toBe(false);
    expect(result.current.userMessageOffset).toBe(0);
    expect(result.current.hasPendingToolCalls).toBe(false);
    expect(result.current.completedTurnIds).toEqual(["turn-3"]);
    expect(result.current.continuity).toBe("overlap");
    expect(result.current.lineage).toBe(loadedLineage);
  });

  it("starts a new lineage when more than 160 new rows remove all latest-page overlap", async () => {
    const oldWindow = Array.from({ length: 160 }, (_, index) => ({
      id: `old-${index}`,
      role: index % 2 === 0 ? "user" as const : "assistant" as const,
      content: `old window row ${index}`,
      turnId: `old-turn-${Math.floor(index / 2)}`,
      createdAt: index,
    }));
    const newWindow = Array.from({ length: 160 }, (_, index) => ({
      id: `new-${index}`,
      role: index % 2 === 0 ? "user" as const : "assistant" as const,
      content: `new window row ${index}`,
      turnId: `new-turn-${Math.floor(index / 2)}`,
      createdAt: 1_000 + index,
    }));
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: oldWindow,
        page: {
          before_cursor: "old-window-cursor",
          has_more_before: true,
        },
      })
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: newWindow,
        page: {
          before_cursor: "new-window-cursor",
          has_more_before: true,
        },
      });

    const { result } = renderHook(() => useSessionHistory("websocket:window-reset"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    const initialLineage = result.current.lineage;
    expect(result.current.messages[0]?.id).toBe("old-0");

    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.messages[0]?.id).toBe("new-0"));

    expect(result.current.messages).toHaveLength(160);
    expect(result.current.messages.at(-1)?.id).toBe("new-159");
    expect(result.current.continuity).toBe("reset");
    expect(result.current.lineage).toBeGreaterThan(initialLineage);
    expect(result.current.hasMoreBefore).toBe(true);
  });

  it("uses the longest consecutive semantic overlap for legacy unstable replay metadata", async () => {
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "repeat-1-old", role: "user", content: "repeat", createdAt: 10 },
          { id: "answer-1-old", role: "assistant", content: "first answer", createdAt: 11 },
          { id: "repeat-2-old", role: "user", content: "repeat", createdAt: 12 },
          { id: "answer-2-old", role: "assistant", content: "second answer", createdAt: 13 },
        ],
        page: {
          before_cursor: "legacy-cursor",
          has_more_before: true,
        },
      })
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "old-prefix", role: "user", content: "old prefix", createdAt: 1 },
        ],
        page: {
          before_cursor: null,
          has_more_before: false,
        },
      })
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "repeat-2-new", role: "user", content: "repeat", createdAt: 9_012 },
          { id: "answer-2-new", role: "assistant", content: "second answer", createdAt: 9_013 },
          { id: "new-tail", role: "assistant", content: "new tail", createdAt: 9_014 },
        ],
        page: {
          before_cursor: "shifted-legacy-cursor",
          has_more_before: true,
        },
      });

    const { result } = renderHook(() => useSessionHistory("websocket:legacy-overlap"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.loadOlder();
    });
    const lineage = result.current.lineage;

    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.messages.at(-1)?.id).toBe("new-tail"));

    expect(result.current.messages.map((message) => message.id)).toEqual([
      "old-prefix",
      "repeat-1-old",
      "answer-1-old",
      "repeat-2-new",
      "answer-2-new",
      "new-tail",
    ]);
    expect(result.current.continuity).toBe("overlap");
    expect(result.current.lineage).toBe(lineage);
  });

  it("ignores an older-page response after a latest refresh resets its lineage", async () => {
    let resolveOlder:
      | ((value: Awaited<ReturnType<typeof api.fetchWebuiThread>>) => void)
      | null = null;
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "old-latest", role: "assistant", content: "old latest", createdAt: 10 },
        ],
        page: {
          before_cursor: "cursor-old-lineage",
          has_more_before: true,
        },
      })
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveOlder = resolve;
      }))
      .mockResolvedValueOnce({
        schemaVersion: 3,
        messages: [
          { id: "new-latest", role: "assistant", content: "new latest", createdAt: 20 },
        ],
        page: {
          before_cursor: "cursor-new-lineage",
          has_more_before: true,
        },
      });

    const { result } = renderHook(() => useSessionHistory("websocket:paged-race"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    const oldLineage = result.current.lineage;
    let olderRequest: Promise<void> | undefined;
    act(() => {
      olderRequest = result.current.loadOlder();
    });
    await waitFor(() => expect(api.fetchWebuiThread).toHaveBeenCalledTimes(2));

    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.messages[0]?.id).toBe("new-latest"));
    expect(result.current.continuity).toBe("reset");
    expect(result.current.lineage).toBeGreaterThan(oldLineage);

    await act(async () => {
      resolveOlder?.({
        schemaVersion: 3,
        messages: [
          { id: "stale-prefix", role: "user", content: "stale prefix", createdAt: 1 },
        ],
        page: {
          before_cursor: null,
          has_more_before: false,
        },
      });
      await olderRequest;
    });

    expect(result.current.messages.map((message) => message.id)).toEqual(["new-latest"]);
    expect(result.current.hasMoreBefore).toBe(true);
  });

  it("preserves authoritative active state while prepending older history", async () => {
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        has_pending_tool_calls: true,
        messages: [
          { id: "u2", role: "user", content: "current question", createdAt: 2 },
          { id: "a2", role: "assistant", content: "partial answer", createdAt: 3 },
        ],
        page: {
          before_cursor: "cursor-active",
          has_more_before: true,
          loaded_message_count: 2,
          user_message_offset: 1,
        },
      })
      .mockResolvedValueOnce({
        schemaVersion: 3,
        has_pending_tool_calls: false,
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

    const { result } = renderHook(() => useSessionHistory("websocket:paged-active"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.hasPendingToolCalls).toBe(true);
    const latestVersion = result.current.version;

    await act(async () => {
      await result.current.loadOlder();
    });

    expect(result.current.hasPendingToolCalls).toBe(true);
    expect(result.current.version).toBe(latestVersion);
  });

  it("preserves authoritative completed state while prepending trace history", async () => {
    vi.mocked(api.fetchWebuiThread)
      .mockResolvedValueOnce({
        schemaVersion: 3,
        has_pending_tool_calls: false,
        messages: [
          {
            id: "t2",
            role: "tool",
            kind: "trace",
            content: "completed trace",
            traces: ["completed trace"],
            createdAt: 2,
          },
        ],
        page: {
          before_cursor: "cursor-complete",
          has_more_before: true,
          loaded_message_count: 1,
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

    const { result } = renderHook(() => useSessionHistory("websocket:paged-complete"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.hasPendingToolCalls).toBe(false);

    await act(async () => {
      await result.current.loadOlder();
    });

    expect(result.current.hasPendingToolCalls).toBe(false);
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
