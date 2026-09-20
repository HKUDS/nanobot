import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import type { InboundEvent, Outbound } from "@/lib/types";

let groupedTopics = false;

vi.mock("@/lib/bootstrap", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/bootstrap")>(),
  fetchBootstrap: async () => ({ token: "test", api_token: "test", ws_path: "/" }),
  deriveWsUrl: () => "ws://test",
}));

// Only the network is fake: App, the workbench, stream hook and multiplexed client are real.
class TestSocket {
  static current: TestSocket;
  readyState = 0;
  sent: Outbound[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  private nextChat = 0;

  constructor() {
    TestSocket.current = this;
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  receive(event: InboundEvent) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event) }));
  }

  send(data: string) {
    const frame = JSON.parse(data) as Outbound;
    this.sent.push(frame);
    if (frame.type === "new_temporary_chat") {
      const chatId = `00000000-0000-4000-8000-${String(++this.nextChat).padStart(12, "0")}`;
      queueMicrotask(() => this.receive({ event: "attached", chat_id: chatId, temporary: true }));
    } else if (frame.type === "set_sidebar_state") {
      queueMicrotask(() => this.receive({ event: "sidebar_state_updated", state: frame.state }));
    }
  }
}

async function startTemporaryChat(text: string) {
  fireEvent.click(await screen.findByRole("button", { name: "Temporary chat" }));
  fireEvent.change(screen.getByLabelText("Message input"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  await waitFor(() => expect(window.location.hash).toMatch(/^#\/temporary\//));
  const chatId = window.location.hash.split("/").at(-1)!;
  await waitFor(() => expect(
    within(screen.getByTestId("thread-message-region")).getByText(text),
  ).toBeInTheDocument());
  await waitFor(() => expect(TestSocket.current.sent).toContainEqual(expect.objectContaining({
    type: "message", chat_id: chatId, content: text,
  })));
  const frame = TestSocket.current.sent.find((frame) => frame.type === "message" && frame.chat_id === chatId);
  if (frame?.type !== "message") throw new Error("Missing submitted turn");
  act(() => TestSocket.current.receive({
    event: "goal_status", chat_id: chatId, turn_id: frame.turn_id,
    status: "running", started_at: Date.now() / 1000,
  }));
  return chatId;
}

async function selectTopic(name: string) {
  const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
  fireEvent.click(within(sidebar).getByRole("button", { name }));
}

describe("temporary chat navigation", () => {
  beforeEach(() => {
    groupedTopics = false;
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState(null, "", "/");
    vi.stubGlobal("WebSocket", TestSocket);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/sessions") {
        return Response.json({ sessions: ["regular", ...(groupedTopics ? ["child"] : [])].map((id) => ({
          key: `websocket:${id}`,
          title: id === "regular" ? "Regular topic" : "Second pane",
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:00:00Z",
        })) });
      }
      if (path === "/api/webui/sidebar-state" && groupedTopics) {
        return Response.json({ workbench: { version: 1, tabs: {
          "tab:websocket:regular": {
            explicit: true, title: "Regular topic",
            paneKeys: ["websocket:regular", "websocket:child"], layout: "columns",
          },
        } } });
      }
      return new Response(null, { status: 404 });
    }));
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps messages when navigating to a regular workbench and back", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const chatId = await startTemporaryChat("Count from one to three");

    await selectTopic("Regular topic");
    await waitFor(() => expect(window.location.hash).toBe("#/chat/websocket%3Aregular"));
    await selectTopic("Count from one to three");
    await waitFor(() => expect(window.location.hash).toBe(`#/temporary/${chatId}`));

    expect(within(screen.getByTestId("thread-message-region")).getByText(
      "Count from one to three",
    )).toBeInTheDocument();
    expect(screen.queryByTestId("hero-greeting")).not.toBeInTheDocument();
  });

  it.each(["before leaving", "while away", "after returning"])(
    "preserves streamed output when the turn finishes %s",
    async (completion) => {
      render(<App />);
      await screen.findByRole("button", { name: "Temporary chat" });
      act(() => TestSocket.current.open());
      const chatId = await startTemporaryChat("Count from one to three");
      const socket = TestSocket.current;
      const turnId = socket.sent.find((frame) => frame.type === "message")?.turn_id;
      const emit = (event: InboundEvent) => act(() => socket.receive(event));
      const finish = () => {
        emit({ event: "delta", chat_id: chatId, turn_id: turnId, text: " two three" });
        emit({ event: "stream_end", chat_id: chatId, turn_id: turnId });
        emit({ event: "turn_end", chat_id: chatId, turn_id: turnId });
      };
      emit({ event: "delta", chat_id: chatId, turn_id: turnId, text: "one" });
      await screen.findByText("one");
      if (completion === "before leaving") finish();

      await selectTopic("Regular topic");
      if (completion === "while away") finish();
      await selectTopic("Count from one to three");
      if (completion === "after returning") {
        expect(screen.getByRole("button", { name: "Stop response" })).toBeInTheDocument();
        finish();
      }

      await waitFor(() => expect(within(screen.getByTestId("thread-message-region"))
        .getAllByText("one two three")).toHaveLength(1));
      expect(within(screen.getByTestId("thread-message-region"))
        .getAllByText("Count from one to three")).toHaveLength(1);
      expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
    },
  );

  it("keeps temporary messages when a compact workbench unmounts the root pane", async () => {
    groupedTopics = true;
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("max-width: 767px"), media: query,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }));
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    await startTemporaryChat("Count from one to three");
    await selectTopic("Second pane");
    expect(screen.queryByTestId("workbench-pane-websocket:regular")).not.toBeInTheDocument();
    await selectTopic("Count from one to three");
    expect(within(screen.getByTestId("thread-message-region"))
      .getByText("Count from one to three")).toBeInTheDocument();
  });

  it("retains deltas received just before switching away, before the next paint", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const chatId = await startTemporaryChat("Count from one to three");
    const turnId = TestSocket.current.sent.find((frame) => frame.type === "message")?.turn_id;
    act(() => {
      TestSocket.current.receive({ event: "delta", chat_id: chatId, turn_id: turnId, text: "one" });
      const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
      fireEvent.click(within(sidebar).getByRole("button", { name: "Regular topic" }));
    });
    await selectTopic("Count from one to three");
    await waitFor(() => expect(within(screen.getByTestId("thread-message-region"))
      .getAllByText("one")).toHaveLength(1));
  });

  it.each(["stream_end", "turn_end", "message"] as const)(
    "retains a received %s when navigation unmounts the pane before React commits",
    async (event) => {
      groupedTopics = true;
      vi.stubGlobal("matchMedia", (query: string) => ({
        matches: query.includes("max-width: 767px"), media: query,
        addEventListener: vi.fn(), removeEventListener: vi.fn(),
      }));
      render(<App />);
      await screen.findByRole("button", { name: "Temporary chat" });
      act(() => TestSocket.current.open());
      const chatId = await startTemporaryChat("Count from one to three");
      const turnId = TestSocket.current.sent.find((frame) => frame.type === "message")?.turn_id;
      act(() => {
        if (event !== "message") {
          TestSocket.current.receive({ event: "delta", chat_id: chatId, turn_id: turnId, text: "one two three" });
        }
        TestSocket.current.receive({ event, chat_id: chatId, turn_id: turnId, text: "one two three" });
        const sidebar = screen.getByRole("navigation", { name: "Sidebar navigation" });
        fireEvent.click(within(sidebar).getByRole("button", { name: "Second pane" }));
      });
      expect(screen.queryByTestId("workbench-pane-websocket:regular")).not.toBeInTheDocument();
      await selectTopic("Count from one to three");
      const region = screen.getByTestId("thread-message-region");
      expect(region.textContent).toContain("one two three");
      expect(within(region).getAllByText("one two three")).toHaveLength(1);
      expect(within(region).getAllByText("Count from one to three")).toHaveLength(1);
      if (event === "turn_end") {
        expect(screen.queryByRole("button", { name: "Stop response" })).not.toBeInTheDocument();
      }
    },
  );

  it("keeps multiple temporary chats isolated and releases the closed chat's cache", async () => {
    const deleteCache = vi.spyOn(ThreadMessageCache.prototype, "delete");
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const firstChatId = await startTemporaryChat("Count from one to three");
    const firstTurnId = TestSocket.current.sent.find((frame) => frame.type === "message")?.turn_id;
    await selectTopic("New topic");
    const secondChatId = await startTemporaryChat("List three colors");
    act(() => {
      TestSocket.current.receive({ event: "delta", chat_id: firstChatId, turn_id: firstTurnId, text: "one two three" });
      TestSocket.current.receive({ event: "turn_end", chat_id: firstChatId, turn_id: firstTurnId });
    });
    expect(screen.queryByText("one two three")).not.toBeInTheDocument();
    await selectTopic("Regular topic");
    await selectTopic("Count from one to three");
    await waitFor(() => expect(within(screen.getByTestId("thread-message-region"))
      .getAllByText("one two three")).toHaveLength(1));
    expect(within(screen.getByTestId("thread-message-region"))
      .queryByText("List three colors")).not.toBeInTheDocument();
    await selectTopic("List three colors");
    expect(within(screen.getByTestId("thread-message-region"))
      .getAllByText("List three colors")).toHaveLength(1);

    await selectTopic("Close temporary chat: Count from one to three");
    expect(deleteCache).toHaveBeenCalledWith(firstChatId);
    expect(TestSocket.current.sent).toContainEqual({ type: "discard_temporary_chat", chat_id: firstChatId });
    expect(window.location.hash).toBe(`#/temporary/${secondChatId}`);
    await selectTopic("Close temporary chat: List three colors");
    expect(deleteCache).toHaveBeenCalledWith(secondChatId);
    expect(await screen.findByTestId("hero-greeting")).toBeInTheDocument();
    for (const cache of deleteCache.mock.contexts) {
      if (!(cache instanceof ThreadMessageCache)) throw new Error("Expected thread message cache");
      expect(cache.get(firstChatId)).toBeUndefined();
      expect(cache.get(secondChatId)).toBeUndefined();
    }

    // No history reads, sidebar persistence or browser storage may contain these chats.
    const requests = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    for (const chatId of [firstChatId, secondChatId]) {
      expect(requests.some((url) => url.includes(chatId))).toBe(false);
      expect(JSON.stringify(TestSocket.current.sent.filter((frame) => frame.type === "set_sidebar_state")))
        .not.toContain(chatId);
    }
    for (const storage of [localStorage, sessionStorage]) {
      const values = Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index)!));
      expect(JSON.stringify(values)).not.toMatch(/Count from one to three|List three colors|one two three/);
    }
    deleteCache.mockRestore();
  });

  it("still ends temporary chats and clears their cache on disconnect", async () => {
    const deleteCache = vi.spyOn(ThreadMessageCache.prototype, "delete");
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const chatId = await startTemporaryChat("Count from one to three");
    await selectTopic("Regular topic");
    // Do not let the synthetic disconnected client reconnect after teardown.
    vi.useFakeTimers();
    await act(async () => TestSocket.current.close());
    expect(deleteCache).toHaveBeenCalledWith(chatId);
    for (const cache of deleteCache.mock.contexts) {
      if (!(cache instanceof ThreadMessageCache)) throw new Error("Expected thread message cache");
      expect(cache.get(chatId)).toBeUndefined();
    }
    expect(screen.queryByRole("button", { name: "Count from one to three" })).not.toBeInTheDocument();
    deleteCache.mockRestore();
  });

  it("does not truncate a temporary reply that keeps streaming while away", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const chatId = await startTemporaryChat("Count from one to three");
    const turnId = TestSocket.current.sent.find((frame) => frame.type === "message")?.turn_id;
    await selectTopic("Regular topic");
    const chunks = Array.from({ length: 2_010 }, (_, index) => `word${index} `);
    act(() => {
      for (const text of chunks) {
        TestSocket.current.receive({ event: "delta", chat_id: chatId, turn_id: turnId, text });
      }
      TestSocket.current.receive({ event: "turn_end", chat_id: chatId, turn_id: turnId });
    });
    await selectTopic("Count from one to three");
    await waitFor(() => expect(within(screen.getByTestId("thread-message-region"))
      .getAllByText(chunks.join("").trim())).toHaveLength(1));
  });
});
