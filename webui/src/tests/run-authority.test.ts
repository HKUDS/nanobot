import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NanobotClient } from "@/lib/nanobot-client";
import { decodeRunSnapshot, type ServerRun, type ServerRunSnapshot } from "@/lib/server-run-state";

class Socket {
  readyState = 0;
  sent: Array<Record<string, unknown>> = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send(frame: string) { this.sent.push(JSON.parse(frame)); }
  close() { this.readyState = 3; this.onclose?.(); }
  emit(frame: unknown) { this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent); }
  open(instance: string | null = "host-a") {
    this.readyState = 1;
    this.onopen?.();
    this.emit({ event: "ready", chat_id: "default", client_id: "browser", ...(instance ? { run_state_instance_id: instance } : {}) });
  }
}

const run = (id = "owner-a", turn = "turn-a", phase: ServerRun["phase"] = "running"): ServerRun => ({
  run_id: id, turn_id: turn, phase, started_at: null,
});
const snapshot = (revision: number, runs: ServerRun[] = [], instance = "host-a"): ServerRunSnapshot => ({
  instance_id: instance, revision, runs, completed: [],
});
let clients: NanobotClient[];
function setup(reconnect = false) {
  const sockets: Socket[] = [];
  const client = new NanobotClient({ url: "ws://test", reconnect, maxBackoffMs: 1,
    socketFactory: () => { const socket = new Socket(); sockets.push(socket); return socket as unknown as WebSocket; } });
  clients.push(client);
  client.connect();
  return { client, sockets, socket: sockets[0] };
}
function update(socket: Socket, state: ServerRunSnapshot, chatId = "chat") {
  socket.emit({ event: "run_state", chat_id: chatId, run_state: state });
}

beforeEach(() => { clients = []; vi.useFakeTimers(); });
afterEach(() => { for (const client of clients) client.close(); vi.useRealTimers(); });

