import { act, cleanup, render, renderHook } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useHostSessions } from "@/components/remote/useHostSessions";
import type { RemoteConnection, RemoteDirectory } from "@/lib/remote-instances";

const mocks = vi.hoisted(() => {
  const events = new Set<() => void>();
  const statuses = new Set<(status: string) => void>();
  const state = { capabilities: ["webui.state-events.v1"], status: "open" };
  const mutate = vi.fn();
  const client = {
    get status() { return state.status; },
    requestMutation: mutate,
    onStatus: vi.fn((handler: (status: string) => void) => {
      statuses.add(handler); handler(state.status);
      return () => { statuses.delete(handler); };
    }),
    onStateChange: vi.fn((_resource: string, handler: () => void) => {
      events.add(handler);
      return () => { events.delete(handler); };
    }),
  };
  return { client, state, events, statuses, mutate, read: vi.fn(), token: () => "synthetic-local-token" };
});
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({
  client: mocks.client, getToken: mocks.token, webuiCapabilities: mocks.state.capabilities,
}) }));
vi.mock("@/lib/remote-instances", async (original) => ({
  ...await original<typeof import("@/lib/remote-instances")>(), readRemoteInstances: mocks.read,
}));

const profile = { id: "3b968d52-081d-4898-9970-ff0a1fc93817", name: "Team", host: "ubuntu@example.test",
  port: 22, config_path: "~/.nanobot/config.json", ssh_config: "", identity_file: "", runtime_user: "",
  connected: true, gateway_id: "remote-one", view_id: "local-lifetime" };
const connection: RemoteConnection = { ...profile, hostname: "team-host",
  url: "http://127.0.0.1:23456/#/?bootstrapSecret=synthetic-capability" };
const directory: RemoteDirectory = { available: true, profiles: [profile] };
const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
const invalidate = () => { for (const handler of mocks.events) handler(); };
const status = (value: string) => {
  mocks.state.status = value;
  for (const handler of mocks.statuses) handler(value);
};

beforeEach(() => {
  window.sessionStorage.clear(); window.localStorage.clear();
  mocks.events.clear(); mocks.statuses.clear();
  mocks.state.capabilities = ["webui.state-events.v1"]; mocks.state.status = "open";
  mocks.client.onStatus.mockClear(); mocks.client.onStateChange.mockClear();
  mocks.mutate.mockReset().mockResolvedValue(connection);
  mocks.read.mockReset().mockResolvedValue(directory);
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.restoreAllMocks();
  if (originalVisibility) Object.defineProperty(document, "visibilityState", originalVisibility);
  else Reflect.deleteProperty(document, "visibilityState");
});

async function openFrame(result: { current: ReturnType<typeof useHostSessions> }) {
  let opening!: Promise<void>;
  await act(async () => { opening = result.current.connect(profile.id); });
  act(() => result.current.loaded(profile.id));
  await act(async () => { await opening; });
}

