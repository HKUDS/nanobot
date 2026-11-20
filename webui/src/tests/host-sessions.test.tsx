import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useHostSessions, MAX_HOST_VIEWS } from "@/components/remote/useHostSessions";
import type { RemoteConnection } from "@/lib/remote-instances";

const mocks = vi.hoisted(() => ({ read: vi.fn(), request: vi.fn(), token: () => "token",
  client: { requestMutation: (...args: unknown[]) => mocks.request(...args), onStatus: () => () => {} } }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: mocks.client, getToken: mocks.token }) }));
vi.mock("@/lib/remote-instances", async (original) => ({
  ...await original<typeof import("@/lib/remote-instances")>(), readRemoteInstances: mocks.read,
}));
const ids = Array.from({ length: 4 }, (_, i) => `3b968d52-081d-4898-9970-ff0a1fc9381${i}`);
const connections: RemoteConnection[] = ids.map((id, i) => ({ id, name: `Server ${i}`, host: `host-${i}`, hostname: `host-${i}`,
  config_path: "/home/test/.nanobot/config.json", gateway_id: `gateway-${i}`, url: `http://127.0.0.1:${24000 + i}/#/?bootstrapSecret=secret` }));
const directory = { available: true, profiles: connections.map((item) => ({ ...item, connected: true })) };
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
type Session = ReturnType<typeof useHostSessions>;
async function start(result: { current: Session }, index: number) {
  let completion!: Promise<void>;
  await act(async () => { completion = result.current.connect(ids[index]); });
  return { completion };
}
async function ready(result: { current: Session }, index: number) {
  const { completion } = await start(result, index);
  await act(async () => { result.current.loaded(ids[index]); await completion; });
}