describe("backend-authoritative execution", () => {
  it("requires an authenticated ready epoch, not an HTTP snapshot or a timestamp", () => {
    const { client, socket } = setup();
    expect(client.ingestRunSnapshot("chat", snapshot(2, [run()]))).toBe(false);
    socket.open();
    update(socket, snapshot(2, [run()]));
    expect(client.getRunState("chat")).toMatchObject({ active: true, freshness: "fresh", phase: "running", startedAt: null });
  });

  it("separates accepted queue admission from actual running", () => {
    const { client, socket } = setup(); socket.open();
    update(socket, snapshot(1, [run("owner-a", "turn-a", "queued")]));
    expect(client.getRunState("chat").phase).toBe("queued");
    update(socket, snapshot(2, [run()]));
    expect(client.getRunState("chat").phase).toBe("running");
  });

  it("never reopens execution from history, legacy status, output or recovery", () => {
    const { client, socket } = setup(); socket.open();
    update(socket, snapshot(4));
    for (const event of [
      { event: "goal_status", status: "running", started_at: 123 },
      { event: "delta", text: "late text" },
      { event: "stream_end" },
      { event: "retry_status", state: "retrying", attempt: 1 },
      { event: "recovery_state", status: "resuming", recovery_id: "recovery" },
      { event: "attached", recovery_state: { status: "resuming", recovery_id: "recovery" } },
    ]) socket.emit({ ...event, chat_id: "chat", turn_id: "old-turn" });
    expect(client.getRunState("chat")).toMatchObject({ active: false, freshness: "fresh", phase: "idle" });
    expect(client.ingestRunSnapshot("chat", snapshot(3, [run()]))).toBe(false);
    expect(client.getRunState("chat").active).toBe(false);
  });

  it("keeps other execution owners active when one owner exits", () => {
    const { client, socket } = setup(); socket.open();
    update(socket, snapshot(1, [run(), run("owner-b", "turn-b")]));
    socket.emit({ event: "turn_end", chat_id: "chat", turn_id: "turn-a" });
    update(socket, snapshot(2, [run("owner-b", "turn-b")]));
    socket.emit({ event: "goal_status", chat_id: "chat", turn_id: "turn-a", status: "idle" });
    expect(client.getRunState("chat").runs.map((owner) => owner.run_id)).toEqual(["owner-b"]);
    expect(client.getRunState("chat").active).toBe(true);
  });

  it("marks disconnection unknown and revalidates an equal-version reconnect baseline", async () => {
    const { client, socket, sockets } = setup(true); socket.open();
    update(socket, snapshot(2, [run()]));
    socket.close();
    expect(client.getRunState("chat")).toMatchObject({ active: true, freshness: "unknown" });
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].open();
    expect(client.getRunState("chat").freshness).toBe("syncing");
    // Same-instance, equal-revision HTTP that started before the outage is not a socket baseline.
    expect(client.ingestRunSnapshot("chat", snapshot(2, [run()]))).toBe(false);
    expect(client.getRunState("chat").freshness).toBe("syncing");
    update(sockets[1], snapshot(2, [run()]));
    expect(client.getRunState("chat").freshness).toBe("fresh");
  });

  it("rejects a prior socket and old HTTP epoch after gateway restart", async () => {
    const { client, socket, sockets } = setup(true); socket.open();
    update(socket, snapshot(8, [run()]));
    socket.close(); await vi.advanceTimersByTimeAsync(1);
    sockets[1].open("host-b");
    update(sockets[1], snapshot(0, [], "host-b"));
    socket.emit({ event: "ready", chat_id: "chat", client_id: "old", run_state_instance_id: "host-a" });
    update(socket, snapshot(99, [run()]));
    expect(client.ingestRunSnapshot("chat", snapshot(100, [run()]))).toBe(false);
    expect(client.getRunState("chat")).toMatchObject({ active: false, freshness: "fresh" });
  });

  it("watches sidebar runtime state without attaching background transcripts", () => {
    const { client, socket } = setup();
    client.watchRuns(["background-b", "background-a"]); socket.open();
    const watches = socket.sent.filter((frame) => frame.type === "watch_runs");
    expect(watches.at(-1)?.chat_ids).toEqual(["background-a", "background-b"]);
    expect(socket.sent.some((frame) => frame.type === "attach" && frame.chat_id === "background-a")).toBe(false);
    update(socket, snapshot(1, [run()]), "background-a");
    expect(client.getRunState("background-a").active).toBe(true);
    expect(client.getRunState("background-b").active).toBe(false);
  });

  it("keeps basic chat usable on an old host without fabricating authority", () => {
    const { client, socket } = setup(); socket.open(null);
    const receive = vi.fn(); client.onTranscript("chat", receive);
    client.sendMessage("chat", "hello", undefined, { turnId: "turn-a" });
    socket.emit({ event: "goal_status", chat_id: "chat", turn_id: "turn-a", status: "running", started_at: 123 });
    socket.emit({ event: "message", chat_id: "chat", turn_id: "turn-a", text: "hello back" });
    expect(receive).toHaveBeenCalledWith(expect.objectContaining({ text: "hello back" }));
    expect(client.getRunState("chat")).toMatchObject({ active: false, freshness: "unavailable" });
    expect(socket.sent.some((frame) => frame.type === "watch_runs")).toBe(false);
  });
});

