import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useReconnectRuns } from "@/hooks/useReconnectRuns";
import { NanobotClient } from "@/lib/nanobot-client";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { WebuiThreadPersistedPayload } from "@/lib/types";
import { webuiThreadCache } from "@/lib/webui-thread-cache";

class TestSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send() {}
  close() { this.readyState = 3; this.onclose?.(); }
  open() { this.readyState = 1; this.onopen?.(); }
  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }
}

function completedThread(chatId = "inactive", turnId = "turn-old"): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 1,
    projection: "events",
    has_pending_tool_calls: false,
    events: [
      { event: "user_message", chat_id: chatId, turn_id: turnId, text: "Take your time", starts_turn: true },
      { event: "message", chat_id: chatId, turn_id: turnId, text: "The complete answer" },
      { event: "turn_end", chat_id: chatId, turn_id: turnId },
    ],
  };
}

function response(body: WebuiThreadPersistedPayload): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

function setup() {
  const sockets: TestSocket[] = [];
  const client = new NanobotClient({
    url: "ws://test", reconnect: true, maxBackoffMs: 10,
    socketFactory: () => {
      const socket = new TestSocket();
      sockets.push(socket);
      return socket as unknown as WebSocket;
    },
  });
  client.connect();
  sockets[0].open();
  const hook = renderHook(() => useReconnectRuns(client, () => "renewed-token"));
  const running = (chatId = "inactive", turnId = "turn-old", startedAt = 123) => sockets.at(-1)!.receive({
    event: "goal_status", chat_id: chatId, turn_id: turnId,
    status: "running", started_at: startedAt,
  });
  const reopen = async () => {
    act(() => sockets.at(-1)!.close());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    await act(async () => { sockets.at(-1)!.open(); });
  };
  const close = () => { hook.unmount(); client.close(); };
  return { client, sockets, running, reopen, close, hook };
}

beforeEach(() => {
  vi.useFakeTimers();
  webuiThreadCache.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  webuiThreadCache.clear();
});

