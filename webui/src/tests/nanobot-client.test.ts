import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NanobotClient } from "@/lib/nanobot-client";

/**
 * Minimal fake WebSocket implementing the subset NanobotClient touches.
 * Every instance is retrievable via ``FakeSocket.instances`` so tests can
 * drive open/close/message lifecycles deterministically.
 */
class FakeSocket {
  static instances: FakeSocket[] = [];
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  url: string;
  readyState = FakeSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((ev?: { code?: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.();
  }

  /** Simulate a server-initiated drop with a specific wire-level close code
   * (e.g. ``1009`` for Message Too Big). */
  fakeCloseWithCode(code: number) {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.({ code });
  }

  fakeOpen() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  fakeMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

function lastSocket(): FakeSocket {
  const s = FakeSocket.instances.at(-1);
  if (!s) throw new Error("no socket created yet");
  return s;
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  Reflect.deleteProperty(window, "nanobotHost");
  vi.useRealTimers();
});

describe("NanobotClient", () => {
  it("routes events to the matching chat handler", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onChat("chat-a", handler);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({ event: "message", chat_id: "chat-a", text: "hi" });
    lastSocket().fakeMessage({ event: "message", chat_id: "chat-b", text: "no" });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0]).toMatchObject({
      event: "message",
      chat_id: "chat-a",
      text: "hi",
    });
  });

  it("can swap the socket factory when the runtime URL changes", () => {
    const browserFactory = vi.fn(
      (url: string) => new FakeSocket(`browser:${url}`) as unknown as WebSocket,
    );
    const hostFactory = vi.fn(
      (url: string) => new FakeSocket(`host:${url}`) as unknown as WebSocket,
    );
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: browserFactory,
    });

    client.connect();
    expect(lastSocket().url).toBe("browser:ws://test");
    client.close();
    client.updateUrl("nanobot-host://engine/", hostFactory);
    client.connect();

