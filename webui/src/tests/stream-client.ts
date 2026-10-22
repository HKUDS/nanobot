import { NanobotClient } from "@/lib/nanobot-client";
import { decodeRunSnapshot, type ServerRun, type ServerRunSnapshot } from "@/lib/server-run-state";

/** Explicit wire fixture: output and lifecycle frames never manufacture execution state. */
export function createStreamClient({ instanceId = "fixture-host" }: { instanceId?: string | null } = {}) {
  const snapshots = new Map<string, ServerRunSnapshot>();
  const receive = (event: unknown) => {
    socket.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  };
  const updateRuns = (chatId: string, runs: ServerRun[]) => {
    const value: ServerRunSnapshot = {
      instance_id: instanceId ?? "unsupported", revision: (snapshots.get(chatId)?.revision ?? 0) + 1, runs,
    };
    snapshots.set(chatId, value);
    receive({ event: "run_state", chat_id: chatId, run_state: value });
    return value;
  };
  const socket = {
    readyState: 0,
    onopen: null as (() => void) | null,
    onmessage: null as ((event: MessageEvent) => void) | null,
    onclose: null as (() => void) | null,
    onerror: null as (() => void) | null,
    send(serialized: string) {
      const frame = JSON.parse(serialized) as Record<string, unknown>;
      if (frame.type === "webui_request" && frame.action === "runs.stop") {
        receive({ event: "webui_response", request_id: frame.request_id, ok: true, result: {} });
      }
    },
    close() { socket.readyState = 3; socket.onclose?.(); },
    open() {
      socket.readyState = 1;
      socket.onopen?.();
      receive({ event: "ready", chat_id: "default", client_id: "fixture-browser",
        ...(instanceId ? { run_state_instance_id: instanceId } : {}),
      });
    },
  };
  const client = new NanobotClient({
    url: "ws://test", reconnect: false,
    socketFactory: () => socket as unknown as WebSocket,
  });
  client.connect();
  socket.open();
  return {
    client, receive, updateRuns,
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