describe("delivery, cancellation and final result are not execution", () => {
  it("does not show a local send as executing and does not invent success for a lost ACK", async () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1));
    client.sendMessage("chat", "hello", undefined, { turnId: "turn-a" });
    expect(client.getRunState("chat")).toMatchObject({ active: false, delivery: "sending", unsettled: true });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(client.getRunState("chat").delivery).toBe("unknown");
    expect(client.reconcileCanonicalCompletion("chat", client.getRunGeneration("chat"), [], {
      observedTurnIds: [], hasPendingToolCalls: false, completionIdsProvided: true,
    })).toBe(false);
    expect(client.getRunState("chat")).toMatchObject({ active: false, delivery: "unknown", unsettled: true });
    expect(socket.sent.filter((frame) => frame.type === "message")).toHaveLength(1);
  });

  it("does not queue an application retry when a socket write fails ambiguously", () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1));
    socket.send = () => { throw new Error("transport changed"); };
    client.sendMessage("chat", "hello", undefined, { turnId: "turn-a" });
    expect(client.getRunState("chat")).toMatchObject({ active: false, delivery: "unknown", unsettled: true });
  });

  it("rejects an outstanding Stop request on deliberate client close", async () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1, [run()]));
    const stopping = client.requestStop("chat");
    client.close();
    await expect(stopping).rejects.toThrow("Socket closed");
    expect(client.getRunState("chat")).toMatchObject({ active: true, freshness: "unknown", cancelPending: false });
  });

  it("scopes Stop to confirmed owners, and waits for actual execution exit", async () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1, [run()]));
    const stopping = client.requestStop("chat");
    const request = socket.sent.at(-1)!;
    expect(request).toMatchObject({ type: "webui_request", action: "runs.stop", payload: { chat_id: "chat", run_ids: ["owner-a"] } });
    expect(client.getRunState("chat")).toMatchObject({ active: true, cancelPending: true });
    socket.emit({ event: "webui_response", request_id: request.request_id, ok: true, result: {} });
    await stopping;
    update(socket, snapshot(2, [run("owner-a", "turn-a", "stopping")]));
    expect(client.getRunState("chat")).toMatchObject({ active: true, phase: "stopping", cancelPending: true });
    update(socket, snapshot(3));
    expect(client.getRunState("chat")).toMatchObject({ active: false, cancelPending: false, unsettled: true });
  });

  it("keeps execution after a rejected Stop and allows an explicit retry", async () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1, [run()]));
    const stopping = client.requestStop("chat");
    const request = socket.sent.at(-1)!;
    socket.emit({ event: "webui_response", request_id: request.request_id, ok: false, error: { status: 409, message: "Owner changed" } });
    await expect(stopping).rejects.toThrow("Owner changed");
    expect(client.getRunState("chat")).toMatchObject({ active: true, cancelPending: false });
  });

  it("preserves final transcript delivery before releasing the local result", () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1, [run()]));
    const order: string[] = [];
    client.onTranscript("chat", (frame) => {
      if (frame.event === "message") order.push(frame.text);
      if (frame.event === "turn_end") {
        expect(client.hasUnsettledRun("chat")).toBe(true);
        order.push("render-complete");
      }
    });
    client.onRunStatus((chatId, state) => {
      if (chatId === "chat" && !state.unsettled) order.push("settled");
    });
    update(socket, snapshot(2));
    expect(client.hasUnsettledRun("chat")).toBe(true);
    socket.emit({ event: "message", chat_id: "chat", turn_id: "turn-a", text: "Final result" });
    socket.emit({ event: "turn_end", chat_id: "chat", turn_id: "turn-a" });
    expect(order).toEqual(["Final result", "render-complete", "settled"]);
    expect(client.getRunState("chat").active).toBe(false);
  });

  it("reconciles a lost guidance ACK from its durable input without inventing another completed run", () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1, [run()]));
    client.sendMessage("chat", "guidance", undefined, { turnId: "guidance", startsNewRun: false });
    socket.close();
    expect(client.getRunState("chat").delivery).toBe("unknown");
    expect(client.reconcileCanonicalCompletion("chat", client.getRunGeneration("chat"), ["turn-a"], {
      observedTurnIds: ["turn-a", "guidance"], hasPendingToolCalls: false, completionIdsProvided: true,
    })).toBe(true);
    expect(client.getRunState("chat")).toMatchObject({ delivery: "none", unsettled: false });
    expect(client.isRunCompleted("chat", "guidance")).toBe(false);
  });

  it("does not equate a runtime completion receipt with a delivered result", () => {
    const { client, socket } = setup(); socket.open(); update(socket, snapshot(1, [run()]));
    update(socket, { ...snapshot(2), completed: [{ run_id: "owner-a", turn_id: "turn-a", outcome: "failed" }] });
    expect(client.getRunState("chat")).toMatchObject({ active: false, unsettled: true });
    expect(client.isRunCompleted("chat", "turn-a")).toBe(false);
  });
});

it("rejects malformed runtime snapshots at the network boundary", () => {
  expect(decodeRunSnapshot({ ...snapshot(1), runs: [{ ...run(), phase: "invented" }] })).toBeNull();
  expect(decodeRunSnapshot({ ...snapshot(1), runs: [run(), run()] })).toBeNull();
  expect(decodeRunSnapshot({ ...snapshot(1), revision: -1 })).toBeNull();
});
