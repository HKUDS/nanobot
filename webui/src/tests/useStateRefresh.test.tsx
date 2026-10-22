import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useStateRefresh } from "@/hooks/useStateRefresh";
import type { ConnectionStatus, WebUIStateResource } from "@/lib/types";

const source = vi.hoisted(() => {
  const handlers = new Map<string, Set<() => void>>();
  const statuses = new Set<(status: ConnectionStatus) => void>();
  const client = {
    status: "open" as ConnectionStatus,
    onStateChange(resource: string, callback: () => void) {
      const subscribers = handlers.get(resource) ?? new Set();
      handlers.set(resource, subscribers);
      subscribers.add(callback);
      return () => { subscribers.delete(callback); };
    },
    onStatus(callback: (status: ConnectionStatus) => void) {
      statuses.add(callback);
      callback(client.status);
      return () => { statuses.delete(callback); };
    },
  };
  return { client, handlers, statuses, capabilities: ["webui.state-events.v1"] };
});
vi.mock("@/providers/ClientProvider", () => ({
  useClient: () => ({ client: source.client, webuiCapabilities: source.capabilities }),
}));

function invalidate(resource: WebUIStateResource) {
  act(() => { for (const callback of source.handlers.get(resource) ?? []) callback(); });
}
function status(value: ConnectionStatus) {
  act(() => {
    source.client.status = value;
    for (const callback of source.statuses) callback(value);
  });
}
function visibility(value: DocumentVisibilityState) {
  act(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value });
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

let visibilityDescriptor: PropertyDescriptor | undefined;
beforeEach(() => {
  vi.useFakeTimers();
  source.handlers.clear();
  source.statuses.clear();
  source.client.status = "open";
  source.capabilities = ["webui.state-events.v1"];
  visibilityDescriptor = Object.getOwnPropertyDescriptor(document, "visibilityState");
  visibility("visible");
});
afterEach(() => {
  vi.useRealTimers();
  if (visibilityDescriptor) Object.defineProperty(document, "visibilityState", visibilityDescriptor);
  else Reflect.deleteProperty(document, "visibilityState");
});

describe("WebUI state refresh", () => {
  it("reads on entry and on the matching event, without idle queries", async () => {
    const read = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() => useStateRefresh("pairing", true, read, 15_000));
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(read).toHaveBeenCalledTimes(1);
    invalidate("usage");
    invalidate("pairing");
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(2);
    unmount();
    invalidate("pairing");
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("retains an invalidation during a pending read and coalesces the rest", async () => {
    let finish!: () => void;
    const read = vi.fn().mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }))
      .mockResolvedValue(undefined);
    const { unmount } = renderHook(() => useStateRefresh("automations", true, read, 3000));
    invalidate("automations");
    invalidate("automations");
    expect(read).toHaveBeenCalledTimes(1);
    await act(async () => { finish(); });
    expect(read).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("retires stale reads on scope changes and refreshes on visible return and reconnect", async () => {
    const read = vi.fn().mockResolvedValue(undefined);
    const { rerender, unmount } = renderHook(({ scope }) => useStateRefresh("automations", true, read, 3000, scope), {
      initialProps: { scope: "chat-a" },
    });
    await act(async () => {});
    const firstSignal = read.mock.calls[0][0] as AbortSignal;
    rerender({ scope: "chat-b" });
    await act(async () => {});
    expect(firstSignal.aborted).toBe(true);
    expect(read).toHaveBeenCalledTimes(2);
    visibility("hidden");
    invalidate("automations");
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(read).toHaveBeenCalledTimes(2);
    visibility("visible");
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(3);
    status("reconnecting");
    status("open");
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(4);
    unmount();
  });

  it("keeps visible polling for an older gateway that cannot send notifications", async () => {
    source.capabilities = [];
    const read = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() => useStateRefresh("usage", true, read, 5000));
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(read).toHaveBeenCalledTimes(2);
    visibility("hidden");
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(read).toHaveBeenCalledTimes(2);
    visibility("visible");
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(3);
    unmount();
  });

  it("routes an explicit retry through the active lifetime and ignores it after leaving", async () => {
    let finish!: () => void;
    const read = vi.fn().mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }))
      .mockResolvedValue(undefined);
    const { result, unmount } = renderHook(() => useStateRefresh("pairing", true, read, 15_000));
    const retry = result.current;
    const cancelled = expect(retry()).rejects.toMatchObject({ name: "AbortError" });
    expect(read).toHaveBeenCalledTimes(1);
    visibility("hidden");
    await act(async () => { await retry(); });
    visibility("visible");
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(2);
    expect((read.mock.calls[0][0] as AbortSignal).aborted).toBe(true);
    await act(async () => { finish(); await cancelled; });
    expect(read).toHaveBeenCalledTimes(2);
    unmount();
    await act(async () => { await retry(); });
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("propagates a failed follow-up to the caller awaiting an explicit refresh", async () => {
    let finish!: () => void;
    const failure = new Error("directory unavailable");
    const read = vi.fn().mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }))
      .mockRejectedValue(failure);
    const { result, unmount } = renderHook(() => useStateRefresh("remote_instances", true, read, 5000));
    const rejected = expect(result.current()).rejects.toBe(failure);
    await act(async () => { finish(); await rejected; });
    expect(read).toHaveBeenCalledTimes(2);
    unmount();
  });

  it("bounds transient retries and lets a later change recover a failed read", async () => {
    const read = vi.fn().mockRejectedValue(new Error("offline"));
    const { unmount } = renderHook(() => useStateRefresh("channels", true, read, 5000));
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(read).toHaveBeenCalledTimes(4);
    read.mockResolvedValue(undefined);
    invalidate("channels");
    await act(async () => {});
    expect(read).toHaveBeenCalledTimes(5);
    unmount();
  });
});
