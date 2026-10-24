import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePairingRefresh } from "@/hooks/usePairingRefresh";
import { NanobotClient } from "@/lib/nanobot-client";

const source = vi.hoisted(() => ({ client: null as NanobotClient | null, getToken: () => "tok" }));
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: source.client, getToken: source.getToken }),
}));

class PairingSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send() {}
  open() { this.readyState = 1; this.onopen?.(); }
  close() { this.readyState = 3; this.onclose?.(); }
  pairingChanged() { this.onmessage?.({ data: JSON.stringify({ event: "pairing_changed" }) } as MessageEvent); }
}

const sockets: PairingSocket[] = [];
const deliveredRequest = { code: "ABCD-EFGH", channel: "feishu", sender_id: "alice", delivery_status: "sent" };
const response = (requests: unknown[]) => ({ ok: true, json: async () => ({ requests }) }) as Response;

function visibility(value: DocumentVisibilityState) {
  act(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

let visibilityDescriptor: PropertyDescriptor | undefined;
beforeEach(() => {
  vi.useFakeTimers();
  visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
  visibility("visible");
  sockets.length = 0;
  source.client = new NanobotClient({ url: "ws://pairing-test", socketFactory: () => {
    const socket = new PairingSocket();
    sockets.push(socket);
    return socket as unknown as WebSocket;
  } });
  source.client.connect();
  sockets[0].open();
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([])));
});
afterEach(() => {
  cleanup();
  source.client?.close();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  if (visibilityDescriptor) Object.defineProperty(document, "visibilityState", visibilityDescriptor);
  else Reflect.deleteProperty(document, "visibilityState");
});

describe("pairing refresh", () => {
  it("reads immediately when a real client event arrives 1s after an empty initial snapshot", async () => {
    const snapshot = vi.fn();
    const { unmount } = renderHook(() => usePairingRefresh(snapshot));
    await act(async () => {});
    expect(snapshot).toHaveBeenCalledWith([]);
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    vi.mocked(fetch).mockResolvedValue(response([deliveredRequest]));
    await act(async () => { sockets[0].pairingChanged(); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(snapshot).toHaveBeenLastCalledWith([deliveredRequest]);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(2);
    unmount();
    sockets[0].pairingChanged();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("subscribes before reading and coalesces changes during a pending body into one serial follow-up", async () => {
    const subscribed = vi.spyOn(source.client!, "onPairingChange");
    let finish!: (value: unknown) => void;
    vi.mocked(fetch).mockImplementationOnce(async () => {
      expect(subscribed).toHaveBeenCalledTimes(1);
      return { ok: true, json: () => new Promise((resolve) => { finish = resolve; }) } as Response;
    }).mockResolvedValue(response([deliveredRequest]));
    const snapshot = vi.fn();
    renderHook(() => usePairingRefresh(snapshot));
    await act(async () => {});
    act(() => { sockets[0].pairingChanged(); sockets[0].pairingChanged(); sockets[0].pairingChanged(); });
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ requests: [] }); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(snapshot.mock.calls).toEqual([[[]], [[deliveredRequest]]]);
  });

  it("cancels hidden reads, settles awaiting callers and isolates their late bodies after visible return", async () => {
    let finishRetired!: (value: unknown) => void;
    const signals: AbortSignal[] = [];
    vi.mocked(fetch).mockImplementation(async (_input, init) => {
      signals.push(init!.signal!);
      return signals.length === 1
        ? { ok: true, json: () => new Promise((resolve, reject) => {
          finishRetired = resolve;
          init!.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
        }) } as Response
        : response([deliveredRequest]);
    });
    const snapshot = vi.fn();
    const { result, unmount } = renderHook(() => usePairingRefresh(snapshot));
    await act(async () => {});
    const refresh = result.current;
    const cancelled = expect(refresh()).rejects.toMatchObject({ name: "AbortError" });
    visibility("hidden");
    await act(async () => { await cancelled; });
    expect(signals[0].aborted).toBe(true);
    sockets[0].pairingChanged();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(1);
    visibility("visible");
    await act(async () => {});
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(snapshot).toHaveBeenCalledTimes(1);
    expect(snapshot).toHaveBeenLastCalledWith([deliveredRequest]);
    await act(async () => { finishRetired({ requests: [] }); });
    expect(snapshot).toHaveBeenCalledTimes(1);
    unmount();
    expect(signals[1].aborted).toBe(false); // Its successful body already released the transport listener.
    await act(async () => { await refresh(); sockets[0].pairingChanged(); });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("aborts an unfinished body on unmount and never publishes its eventual snapshot", async () => {
    let finish!: (value: unknown) => void;
    let signal!: AbortSignal;
    vi.mocked(fetch).mockImplementation(async (_input, init) => {
      signal = init!.signal!;
      return { ok: true, json: () => new Promise((resolve, reject) => {
        finish = resolve;
        signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      }) } as Response;
    });
    const snapshot = vi.fn();
    const { result, unmount } = renderHook(() => usePairingRefresh(snapshot));
    await act(async () => {});
    const cancelled = expect(result.current()).rejects.toMatchObject({ name: "AbortError" });
    unmount();
    await cancelled;
    expect(signal.aborted).toBe(true);
    await act(async () => { finish({ requests: [deliveredRequest] }); sockets[0].pairingChanged(); });
    expect(snapshot).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("refreshes on WebSocket reconnect and focus without remounting its consumer", async () => {
    const snapshot = vi.fn();
    renderHook(() => usePairingRefresh(snapshot));
    await act(async () => {});
    act(() => { sockets[0].close(); });
    expect(source.client!.status).toBe("reconnecting");
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(sockets).toHaveLength(2);
    vi.mocked(fetch).mockResolvedValue(response([deliveredRequest]));
    await act(async () => { sockets[1].open(); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(snapshot).toHaveBeenLastCalledWith([deliveredRequest]);
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("releases the serial reader after a body deadline so a bounded retry can recover", async () => {
    vi.mocked(fetch).mockImplementationOnce(async (_input, init) => ({ ok: true,
      json: () => new Promise((_resolve, reject) => {
        init!.signal!.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      }),
    }) as Response).mockResolvedValue(response([deliveredRequest]));
    const snapshot = vi.fn();
    renderHook(() => usePairingRefresh(snapshot));
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(snapshot).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(snapshot).toHaveBeenLastCalledWith([deliveredRequest]);
  });

  it("bounds error retries, recovers on a later notice and clears scheduled retries on unmount", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("offline"));
    const snapshot = vi.fn();
    const { unmount } = renderHook(() => usePairingRefresh(snapshot));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(4);
    expect(snapshot).not.toHaveBeenCalled();
    vi.mocked(fetch).mockResolvedValue(response([deliveredRequest]));
    await act(async () => { sockets[0].pairingChanged(); });
    expect(fetch).toHaveBeenCalledTimes(5);
    expect(snapshot).toHaveBeenLastCalledWith([deliveredRequest]);
    vi.mocked(fetch).mockRejectedValue(new Error("offline again"));
    await act(async () => { sockets[0].pairingChanged(); });
    expect(fetch).toHaveBeenCalledTimes(6);
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetch).toHaveBeenCalledTimes(6);
  });
});