describe("durable run recovery", () => {
  it("settles an inactive completed chat and retains its answer before clearing the run", async () => {
    // The oldest protocol-1 host need not supply active_turn_id or completed_turn_ids.
    const body = completedThread();
    const fetchMock = vi.fn().mockResolvedValue(response(body));
    vi.stubGlobal("fetch", fetchMock);
    const { client, sockets, running, reopen, close } = setup();
    running();
    sockets[0].receive({ event: "delta", chat_id: "inactive", turn_id: "turn-old", text: "The" });
    const cachedAtCompletion: WebuiThreadPersistedPayload[] = [];
    client.onRunStatus((chatId, startedAt) => {
      if (startedAt === null) cachedAtCompletion.push(webuiThreadCache.get(`websocket:${chatId}`)!);
    });

    await reopen();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Ainactive/webui-thread?limit=40&direction=latest",
      expect.objectContaining({ headers: { Authorization: "Bearer renewed-token" } }),
    );
    expect(client.getRunStartedAt("inactive")).toBeNull();
    expect(client.hasUnsettledRun("inactive")).toBe(false);
    expect(cachedAtCompletion).toEqual([body]);
    expect(projectThreadEvents(cachedAtCompletion[0].events).at(-1)?.content).toBe("The complete answer");
    const delayed = vi.fn();
    client.onChat("inactive", delayed);
    expect(delayed).not.toHaveBeenCalled();
    close();
  });

  it("checks every unsettled chat while keeping a still-running chat active", async () => {
    const body = completedThread("running", "turn-running");
    body.events = body.events.slice(0, 1);
    body.has_pending_tool_calls = true;
    body.active_turn_id = "turn-running";
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve(response(
      url.includes("websocket%3Arunning") ? body : completedThread(),
    )));
    vi.stubGlobal("fetch", fetchMock);
    const { client, running, reopen, close } = setup();
    running();
    running("running", "turn-running", 456);
    const runStatus = vi.fn();
    client.onRunStatus(runStatus);
    await reopen();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(client.getRunStartedAt("inactive")).toBeNull();
    expect(client.getRunStartedAt("running")).toBe(456);
    expect(client.getRunTurnId("running")).toBe("turn-running");
    expect(client.hasUnsettledRun("running")).toBe(true);
    expect(runStatus).toHaveBeenCalledTimes(3);
    close();
  });

  it.each(["failed read", "missing activity state"])("leaves %s unresolved", async (failure) => {
    const body = completedThread();
    delete body.has_pending_tool_calls;
    body.events = body.events.slice(0, 2);
    const fetchMock = failure === "failed read"
      ? vi.fn().mockRejectedValue(new Error("offline"))
      : vi.fn().mockResolvedValue(response(body));
    vi.stubGlobal("fetch", fetchMock);
    const { client, running, reopen, close } = setup();
    running();
    await reopen();
    expect(client.getRunStartedAt("inactive")).toBe(123);
    expect(client.hasUnsettledRun("inactive")).toBe(true);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    close();
  });

  it("does not let an in-flight old snapshot settle a newer turn", async () => {
    let resolveRead!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRead = resolve;
    })));
    const { client, running, reopen, close } = setup();
    running();
    await reopen();
    running("inactive", "turn-new", 456);
    await act(async () => { resolveRead(response(completedThread())); });
    expect(client.getRunStartedAt("inactive")).toBe(456);
    expect(client.getRunTurnId("inactive")).toBe("turn-new");
    expect(client.hasUnsettledRun("inactive")).toBe(true);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    close();
  });

  it("keeps an ACK-lost local send unresolved when an idle snapshot does not contain it", async () => {
    const body = completedThread("inactive", "previous-turn");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const { client, reopen, close } = setup();
    client.sendMessage("inactive", "A newly submitted task", undefined, { turnId: "unacknowledged-turn" });
    await reopen();
    expect(client.getRunTurnId("inactive")).toBe("unacknowledged-turn");
    expect(client.hasUnsettledRun("inactive")).toBe(true);
    close();
  });

  it("accepts an explicit completed turn when an older host omits activity metadata", async () => {
    const body = completedThread();
    delete body.has_pending_tool_calls;
    body.completed_turn_ids = ["turn-old"];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const { client, running, reopen, close } = setup();
    running();
    await reopen();
    expect(client.getRunStartedAt("inactive")).toBeNull();
    expect(client.hasUnsettledRun("inactive")).toBe(false);
    expect(webuiThreadCache.get("websocket:inactive")).toEqual(body);
    close();
  });

  it("keeps an incomplete transcript active when its completion list excludes projected turn_end", async () => {
    const body = completedThread();
    body.completed_turn_ids = [];
    body.has_pending_tool_calls = true;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const { client, running, reopen, close } = setup();
    running();
    await reopen();
    expect(client.getRunStartedAt("inactive")).toBe(123);
    expect(client.hasUnsettledRun("inactive")).toBe(true);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    close();
  });

  it("ignores a previous connection's HTTP response after another transport drop", async () => {
    let resolveRead!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRead = resolve;
    })));
    const { client, sockets, running, reopen, close } = setup();
    running();
    await reopen();
    act(() => sockets.at(-1)!.close());
    await act(async () => { resolveRead(response(completedThread())); });
    expect(client.getRunStartedAt("inactive")).toBe(123);
    expect(client.hasUnsettledRun("inactive")).toBe(true);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    close();
  });

  it("ignores reads from a disposed host coordinator", async () => {
    let resolveRead!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRead = resolve;
    })));
    const { client, running, reopen, close, hook } = setup();
    running();
    await reopen();
    hook.unmount();
    await act(async () => { resolveRead(response(completedThread())); });
    expect(client.getRunStartedAt("inactive")).toBe(123);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    close();
  });
});
