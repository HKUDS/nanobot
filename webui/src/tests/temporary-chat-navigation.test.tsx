import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import { FilePreviewStore } from "@/hooks/useFilePreviewState";
import type { InboundEvent, Outbound } from "@/lib/types";
import { fetchBootstrap } from "@/lib/bootstrap";
import { canonicalThreadPayload } from "./thread-test-payload";

let groupedTopics = false;
let withFiles = false;
const previewFile = (path: string) => ({
  path: `/workspace/${path}`, display_path: path, project_path: "/workspace",
  language: "text", content: `Preview of ${path}`, size: 20, truncated: false,
});

vi.mock("@/lib/bootstrap", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/bootstrap")>(),
  fetchBootstrap: vi.fn(async () => ({ token: "test", api_token: "test", ws_path: "/" })),
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
    } else if (frame.type === "webui_request" && frame.action === "temporary_chat.file_preview") {
      queueMicrotask(() => this.receive({
        event: "webui_response", request_id: frame.request_id, ok: true,
        result: frame.payload.metadata
          ? { path: `/workspace/${String(frame.payload.path)}`, relative_path: frame.payload.path }
          : frame.payload.probe ? { available: true } : previewFile(String(frame.payload.path)),
      }));
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
    vi.mocked(fetchBootstrap).mockReset().mockResolvedValue({ token: "test", api_token: "test", ws_path: "/" });
    groupedTopics = false;
    withFiles = false;
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
      if (path.includes("/file-preview?")) {
        const query = new URL(path, "http://test").searchParams;
        if (query.has("metadata")) return Response.json({ path: `/workspace/${query.get("path")}`, relative_path: query.get("path") });
        return Response.json(query.has("probe") ? { available: true } : previewFile(query.get("path")!));
      }
      if (withFiles && path.includes("/webui-thread")) {
        return Response.json(canonicalThreadPayload({
          schemaVersion: 3,
          messages: [{
            id: "file-reply", role: "assistant", createdAt: 1,
            content: "Files: [notes.txt](notes.txt) and [second.txt](second.txt). [Website](https://example.com/demo)",
          }],
        }));
      }
      return new Response(null, { status: 404 });
    }));
  });

  afterEach(() => {
    cleanup();
    if (vi.isFakeTimers()) vi.clearAllTimers();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it.each(["settings", "apps", "automations", "skills", "channels"])(
    "opens %s directly without mounting chat or retaining a chat query",
    async (view) => {
      window.history.replaceState(null, "", `/#/${view}?chat=websocket%3Aregular`);
      render(<App />);
      await screen.findByRole("button", { name: "Back to chat" });
      act(() => TestSocket.current.open());
      await waitFor(() => expect(window.location.hash).toBe(`#/${view}`));
      expect(window.history.state.nanobotReturnChat.key).toBe("websocket:regular");
      expect(screen.queryByTestId("thread-message-region")).not.toBeInTheDocument();
      const requests = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
      expect(requests.filter((url) => url.includes("/webui-thread") || url === "/api/commands")).toEqual([]);
    },
  );

  it("restores the return destination after refreshing a clean settings URL", async () => {
    const first = render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    await selectTopic("Regular topic");
    fireEvent.click(screen.getByRole("button", { name: "Settings", exact: true }));
    await screen.findByRole("button", { name: "Back to chat" });
    expect(window.location.hash).toBe("#/settings");
    first.unmount();
    vi.mocked(fetch).mockClear();
    render(<App />);
    await screen.findByRole("button", { name: "Back to chat" });
    act(() => TestSocket.current.open());
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/webui-thread"))).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    await waitFor(() => expect(window.location.hash).toBe("#/chat/websocket%3Aregular"));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("/webui-thread"))).toBe(true));
  });

  it("returns from settings to the same temporary chat and keeps its live messages", async () => {
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const chatId = await startTemporaryChat("Temporary navigation check");
    fireEvent.click(screen.getByRole("button", { name: "Settings", exact: true }));
    await screen.findByRole("button", { name: "Back to chat" });
    expect(window.location.hash).toBe("#/settings");
    act(() => TestSocket.current.receive({ event: "message", chat_id: chatId, text: "Reply while in settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    await waitFor(() => expect(window.location.hash).toBe(`#/temporary/${chatId}`));
    await screen.findByText("Reply while in settings");
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes(chatId))).toEqual([]);
  });

  it("keeps the preview resource stable across bootstrap token refresh", async () => {
    withFiles = true;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(fetchBootstrap)
      .mockResolvedValueOnce({ token: "old", api_token: "old", ws_path: "/", expires_in: 30 })
      .mockResolvedValue({ token: "renewed", api_token: "renewed", ws_path: "/", expires_in: 300 });
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    await selectTopic("Regular topic");
    fireEvent.click(await screen.findByRole("button", { name: "notes.txt" }));
    await screen.findByText("Preview of notes.txt");
    const panel = screen.getByTestId("file-preview-panel");
    const fullPreviewRequests = () => vi.mocked(fetch).mock.calls.filter(([url]) =>
      String(url).includes("/file-preview?path=") && !String(url).includes("probe=") && !String(url).includes("metadata="));
    expect(fullPreviewRequests()).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(fetchBootstrap).toHaveBeenCalledTimes(2);
    // Lazy syntax highlighting can replace text spans independently of token refresh.
    expect(screen.getByTestId("file-preview-panel")).toBe(panel);
    expect(screen.getByText("Preview of notes.txt")).toBeInTheDocument();
    expect(fullPreviewRequests()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "second.txt" }));
    await screen.findByText("Preview of second.txt");
    expect(new Headers(fullPreviewRequests().at(-1)?.[1]?.headers).get("Authorization")).toBe("Bearer renewed");
  });

  it.each([false, true])("restores file previews after pane navigation (temporary=%s)", async (temporary) => {
    withFiles = true;
    groupedTopics = true;
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("max-width: 767px"), media: query,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }));
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    if (temporary) {
      const chatId = await startTemporaryChat("Show example files");
      act(() => TestSocket.current.receive({
        event: "message", chat_id: chatId,
        text: "Files: [notes.txt](notes.txt) and [second.txt](second.txt)",
      }));
    } else {
      await selectTopic("Regular topic");
    }
    fireEvent.contextMenu(await screen.findByRole("button", { name: "notes.txt" }));
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "Copy absolute path" })).not.toHaveAttribute("data-disabled"));
    if (temporary) {
      expect(TestSocket.current.sent).toContainEqual(expect.objectContaining({
        type: "webui_request", action: "temporary_chat.file_preview",
        payload: expect.objectContaining({ path: "notes.txt", metadata: true }),
      }));
    } else {
      expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("path=notes.txt&metadata=1"))).toBe(true);
    }
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "notes.txt" }));
    await screen.findByText("Preview of notes.txt");
    fireEvent.click(screen.getByRole("button", { name: "second.txt" }));
    await screen.findByText("Preview of second.txt");
    const pane = screen.getByTestId("preview-pane");
    expect(within(pane).getAllByText("second.txt")).toHaveLength(1);
    expect(within(pane).queryByRole("navigation", { name: "File path" })).not.toBeInTheDocument();
    expect(within(pane).queryByRole("button", { name: /File actions/ })).not.toBeInTheDocument();
    fireEvent.contextMenu(within(pane).getByRole("tab", { name: "second.txt" }));
    await waitFor(() => expect(screen.getByRole("menuitem", { name: "Copy absolute path" })).not.toHaveAttribute("data-disabled"));
    if (temporary) {
      expect(TestSocket.current.sent).toContainEqual(expect.objectContaining({
        type: "webui_request", action: "temporary_chat.file_preview",
        payload: expect.objectContaining({ path: "second.txt", metadata: true }),
      }));
    } else {
      expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("path=second.txt&metadata=1"))).toBe(true);
    }
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    expect(screen.getByTestId("preview-pane")).toBe(pane);
    const previewRequestCount = () => temporary
      ? TestSocket.current.sent.filter((frame) => frame.type === "webui_request" && frame.action === "temporary_chat.file_preview"
        && frame.payload?.path === "notes.txt" && !frame.payload?.metadata && !frame.payload?.probe).length
      : vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/file-preview?path=notes.txt")
        && !String(url).includes("metadata=") && !String(url).includes("probe=")).length;
    const beforeReturn = previewRequestCount();
    fireEvent.click(screen.getByRole("tab", { name: "notes.txt" }));
    expect(screen.getByText("Preview of notes.txt")).toBeInTheDocument();
    expect(previewRequestCount()).toBe(beforeReturn);
    await selectTopic("Second pane");
    expect(screen.queryByTestId("file-preview-panel")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "second.txt" }));
    await screen.findByText("Preview of second.txt");
    await selectTopic(temporary ? "Show example files" : "Regular topic");
    await screen.findByText("Preview of notes.txt");
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "notes.txt" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Preview of second.txt")).not.toBeInTheDocument();

    // Explicit close must stick even if switching interrupts the close animation.
    fireEvent.click(screen.getByRole("button", { name: "Close preview pane" }));
    await selectTopic("Second pane");
    await selectTopic(temporary ? "Show example files" : "Regular topic");
    expect(screen.queryByTestId("file-preview-panel")).not.toBeInTheDocument();

    if (temporary) {
      const requests = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
      expect(requests.some((url) => url.includes("00000000-"))).toBe(false);
    }
    for (const storage of [localStorage, sessionStorage]) {
      const values = Array.from({ length: storage.length }, (_, i) => storage.getItem(storage.key(i)!));
      expect(JSON.stringify(values)).not.toContain("/workspace/notes.txt");
      expect(JSON.stringify(values)).not.toContain("Preview of notes.txt");
    }
  });

  it("restores website targets per session, switches to files, and closes below menus", async () => {
    withFiles = true;
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    await startTemporaryChat("Synthetic separate session");
    await selectTopic("Regular topic");
    const website = await screen.findByRole("link", { name: "Website" });
    const storedWebsiteValues = () => [localStorage, sessionStorage].map((storage) =>
      Array.from({ length: storage.length }, (_, i) => storage.getItem(storage.key(i)!))
        .filter((value) => value?.includes("https://example.com/demo")));
    const beforePreview = storedWebsiteValues();
    fireEvent.contextMenu(website);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Preview website" }));
    await screen.findByTestId("web-preview-panel");
    await selectTopic("Synthetic separate session");
    await waitFor(() => expect(screen.queryByTestId("web-preview-panel")).not.toBeInTheDocument());
    await selectTopic("Regular topic");
    await screen.findByTestId("web-preview-panel");
    fireEvent.contextMenu(screen.getByRole("link", { name: "Website" }));
    await screen.findByRole("menu");
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.getByTestId("web-preview-panel")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("web-preview-panel")).not.toBeInTheDocument());
    // The same pane is reachable with taps only, without intercepting a native
    // touch context menu or adding a button next to every rendered link.
    fireEvent.click(screen.getByRole("button", { name: "Message actions" }));
    fireEvent.click(await screen.findByRole("button", { name: "View links" }));
    fireEvent.click(await screen.findByRole("button", { name: "Preview website" }));
    await screen.findByTestId("web-preview-panel");
    expect(screen.queryByRole("dialog", { name: "Message actions" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "notes.txt" }));
    await waitFor(() => expect(screen.queryByTestId("web-preview-panel")).not.toBeInTheDocument());
    await screen.findByText("Preview of notes.txt");
    fireEvent.contextMenu(screen.getByRole("link", { name: "Website" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Preview website" }));
    expect(screen.queryByTestId("file-preview-panel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close preview pane" }));
    await waitFor(() => expect(screen.queryByTestId("web-preview-panel")).not.toBeInTheDocument());
    // The transcript may cache its link; preview targets must not add persisted state.
    expect(storedWebsiteValues()).toEqual(beforePreview);
  });

  it("keeps the sidebar mounted across tabs, deduplicates repeated opens, and handles Escape below dialogs", async () => {
    withFiles = true;
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    await selectTopic("Regular topic");
    fireEvent.click(await screen.findByRole("button", { name: "notes.txt" }));
    await screen.findByText("Preview of notes.txt");
    fireEvent.click(screen.getByRole("button", { name: "second.txt" }));
    await screen.findByText("Preview of second.txt");
    const pane = screen.getByTestId("preview-pane");
    fireEvent.click(screen.getByRole("button", { name: "second.txt" }));
    expect(screen.getByTestId("preview-pane")).toBe(pane);
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "second.txt" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: "Close second.txt" }));
    await screen.findByText("Preview of notes.txt");
    expect(screen.getByTestId("preview-pane")).toBe(pane);
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "notes.txt" }));
    await screen.findByText("Preview of notes.txt");
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.append(dialog);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByTestId("file-preview-panel")).toBeInTheDocument();
    dialog.remove();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByTestId("file-preview-panel")).not.toBeInTheDocument());
  });

  it("forgets preview paths on temporary close and disconnect", async () => {
    const update = vi.spyOn(FilePreviewStore.prototype, "open");
    render(<App />);
    await screen.findByRole("button", { name: "Temporary chat" });
    act(() => TestSocket.current.open());
    const chatId = await startTemporaryChat("Show example files");
    act(() => TestSocket.current.receive({
      event: "message", chat_id: chatId, text: "[notes.txt](notes.txt)",
    }));
    fireEvent.click(await screen.findByRole("button", { name: "notes.txt" }));
    await screen.findByText("Preview of notes.txt");
    const store = update.mock.contexts.find((value) => value.get(`websocket:${chatId}`).tabs.length)!;
    expect(store.get(`websocket:${chatId}`).activeId).toBe("file:notes.txt");
    await selectTopic("Close temporary chat: Show example files");
    expect(store.get(`websocket:${chatId}`).tabs).toEqual([]);
    act(() => store.open("websocket:regular", "file", "notes.txt"));
    vi.useFakeTimers();
    act(() => TestSocket.current.close());
    expect(store.get("websocket:regular").tabs).toEqual([]);
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
