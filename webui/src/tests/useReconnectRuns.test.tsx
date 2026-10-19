import { act, renderHook } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useReconnectRuns } from "@/hooks/useReconnectRuns";
import { useNanobotStream } from "@/hooks/useNanobotStream";
import { useSessionHistory } from "@/hooks/useSessions";
import { NanobotClient } from "@/lib/nanobot-client";
import { projectThreadEvents } from "@/lib/thread-event-projection";
import type { WebuiThreadPersistedPayload } from "@/lib/types";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import { ClientProvider } from "@/providers/ClientProvider";

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
  it("bounds recovery reads while draining all chats and preserving a newer queued turn", async () => {
    const reads: Array<{ chatId: string; resolve: (value: Response) => void }> = [];
    let active = 0;
    let peak = 0;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      active += 1;
      peak = Math.max(peak, active);
      const key = decodeURIComponent(url.split("/sessions/")[1].split("/")[0]);
      return new Promise<Response>((resolve) => { reads.push({ chatId: key.slice("websocket:".length), resolve }); })
        .finally(() => { active -= 1; });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { client, running, reopen, close } = setup();
    for (let index = 0; index < 9; index += 1) running(`chat-${index}`);
    await reopen();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    running("chat-8", "turn-new", 456);
    let answered = 0;
    for (let round = 0; round < 9 && answered < 9; round += 1) {
      const batch = reads.slice(answered);
      await act(async () => {
        for (const read of batch) read.resolve(response(completedThread(read.chatId)));
      });
      answered += batch.length;
    }
    expect(fetchMock).toHaveBeenCalledTimes(9);
    expect(peak).toBe(4);
    expect(client.getUnsettledRunChatIds()).toEqual(["chat-8"]);
    expect(client.getRunStartedAt("chat-8")).toBe(456);
    expect(webuiThreadCache.get("websocket:chat-8")).toBeUndefined();
    close();
  });

  it("aborts outstanding recovery reads without starting queued chats after another drop", async () => {
    const reads: Array<{ signal: AbortSignal; resolve: (value: Response) => void }> = [];
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => (
      new Promise<Response>((resolve) => { reads.push({ signal: init.signal!, resolve }); })
    ));
    vi.stubGlobal("fetch", fetchMock);
    const { client, sockets, running, reopen, close } = setup();
    for (let index = 0; index < 8; index += 1) running(`chat-${index}`);
    await reopen();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    await act(async () => { sockets.at(-1)!.close(); });
    expect(reads.every((read) => read.signal.aborted)).toBe(true);
    await act(async () => {
      for (const read of reads) read.resolve(response(completedThread()));
    });
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(client.getUnsettledRunChatIds()).toHaveLength(8);
    close();
  });

  it("shares one simultaneous recovery HTTP read with the mounted history hook", async () => {
    const cached = completedThread();
    cached.events = cached.events.slice(0, 2);
    cached.events[1] = { event: "message", chat_id: "inactive", turn_id: "turn-old", text: "Partial" };
    cached.has_pending_tool_calls = true;
    cached.active_turn_id = "turn-old";
    cached.revision = "active-page";
    webuiThreadCache.set("websocket:inactive", cached);
    let resolveRecovery!: (value: Response) => void;
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(null, { status: 304 }))
      .mockImplementation(() => new Promise<Response>((resolve) => { resolveRecovery = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const { client, running, reopen, close } = setup();
    running();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="renewed-token">{children}</ClientProvider>
    );
    const mounted = renderHook(() => {
      const history = useSessionHistory("websocket:inactive");
      useEffect(() => {
        let refreshOnOpen = false;
        return client.onStatus((status) => {
          if (status !== "open") refreshOnOpen = true;
          else if (refreshOnOpen) {
            refreshOnOpen = false;
            history.refresh();
          }
        });
      }, [history.refresh]);
      return history;
    }, { wrapper });
    await act(async () => {});
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await reopen();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][1].headers["If-None-Match"]).toBe('"active-page"');
    await act(async () => { resolveRecovery(response(completedThread())); });
    expect(mounted.result.current.messages.at(-1)?.content).toBe("The complete answer");
    expect(client.getRunStartedAt("inactive")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    mounted.unmount();
    close();
  });

  it.each(["together", "separate"] as const)("starts fresh terminal history without adopting the old read when completion frames arrive %s", async (timing) => {
    const idle: WebuiThreadPersistedPayload = {
      schemaVersion: 1, projection: "events", events: [],
      completed_turn_ids: [], has_pending_tool_calls: false, active_turn_id: null,
    };
    const active = completedThread();
    active.events = active.events.slice(0, 1);
    active.completed_turn_ids = [];
    active.has_pending_tool_calls = true;
    active.active_turn_id = "turn-old";
    const reads: Array<{ signal: AbortSignal; resolve: (value: Response) => void }> = [];
    const fetchMock = vi.fn().mockResolvedValueOnce(response(idle))
      .mockImplementation((_url: string, init: RequestInit) => new Promise<Response>((resolve) => {
        reads.push({ signal: init.signal!, resolve });
      }));
    vi.stubGlobal("fetch", fetchMock);
    const { client, sockets, running, reopen, close } = setup();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="renewed-token">{children}</ClientProvider>
    );
    const mounted = renderHook(() => {
      const history = useSessionHistory("websocket:inactive");
      const stream = useNanobotStream(
        "inactive", history.messages, history.hasPendingToolCalls,
        undefined, undefined, history.completedTurnIds,
      );
      useEffect(() => client.onSessionUpdate((chatId, scope) => {
        if (chatId === "inactive" && scope !== "metadata") history.refresh();
      }), [history.refresh]);
      useEffect(() => {
        let refreshOnOpen = false;
        return client.onStatus((status) => {
          if (status !== "open") refreshOnOpen = true;
          else if (refreshOnOpen) {
            refreshOnOpen = false;
            history.refresh();
          }
        });
      }, [history.refresh]);
      return { history, stream };
    }, { wrapper });
    await act(async () => {});
    act(() => running());
    await reopen();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    act(() => {
      sockets.at(-1)!.receive({ event: "message", chat_id: "inactive", turn_id: "turn-old", text: "The complete answer" });
      sockets.at(-1)!.receive({ event: "turn_end", chat_id: "inactive", turn_id: "turn-old" });
      if (timing === "together") {
        sockets.at(-1)!.receive({ event: "session_updated", chat_id: "inactive", scope: "thread" });
      }
    });
    await act(async () => {});
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(reads[0].signal.aborted).toBe(true);
    await act(async () => { reads[0].resolve(response(active)); });
    expect(mounted.result.current.history.hasPendingToolCalls).toBe(false);
    expect(mounted.result.current.stream.isStreaming).toBe(false);
    const completed = completedThread();
    completed.completed_turn_ids = ["turn-old"];
    if (timing === "separate") {
      act(() => sockets.at(-1)!.receive({ event: "session_updated", chat_id: "inactive", scope: "thread" }));
      await act(async () => {});
      expect(fetchMock).toHaveBeenCalledTimes(4);
      await act(async () => {
        reads[1].resolve(response(completed));
        reads[2].resolve(new Response("unavailable", { status: 503 }));
      });
      expect(mounted.result.current.history.error).toBe("HTTP 503");
      expect(mounted.result.current.history.loading).toBe(false);
      expect(mounted.result.current.stream.messages.at(-1)?.content).toBe("The complete answer");
    } else {
      await act(async () => { reads[1].resolve(response(completed)); });
      expect(mounted.result.current.history.messages.at(-1)?.content).toBe("The complete answer");
    }
    expect(mounted.result.current.stream.isStreaming).toBe(false);
    expect(client.hasUnsettledRun("inactive")).toBe(false);
    mounted.unmount();
    close();
  });

  it.each(["before", "during"] as const)("starts fresh recovery instead of sharing a mounted read from %s the outage", async (timing) => {
    const stale = completedThread();
    stale.events = stale.events.slice(0, 1);
    stale.has_pending_tool_calls = true;
    stale.active_turn_id = "turn-old";
    const reads: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { reads.push(resolve); }));
    vi.stubGlobal("fetch", fetchMock);
    const { client, sockets, running, reopen, close } = setup();
    running();
    if (timing === "during") {
      act(() => sockets.at(-1)!.close());
      await act(async () => { await vi.advanceTimersByTimeAsync(10); });
      expect(client.status).toBe("connecting");
    }
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="renewed-token">{children}</ClientProvider>
    );
    const mounted = renderHook(() => useSessionHistory("websocket:inactive"), { wrapper });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    if (timing === "before") await reopen();
    else await act(async () => { sockets.at(-1)!.open(); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => { reads[1](response(completedThread())); });
    await act(async () => { reads[0](response(stale)); });
    expect(mounted.result.current.messages.at(-1)?.content).toBe("The complete answer");
    expect(mounted.result.current.hasPendingToolCalls).toBe(false);
    expect(client.getRunStartedAt("inactive")).toBeNull();
    mounted.unmount();
    close();
  });

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
    client.onTranscript("inactive", delayed);
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

  it("keeps a queued turn and its resumed frames active when a racing idle page has no completion", async () => {
    let resolveRead!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => {
      resolveRead = resolve;
    })));
    const { client, sockets, running, close } = setup();
    act(() => sockets[0].close());
    client.sendMessage("inactive", "A queued task", undefined, { turnId: "turn-queued" });
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    await act(async () => { sockets.at(-1)!.open(); });
    act(() => running("inactive", "turn-queued", 456));
    const body = completedThread("inactive", "turn-queued");
    body.events = body.events.slice(0, 1);
    body.completed_turn_ids = [];
    body.active_turn_id = null;
    await act(async () => { resolveRead(response(body)); });
    expect(client.getRunStartedAt("inactive")).toBe(456);
    expect(client.hasUnsettledRun("inactive")).toBe(true);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    const resumed = vi.fn();
    client.onTranscript("inactive", resumed);
    resumed.mockClear();
    act(() => {
      running("inactive", "turn-queued", 456);
      sockets.at(-1)!.receive({ event: "delta", chat_id: "inactive", turn_id: "turn-queued", text: "Resumed answer" });
    });
    expect(resumed).toHaveBeenCalledWith(expect.objectContaining({ event: "goal_status", status: "running" }));
    expect(resumed).toHaveBeenCalledWith(expect.objectContaining({ event: "delta", text: "Resumed answer" }));
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
