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
  it("settles an unmounted run without losing buffered or late output absent from its completed latest fragment", async () => {
    const chatId = "inactive";
    const turnId = "turn-old";
    const body: WebuiThreadPersistedPayload = {
      schemaVersion: 3, sessionKey: `websocket:${chatId}`, projection: "events",
      has_pending_tool_calls: false, active_turn_id: null, completed_turn_ids: [turnId],
      page: { history_generation: "generation", record_range: { turn: 0, start: 5, end: 8 },
        before_cursor: "before-5", has_more_before: true, truncated_oversized_turn: true },
      events: [
        { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 7, text: "Later persisted answer" },
        { event: "turn_end", chat_id: chatId, turn_id: turnId, turn_seq: 8 },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const { client, sockets, running, reopen, close } = setup();
    const early = { event: "delta", chat_id: chatId, turn_id: turnId, turn_seq: 2, stream_id: "wire", text: "Unpersisted earlier output" };
    const late = { event: "delta", chat_id: chatId, turn_id: turnId, turn_seq: 3, stream_id: "wire", text: "Late output" };
    const activity = { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 4, kind: "tool_hint", text: "search(query)" };
    running();
    sockets[0].receive(early);
    sockets[0].receive({ event: "recovery_state", chat_id: chatId, turn_id: turnId,
      status: "resuming", recovery_id: "buffered-recovery", attempts: 0 });

    await reopen();

    expect(client.getRunState(chatId)).toMatchObject({ active: false, unsettled: false, startedAt: null });
    expect(client.isRunCompleted(chatId, turnId)).toBe(true);
    expect(webuiThreadCache.get(`websocket:${chatId}`)).toEqual(body);
    act(() => {
      sockets.at(-1)!.receive(late);
      sockets.at(-1)!.receive(activity);
      running(chatId, turnId, 999);
      sockets.at(-1)!.receive({ event: "recovery_state", chat_id: chatId, turn_id: turnId,
        status: "resuming", recovery_id: "r1", attempts: 0 });
      client.restorePendingRun(chatId, client.getRunGeneration(chatId), turnId);
    });
    expect(client.getRunState(chatId)).toMatchObject({ active: false, unsettled: false, startedAt: null });
    const replay = vi.fn();
    client.onTranscript(chatId, replay);
    expect(replay).toHaveBeenCalledWith(early);
    expect(replay).toHaveBeenCalledWith(late);
    expect(replay).toHaveBeenCalledWith(activity);
    expect(replay).not.toHaveBeenCalledWith(expect.objectContaining({ event: "goal_status", turn_id: turnId, status: "running" }));
    expect(replay).not.toHaveBeenCalledWith(expect.objectContaining({ event: "recovery_state", status: "resuming" }));
    close();
  });

  it("projects an unpersisted buffered tool event when the user returns to the recovered thread", async () => {
    const chatId = "inactive";
    const turnId = "turn-old";
    const body: WebuiThreadPersistedPayload = {
      schemaVersion: 3, sessionKey: `websocket:${chatId}`, projection: "events",
      has_pending_tool_calls: false, active_turn_id: null, completed_turn_ids: [turnId],
      page: { history_generation: "generation", record_range: { turn: 0, start: 5, end: 8 },
        before_cursor: "before-5", has_more_before: true, truncated_oversized_turn: true },
      events: [
        { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 7, text: "Persisted answer", projection_id: "answer" },
        { event: "turn_end", chat_id: chatId, turn_id: turnId, turn_seq: 8, projection_id: "end" },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const { client, sockets, running, reopen, close } = setup();
    running();
    sockets[0].receive({ event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 2,
      kind: "tool_hint", text: "search(unpersisted)" });
    await reopen();
    expect(client.getRunState(chatId).active).toBe(false);

    const wrapper = ({ children }: { children: ReactNode }) => <ClientProvider client={client} token="renewed-token">{children}</ClientProvider>;
    const mounted = renderHook(() => useNanobotStream(chatId, [], false, undefined, undefined, [], { key: `websocket:${chatId}` }), { wrapper });
    await act(async () => {});
    expect(mounted.result.current.messages.map((message) => message.content)).toContain("search(unpersisted)");
    expect(mounted.result.current.messages.map((message) => message.content)).toContain("Persisted answer");
    expect(mounted.result.current.isStreaming).toBe(false);
    act(() => sockets.at(-1)!.receive({ event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 3,
      kind: "tool_hint", text: "search(late)" }));
    expect(mounted.result.current.messages.map((message) => message.content)).toContain("search(late)");
    expect(client.getRunState(chatId).active).toBe(false);
    mounted.unmount();
    close();
  });

  it("settles only the explicitly completed T when U starts during a fragment read", async () => {
    let finishRead!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { finishRead = resolve; })));
    const { client, sockets, running, reopen, close } = setup();
    const chatId = "inactive";
    const earlyT = { event: "delta", chat_id: chatId, turn_id: "turn-old", turn_seq: 2, stream_id: "T", text: "T buffered" };
    const frameU = { event: "delta", chat_id: chatId, turn_id: "turn-new", turn_seq: 2, stream_id: "U", text: "U buffered" };
    const lateT = { event: "delta", chat_id: chatId, turn_id: "turn-old", turn_seq: 3, stream_id: "T", text: "T late" };
    running();
    sockets[0].receive(earlyT);
    await reopen();
    act(() => {
      running(chatId, "turn-new", 456);
      sockets.at(-1)!.receive(frameU);
    });
    const body: WebuiThreadPersistedPayload = {
      schemaVersion: 3, sessionKey: `websocket:${chatId}`, projection: "events",
      has_pending_tool_calls: false, active_turn_id: null, completed_turn_ids: ["turn-old"],
      page: { history_generation: "generation", record_range: { turn: 0, start: 5, end: 8 },
        before_cursor: "before-5", has_more_before: true, truncated_oversized_turn: true },
      events: [{ event: "turn_end", chat_id: chatId, turn_id: "turn-old", turn_seq: 8 }],
    };
    await act(async () => { finishRead(response(body)); });
    expect(client.isRunCompleted(chatId, "turn-old")).toBe(true);
    expect(client.getRunState(chatId)).toMatchObject({ active: true, unsettled: true, latestTurnId: "turn-new", startedAt: 456 });
    expect(webuiThreadCache.get(`websocket:${chatId}`)).toBeUndefined();
    const generationU = client.getRunGeneration(chatId);
    act(() => {
      sockets.at(-1)!.receive(lateT);
      running(chatId, "turn-old", 999);
      sockets.at(-1)!.receive({ event: "recovery_state", chat_id: chatId, turn_id: "turn-old",
        status: "resuming", recovery_id: "r1", attempts: 0 });
      sockets.at(-1)!.receive({ event: "user_message", chat_id: chatId, turn_id: "guidance",
        text: "A delayed input", starts_turn: false, active_turn_id: "turn-old", started_at: 123 });
    });
    expect(client.getRunState(chatId)).toMatchObject({ active: true, unsettled: true, latestTurnId: "turn-new", startedAt: 456, generation: generationU });
    const replay = vi.fn();
    client.onTranscript(chatId, replay);
    expect(replay).toHaveBeenCalledWith(earlyT);
    expect(replay).toHaveBeenCalledWith(frameU);
    expect(replay).toHaveBeenCalledWith(lateT);
    act(() => sockets.at(-1)!.receive({ event: "turn_end", chat_id: chatId, turn_id: "turn-new" }));
    expect(client.getRunState(chatId)).toMatchObject({ active: false, unsettled: false, latestTurnId: "turn-new" });
    close();
  });

  it("settles a mounted run after accepting a published reconnect fragment without a gap", async () => {
    const chatId = "inactive";
    const turnId = "turn-old";
    const initial: WebuiThreadPersistedPayload = {
      schemaVersion: 3, sessionKey: `websocket:${chatId}`, projection: "events",
      has_pending_tool_calls: true, active_turn_id: turnId, completed_turn_ids: [],
      page: { history_generation: "generation", record_range: { turn: 0, start: 1, end: 3 },
        before_cursor: "before-1", has_more_before: true, truncated_oversized_turn: true },
      events: [{ event: "delta", chat_id: chatId, turn_id: turnId, turn_seq: 2, stream_id: "wire", text: "Before" }],
    };
    const latest: WebuiThreadPersistedPayload = {
      ...initial, has_pending_tool_calls: false, active_turn_id: null, completed_turn_ids: [turnId],
      page: { ...initial.page, record_range: { turn: 0, start: 1, end: 5 } },
      events: [
        ...initial.events,
        { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 4, text: "Answer" },
        { event: "turn_end", chat_id: chatId, turn_id: turnId, turn_seq: 5 },
      ],
    };
    let finishLatest!: (value: Response) => void;
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(() => {
      const read = reads++;
      if (read === 0) return Promise.resolve(response(initial));
      if (read === 1) return new Promise<Response>((resolve) => { finishLatest = resolve; });
      return Promise.resolve(response(latest));
    }));
    const { client, running, reopen, close } = setup();
    const wrapper = ({ children }: { children: ReactNode }) => <ClientProvider client={client} token="renewed-token">{children}</ClientProvider>;
    const mounted = renderHook(() => {
      const stream = useNanobotStream(chatId, [], false, undefined, undefined, [], { key: `websocket:${chatId}` });
      useEffect(() => {
        let refreshOnOpen = false;
        return client.onStatus((status) => {
          if (status !== "open") refreshOnOpen = true;
          else if (refreshOnOpen) { refreshOnOpen = false; stream.refreshHistory(); }
        });
      }, [stream.refreshHistory]);
      return stream;
    }, { wrapper });
    await act(async () => { running(); });
    await act(async () => {});
    await reopen();
    await act(async () => { finishLatest(response(latest)); });
    expect(webuiThreadCache.get(`websocket:${chatId}`)).toEqual(latest);
    expect(mounted.result.current.messages.map((message) => message.content)).toContain("Answer");
    expect(client.getRunState(chatId).active).toBe(false);
    expect(mounted.result.current.isStreaming).toBe(false);
    mounted.unmount();
    close();
  });

  it("settles a held overlapping signed-image fragment only after loading its user prefix", async () => {
    const chatId = "inactive";
    const turnId = "turn-old";
    const rawImage = "![image](images/photo.png)";
    const signedImage = "![image](/api/media/signed.png)";
    const initial: WebuiThreadPersistedPayload = {
      schemaVersion: 3, sessionKey: `websocket:${chatId}`, projection: "events",
      has_pending_tool_calls: true, active_turn_id: turnId, completed_turn_ids: [],
      page: { history_generation: "generation", record_range: { turn: 0, start: 1, end: 2 },
        before_cursor: "inside", has_more_before: true, truncated_oversized_turn: true },
      events: [{ event: "model_request", chat_id: chatId, turn_id: turnId, turn_seq: 2,
        request_id: "request", run_id: "run", sequence: 1, phase: "started", projection_id: "request" }],
    };
    const latest: WebuiThreadPersistedPayload = {
      ...initial, has_pending_tool_calls: false, active_turn_id: null, completed_turn_ids: [turnId],
      page: { ...initial.page, record_range: { turn: 0, start: 1, end: 4 } },
      events: [...initial.events,
        { event: "stream_end", chat_id: chatId, turn_id: turnId, turn_seq: 4,
          stream_id: "wire", text: signedImage, projection_id: "answer" },
        { event: "turn_end", chat_id: chatId, turn_id: turnId, turn_seq: 5, projection_id: "done" }],
    };
    const prefix: WebuiThreadPersistedPayload = {
      ...initial, has_pending_tool_calls: false, active_turn_id: null,
      page: { ...initial.page, record_range: { turn: 0, start: 0, end: 1 },
        before_cursor: null, has_more_before: false },
      events: [{ event: "user_message", chat_id: chatId, turn_id: turnId, turn_seq: 1,
        text: "Show the image", starts_turn: true, projection_id: "question" }],
    };
    let latestReads = 0;
    let finishPrefix!: (value: Response) => void;
    const fetchMock = vi.fn((url: string) => url.includes("before=")
      ? new Promise<Response>((resolve) => { finishPrefix = resolve; })
      : Promise.resolve(response(latestReads++ ? latest : initial)));
    vi.stubGlobal("fetch", fetchMock);
    const { client, sockets, running, close } = setup();
    const wrapper = ({ children }: { children: ReactNode }) => <ClientProvider client={client} token="token">{children}</ClientProvider>;
    const mounted = renderHook(() => useNanobotStream(chatId, [], false, undefined, undefined, [],
      { key: `websocket:${chatId}` }), { wrapper });
    act(() => {
      running();
      sockets.at(-1)!.receive({ event: "delta", chat_id: chatId, turn_id: turnId, turn_seq: 3,
        stream_id: "wire", text: rawImage });
    });
    await act(async () => {});
    expect(mounted.result.current.messages.map((message) => message.content)).toEqual([rawImage]);
    await act(async () => { mounted.result.current.refreshHistory(); });
    await act(async () => {});
    expect(mounted.result.current.history.error).toBeNull();
    expect(mounted.result.current.history.hasMoreBefore).toBe(true);
    expect(mounted.result.current.messages.map((message) => message.content)).toEqual([rawImage]);
    expect(mounted.result.current.isStreaming).toBe(true);
    expect(client.getRunState(chatId)).toMatchObject({ active: true, unsettled: true });

    let older!: Promise<void>;
    act(() => { older = mounted.result.current.loadOlder(); });
    expect(fetchMock.mock.calls.at(-1)?.[0]).toContain("before=inside");
    await act(async () => { finishPrefix(response(prefix)); await older; });
    expect(mounted.result.current.messages.map((message) => message.content)).toEqual(["Show the image", signedImage]);
    expect(mounted.result.current.messages.filter((message) => message.role === "assistant")).toHaveLength(1);
    expect(mounted.result.current.history.hasMoreBefore).toBe(false);
    expect(mounted.result.current.isStreaming).toBe(false);
    expect(client.getRunState(chatId)).toMatchObject({ active: false, unsettled: false });
    mounted.unmount();
    close();
  });

  it.each(["reconnect", "refresh"] as const)("keeps live delivery until the %s fragment joins the visible history", async (trigger) => {
    const chatId = "inactive";
    const turnId = "turn-old";
    const chunk = (seq: number, text: string) => ({
      event: "delta" as const, chat_id: chatId, turn_id: turnId, turn_seq: seq,
      stream_id: "wire", text, projection_id: `history-${seq}`,
    });
    const page = (start: number, end: number, events: WebuiThreadPersistedPayload["events"], completed = false): WebuiThreadPersistedPayload => ({
      schemaVersion: 3, sessionKey: `websocket:${chatId}`, projection: "events", events,
      has_pending_tool_calls: !completed, active_turn_id: completed ? null : turnId,
      completed_turn_ids: completed ? [turnId] : [],
      page: { history_generation: "generation", record_range: { turn: 0, start, end },
        before_cursor: `before-${start}`, has_more_before: start > 0, truncated_oversized_turn: true },
    });
    const initial = page(1, 3, [chunk(2, "B"), chunk(3, "C")]);
    const latest = page(6, 9, [chunk(8, "H"), chunk(9, "I"),
      { event: "turn_end", chat_id: chatId, turn_id: turnId, turn_seq: 10, projection_id: "history-end" }], true);
    const missing = page(3, 6, [chunk(5, "E"), chunk(6, "F"), chunk(7, "G")]);
    let finishLatest!: (value: Response) => void;
    let finishMissing!: (value: Response) => void;
    let latestReads = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("before=")) return new Promise<Response>((resolve) => { finishMissing = resolve; });
      const read = latestReads++;
      if (read === 0) return Promise.resolve(response(initial));
      if (read === 1) return new Promise<Response>((resolve) => { finishLatest = resolve; });
      return Promise.resolve(response(latest));
    }));
    const { client, sockets, running, reopen, close } = setup();
    const wrapper = ({ children }: { children: ReactNode }) => <ClientProvider client={client} token="renewed-token">{children}</ClientProvider>;
    const mounted = renderHook(() => {
      const stream = useNanobotStream(chatId, [], false, undefined, undefined, [], { key: `websocket:${chatId}` });
      useEffect(() => {
        let refreshOnOpen = false;
        return client.onStatus((status) => {
          if (status !== "open") refreshOnOpen = true;
          else if (refreshOnOpen) { refreshOnOpen = false; stream.refreshHistory(); }
        });
      }, [stream.refreshHistory]);
      return stream;
    }, { wrapper });
    await act(async () => { running(); });
    await act(async () => {});
    act(() => sockets[0].receive({ event: "delta", chat_id: chatId, turn_id: turnId,
      turn_seq: 4, stream_id: "wire", text: "D" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(mounted.result.current.messages.at(-1)?.content).toBe("BCD");
    const reconcile = vi.spyOn(client, "reconcileCanonicalCompletion");
    const fence = vi.spyOn(client, "fenceCanonicalCompletedTurns");

    if (trigger === "reconnect") await reopen();
    else await act(async () => { mounted.result.current.refreshHistory(); });
    await act(async () => { finishLatest(response(latest)); });
    expect(webuiThreadCache.get(`websocket:${chatId}`)).toEqual(latest);
    expect(mounted.result.current.history.error).toBeNull();
    expect(mounted.result.current.history.loadingOlder).toBe(true);
    expect(finishMissing).toBeTypeOf("function");
    expect(reconcile).not.toHaveBeenCalled();
    expect(fence).not.toHaveBeenCalled();
    expect(client.getRunState(chatId).active).toBe(true);
    expect(mounted.result.current.isStreaming).toBe(true);
    act(() => sockets.at(-1)!.receive({ event: "delta", chat_id: chatId, turn_id: turnId,
      turn_seq: 5, stream_id: "wire", text: "E" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    expect(mounted.result.current.messages.at(-1)?.content).toBe("BCDE");
    await act(async () => { finishMissing(response(missing)); });
    expect(mounted.result.current.messages.at(-1)?.content).toBe("BCDEFGHI");
    expect(client.getRunState(chatId).active).toBe(false);
    expect(mounted.result.current.isStreaming).toBe(false);
    const late = { event: "message", chat_id: chatId, turn_id: turnId, turn_seq: 11,
      kind: "tool_hint", text: "late activity" };
    const observed = vi.fn();
    const unsubscribe = client.onChat(chatId, observed);
    act(() => sockets.at(-1)!.receive(late));
    expect(observed).toHaveBeenCalledWith(late);
    expect(mounted.result.current.messages.map((message) => message.content)).toContain("late activity");
    expect(client.getRunState(chatId).active).toBe(false);
    unsubscribe();
    mounted.unmount();
    close();
  });

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
    expect(client.getRunState("chat-8").startedAt).toBe(456);
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
    expect(client.getRunState("inactive").startedAt).toBeNull();
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
    expect(client.getRunState("inactive").startedAt).toBeNull();
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
    client.onRunStatus((chatId, state) => {
      if (!state.active) cachedAtCompletion.push(webuiThreadCache.get(`websocket:${chatId}`)!);
    });

    await reopen();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Ainactive/webui-thread?limit=40&direction=latest&include_model_requests=1&context_graph_encoding=references-v1",
      expect.objectContaining({ headers: { Authorization: "Bearer renewed-token" } }),
    );
    expect(client.getRunState("inactive").startedAt).toBeNull();
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
    expect(client.getRunState("inactive").startedAt).toBeNull();
    expect(client.getRunState("running").startedAt).toBe(456);
    expect(client.getRunTurnId("running")).toBe("turn-running");
    expect(client.hasUnsettledRun("running")).toBe(true);
    expect(runStatus).toHaveBeenCalledTimes(3);
    close();
  });

  it.each(["failed read", "missing activity state"])("leaves %s unresolved", async (failure) => {
    const body = completedThread();
    Reflect.deleteProperty(body, "has_pending_tool_calls");
    body.events = body.events.slice(0, 2);
    const fetchMock = failure === "failed read"
      ? vi.fn().mockRejectedValue(new Error("offline"))
      : vi.fn().mockResolvedValue(response(body));
    vi.stubGlobal("fetch", fetchMock);
    const { client, running, reopen, close } = setup();
    running();
    await reopen();
    expect(client.getRunState("inactive").startedAt).toBe(123);
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
    expect(client.getRunState("inactive").startedAt).toBe(456);
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
    Reflect.deleteProperty(body, "has_pending_tool_calls");
    body.completed_turn_ids = ["turn-old"];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const { client, running, reopen, close } = setup();
    running();
    await reopen();
    expect(client.getRunState("inactive").startedAt).toBeNull();
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
    expect(client.getRunState("inactive").startedAt).toBe(123);
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
    expect(client.getRunState("inactive").startedAt).toBe(456);
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
    expect(client.getRunState("inactive").startedAt).toBe(123);
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
    expect(client.getRunState("inactive").startedAt).toBe(123);
    expect(webuiThreadCache.get("websocket:inactive")).toBeUndefined();
    close();
  });
});
