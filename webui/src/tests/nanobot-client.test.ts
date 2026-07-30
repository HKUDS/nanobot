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

  it("routes message acceptance acknowledgements to the matching chat handler", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onChat("chat-ack", handler);
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-ack", "hello", undefined, { turnId: "turn-ack" });

    lastSocket().fakeMessage({
      event: "message_accepted",
      chat_id: "chat-ack",
      turn_id: "turn-ack",
    });

    expect(handler).toHaveBeenCalledWith({
      event: "message_accepted",
      chat_id: "chat-ack",
      turn_id: "turn-ack",
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
    expect(handler).toHaveBeenLastCalledWith("chat-strip", null);
  });

  it("rejects a completed snapshot when a newer run is not represented", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    const requestGeneration = client.getRunGeneration("chat-race");

    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-race",
      status: "running",
      started_at: 12_345,
      turn_id: "turn-new",
    });

    expect(
      client.reconcileCanonicalCompletion("chat-race", requestGeneration, ["turn-old"]),
    ).toBe(false);
    expect(client.getRunStartedAt("chat-race")).toBe(12_345);
  });

  it("rejects a user-only snapshot for a submitted turn that has not completed", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-submitted", "question", undefined, { turnId: "turn-submitted" });
    const requestGeneration = client.getRunGeneration("chat-submitted");

    expect(
      client.reconcileCanonicalCompletion("chat-submitted", requestGeneration, []),
    ).toBe(false);
  });

  it("does not register injected guidance as an independently unsettled run", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-guidance",
      status: "running",
      started_at: 12_345,
      turn_id: "turn-active",
    });
    const requestGeneration = client.getRunGeneration("chat-guidance");

    client.sendMessage("chat-guidance", "focus on sources", undefined, {
      turnId: "turn-guidance",
      startsNewRun: false,
    });

    expect(client.getRunGeneration("chat-guidance")).toBe(requestGeneration);
    expect(
      client.reconcileCanonicalCompletion(
        "chat-guidance",
        requestGeneration,
        ["turn-active"],
      ),
    ).toBe(true);
  });

  it("accepts an explicitly completed turn with no assistant row", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-empty-answer", "question", undefined, {
      turnId: "turn-empty-answer",
    });
    const requestGeneration = client.getRunGeneration("chat-empty-answer");

    expect(
      client.reconcileCanonicalCompletion(
        "chat-empty-answer",
        requestGeneration,
        ["turn-empty-answer"],
      ),
    ).toBe(true);
  });

  it.each([
    "message_rejected",
    "attachment_rejected",
    "workspace_scope_rejected",
  ])("settles a specifically rejected outbound turn (%s)", (detail) => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-rejected", "question", undefined, {
      turnId: "turn-rejected",
    });
    const requestGeneration = client.getRunGeneration("chat-rejected");

    expect(
      client.reconcileCanonicalCompletion("chat-rejected", requestGeneration, []),
    ).toBe(false);

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-rejected",
      turn_id: "turn-rejected",
      detail,
      reason: "policy",
    });

    expect(
      client.reconcileCanonicalCompletion("chat-rejected", requestGeneration, []),
    ).toBe(true);
  });

  it("does not let an older rejection settle or stop a newer run", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-rejection-race", "first", undefined, {
      turnId: "turn-old",
    });
    client.sendMessage("chat-rejection-race", "second", undefined, {
      turnId: "turn-new",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-rejection-race",
      status: "running",
      started_at: 2_000,
      turn_id: "turn-new",
    });
    const requestGeneration = client.getRunGeneration("chat-rejection-race");

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-rejection-race",
      turn_id: "turn-old",
      detail: "message_rejected",
      reason: "text_too_large",
    });

    expect(client.getRunStartedAt("chat-rejection-race")).toBe(2_000);
    expect(
      client.reconcileCanonicalCompletion("chat-rejection-race", requestGeneration, []),
    ).toBe(false);
  });

  it("restores the previous turn clock when the newer running turn is rejected", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-reject-newer-clock", "first", undefined, {
      turnId: "turn-clock-first",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-reject-newer-clock",
      status: "running",
      started_at: 1_000,
      turn_id: "turn-clock-first",
    });
    client.sendMessage("chat-reject-newer-clock", "second", undefined, {
      turnId: "turn-clock-second",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-reject-newer-clock",
      status: "running",
      started_at: 2_000,
      turn_id: "turn-clock-second",
    });

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-reject-newer-clock",
      turn_id: "turn-clock-second",
      detail: "message_rejected",
    });

    expect(client.getRunStartedAt("chat-reject-newer-clock")).toBe(1_000);
    expect(client.hasUnsettledRun("chat-reject-newer-clock")).toBe(true);
  });

  it("rolls back lifecycle sends that close 1009 before server acceptance", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-too-big", "oversized", undefined, {
      turnId: "turn-too-big",
    });
    const requestGeneration = client.getRunGeneration("chat-too-big");

    lastSocket().fakeCloseWithCode(1009);

    expect(errors).toEqual([{
      kind: "message_too_big",
      chatId: "chat-too-big",
      turnId: "turn-too-big",
    }]);
    expect(
      client.reconcileCanonicalCompletion("chat-too-big", requestGeneration, []),
    ).toBe(true);
  });

  it("preserves an accepted older run when a newer send closes 1009", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-too-big-race", "first", undefined, {
      turnId: "turn-accepted",
    });
    lastSocket().fakeMessage({
      event: "message_accepted",
      chat_id: "chat-too-big-race",
      turn_id: "turn-accepted",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-too-big-race",
      status: "running",
      started_at: 1_000,
      turn_id: "turn-accepted",
    });
    client.sendMessage("chat-too-big-race", "oversized", undefined, {
      turnId: "turn-rejected",
    });
    const requestGeneration = client.getRunGeneration("chat-too-big-race");

    lastSocket().fakeCloseWithCode(1009);

    expect(errors).toEqual([{
      kind: "message_too_big",
      chatId: "chat-too-big-race",
      turnId: "turn-rejected",
    }]);
    expect(client.getRunStartedAt("chat-too-big-race")).toBe(1_000);
    expect(
      client.reconcileCanonicalCompletion(
        "chat-too-big-race",
        requestGeneration,
        [],
      ),
    ).toBe(false);
  });

  it("does not roll back a lifecycle send after its acceptance ACK", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-accepted", "question", undefined, {
      turnId: "turn-accepted",
    });
    const requestGeneration = client.getRunGeneration("chat-accepted");
    lastSocket().fakeMessage({
      event: "message_accepted",
      chat_id: "chat-accepted",
      turn_id: "turn-accepted",
    });

    lastSocket().fakeCloseWithCode(1009);

    expect(
      client.reconcileCanonicalCompletion("chat-accepted", requestGeneration, []),
    ).toBe(false);
  });

  it("preflights exact websocket frame bytes and rejects only the oversized turn", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      maxFrameBytes: 180,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    const sentBefore = lastSocket().sent.length;

    client.sendMessage("chat-preflight-size", "x".repeat(500), undefined, {
      turnId: "turn-preflight-size",
    });

    expect(lastSocket().sent).toHaveLength(sentBefore);
    expect(client.hasUnsettledRun("chat-preflight-size")).toBe(false);
    expect(errors).toEqual([{
      kind: "message_too_big",
      chatId: "chat-preflight-size",
      turnId: "turn-preflight-size",
    }]);
  });

  it("does not attribute a fallback 1009 close across multiple unacknowledged chats", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-size-a", "first", undefined, { turnId: "turn-size-a" });
    client.sendMessage("chat-size-b", "second", undefined, { turnId: "turn-size-b" });

    lastSocket().fakeCloseWithCode(1009);

    expect(errors).toEqual([{ kind: "message_too_big" }]);
    expect(client.hasUnsettledRun("chat-size-a")).toBe(true);
    expect(client.hasUnsettledRun("chat-size-b")).toBe(true);
  });

  it("does not attribute 1009 to an unacknowledged message when another frame followed it", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-before-audio", "question", undefined, {
      turnId: "turn-before-audio",
    });
    const transcription = client.transcribeAudio("data:audio/webm;base64,AAAA");

    lastSocket().fakeCloseWithCode(1009);

    await expect(transcription).rejects.toThrow("socket closed");
    expect(errors).toEqual([{ kind: "message_too_big" }]);
    expect(client.hasUnsettledRun("chat-before-audio")).toBe(true);
  });

  it("settles an unknown send absent from an idle canonical snapshot after disconnect", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-never-arrived", "question", undefined, {
      turnId: "turn-never-arrived",
    });
    const requestGeneration = client.getRunGeneration("chat-never-arrived");

    lastSocket().close();

    const snapshot = {
      observedTurnIds: [],
      hasPendingToolCalls: false,
      activeTurnId: null,
    };
    expect(
      client.canReconcileCanonicalCompletion(
        "chat-never-arrived",
        requestGeneration,
        [],
        snapshot,
      ),
    ).toBe(true);
    expect(
      client.reconcileCanonicalCompletion(
        "chat-never-arrived",
        requestGeneration,
        [],
        snapshot,
      ),
    ).toBe(true);
    expect(client.hasUnsettledRun("chat-never-arrived")).toBe(false);
  });

  it("keeps an ACK-lost observed turn active, then settles it from an idle snapshot", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-ack-lost", "question", undefined, {
      turnId: "turn-ack-lost",
    });
    const requestGeneration = client.getRunGeneration("chat-ack-lost");
    lastSocket().close();

    expect(
      client.canReconcileCanonicalCompletion(
        "chat-ack-lost",
        requestGeneration,
        [],
        {
          observedTurnIds: ["turn-ack-lost"],
          hasPendingToolCalls: true,
          activeTurnId: "turn-ack-lost",
        },
      ),
    ).toBe(false);
    expect(
      client.reconcileCanonicalCompletion(
        "chat-ack-lost",
        requestGeneration,
        [],
        {
          observedTurnIds: ["turn-ack-lost"],
          hasPendingToolCalls: false,
          activeTurnId: null,
        },
      ),
    ).toBe(true);
    expect(client.hasUnsettledRun("chat-ack-lost")).toBe(false);
  });

  it("settles an accepted turn that never reached running from canonical idle", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-accepted-idle", "question", undefined, {
      turnId: "turn-accepted-idle",
    });
    const requestGeneration = client.getRunGeneration("chat-accepted-idle");
    lastSocket().fakeMessage({
      event: "message_accepted",
      chat_id: "chat-accepted-idle",
      turn_id: "turn-accepted-idle",
    });

    expect(
      client.reconcileCanonicalCompletion(
        "chat-accepted-idle",
        requestGeneration,
        [],
        {
          observedTurnIds: ["turn-accepted-idle"],
          hasPendingToolCalls: false,
          activeTurnId: null,
        },
      ),
    ).toBe(true);
    expect(client.hasUnsettledRun("chat-accepted-idle")).toBe(false);
  });

  it("does not let a pre-send idle response erase a newly accepted turn", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    const requestGeneration = client.getRunGeneration("chat-stale-idle");
    client.sendMessage("chat-stale-idle", "question", undefined, {
      turnId: "turn-after-request",
    });
    lastSocket().fakeMessage({
      event: "message_accepted",
      chat_id: "chat-stale-idle",
      turn_id: "turn-after-request",
    });

    expect(
      client.reconcileCanonicalCompletion(
        "chat-stale-idle",
        requestGeneration,
        [],
        {
          observedTurnIds: [],
          hasPendingToolCalls: false,
          activeTurnId: null,
        },
      ),
    ).toBe(false);
    expect(client.hasUnsettledRun("chat-stale-idle")).toBe(true);
  });

  it("correlates a legacy rejection only to one currently sent turn", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-legacy-reject", "question", undefined, {
      turnId: "turn-legacy-reject",
    });

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-legacy-reject",
      detail: "message_rejected",
      reason: "text_too_large",
    });

    expect(client.hasUnsettledRun("chat-legacy-reject")).toBe(false);
    expect(errors).toEqual([expect.objectContaining({
      kind: "turn_rejected",
      chatId: "chat-legacy-reject",
      turnId: "turn-legacy-reject",
    })]);
  });

  it("correlates legacy lifecycle completion when exactly one turn is unsettled", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onChat("chat-legacy-idle", handler);
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-legacy-idle", "question", undefined, {
      turnId: "turn-legacy-idle",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-legacy-idle",
      status: "running",
      started_at: 4321,
    });

    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-legacy-idle",
      status: "idle",
    });

    expect(client.hasUnsettledRun("chat-legacy-idle")).toBe(false);
    expect(client.getRunStartedAt("chat-legacy-idle")).toBeNull();
    expect(handler).toHaveBeenLastCalledWith(expect.objectContaining({
      event: "goal_status",
      status: "idle",
      turn_id: "turn-legacy-idle",
    }));
  });

  it("does not apply an uncorrelated legacy idle to multiple unsettled turns", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const handler = vi.fn();
    client.onChat("chat-legacy-ambiguous", handler);
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-legacy-ambiguous", "first", undefined, {
      turnId: "turn-legacy-first",
    });
    client.sendMessage("chat-legacy-ambiguous", "second", undefined, {
      turnId: "turn-legacy-second",
    });
    handler.mockClear();

    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-legacy-ambiguous",
      status: "idle",
    });

    expect(client.hasUnsettledRun("chat-legacy-ambiguous")).toBe(true);
    expect(handler).not.toHaveBeenCalled();
  });

  it("does not correlate a legacy scope error to an already accepted turn", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const errors: Array<{ kind: string; chatId?: string; turnId?: string }> = [];
    client.onError((error) => errors.push(error));
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-legacy-scope", "question", undefined, {
      turnId: "turn-already-accepted",
    });
    lastSocket().fakeMessage({
      event: "message_accepted",
      chat_id: "chat-legacy-scope",
      turn_id: "turn-already-accepted",
    });

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-legacy-scope",
      detail: "workspace_scope_rejected",
      reason: "chat_running",
    });

    expect(client.hasUnsettledRun("chat-legacy-scope")).toBe(true);
    expect(errors).toEqual([{
      kind: "workspace_scope_rejected",
      reason: "chat_running",
      chatId: "chat-legacy-scope",
      turnId: undefined,
    }]);
  });

  it("does not correlate a scope-control rejection to a preceding unacknowledged message", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-scope-control", "question", undefined, {
      turnId: "turn-before-scope-control",
    });
    client.setWorkspaceScope("chat-scope-control", {
      project_path: "/tmp/project",
      project_name: "project",
      access_mode: "restricted",
    });

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-scope-control",
      detail: "workspace_scope_rejected",
      reason: "chat_running",
    });

    expect(client.hasUnsettledRun("chat-scope-control")).toBe(true);
  });

  it("does not correlate a new-chat scope rejection to an unrelated sent turn", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-unrelated-scope", "question", undefined, {
      turnId: "turn-unrelated-scope",
    });
    const pendingChat = client.newChat(5_000, {
      project_path: "/missing",
      project_name: "missing",
      access_mode: "restricted",
    });

    lastSocket().fakeMessage({
      event: "error",
      detail: "workspace_scope_rejected",
      reason: "project_path must be an existing directory",
    });

    await expect(pendingChat).rejects.toThrow("workspace_scope_rejected");
    expect(client.hasUnsettledRun("chat-unrelated-scope")).toBe(true);
  });

  it("rejects a correlated system command instead of leaving it pending", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    const pending = client.sendSystemCommand("chat-system-reject", "/model invalid");
    const sent = JSON.parse(lastSocket().sent.at(-1) ?? "{}") as { turn_id?: string };
    expect(sent.turn_id).toMatch(/^webui-system:/);

    lastSocket().fakeMessage({
      event: "error",
      chat_id: "chat-system-reject",
      turn_id: sent.turn_id,
      detail: "message_rejected",
      reason: "invalid_command",
    });

    await expect(pending).rejects.toThrow("message_rejected:invalid_command");
  });

  it("ignores a delayed idle event from an older turn after a new run starts", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const chatHandler = vi.fn();
    const runHandler = vi.fn();
    client.onChat("chat-delayed-idle", chatHandler);
    client.onRunStatus(runHandler);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-delayed-idle",
      status: "running",
      started_at: 1_000,
      turn_id: "turn-old",
    });
    client.sendMessage("chat-delayed-idle", "next question", undefined, {
      turnId: "turn-new",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-delayed-idle",
      status: "running",
      started_at: 2_000,
      turn_id: "turn-new",
    });
    chatHandler.mockClear();
    runHandler.mockClear();

    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-delayed-idle",
      status: "idle",
      turn_id: "turn-old",
    });

    expect(client.getRunStartedAt("chat-delayed-idle")).toBe(2_000);
    expect(runHandler).not.toHaveBeenCalled();
    expect(chatHandler).not.toHaveBeenCalled();
  });

  it("accepts a completed snapshot that represents a delayed running frame", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();
    const requestGeneration = client.getRunGeneration("chat-delayed-run");

    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-delayed-run",
      status: "running",
      started_at: 12_345,
      turn_id: "turn-complete",
    });

    expect(
      client.reconcileCanonicalCompletion(
        "chat-delayed-run",
        requestGeneration,
        ["turn-complete"],
      ),
    ).toBe(true);
    expect(client.getRunStartedAt("chat-delayed-run")).toBeNull();
  });

  it("preflights canonical completion without fencing or settling the turn", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const chatHandler = vi.fn();
    client.onChat("chat-preflight", chatHandler);
    client.connect();
    lastSocket().fakeOpen();
    client.sendMessage("chat-preflight", "question", undefined, {
      turnId: "turn-preflight",
    });
    const requestGeneration = client.getRunGeneration("chat-preflight");

    expect(
      client.canReconcileCanonicalCompletion(
        "chat-preflight",
        requestGeneration,
        ["turn-preflight"],
      ),
    ).toBe(true);
    expect(
      client.canReconcileCanonicalCompletion("chat-preflight", requestGeneration, []),
    ).toBe(false);

    lastSocket().fakeMessage({
      event: "delta",
      chat_id: "chat-preflight",
      turn_id: "turn-preflight",
      text: "still live",
    });
    expect(chatHandler).toHaveBeenCalledWith(
      expect.objectContaining({ event: "delta", text: "still live" }),
    );
  });

  it("clears the run cache and fences delayed frames after canonical completion", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const chatHandler = vi.fn();
    const runHandler = vi.fn();
    client.onChat("chat-canonical", chatHandler);
    client.onRunStatus(runHandler);
    client.connect();
    lastSocket().fakeOpen();
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-canonical",
      status: "running",
      started_at: 12_345,
      turn_id: "turn-canonical",
    });
    const requestGeneration = client.getRunGeneration("chat-canonical");

    expect(
      client.reconcileCanonicalCompletion(
        "chat-canonical",
        requestGeneration,
        ["turn-canonical"],
      ),
    ).toBe(true);
    expect(client.getRunStartedAt("chat-canonical")).toBeNull();
    expect(runHandler).toHaveBeenLastCalledWith("chat-canonical", null);
    const deliveredBeforeLateFrames = chatHandler.mock.calls.length;

    lastSocket().fakeMessage({
      event: "delta",
      chat_id: "chat-canonical",
      text: " delayed",
      turn_id: "turn-canonical",
    });
    lastSocket().fakeMessage({
      event: "turn_end",
      chat_id: "chat-canonical",
      turn_id: "turn-canonical",
    });
    lastSocket().fakeMessage({
      event: "goal_status",
      chat_id: "chat-canonical",
      status: "idle",
      turn_id: "turn-canonical",
    });

    expect(chatHandler).toHaveBeenCalledTimes(deliveredBeforeLateFrames);
    expect(client.getRunStartedAt("chat-canonical")).toBeNull();
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
    expect(handler).toHaveBeenCalledWith("chat-status", null);
    expect(lateHandler).toHaveBeenCalledWith("chat-status", null);
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

  it("dispatches turn model updates to the active chat", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const chatHandler = vi.fn();
    client.onChat("chat-a", chatHandler);
    client.connect();
    lastSocket().fakeOpen();

    lastSocket().fakeMessage({
      event: "turn_model_updated",
      chat_id: "chat-a",
      model_name: "deepseek/deepseek-chat",
    });

    expect(chatHandler).toHaveBeenCalledWith({
      event: "turn_model_updated",
      chat_id: "chat-a",
      model_name: "deepseek/deepseek-chat",
    });
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

  it("handles the silent system-command lifecycle without hiding concurrent events", async () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    const chatHandler = vi.fn();
    client.onChat("chat-x", chatHandler);
    client.connect();
    lastSocket().fakeOpen();

    const pending = client.sendSystemCommand("chat-x", "  /model fast  ", 1_000);
    const frame = JSON.parse(lastSocket().sent.at(-1) as string);
    expect(frame).toMatchObject({
      type: "message",
      chat_id: "chat-x",
      content: "/model fast",
      webui: true,
    });
    expect(frame.turn_id).toMatch(/^webui-system:/);

    lastSocket().fakeMessage({
      event: "message",
      chat_id: "chat-x",
      text: "normal reply",
      turn_id: "normal-turn",
    });
    lastSocket().fakeMessage({
      event: "message",
      chat_id: "chat-x",
      text: "Switched model preset to fast.",
      turn_id: frame.turn_id,
    });

    await expect(pending).resolves.toBeUndefined();
    expect(chatHandler).toHaveBeenCalledTimes(1);
    expect(chatHandler).toHaveBeenCalledWith(expect.objectContaining({
      text: "normal reply",
      turn_id: "normal-turn",
    }));
    const interrupted = client.sendSystemCommand("chat-x", "/model fast", 1_000);
    lastSocket().close();
    await expect(interrupted).rejects.toThrow("socket closed");
  });

  it("sends selected assistant text as separate quoted context", () => {
    const client = new NanobotClient({
      url: "ws://test",
      reconnect: false,
      socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    });
    client.connect();
    lastSocket().fakeOpen();

    client.sendMessage("chat-x", "What does this mean?", undefined, {
      quotedContext: "  selected answer excerpt  ",
    });

    expect(JSON.parse(lastSocket().sent.at(-1) as string)).toEqual({
      type: "message",
      chat_id: "chat-x",
      content: "What does this mean?",
      quoted_context: "selected answer excerpt",
      webui: true,
    });
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