describe("remote directory state refresh", () => {
  it("uses one confirmed backend change to cover a frame, preserving identity and explicit reconnect ownership", async () => {
    const { result } = renderHook(() => useHostSessions());
    await act(async () => {});
    await openFrame(result);
    const url = result.current.frames[0].connection.url;
    mocks.read.mockClear().mockResolvedValue({ available: true, profiles: [{ ...profile,
      connected: false, connection_error: "remote_unreachable" }] });
    await act(async () => invalidate());
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(result.current.frames[0]).toMatchObject({ offline: true, error: "remote_unreachable", failures: 2 });
    expect(result.current.frames[0].connection.url).toBe(url);
    expect(result.current.selected?.id).toBe(profile.id);
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    expect(mocks.client.onStateChange).toHaveBeenCalledWith("remote_instances", expect.any(Function));
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, name: "Renamed in another tab" }] });
    await act(async () => invalidate());
    expect(result.current.frames[0]).toMatchObject({ offline: false, connection: { name: "Renamed in another tab", url } });
    expect(result.current.selected?.name).toBe("Renamed in another tab");
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
  });

  it("covers a cold view from the only offline event received while its load is pending", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useHostSessions());
    await act(async () => {});
    let opening!: Promise<void>;
    await act(async () => { opening = result.current.connect(profile.id); });
    const frame = result.current.frames[0];
    expect(result.current.pending?.id).toBe(profile.id);
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile,
      connected: false, connection_error: "remote_unreachable" }] });
    await act(async () => invalidate());
    expect(frame.offline).toBe(false);
    await act(async () => { result.current.loaded(profile.id); await opening; });
    expect(result.current.pending).toBeNull();
    expect(result.current.frames[0]).toBe(frame);
    expect(frame).toMatchObject({ loaded: true, offline: true, error: "remote_unreachable" });
    expect(frame.connection).toEqual(connection);
    expect(result.current.selected?.id).toBe(profile.id);
    const reads = mocks.read.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).toHaveBeenCalledTimes(reads);
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
  });

  it.each(["before", "after"])("ignores a pre-connect health read that finishes %s the connect acknowledgement", async (timing) => {
    const offline = { available: true, profiles: [{ ...profile, connected: false }] };
    mocks.read.mockResolvedValueOnce(offline);
    const { result } = renderHook(() => useHostSessions());
    await act(async () => {});
    let finishConnect!: (next: RemoteConnection) => void;
    mocks.mutate.mockImplementationOnce(() => new Promise<RemoteConnection>((resolve) => { finishConnect = resolve; }));
    let opening!: Promise<void>;
    await act(async () => { opening = result.current.connect(profile.id); });
    let finishStale!: (next: RemoteDirectory) => void;
    let finishFresh!: (next: RemoteDirectory) => void;
    mocks.read.mockImplementationOnce(() => new Promise<RemoteDirectory>((resolve) => { finishStale = resolve; }))
      .mockImplementationOnce(() => new Promise<RemoteDirectory>((resolve) => { finishFresh = resolve; }));
    act(() => invalidate());
    if (timing === "before") await act(async () => finishStale(offline));
    await act(async () => finishConnect(connection));
    const frame = result.current.frames[0];
    await act(async () => { result.current.loaded(profile.id); await opening; });
    if (timing === "after") await act(async () => finishStale(offline));
    expect(result.current.pending).toBeNull();
    expect(frame).toMatchObject({ loaded: true, offline: false, failures: 0 });
    await act(async () => finishFresh(directory));
    expect(result.current.frames[0]).toBe(frame);
    expect(frame.connection).toEqual(connection);
    expect(frame.offline).toBe(false);
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
  });

  it("does not poll supported hosts and fills hidden-return and reconnect snapshots without reconnecting SSH", async () => {
    vi.useFakeTimers();
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result, unmount } = renderHook(() => useHostSessions());
    await act(async () => {});
    await openFrame(result);
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).not.toHaveBeenCalled();
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await act(async () => {
      invalidate(); window.dispatchEvent(new Event("online")); window.dispatchEvent(new Event("pageshow"));
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(mocks.read).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(mocks.read).toHaveBeenCalledTimes(1);
    await act(async () => { status("reconnecting"); status("open"); });
    expect(mocks.read).toHaveBeenCalledTimes(2);
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    unmount(); mocks.read.mockClear();
    await act(async () => { invalidate(); status("open"); window.dispatchEvent(new Event("online")); });
    expect(mocks.read).not.toHaveBeenCalled();
    expect(mocks.events.size).toBe(0);
  });

  it("coalesces notifications during a directory read and replays the final snapshot", async () => {
    let finish!: (next: RemoteDirectory) => void;
    mocks.read.mockImplementationOnce(() => new Promise<RemoteDirectory>((resolve) => { finish = resolve; }));
    const { result } = renderHook(() => useHostSessions());
    act(() => { invalidate(); invalidate(); invalidate(); });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, name: "Latest name" }] });
    await act(async () => finish(directory));
    expect(mocks.read).toHaveBeenCalledTimes(2);
    expect(result.current.directory?.profiles[0].name).toBe("Latest name");
    expect(mocks.mutate).not.toHaveBeenCalled();
  });

  it("does not let a hidden read swallow the visible-return refresh", async () => {
    let finish!: (next: RemoteDirectory) => void;
    mocks.read.mockImplementationOnce(() => new Promise<RemoteDirectory>((resolve) => { finish = resolve; }));
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result } = renderHook(() => useHostSessions());
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    visibility.mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    mocks.read.mockResolvedValue({ available: true, profiles: [{ ...profile, name: "Visible snapshot" }] });
    await act(async () => finish(directory));
    expect(mocks.read).toHaveBeenCalledTimes(2);
    expect(result.current.directory?.profiles[0].name).toBe("Visible snapshot");
  });

  it("aborts an in-flight hidden read and resumes with the current visibility signal", async () => {
    const signals: AbortSignal[] = [];
    let finish!: (next: RemoteDirectory) => void;
    mocks.read.mockImplementation((_token: string, signal: AbortSignal) => {
      signals.push(signal);
      return new Promise<RemoteDirectory>((resolve, reject) => {
        finish = resolve;
        signal.addEventListener("abort", () => reject(new DOMException("Hidden", "AbortError")), { once: true });
      });
    });
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result } = renderHook(() => useHostSessions());
    expect(signals).toHaveLength(1);
    visibility.mockReturnValue("hidden");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(signals[0].aborted).toBe(true);
    expect(result.current.directoryError).toBe(false);
    visibility.mockReturnValue("visible");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(signals).toHaveLength(2);
    expect(signals[1].aborted).toBe(false);
    await act(async () => finish(directory));
    expect(result.current.directory).toEqual(directory);
  });

  it.each(["visible", "hidden"] as const)("scopes a child-initiated directory read to its %s mount lifecycle", async (initialVisibility) => {
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue(initialVisibility);
    const signals: AbortSignal[] = [];
    mocks.read.mockImplementation((_token: string, signal: AbortSignal) => {
      signals.push(signal);
      return new Promise<RemoteDirectory>((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("Hidden", "AbortError")), { once: true });
      });
    });
    function DirectoryPage({ refresh }: { refresh: () => Promise<RemoteDirectory> }) {
      useEffect(() => { void refresh().catch(() => {}); }, [refresh]);
      return null;
    }
    function Shell() {
      const hosts = useHostSessions();
      return <DirectoryPage refresh={hosts.refresh} />;
    }
    render(<Shell />);
    if (initialVisibility === "hidden") {
      expect(mocks.read).not.toHaveBeenCalled();
      visibility.mockReturnValue("visible");
      await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    }
    expect(signals).toHaveLength(1);
    visibility.mockReturnValue("hidden");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(signals[0].aborted).toBe(true);
    expect(mocks.read).toHaveBeenCalledTimes(1);
  });

  it("forwards cancellation through the actual remote HTTP read", async () => {
    const { readRemoteInstances } = await vi.importActual<typeof import("@/lib/remote-instances")>("@/lib/remote-instances");
    let requestSignal: AbortSignal | null | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      requestSignal = init?.signal;
      return new Promise<Response>((_resolve, reject) => {
        requestSignal?.addEventListener("abort", () => reject(new DOMException("Hidden", "AbortError")), { once: true });
      });
    });
    const controller = new AbortController();
    const request = readRemoteInstances("synthetic-local-token", controller.signal);
    const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await rejected;
    expect(requestSignal?.aborted).toBe(true);
  });

  it("keeps visible legacy sampling and its browser debounce while stopping hidden reads", async () => {
    vi.useFakeTimers(); mocks.state.capabilities = [];
    const visibility = vi.spyOn(document, "visibilityState", "get");
    const { result } = renderHook(() => useHostSessions());
    await act(async () => {});
    await openFrame(result);
    mocks.read.mockClear().mockResolvedValue({ available: true, profiles: [{ ...profile,
      connected: false, connection_error: "remote_unreachable" }] });
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(result.current.frames[0].offline).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.frames[0].offline).toBe(true);
    expect(mocks.client.onStateChange).not.toHaveBeenCalled();
    visibility.mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    mocks.read.mockClear();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(mocks.read).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible"); mocks.read.mockResolvedValue(directory);
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(result.current.frames[0].offline).toBe(false);
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
  });
});
