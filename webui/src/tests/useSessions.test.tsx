import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionHistory, useSessions } from "@/hooks/useSessions";
import * as api from "@/lib/api";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    listSessions: vi.fn(),
    deleteSession: vi.fn(),
    fetchSessionMessages: vi.fn(),
  };
});

function fakeClient() {
  const sessionUpdateHandlers = new Set<(chatId: string) => void>();
  return {
    status: "open" as const,
    defaultChatId: null as string | null,
    onStatus: () => () => {},
    onError: () => () => {},
    onChat: () => () => {},
    onSessionUpdate: (handler: (chatId: string) => void) => {
      sessionUpdateHandlers.add(handler);
      return () => sessionUpdateHandlers.delete(handler);
    },
    emitSessionUpdate: (chatId: string) => {
      for (const handler of sessionUpdateHandlers) handler(chatId);
    },
    sendMessage: vi.fn(),
    newChat: vi.fn(),
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
    vi.mocked(api.fetchSessionMessages).mockReset();
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
    vi.mocked(api.deleteSession).mockResolvedValue(true);

    const { result } = renderHook(() => useSessions(), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(2));

    await act(async () => {
      await result.current.deleteChat("websocket:chat-a");
    });

    expect(api.deleteSession).toHaveBeenCalledWith("tok", "websocket:chat-a");
    expect(result.current.sessions.map((s) => s.key)).toEqual(["websocket:chat-b"]);
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

  it("hydrates media_urls from historical user turns into UIMessage.images", async () => {
    // Round-trip check for the signed-media replay: the backend emits
    // ``media_urls`` on a historical user row and the hook must surface them
    // as ``images`` so the bubble can render the preview. Assistant turns
    // carry no media_urls and should not sprout an ``images`` field.
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-media",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "user",
          content: "what's this?",
          timestamp: "2026-04-20T10:00:00Z",
          media_urls: [
            { url: "/api/media/sig-1/payload-1", name: "snap.png" },
            { url: "/api/media/sig-2/payload-2", name: "diag.jpg" },
          ],
        },
        {
          role: "assistant",
          content: "it's a cat",
          timestamp: "2026-04-20T10:00:01Z",
        },
        {
          role: "user",
          content: "follow-up without images",
          timestamp: "2026-04-20T10:01:00Z",
        },
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

  it("hydrates historical assistant video media_urls into media attachments", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-video",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "clip ready",
          timestamp: "2026-04-20T10:00:01Z",
          media_urls: [
            { url: "/api/media/sig-v/payload-v", name: "clip.mp4" },
          ],
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-video"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages[0].role).toBe("assistant");
    expect(result.current.messages[0].images).toBeUndefined();
    expect(result.current.messages[0].media).toEqual([
      { kind: "video", url: "/api/media/sig-v/payload-v", name: "clip.mp4" },
    ]);
  });

  it("hydrates persisted assistant reasoning into the replayed message", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-reasoning",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "final answer",
          timestamp: "2026-04-20T10:00:01Z",
          reasoning_content: "hidden but persisted reasoning",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-reasoning"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("assistant");
    expect(result.current.messages[0].content).toBe("final answer");
    expect(result.current.messages[0].reasoning).toBe("hidden but persisted reasoning");
    expect(result.current.messages[0].reasoningStreaming).toBe(false);
  });

  it("drops replayed assistant turns that only contain reasoning", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-empty-reasoning",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "",
          timestamp: "2026-04-20T10:00:01Z",
          reasoning_content: "orphan reasoning",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-empty-reasoning"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages).toHaveLength(0);
  });

  it("hydrates historical assistant tool calls into a replay trace row", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-tools",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "user",
          content: "research this",
          timestamp: "2026-04-20T10:00:00Z",
        },
        {
          role: "assistant",
          content: "",
          timestamp: "2026-04-20T10:00:01Z",
          tool_calls: [
            {
              id: "call-1",
              type: "function",
              function: { name: "web_search", arguments: "{\"query\":\"agents\"}" },
            },
            {
              id: "call-2",
              type: "function",
              function: { name: "web_fetch", arguments: "{\"url\":\"https://example.com\"}" },
            },
          ],
        },
        {
          role: "tool",
          content: "tool output that should not render directly",
          timestamp: "2026-04-20T10:00:02Z",
          tool_call_id: "call-1",
        },
        {
          role: "assistant",
          content: "summary",
          timestamp: "2026-04-20T10:00:03Z",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-tools"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "tool", "assistant"]);
    const trace = result.current.messages[1];
    expect(trace.kind).toBe("trace");
    expect(trace.traces).toEqual([
      "web_search({\"query\":\"agents\"})",
      "web_fetch({\"url\":\"https://example.com\"})",
    ]);
    expect(result.current.messages[2].content).toBe("summary");
  });

  it("flags history with trailing assistant tool calls as still pending", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-pending",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "Using 2 tools",
          timestamp: "2026-04-20T10:00:01Z",
          tool_calls: [{ id: "call-1" }],
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-pending"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPendingToolCalls).toBe(true);
  });

  it("keeps pending when tool result rows trail assistant tool calls", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-pending-tool-result",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "Using 1 tool",
          timestamp: "2026-04-20T10:00:01Z",
          tool_calls: [{ id: "call-1" }],
        },
        {
          role: "tool",
          content: "tool output",
          timestamp: "2026-04-20T10:00:02Z",
          tool_call_id: "call-1",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-pending-tool-result"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPendingToolCalls).toBe(true);
  });

  it("does not flag history as pending once the assistant turn has no tool calls", async () => {
    vi.mocked(api.fetchSessionMessages).mockResolvedValue({
      key: "websocket:chat-done",
      created_at: "2026-04-20T10:00:00Z",
      updated_at: "2026-04-20T10:05:00Z",
      messages: [
        {
          role: "assistant",
          content: "All done",
          timestamp: "2026-04-20T10:00:01Z",
        },
      ],
    });

    const { result } = renderHook(() => useSessionHistory("websocket:chat-done"), {
      wrapper: wrap(fakeClient()),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

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
