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
    fetchWebuiThread: vi.fn(),
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
    getRunStartedAt: () => null,
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
    vi.mocked(api.fetchWebuiThread).mockReset();
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
