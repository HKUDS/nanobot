import { act, renderHook } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNanobotStream } from "@/hooks/useNanobotStream";
import { useReconnectRuns } from "@/hooks/useReconnectRuns";
import { NanobotClient } from "@/lib/nanobot-client";
import { ThreadMessageCache } from "@/lib/thread-message-cache";
import type { WebuiThreadPersistedPayload } from "@/lib/types";
import { webuiThreadCache } from "@/lib/webui-thread-cache";
import { ClientProvider } from "@/providers/ClientProvider";

class Socket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send() {}
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
  receive(payload: unknown) { this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent); }
}

interface Read {
  chat: string;
  signal: AbortSignal;
  resolve: (body: WebuiThreadPersistedPayload) => void;
  fail: (status: number) => void;
}

function history(chat: string, completed: string[], active: string | null = null): WebuiThreadPersistedPayload {
  return {
    schemaVersion: 3, sessionKey: `websocket:${chat}`, projection: "events",
    completed_turn_ids: completed, has_pending_tool_calls: active !== null, active_turn_id: active,
    page: { history_generation: "real-use", before_cursor: null, has_more_before: false },
    events: [
      ...completed.flatMap((turn) => [
        { event: "user_message" as const, chat_id: chat, turn_id: turn, turn_seq: 1,
          projection_id: `${chat}-${turn}-question`, text: `${chat} question ${turn}`, starts_turn: true },
        { event: "message" as const, chat_id: chat, turn_id: turn, turn_seq: 2,
          projection_id: `${chat}-${turn}-answer`, text: `${chat} answer ${turn}` },
        { event: "turn_end" as const, chat_id: chat, turn_id: turn, turn_seq: 3,
          projection_id: `${chat}-${turn}-end` },
      ]),
      ...(active ? [{ event: "user_message" as const, chat_id: chat, turn_id: active, turn_seq: 1,
        projection_id: `${chat}-${active}-question`, text: `${chat} question ${active}`, starts_turn: true }] : []),
    ],
  };
}

function harness() {
  const reads: Read[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
    if (!String(url).includes("/webui-thread")) return Promise.resolve(new Response("{}", { status: 404 }));
    const key = decodeURIComponent(new URL(String(url), "http://test").pathname.split("/")[3]);
    return new Promise<Response>((resolve) => {
      reads.push({ chat: key.slice("websocket:".length), signal: init.signal as AbortSignal,
        // Deliberately allow delivery after cancellation: the consumer must reject it.
        resolve: (body) => resolve(new Response(JSON.stringify(body), { status: 200 })),
        fail: (status) => resolve(new Response("Synthetic failure", { status })) });
    });
  }));
  const sockets: Socket[] = [];
  const client = new NanobotClient({ url: "ws://test", reconnect: true, maxBackoffMs: 10,
    socketFactory: () => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket; } });
  client.connect();
  sockets[0].open();
  const token = () => "synthetic-token";
  const recovery = renderHook(() => useReconnectRuns(client, token));
  const socket = () => sockets.at(-1)!;
  const running = (chat: string, turn: string, startedAt: number) => socket().receive({
    event: "goal_status", chat_id: chat, turn_id: turn, status: "running", started_at: startedAt,
  });
  const reopen = async () => {
    act(() => socket().close());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    await act(async () => { socket().open(); });
  };
  const cache = new ThreadMessageCache(() => false);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ClientProvider client={client} token="synthetic-token">{children}</ClientProvider>
  );
  const mount = (initialChat: string) => renderHook(({ chat }) => {
    const stream = useNanobotStream(chat, [], false, undefined, undefined, [], { key: `websocket:${chat}`, cache });
    useEffect(() => {
      let refreshOnNextOpen = client.status !== "open";
      return client.onStatus((status) => {
        if (status !== "open") refreshOnNextOpen = true;
        else { if (refreshOnNextOpen) stream.refreshHistory(); refreshOnNextOpen = false; }
      });
    }, [stream.refreshHistory]);
    return stream;
  }, { wrapper, initialProps: { chat: initialChat } });
  return { client, reads, socket, running, reopen, mount,
    close: () => { recovery.unmount(); client.close(); } };
}