    expect(hostFactory).toHaveBeenCalledWith("nanobot-host://engine/");
    expect(lastSocket().url).toBe("host:nanobot-host://engine/");
  });

  it("uses the host socket bridge for native host URLs", async () => {
    let socketEventHandler:
      | ((event: { id: string; type: "open" | "close" | "error"; message?: string }) => void)
      | null = null;
    const openSocket = vi.fn(async () => "host-socket-1");
    Object.defineProperty(window, "nanobotHost", {
      configurable: true,
      value: {
        openSocket,
        sendSocket: vi.fn(async () => undefined),
        closeSocket: vi.fn(async () => undefined),
        onSocketEvent: vi.fn((handler) => {
          socketEventHandler = handler;
          return vi.fn();
        }),
      },
    });
    const client = new NanobotClient({
      url: "nanobot-host://engine/",
      reconnect: false,
    });
    const status = vi.fn();
    client.onStatus(status);

    client.connect();
    await Promise.resolve();
    socketEventHandler?.({ id: "host-socket-1", type: "open" });

    expect(openSocket).toHaveBeenCalledWith("nanobot-host://engine/");
    expect(status).toHaveBeenLastCalledWith("open");
  });

  it("buffers chat events while no chat handler is registered and replays on subscribe", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    // Nobody listening yet — deltas must not be dropped (user switched away).
    lastSocket().fakeMessage({ event: "delta", chat_id: "chat-queue", text: "a" });
    lastSocket().fakeMessage({ event: "delta", chat_id: "chat-queue", text: "b" });
    const handler = vi.fn();
    client.onChat("chat-queue", handler);
    expect(handler).toHaveBeenCalledTimes(2);
    expect(handler.mock.calls[0][0]).toMatchObject({ event: "delta", text: "a" });
    expect(handler.mock.calls[1][0]).toMatchObject({ event: "delta", text: "b" });
    lastSocket().fakeMessage({ event: "delta", chat_id: "chat-queue", text: "c" });
    expect(handler).toHaveBeenCalledTimes(3);
  });

  it("records goal_status run strip without an onChat subscriber", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-strip",
      status: "running",
      started_at: 12_345,
    });
    expect(client.getRunStartedAt("chat-strip")).toBe(12_345);
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-strip",
      status: "idle",
    });
    expect(client.getRunStartedAt("chat-strip")).toBeNull();
  });

  it("clears stale run strip when reconnecting after a dropped socket", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: true,
      maxBackoffMs: 10,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onRunStatus(handler);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-strip",
      status: "running",
      started_at: 12_345,
    });

    lastSocket().close();

    expect(client.getRunStartedAt("chat-strip")).toBeNull();
    expect(handler).toHaveBeenLastCalledWith("chat-strip", null);
    await vi.advanceTimersByTimeAsync(20);
    expect(FakeSocket.instances.length).toBeGreaterThan(1);
  });

  it("clears run strip when a turn_end arrives without idle", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onRunStatus(handler);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-strip",
      status: "running",
      started_at: 12_345,
    });
    lastSocket().fakeMessage({
      event: "turn_end",
      chat_id: "chat-strip",
    });
    expect(client.getRunStartedAt("chat-strip")).toBeNull();
    expect(handler).toHaveBeenLastCalledWith("chat-strip", null, true);

    lastSocket().fakeMessage({
      event: "turn_end",
      chat_id: "chat-missed-running",
    });
    expect(handler).toHaveBeenLastCalledWith("chat-missed-running", null, true);
  });

  it("notifies run status subscribers and replays running chats", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onRunStatus(handler);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-status",
      status: "running",
      started_at: 12_345,
    });
    expect(handler).toHaveBeenCalledWith("chat-status", 12_345);

    const lateHandler = vi.fn();
    client.onRunStatus(lateHandler);
    expect(lateHandler).toHaveBeenCalledWith("chat-status", 12_345);

    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-status",
      status: "idle",
    });
    expect(handler).toHaveBeenCalledWith("chat-status", null, true);
    expect(lateHandler).toHaveBeenCalledWith("chat-status", null, true);
  });

  it("records goal_state per chat_id without an onChat subscriber", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_state",
      chat_id: "chat-goal-a",
      goal_state: { active: true, ui_summary: "Docs" },
    });
    lastSocket().fakeMessage({
      event: "goal_state",
      chat_id: "chat-goal-b",
      goal_state: { active: true, objective: "Ship API" },
    });
    expect(client.getGoalState("chat-goal-a")).toEqual({ active: true, ui_summary: "Docs" });
    expect(client.getGoalState("chat-goal-b")).toEqual({
      active: true,
      objective: "Ship API",
    });
    lastSocket().fakeMessage({
      event: "goal_state",
      chat_id: "chat-goal-a",
      goal_state: { active: false },
    });
    expect(client.getGoalState("chat-goal-a")).toEqual({ active: false });
  });

  it("records goal_state from turn_end payload when present", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "turn_end",
      chat_id: "chat-te",
      goal_state: { active: true, objective: "Long task" },
    });
    expect(client.getGoalState("chat-te")).toEqual({ active: true, objective: "Long task" });
  });

  it("buffers after unsubscribe until the chat is subscribed again", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const h1 = vi.fn();
    const unsub = client.onChat("chat-rejoin", h1);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({ event: "delta", chat_id: "chat-rejoin", text: "live" });
    expect(h1).toHaveBeenCalledTimes(1);
    unsub();
    lastSocket().fakeMessage({ event: "delta", chat_id: "chat-rejoin", text: "queued" });
    expect(h1).toHaveBeenCalledTimes(1);
    const h2 = vi.fn();
    client.onChat("chat-rejoin", h2);
    expect(h2).toHaveBeenCalledTimes(1);
    expect(h2.mock.calls[0][0]).toMatchObject({ event: "delta", text: "queued" });
  });

  it("dispatches runtime model updates globally", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onRuntimeModelUpdate(handler);
    client.connect();
    lastSocket().fakeOpen();

    lastSocket().fakeMessage({
      event: "runtime_model_updated",
      model_name: "openai/gpt-4.1",
      model_preset: "fast",
    });

    expect(handler).toHaveBeenCalledWith("openai/gpt-4.1", "fast");
  });

  it("dispatches session updates globally", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const globalHandler = vi.fn();
    const chatHandler = vi.fn();
    client.onSessionUpdate(globalHandler);
    client.onChat("chat-title", chatHandler);
    client.connect();
    lastSocket().fakeOpen();

    lastSocket().fakeMessage({
      event: "session_updated",
      chat_id: "chat-title",
      scope: "metadata",
      workspace_scope: {
        project_path: "/tmp/project",
        project_name: "project",
        access_mode: "restricted",
        restrict_to_workspace: true,
      },
    });

    expect(globalHandler).toHaveBeenCalledWith(
      "chat-title",
      "metadata",
      expect.objectContaining({ project_path: "/tmp/project" }),
    );
    expect(chatHandler).not.toHaveBeenCalled();
  });

  it("resolves newChat() via the server-assigned chat_id", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    const promise = client.newChat(1_000);
    expect(lastSocket().sent).toContain(JSON.stringify({ type: "new_chat" }));
    lastSocket().fakeMessage({ event: "attached", chat_id: "fresh-id" });
    await expect(promise).resolves.toBe("fresh-id");
  });

  it("serializes workspace scope for new chats and messages", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const workspaceScope = {
      project_path: "/tmp/project",
      project_name: "project",
      access_mode: "full" as const,
      restrict_to_workspace: false,
    };
    client.connect();
    lastSocket().fakeOpen();

    const promise = client.newChat(1_000, workspaceScope);
    expect(lastSocket().sent).toContain(
      JSON.stringify({ type: "new_chat", workspace_scope: workspaceScope }),
    );
    lastSocket().fakeMessage({ event: "attached", chat_id: "fresh-id" });
    await expect(promise).resolves.toBe("fresh-id");

    client.sendMessage("fresh-id", "hello", undefined, { workspaceScope });
    expect(lastSocket().sent).toContain(
      JSON.stringify({
        type: "message",
        chat_id: "fresh-id",
        content: "hello",
        workspace_scope: workspaceScope,
        webui: true,
      }),
    );
  });

  it("sends transcription requests and resolves transcription results outside chat dispatch", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onChat("chat-a", handler);
    client.connect();
    lastSocket().fakeOpen();

    const promise = client.transcribeAudio("data:audio/webm;base64,AAAA", {
      durationMs: 1234,
      timeoutMs: 1_000,
    });
    const frame = JSON.parse(lastSocket().sent.at(-1) as string);
    expect(frame).toMatchObject({
      type: "transcribe_audio",
      data_url: "data:audio/webm;base64,AAAA",
      duration_ms: 1234,
    });
    expect(typeof frame.request_id).toBe("string");

    lastSocket().fakeMessage({
      event: "transcription_result",
      request_id: frame.request_id,
      text: "hello from voice",
    });
    await expect(promise).resolves.toBe("hello from voice");
    expect(handler).not.toHaveBeenCalled();
  });

  it("rejects pending transcription requests on server errors and socket close", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();

    const errored = client.transcribeAudio("data:audio/webm;base64,AAAA", { timeoutMs: 1_000 });
    const errorFrame = JSON.parse(lastSocket().sent.at(-1) as string);
    lastSocket().fakeMessage({
      event: "transcription_error",
      request_id: errorFrame.request_id,
      detail: "not_configured",
    });
    await expect(errored).rejects.toThrow("not_configured");

    const dropped = client.transcribeAudio("data:audio/webm;base64,BBBB", { timeoutMs: 1_000 });
    lastSocket().close();
    await expect(dropped).rejects.toThrow("socket closed");
  });

  it("queues sends while connecting and flushes on open", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    client.sendMessage("chat-x", "hello");
    expect(lastSocket().sent).toEqual([]);
    lastSocket().fakeOpen();
    // Attach is sent first because sendMessage adds to knownChats, which
    // handleOpen re-attaches; then the queued message follows.
    expect(lastSocket().sent).toContain(
      JSON.stringify({ type: "message", chat_id: "chat-x", content: "hello", webui: true }),
    );
  });

  it("includes an explicit turn id on outbound WebUI messages", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-x", "hello", undefined, { turnId: "turn-1" });
    expect(JSON.parse(lastSocket().sent.at(-1) as string)).toEqual({
      type: "message",
      chat_id: "chat-x",
      content: "hello",
      turn_id: "turn-1",
      webui: true,
    });
  });

  it("includes image generation options in outbound messages", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();

    client.sendMessage(
      "chat-img",
      "draw a banner",
      undefined,
      { imageGeneration: { enabled: true, aspect_ratio: "16:9" } },
    );

    expect(lastSocket().sent).toContain(
      JSON.stringify({
        type: "message",
        chat_id: "chat-img",
        content: "draw a banner",
        image_generation: { enabled: true, aspect_ratio: "16:9" },
        webui: true,
      }),
    );
  });

  it("includes CLI app attachments in outbound messages", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();

    client.sendMessage(
      "chat-cli",
      "@drawio please make this diagram",
      undefined,
      {
        cliApps: [{
          name: "drawio",
          display_name: "Draw.io",
          category: "diagrams",
          entry_point: "cli-anything-drawio",
          logo_url: null,
          brand_color: "#F08705",
        }],
      },
    );

    expect(lastSocket().sent).toContain(
      JSON.stringify({
        type: "message",
        chat_id: "chat-cli",
        content: "@drawio please make this diagram",
        cli_apps: [{
          name: "drawio",
          display_name: "Draw.io",
          category: "diagrams",
          entry_point: "cli-anything-drawio",
          logo_url: null,
          brand_color: "#F08705",
        }],
        webui: true,
      }),
    );
  });

  it("includes MCP preset attachments in outbound messages", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();

    client.sendMessage(
      "chat-mcp",
      "@browserbase check this page",
      undefined,
      {
        mcpPresets: [{
          name: "browserbase",
          display_name: "Browserbase",
          category: "browser",
          transport: "streamableHttp",
          status: "configured",
          configured: true,
          logo_url: "https://example.invalid/browserbase.svg",
          brand_color: "#111827",
        }],
      },
    );

    expect(lastSocket().sent).toContain(
      JSON.stringify({
        type: "message",
        chat_id: "chat-mcp",
        content: "@browserbase check this page",
        mcp_presets: [{
          name: "browserbase",
          display_name: "Browserbase",
          category: "browser",
          transport: "streamableHttp",
          status: "configured",
          configured: true,
          logo_url: "https://example.invalid/browserbase.svg",
          brand_color: "#111827",
        }],
        webui: true,
      }),
    );
  });

  it("re-attaches known chats after a reconnect", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: true,
      maxBackoffMs: 10,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.onChat("chat-z", () => {});
    client.connect();
    lastSocket().fakeOpen();
    expect(lastSocket().sent).toContain(
      JSON.stringify({ type: "attach", chat_id: "chat-z" }),
    );
    // Drop the socket.
    lastSocket().close();
    // Advance the backoff timer.
    await vi.advanceTimersByTimeAsync(20);
    const reconnected = lastSocket();
    expect(reconnected).not.toBe(FakeSocket.instances[0]);
    reconnected.fakeOpen();
    expect(reconnected.sent).toContain(
      JSON.stringify({ type: "attach", chat_id: "chat-z" }),
    );
  });

  it("reports status transitions through onStatus", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const seen: string[] = [];
    client.onStatus((s) => seen.push(s));
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().close();
    expect(seen).toEqual(["idle", "connecting", "open", "closed"]);
  });

  it("does not schedule a reconnect when close() is called explicitly", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: true,
      maxBackoffMs: 10,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const seen: string[] = [];
    client.onStatus((s) => seen.push(s));
    client.connect();
    lastSocket().fakeOpen();
    client.close();
    // Advance past any possible backoff window to prove no reconnect was scheduled.
    await vi.advanceTimersByTimeAsync(200);
    expect(FakeSocket.instances).toHaveLength(1);
    // "reconnecting" must never appear after an intentional close.
    expect(seen).not.toContain("reconnecting");
    expect(seen.at(-1)).toBe("closed");
  });

  it("passes media through into the message envelope", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-x", "look", [
      { data_url: "data:image/png;base64,AAAA", name: "shot.png" },
    ]);
    const lastFrame = JSON.parse(lastSocket().sent.at(-1) as string);
    expect(lastFrame).toEqual({
      type: "message",
      chat_id: "chat-x",
      content: "look",
      media: [{ data_url: "data:image/png;base64,AAAA", name: "shot.png" }],
      webui: true,
    });
  });

  it("omits media from the envelope when no images are attached", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-x", "hello");
    const lastFrame = JSON.parse(lastSocket().sent.at(-1) as string);
    expect(lastFrame).not.toHaveProperty("media");
    expect(lastFrame).toEqual({
      type: "message",
      chat_id: "chat-x",
      content: "hello",
      webui: true,
    });
  });

  it("emits a message_too_big error when the socket closes with code 1009", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string }> = [];
    client.onError((e) => errors.push(e));
    client.connect();
    lastSocket().fakeOpen();
    // Server rejected an outbound frame as too large.
    lastSocket().fakeCloseWithCode(1009);
    expect(errors).toEqual([{ kind: "message_too_big" }]);
  });

  it("emits workspace scope rejection errors from server frames", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; reason?: string; chatId?: string }> = [];
    client.onError((e) => errors.push(e));
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-a",
      detail: "workspace_scope_rejected",
      reason: "chat_running",
    });
    expect(errors).toEqual([
      {
        kind: "workspace_scope_rejected",
        reason: "chat_running",
        chatId: "chat-a",
      },
    ]);
  });

  it("rejects pending new chats when workspace scope is rejected", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    const pending = client.newChat(5_000, {
      project_path: "/missing",
      project_name: "missing",
      access_mode: "restricted",
    });
    lastSocket().fakeMessage({
      event: "error",
      detail: "workspace_scope_rejected",
      reason: "project_path must be an existing directory",
    });
    await expect(pending).rejects.toThrow("workspace_scope_rejected");
  });

  it("isolates throwing error handlers so reconnect bookkeeping still runs", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: true,
      maxBackoffMs: 5,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    // First handler explodes; subsequent reconnect state must be untouched.
    client.onError(() => {
      throw new Error("subscriber blew up");
    });
    const seenStatuses: string[] = [];
    client.onStatus((s) => seenStatuses.push(s));
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeCloseWithCode(1009);
    // Despite the throwing handler, the client must still schedule a reconnect.
    expect(seenStatuses).toContain("reconnecting");
    await vi.advanceTimersByTimeAsync(20);
    expect(FakeSocket.instances.length).toBeGreaterThan(1);
  });

  it("does not emit a stream error on a vanilla socket close", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string }> = [];
    client.onError((e) => errors.push(e));
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().close();
    expect(errors).toEqual([]);
  });

  it("surfaces 'reconnecting' only on an unexpected drop", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: true,
      maxBackoffMs: 5,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const seen: string[] = [];
    client.onStatus((s) => seen.push(s));
    client.connect();
    lastSocket().fakeOpen();
    // Simulate the remote side hanging up (no client.close() call).
    lastSocket().close();
    await vi.advanceTimersByTimeAsync(50);
    expect(seen).toContain("reconnecting");
    expect(FakeSocket.instances.length).toBeGreaterThan(1);
  });
});
