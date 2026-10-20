import { NanobotClient } from "@/lib/nanobot-client";
import { decodeRunSnapshot, type ServerRun, type ServerRunCompletion, type ServerRunSnapshot } from "@/lib/server-run-state";
import type { InboundEvent } from "@/lib/types";

/** A protocol-1 host fixture, with authenticated, versioned runtime baselines.
 * Old projection tests supply lifecycle/output frames, so this simulated host
 * admits their owner before output and exits it after terminal delivery. This
 * is backend fixture behavior, not a legacy inference path in the real client.
 * Authority tests can disable it and supply independent snapshots explicitly. */
export function createStreamClient({ autoRunSnapshots = true, instanceId = "fixture-host" }: {
  autoRunSnapshots?: boolean;
  instanceId?: string | null;
} = {}) {
  const sent: Array<Record<string, unknown>> = [];
  const snapshots = new Map<string, ServerRunSnapshot>();
  const lastOwners = new Map<string, string>();
  const ended = new Map<string, Set<string>>();
  const receiveRaw = (event: unknown) => {
    socket.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  };
  const updateRuns = (chatId: string, runs: ServerRun[], completed: ServerRunCompletion[] = []) => {
    const value: ServerRunSnapshot = {
      instance_id: instanceId ?? "unsupported", revision: (snapshots.get(chatId)?.revision ?? 0) + 1,
      runs, completed,
    };
    snapshots.set(chatId, value);
    receiveRaw({ event: "run_state", chat_id: chatId, run_state: value });
    return value;
  };
  const baseline = (chatId: string) => {
    if (!instanceId || !autoRunSnapshots) return;
    const snapshot = snapshots.get(chatId) ?? {
      instance_id: instanceId, revision: 0, runs: [], completed: [],
    };
    receiveRaw({ event: "run_state", chat_id: chatId, run_state: snapshot });
  };
  const socket = {
    readyState: 0,
    onopen: null as (() => void) | null,
    onmessage: null as ((event: MessageEvent) => void) | null,
    onclose: null as (() => void) | null,
    onerror: null as (() => void) | null,
    send(serialized: string) {
      const frame = JSON.parse(serialized) as Record<string, unknown>;
      sent.push(frame);
      if (frame.type === "attach") baseline(String(frame.chat_id));
      if (frame.type === "watch_runs") for (const id of frame.chat_ids as string[]) baseline(id);
      if (frame.type === "webui_request" && frame.action === "runs.stop") {
        receiveRaw({ event: "webui_response", request_id: frame.request_id, ok: true, result: {} });
      }
    },
    close() { socket.readyState = 3; socket.onclose?.(); },
    open() {
      socket.readyState = 1;
      socket.onopen?.();
      receiveRaw({ event: "ready", chat_id: "default", client_id: "fixture-browser",
        ...(instanceId ? { run_state_instance_id: instanceId } : {}),
      });
    },
  };
  const client = new NanobotClient({
    url: "ws://test", reconnect: false,
    socketFactory: () => socket as unknown as WebSocket,
  });
  const receive = (event: InboundEvent) => {
    const chatId = "chat_id" in event ? event.chat_id : undefined;
    if (!autoRunSnapshots || !instanceId || !chatId) { receiveRaw(event); return; }
    const turnId = "turn_id" in event && event.turn_id
      ? event.turn_id : client.getRunTurnId(chatId) ?? lastOwners.get(chatId) ?? `fixture-turn:${chatId}`;
    const ownerId = "active_turn_id" in event && event.active_turn_id ? event.active_turn_id : turnId;
    const current = snapshots.get(chatId)?.runs ?? [];
    const output = ["delta", "stream_end", "reasoning_delta", "tool_hint", "tool_event", "file_edit", "retry_status"].includes(event.event);
    const admission = (event.event === "goal_status" && event.status === "running")
      || ((event.event === "user_message" || event.event === "message_accepted")
        && (event.starts_turn === true || !!event.active_turn_id))
      || (event.event === "recovery_state" && event.status === "resuming")
      || (event.event === "attached" && event.recovery_state?.status === "resuming");
    if ((output || admission) && !ended.get(chatId)?.has(ownerId) && !client.isRunCompleted(chatId, ownerId)) {
      const startedAt = "started_at" in event && typeof event.started_at === "number"
        ? event.started_at : current.find((run) => run.turn_id === ownerId)?.started_at ?? null;
      const existing = current.find((run) => run.turn_id === ownerId);
      if (!existing || existing.started_at !== startedAt) {
        lastOwners.set(chatId, ownerId);
        updateRuns(chatId, [{ run_id: `run:${ownerId}`, turn_id: ownerId, phase: "running", started_at: startedAt }]);
      }
    }
    receiveRaw(event);
    const terminal = event.event === "turn_end"
      || (event.event === "goal_status" && event.status === "idle")
      || (event.event === "recovery_state" && (event.status === "awaiting_user" || event.status === "failed"))
      || (event.event === "error" && !!event.turn_id);
    if (!terminal) return;
    const active = snapshots.get(chatId)?.runs ?? [];
    const matching = active.filter((run) => !("turn_id" in event && event.turn_id) || run.turn_id === turnId);
    if (matching.length === 0) return;
    if (event.event === "turn_end" || event.event === "error") {
      const closed = ended.get(chatId) ?? new Set<string>();
      for (const run of matching) if (run.turn_id) closed.add(run.turn_id);
      ended.set(chatId, closed);
    }
    updateRuns(chatId, active.filter((run) => !matching.includes(run)));
  };
  client.connect();
  socket.open();
  return {
    client, receive, receiveRaw, updateRuns, sent,
    adoptSnapshot(chatId: string, value: unknown) {
      const snapshot = decodeRunSnapshot(value);
      if (snapshot) snapshots.set(chatId, snapshot);
    },
    setConnected(connected: boolean) {
      if (!connected) socket.close();
      else { client.connect(); socket.open(); }
    },
  };
}