beforeEach(() => {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  vi.useFakeTimers();
  window.sessionStorage.clear();
  mocks.read.mockReset().mockResolvedValue(directory);
  mocks.request.mockReset().mockImplementation(async (action: string, payload: { id: string }) =>
    action === "remote.connect" ? connections.find((item) => item.id === payload.id) : {
      ...directory, profiles: directory.profiles.map((profile) =>
        profile.id === payload.id ? { ...profile, connected: false } : profile),
    });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("host session lifecycle", () => {
  it("does not probe retained remote views while local or hidden, and rechecks on return", async () => {
    let visibility: DocumentVisibilityState = "visible";
    vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    act(() => result.current.local());
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).not.toHaveBeenCalled();
    await act(async () => { await result.current.connect(ids[0]); });
    expect(mocks.read.mock.calls.some(([, targets]) => targets?.includes(ids[0]))).toBe(true);
    act(() => { visibility = "hidden"; document.dispatchEvent(new Event("visibilitychange")); });
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).not.toHaveBeenCalled();
    await act(async () => { visibility = "visible"; document.dispatchEvent(new Event("visibilitychange")); });
    expect(mocks.read.mock.calls.some(([, targets]) => targets?.includes(ids[0]))).toBe(true);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(1);
    expect(result.current.frames).toHaveLength(1);
  });

  it("only probes the selected host, not every retained view", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    await ready(result, 1);
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read).toHaveBeenCalledWith("token", [ids[1]]);
    expect(mocks.read.mock.calls.every(([, targets]) => !targets?.includes(ids[0]))).toBe(true);
  });
  it("checks existing connections only while the local directory is observed", async () => {
    mocks.read.mockResolvedValue({ ...directory, profiles: [
      directory.profiles[0], { ...directory.profiles[1], connected: false, connection_error: "remote_unreachable" },
      { ...directory.profiles[2], connected: false, connection_error: "pair_authorization_rejected" },
      { ...directory.profiles[3], connected: false, gateway_id: undefined },
    ] });
    const { result } = renderHook(useHostSessions);
    await act(async () => {});
    let stop!: () => void;
    await act(async () => { stop = result.current.watchDirectory(); });
    expect(mocks.read).toHaveBeenCalledWith("token", ids.slice(0, 3));
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read.mock.calls).toEqual([["token", ids.slice(0, 3)]]);
    act(stop);
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.request).not.toHaveBeenCalled();
  });

  it("discovers connections and then updates the directory through targeted polls", async () => {
    mocks.read.mockResolvedValue({ ...directory, profiles: [] });
    const { result } = renderHook(useHostSessions);
    await act(async () => {});
    await act(async () => { result.current.watchDirectory(); });
    mocks.read.mockResolvedValue({ ...directory, profiles: [directory.profiles[0]] });
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read.mock.calls).toEqual([["token", []], ["token", [ids[0]]]]);
    mocks.read.mockResolvedValue({ ...directory, profiles: directory.profiles.slice(0, 2) });
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read.mock.calls).toEqual([["token", [ids[0]]]]);
    expect(result.current.directory?.profiles).toHaveLength(2);
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read.mock.calls).toEqual([["token", ids.slice(0, 2)]]);
  });

  it("keeps checking an observed host after a setup error and notices its recovery", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    mocks.read.mockResolvedValue({ ...directory, profiles: directory.profiles.map((p) =>
      p.id === ids[0] ? { ...p, connected: false, connection_error: "remote_auth_failed", health_check: 1 } : p) });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.frames[0].offline).toBe(true);
    mocks.read.mockResolvedValue(directory);
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read.mock.calls).toEqual([["token", [ids[0]]]]);
    expect(result.current.frames[0].offline).toBe(false);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(1);
  });

  it("counts distinct failed probes rather than repeated reads of a cached failure", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    let revision = 41;
    let connected = false;
    mocks.read.mockImplementation(async () => ({ ...directory, profiles: directory.profiles.map((p) =>
      p.id === ids[0] ? { ...p, connected, health_check: revision, connection_error: connected ? "" : "remote_unreachable" } : p) }));
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.frames[0].failures).toBe(1);
    await act(async () => { await result.current.refresh(); await result.current.refresh(); });
    expect(result.current.frames[0].failures).toBe(1);
    expect(result.current.frames[0].offline).toBe(false);
    revision += 1;
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.frames[0].offline).toBe(true);
    connected = true; revision += 1;
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.frames[0].offline).toBe(false);
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(1);
  });

  it("does not start a queued probe after its observer leaves", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    const slow = deferred<typeof directory>();
    mocks.read.mockReturnValueOnce(slow.promise);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    let stop!: () => void;
    await act(async () => { stop = result.current.watchDirectory(); });
    act(() => { stop(); result.current.local(); });
    mocks.read.mockClear();
    await act(async () => { slow.resolve(directory); await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).not.toHaveBeenCalled();
    expect(result.current.frames).toHaveLength(1);
  });

  it("rechecks a queued wake immediately even when the old request fails", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    const slow = deferred<typeof directory>();
    mocks.read.mockReturnValueOnce(slow.promise);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    act(() => { window.dispatchEvent(new Event("online")); window.dispatchEvent(new Event("pageshow")); });
    mocks.read.mockClear();
    await act(async () => { slow.reject(new Error("directory_unavailable")); });
    expect(mocks.read.mock.calls.filter(([, targets]) => targets?.length)).toEqual([["token", [ids[0]]]]);
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(result.current.frames[0].offline).toBe(false);
  });

  it("can cancel a warm view's revalidation without activating it", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    act(() => result.current.local());
    const slow = deferred<typeof directory>();
    mocks.read.mockReturnValueOnce(slow.promise);
    const { completion } = await start(result, 0);
    expect(result.current.pending?.id).toBe(ids[0]);
    act(() => result.current.cancel());
    await act(async () => { slow.resolve(directory); await completion; });
    expect(result.current.selected).toBeNull();
    expect(result.current.frames).toHaveLength(1);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(1);
  });

  it("does not reuse a retained view when revalidation finds a different gateway", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    act(() => result.current.local());
    mocks.read.mockResolvedValue({ ...directory, profiles: directory.profiles.map((p) =>
      p.id === ids[0] ? { ...p, gateway_id: "another-gateway" } : p) });
    mocks.request.mockRejectedValueOnce(new Error("instance_changed"));
    await act(async () => { await expect(result.current.connect(ids[0])).rejects.toThrow("instance_changed"); });
    expect(result.current.selected).toBeNull();
    expect(result.current.frames[0].offline).toBe(true);
    expect(result.current.frames[0].connection.gateway_id).toBe("gateway-0");
  });

  it("reveals only a loaded live view for notifications, without connecting", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    await ready(result, 1);
    mocks.request.mockClear();
    act(() => { expect(result.current.reveal(ids[0])).toBe(true); });
    expect(result.current.selected?.id).toBe(ids[0]);
    act(() => { expect(result.current.reveal(ids[3])).toBe(false); });
    let check = 0;
    mocks.read.mockImplementation(async () => ({ ...directory, profiles: directory.profiles.map((p) => ({ ...p, connected: false, health_check: ++check })) }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    act(() => { expect(result.current.reveal(ids[0])).toBe(false); });
    expect(mocks.request).not.toHaveBeenCalled();
  });
  it("clears a failed reconnect only after that host's loaded view recovers", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    mocks.read.mockResolvedValue({ ...directory, profiles: directory.profiles.map((p) => ({ ...p, connected: false })) });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    mocks.request.mockRejectedValueOnce(new Error("ssh_unreachable"));
    await act(async () => { await expect(result.current.connect(ids[0])).rejects.toThrow("ssh_unreachable"); });
    expect(result.current.error).toBe("ssh_unreachable");
    mocks.read.mockResolvedValue(directory);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.frames[0].offline).toBe(false);
    expect(result.current.error).toBe("");
  });

  it("does not clear a failed destination because the active host is healthy", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    mocks.request.mockRejectedValueOnce(new Error("ssh_unreachable"));
    await act(async () => { await expect(result.current.connect(ids[1])).rejects.toThrow("ssh_unreachable"); });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.error).toBe("ssh_unreachable");
    expect(result.current.selected?.id).toBe(ids[0]);
  });

  it("ignores a stale health failure that arrives after reconnect succeeds", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    let revision = 0;
    mocks.read.mockImplementation(async () => ({ ...directory, profiles: directory.profiles.map((p) =>
      ({ ...p, connected: false, connection_error: "remote_unreachable", health_check: ++revision })) }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(result.current.frames[0].offline).toBe(true);
    const stale = deferred<typeof directory>();
    mocks.read.mockReturnValueOnce(stale.promise);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    mocks.read.mockResolvedValue(directory);
    await act(async () => { await result.current.connect(ids[0]); });
    await act(async () => { stale.resolve({ ...directory, profiles: [] }); });
    expect(result.current.frames[0].failures).toBe(0);
    expect(result.current.directory?.profiles).toHaveLength(4);
  });

  it("keeps an old gateway view offline when another tab connects a new gateway", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    mocks.read.mockResolvedValue({ ...directory, profiles: directory.profiles.map((p) =>
      p.id === ids[0] ? { ...p, gateway_id: "restarted-gateway" } : p) });
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(mocks.read.mock.calls).toEqual([["token", [ids[0]]], ["token", [ids[0]]]]);
    expect(result.current.frames[0].offline).toBe(true);
    expect(result.current.selected?.id).toBe(ids[0]);
  });

  it("does not revive an old proxy view after the local gateway restarts", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    mocks.read.mockResolvedValue({ ...directory, profiles: directory.profiles.map((p) =>
      p.id === ids[0] ? { ...p, view_id: "new-local-proxy-session" } : p) });
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(result.current.frames[0].offline).toBe(true);
    expect(result.current.frames[0].error).toBe("instance_changed");
  });

  it("uses the disconnect result without a second directory read", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    const reads = mocks.read.mock.calls.length;
    mocks.read.mockRejectedValue(new Error("directory_unavailable"));
    await act(async () => { await expect(result.current.disconnect(ids[0])).resolves.toBeUndefined(); });
    expect(result.current.selected).toBeNull();
    expect(result.current.frames).toHaveLength(0);
    expect(result.current.directory?.profiles.find((profile) => profile.id === ids[0])?.connected).toBe(false);
    expect(mocks.read).toHaveBeenCalledTimes(reads);
    expect(result.current.directoryError).toBe(false);
  });

  it("keeps the current host until the destination view loads, then switches warm without RPC", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    const { completion } = await start(result, 1);
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(result.current.pending?.id).toBe(ids[1]);
    await act(async () => { result.current.loaded(ids[1]); await completion; });
    expect(result.current.selected?.id).toBe(ids[1]);
    await act(async () => { await result.current.connect(ids[0]); });
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(mocks.request.mock.calls.filter(([action]) => action === "remote.connect")).toHaveLength(2);
  });

  it("retains views and shared tunnels when switching local, including after a long idle", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    const frame = result.current.frames[0];
    act(() => result.current.local());
    await act(async () => { await vi.advanceTimersByTimeAsync(15 * 60_000); });
    expect(result.current.selected).toBeNull();
    expect(result.current.frames[0]).toBe(frame);
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
    await act(async () => { await result.current.connect(ids[0]); });
    expect(result.current.selected?.id).toBe(ids[0]);
  });

  it("a failed destination leaves the active host usable", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    mocks.request.mockRejectedValueOnce(new Error("ssh_unreachable"));
    await act(async () => { await expect(result.current.connect(ids[1])).rejects.toThrow("ssh_unreachable"); });
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(result.current.frames[0].offline).toBe(false);
    expect(result.current.pending).toBeNull();
  });

  it("the latest choice wins even when an earlier SSH request finishes later", async () => {
    const { result } = renderHook(useHostSessions);
    const slow = deferred<RemoteConnection>();
    mocks.request.mockReturnValueOnce(slow.promise);
    const first = await start(result, 0);
    await ready(result, 1);
    await act(async () => { slow.resolve(connections[0]); await first.completion; });
    expect(result.current.selected?.id).toBe(ids[1]);
    expect(result.current.frames).toHaveLength(1);
    expect(mocks.request.mock.calls.some(([action]) => action === "remote.disconnect")).toBe(false);
  });

  it("cancelling SSH suppresses late errors and never activates a host", async () => {
    const { result } = renderHook(useHostSessions);
    const slow = deferred<RemoteConnection>();
    mocks.request.mockReturnValueOnce(slow.promise);
    const first = await start(result, 0);
    act(() => result.current.cancel());
    await act(async () => { slow.reject(new Error("ssh_unreachable")); await first.completion; });
    expect(result.current.selected).toBeNull();
    expect(result.current.pending).toBeNull();
    expect(result.current.error).toBe("");
  });

  it("cancelling page load releases an unused view slot and ignores a late load event", async () => {
    const { result } = renderHook(useHostSessions);
    const first = await start(result, 0);
    await act(async () => { result.current.cancel(); await first.completion; });
    act(() => result.current.loaded(ids[0]));
    expect(result.current.selected).toBeNull();
    expect(result.current.frames).toHaveLength(0);
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(mocks.read).not.toHaveBeenCalled();
  });

  it("a timed-out cold page leaves the old host intact and can be retried", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    const { completion } = await start(result, 1);
    const rejected = expect(completion).rejects.toThrow("view_load_failed");
    await act(async () => { await vi.advanceTimersByTimeAsync(59_999); });
    expect(result.current.pending?.id).toBe(ids[1]);
    expect(result.current.selected?.id).toBe(ids[0]);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); await rejected; });
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(result.current.frames).toHaveLength(1);
    await ready(result, 1);
    expect(result.current.selected?.id).toBe(ids[1]);
  });

  it("a newer request for the same host is not removed by the previous cancelled load", async () => {
    const { result } = renderHook(useHostSessions);
    const first = await start(result, 0);
    const second = await start(result, 0);
    await act(async () => { result.current.loaded(ids[0]); await Promise.all([first.completion, second.completion]); });
    expect(result.current.selected?.id).toBe(ids[0]);
    expect(result.current.frames).toHaveLength(1);
  });

  it("bounds view memory without silently discarding user drafts", async () => {
    const { result } = renderHook(useHostSessions);
    for (let i = 0; i < MAX_HOST_VIEWS; i++) await ready(result, i);
    await act(async () => { await expect(result.current.connect(ids[3])).rejects.toThrow("view_limit"); });
    expect(result.current.frames.map((item) => item.connection.id)).toEqual(ids.slice(0, 3));
    expect(result.current.selected?.id).toBe(ids[2]);
    await act(async () => { await result.current.disconnect(ids[0]); });
    expect(result.current.frames).toHaveLength(2);
    await ready(result, 3);
    expect(result.current.selected?.id).toBe(ids[3]);
  });

  it("releases an unfinished view when a same-host retry fails", async () => {
    const { result } = renderHook(useHostSessions);
    const first = await start(result, 0);
    mocks.request.mockRejectedValueOnce(new Error("ssh_unreachable"));
    await act(async () => {
      await expect(result.current.connect(ids[0])).rejects.toThrow("ssh_unreachable");
      await first.completion;
    });
    expect(result.current.frames).toHaveLength(0);
    expect(result.current.selected).toBeNull();
  });

  it("explicit disconnect closes that view, but never stops the remote bot", async () => {
    const { result } = renderHook(useHostSessions);
    await ready(result, 0);
    await ready(result, 1);
    await act(async () => { await result.current.disconnect(ids[1]); });
    expect(result.current.selected).toBeNull();
    expect(result.current.frames.map((item) => item.connection.id)).toEqual([ids[0]]);
    expect(mocks.request).toHaveBeenCalledWith("remote.disconnect", { id: ids[1] }, 65_000);
    expect(mocks.request.mock.calls.some(([action]) => action.includes("stop"))).toBe(false);
  });
});