beforeEach(() => { vi.useFakeTimers(); webuiThreadCache.clear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); webuiThreadCache.clear(); });

describe("reconnect across chat selection and transport generations", () => {
  it("gives a mounted owner sole responsibility for a shared completed page", async () => {
    const h = harness();
    act(() => h.running("alpha", "turn-1", 100));
    const selected = h.mount("alpha");
    await act(async () => { h.reads[0].resolve(history("alpha", [], "turn-1")); });
    const reconcile = vi.spyOn(h.client, "reconcileCanonicalCompletion");
    await h.reopen();
    await act(async () => { h.reads.at(-1)!.resolve(history("alpha", ["turn-1"])); });
    expect(reconcile).toHaveBeenCalledTimes(1);
    expect(selected.result.current.messages.map((message) => message.content)).toContain("alpha answer turn-1");
    expect(selected.result.current.isStreaming).toBe(false);
    expect(h.client.getUnsettledRunChatIds()).toEqual([]);
    selected.unmount();
    h.close();
  });

  it("settles a mounted old turn when shared reconnect history precedes the newer running frame", async () => {
    const h = harness();
    act(() => h.running("alpha", "turn-1", 100));
    const selected = h.mount("alpha");
    await act(async () => { h.reads[0].resolve(history("alpha", [], "turn-1")); });
    await h.reopen();
    const read = h.reads.at(-1)!;
    expect(read.signal.aborted).toBe(false);
    await act(async () => { read.resolve(history("alpha", ["turn-1"], "turn-2")); });
    const completedFirst = h.client.isRunCompleted("alpha", "turn-1");
    act(() => {
      h.running("alpha", "turn-2", 200);
      h.socket().receive({ event: "message", chat_id: "alpha", turn_id: "turn-2", text: "alpha live answer" });
      h.socket().receive({ event: "turn_end", chat_id: "alpha", turn_id: "turn-2" });
    });
    const observed = { completedFirst, state: h.client.getRunState("alpha"),
      streaming: selected.result.current.isStreaming,
      contents: selected.result.current.messages.map((message) => message.content) };
    selected.unmount();
    h.close();
    expect(observed).toMatchObject({ completedFirst: true,
      state: { active: false, unsettled: false, latestTurnId: "turn-2" }, streaming: false,
      contents: expect.arrayContaining(["alpha answer turn-1", "alpha live answer"]) });
  });

  it.each(["before", "after"] as const)("keeps two chats isolated when obsolete responses arrive %s current recovery across two outages", async (obsoleteTiming) => {
    const h = harness();
    // Turn IDs are deliberately reused across chats; ownership is a chat/turn pair.
    act(() => { h.running("alpha", "turn-1", 100); h.running("beta", "turn-1", 101); });
    const selected = h.mount("alpha");
    await act(async () => { h.reads[0].resolve(history("alpha", [], "turn-1")); });
    await h.reopen();
    const firstRecovery = h.reads.slice(1);
    expect(firstRecovery.map((read) => read.chat).sort()).toEqual(["alpha", "beta"]);
    selected.rerender({ chat: "beta" });
    expect(h.client.hasTranscript("alpha")).toBe(false);
    expect(h.client.hasTranscript("beta")).toBe(true);
    act(() => { h.running("alpha", "turn-2", 200); h.running("beta", "turn-2", 201); });
    // Cancel the whole first recovery batch before either old page returns.
    await h.reopen();
    expect(firstRecovery.every((read) => read.signal.aborted)).toBe(true);
    const secondRecovery = h.reads.slice(3);
    expect(secondRecovery.map((read) => read.chat).sort()).toEqual(["alpha", "beta"]);
    const beforeStale = [h.client.getRunState("alpha"), h.client.getRunState("beta")];
    const deliverObsolete = async () => {
      const states = [h.client.getRunState("alpha"), h.client.getRunState("beta")];
      const cached = [webuiThreadCache.get("websocket:alpha"), webuiThreadCache.get("websocket:beta")];
      await act(async () => { for (const read of firstRecovery) read.resolve(history(read.chat, ["turn-1"])); });
      expect([h.client.getRunState("alpha"), h.client.getRunState("beta")]).toEqual(states);
      expect([webuiThreadCache.get("websocket:alpha"), webuiThreadCache.get("websocket:beta")]).toEqual(cached);
    };
    if (obsoleteTiming === "before") await deliverObsolete();
    // Unmount beta while its shared current read survives in background recovery.
    selected.rerender({ chat: "alpha" });
    const secondAlpha = secondRecovery.find((read) => read.chat === "alpha")!;
    const secondBeta = secondRecovery.find((read) => read.chat === "beta")!;
    await act(async () => { secondBeta.resolve(history("beta", ["turn-1"], "turn-2")); });
    expect(h.client.isRunCompleted("beta", "turn-1")).toBe(true);
    expect(h.client.getRunState("alpha")).toEqual(beforeStale[0]);
    const betaBeforeAlpha = h.client.getRunState("beta");
    await act(async () => { secondAlpha.resolve(history("alpha", ["turn-1"], "turn-2")); });
    expect(h.client.isRunCompleted("alpha", "turn-1")).toBe(true);
    expect(h.client.getRunState("beta")).toEqual(betaBeforeAlpha);
    if (obsoleteTiming === "after") await deliverObsolete();
    for (const chat of ["alpha", "beta"]) expect(h.client.getRunState(chat)).toMatchObject({ active: true, latestTurnId: "turn-2" });
    act(() => {
      for (const chat of ["alpha", "beta"]) {
        h.socket().receive({ event: "message", chat_id: chat, turn_id: "turn-2", turn_seq: 2,
          projection_id: `${chat}-turn-2-answer`, text: `${chat} answer turn-2` });
        h.socket().receive({ event: "turn_end", chat_id: chat, turn_id: "turn-2", turn_seq: 3 });
      }
    });
    for (const chat of ["alpha", "beta"]) expect(h.client.getRunState(chat)).toMatchObject({ active: false, unsettled: false });
    expect(h.client.getUnsettledRunChatIds()).toEqual([]);
    expect(selected.result.current.messages.map((message) => message.content)).toEqual(expect.arrayContaining([
      "alpha answer turn-1", "alpha answer turn-2",
    ]));
    expect(selected.result.current.messages.every((message) => !message.content.includes("beta"))).toBe(true);
    // A third alpha turn starts while the user returns to the now-idle beta.
    act(() => h.running("alpha", "turn-3", 300));
    const alphaThird = h.client.getRunState("alpha");
    selected.rerender({ chat: "beta" });
    await act(async () => { h.reads.at(-1)!.resolve(history("beta", ["turn-1", "turn-2"])); });
    expect(h.client.getRunState("alpha")).toEqual(alphaThird);
    expect(selected.result.current.messages.map((message) => message.content)).toEqual(expect.arrayContaining([
      "beta answer turn-1", "beta answer turn-2",
    ]));
    expect(selected.result.current.messages.every((message) => !message.content.includes("alpha"))).toBe(true);
    expect(selected.result.current.isStreaming).toBe(false);
    act(() => {
      h.socket().receive({ event: "message", chat_id: "alpha", turn_id: "turn-3", text: "alpha answer turn-3" });
      h.socket().receive({ event: "turn_end", chat_id: "alpha", turn_id: "turn-3" });
    });
    expect(h.client.getUnsettledRunChatIds()).toEqual([]);
    expect(selected.result.current.messages.every((message) => !message.content.includes("alpha"))).toBe(true);
    selected.unmount();
    h.close();
  });

  it("preserves anonymous recovery through a mounted full-page cache handoff", async () => {
    const h = harness();
    act(() => h.running("alpha", "turn-1", 100));
    const selected = h.mount("alpha");
    await act(async () => { h.reads[0].resolve(history("alpha", [], "turn-1")); });
    act(() => h.socket().receive({ event: "recovery_state", chat_id: "alpha", status: "resuming",
      recovery_id: "independent", attempts: 1 }));
    await h.reopen();
    const body = { ...history("alpha", ["turn-1"]), has_pending_tool_calls: true };
    await act(async () => { h.reads.at(-1)!.resolve(body); });
    expect(h.client.isRunCompleted("alpha", "turn-1")).toBe(true);
    expect(h.client.getRunState("alpha")).toMatchObject({ active: true, unsettled: false, startedAt: null });
    expect(selected.result.current.isStreaming).toBe(true);
    act(() => h.socket().receive({ event: "recovery_state", chat_id: "alpha", status: "recovered",
      recovery_id: "independent", attempts: 1 }));
    expect(h.client.getRunState("alpha")).toMatchObject({ active: false, unsettled: false });
    expect(selected.result.current.isStreaming).toBe(false);
    selected.unmount();
    h.close();
  });

  it("rejects an abandoned chat's page after switching away and back without reconnecting", async () => {
    const h = harness();
    act(() => { h.running("alpha", "turn-1", 100); h.running("beta", "turn-1", 101); });
    const selected = h.mount("alpha");
    selected.rerender({ chat: "beta" });
    selected.rerender({ chat: "alpha" });
    const [abandonedAlpha, abandonedBeta, currentAlpha] = h.reads;
    expect(abandonedAlpha.signal.aborted).toBe(true);
    expect(abandonedBeta.signal.aborted).toBe(true);
    act(() => h.running("alpha", "turn-2", 200));
    await act(async () => { currentAlpha.resolve(history("alpha", ["turn-1"], "turn-2")); });
    const before = h.client.getRunState("alpha");
    await act(async () => {
      abandonedAlpha.resolve(history("alpha", [], "turn-1"));
      abandonedBeta.resolve(history("beta", ["turn-1"]));
    });
    expect(h.client.getRunState("alpha")).toEqual(before);
    expect(selected.result.current.messages.map((message) => message.content)).toContain("alpha answer turn-1");
    expect(selected.result.current.messages.every((message) => !message.content.includes("beta"))).toBe(true);
    expect(h.client.isRunCompleted("beta", "turn-1")).toBe(false);
    act(() => {
      for (const [chat, turn] of [["alpha", "turn-2"], ["beta", "turn-1"]]) {
        h.socket().receive({ event: "turn_end", chat_id: chat, turn_id: turn });
      }
    });
    expect(h.client.getUnsettledRunChatIds()).toEqual([]);
    selected.unmount();
    h.close();
  });

  it("does not strand an older turn when selection changes before the scheduled mounted refresh", async () => {
    const h = harness();
    act(() => h.running("alpha", "turn-1", 100));
    const selected = h.mount("alpha");
    await h.reopen();
    const oldRead = h.reads.at(-1)!;
    act(() => h.socket().close());
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    const canReconcile = h.client.canReconcileCanonicalCompletion.bind(h.client);
    let pageProcessed!: () => void;
    const processed = new Promise<void>((resolve) => { pageProcessed = resolve; });
    const preflights: boolean[] = [];
    vi.spyOn(h.client, "canReconcileCanonicalCompletion").mockImplementation((...args) => {
      const accepted = canReconcile(...args);
      if (args[2].includes("turn-1") && args[3]?.activeTurnId === "turn-2") {
        preflights.push(accepted);
        pageProcessed();
      }
      return accepted;
    });
    let readsBeforeSwitch = 0;
    await act(async () => {
      h.socket().open();
      h.running("alpha", "turn-2", 200);
      h.reads.at(-1)!.resolve(history("alpha", ["turn-1"], "turn-2"));
      await processed;
      readsBeforeSwitch = h.reads.length;
      selected.rerender({ chat: "beta" });
    });
    act(() => {
      h.socket().receive({ event: "turn_end", chat_id: "alpha", turn_id: "turn-2" });
      h.socket().receive({ event: "session_updated", chat_id: "alpha", scope: "thread" });
    });
    const observed = { preflights, readsBeforeSwitch, oldReadAborted: oldRead.signal.aborted,
      state: h.client.getRunState("alpha"), unsettled: h.client.getUnsettledRunChatIds() };
    selected.unmount();
    h.close();
    expect(observed).toMatchObject({ preflights: [false], readsBeforeSwitch: 3, oldReadAborted: true,
      state: { active: false, unsettled: false }, unsettled: [] });
  });

  it.each(["failed", "fragment"] as const)("clears a completed run after reconnect with a %s history read", async (read) => {
    const h = harness();
    h.client.attach("alpha");
    act(() => h.running("alpha", "turn-1", 100));
    expect(h.client.getRunState("alpha").active).toBe(true);
    await h.reopen();
    await act(async () => {
      const pending = h.reads.at(-1)!;
      if (read === "failed") pending.fail(503);
      else pending.resolve({ ...history("alpha", []), page: {
        history_generation: "real-use", before_cursor: null, has_more_before: true,
        record_range: { turn: 1, start: 1, end: 2 },
      } });
    });
    expect(h.client.getRunState("alpha").active).toBe(true);
    act(() => {
      h.socket().receive({ event: "attached", chat_id: "alpha", live_turn_ids: [] });
      h.running("alpha", "turn-1", 100); // An older running frame was still on the bus.
    });
    expect(h.client.getRunState("alpha").active).toBe(false);
    h.close();
  });

  it("preserves a still-live owner and a newly submitted turn on reattach", async () => {
    const h = harness();
    h.client.attach("alpha");
    act(() => {
      h.running("alpha", "finished", 100);
      h.running("alpha", "still-live", 200);
    });
    await h.reopen();
    act(() => {
      h.client.sendMessage("alpha", "new submission", undefined, { turnId: "new" });
      h.socket().receive({ event: "attached", chat_id: "alpha", live_turn_ids: ["still-live"] });
    });
    expect(h.client.getRunState("alpha").latestTurnId).toBe("new");
    expect(h.client.isRunCompleted("alpha", "new")).toBe(false);
    act(() => h.socket().receive({ event: "turn_end", chat_id: "alpha", turn_id: "new" }));
    expect(h.client.getRunState("alpha").active).toBe(true);
    act(() => h.socket().receive({ event: "turn_end", chat_id: "alpha", turn_id: "still-live" }));
    expect(h.client.getRunState("alpha").active).toBe(false);
    h.close();
  });

  it("recovers six chats beyond the read-concurrency limit after a failed page and repeated drops", async () => {
    const h = harness();
    const chats = Array.from({ length: 6 }, (_, index) => `chat-${index}`);
    act(() => { for (const chat of chats) h.running(chat, "turn-1", 100); });
    await h.reopen();
    const abandoned = [...h.reads];
    expect(abandoned).toHaveLength(4);
    await h.reopen();
    expect(abandoned.every((read) => read.signal.aborted)).toBe(true);
    const current = h.reads.slice(4);
    expect(current).toHaveLength(4);
    await act(async () => {
      current[0].fail(503);
      for (const read of current.slice(1)) read.resolve(history(read.chat, ["turn-1"]));
    });
    const remaining = h.reads.slice(8);
    expect(remaining.map((read) => read.chat).sort()).toEqual(["chat-4", "chat-5"]);
    await act(async () => { for (const read of remaining) read.resolve(history(read.chat, ["turn-1"])); });
    expect(h.client.getUnsettledRunChatIds()).toEqual(["chat-0"]);
    // A failed read is not success; the next real reconnect supplies its evidence.
    await h.reopen();
    expect(h.reads.slice(10).map((read) => read.chat)).toEqual(["chat-0"]);
    await act(async () => { h.reads[10].resolve(history("chat-0", ["turn-1"])); });
    await act(async () => { for (const read of abandoned) read.resolve(history(read.chat, [], "turn-1")); });
    expect(h.client.getUnsettledRunChatIds()).toEqual([]);
    for (const chat of chats) {
      expect(h.client.getRunState(chat)).toMatchObject({ active: false, unsettled: false });
      expect(webuiThreadCache.get(`websocket:${chat}`)?.completed_turn_ids).toEqual(["turn-1"]);
    }
    h.close();
  });
});
