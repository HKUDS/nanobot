import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useSidebarState } from "@/hooks/useSidebarState";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ConnectionStatus, SidebarStatePayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

type SidebarWrite = {
  state: SidebarStatePayload;
  resolve: (saved?: SidebarStatePayload) => void;
  reject: (error: Error) => void;
};

async function renderLoadedSidebarState() {
  const writes: SidebarWrite[] = [];
  let status: ConnectionStatus = "open";
  let onStatus: ((status: ConnectionStatus) => void) | undefined;
  let onState: ((state: SidebarStatePayload) => void) | undefined;
  const setSidebarState = vi.fn((state: SidebarStatePayload) => new Promise<SidebarStatePayload>(
    (resolve, reject) => writes.push({ state, resolve: (saved = state) => resolve(saved), reject }),
  ));
  const client = {
    get status() { return status; },
    onStatus: (handler: (status: ConnectionStatus) => void) => {
      onStatus = handler;
      handler(status);
      return () => { onStatus = undefined; };
    },
    onSidebarStateUpdate: (handler: (state: SidebarStatePayload) => void) => {
      onState = handler;
      return () => { onState = undefined; };
    },
    setSidebarState,
  } as unknown as NanobotClient;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
    title_overrides: { "websocket:a": "Saved title", "websocket:b": "Other title" },
  })));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ClientProvider client={client} token="token">{children}</ClientProvider>
  );
  const hook = renderHook(() => useSidebarState([], false), { wrapper });
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return {
    ...hook,
    writes,
    setSidebarState,
    setStatus: (next: ConnectionStatus) => { status = next; onStatus?.(next); },
    receive: (state: SidebarStatePayload) => onState?.(state),
  };
}

describe("useSidebarState", () => {
  it("blocks writes after a failed read and retries before allowing edits", async () => {
    const setSidebarState = vi.fn(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open",
      onStatus: () => () => {},
      onSidebarStateUpdate: () => () => {},
      setSidebarState,
    } as unknown as NanobotClient;
    const saved = {
      pinned_keys: ["websocket:old"],
      archived_keys: ["websocket:archived"],
      title_overrides: { "websocket:old": "Saved title" },
      tags_by_key: { "websocket:old": ["important"] },
      session_order: ["websocket:old", "websocket:archived"],
    };
    const fetch = vi.fn()
      .mockRejectedValueOnce(new Error("Gateway restarting"))
      .mockResolvedValue({ ok: true, json: async () => saved });
    vi.stubGlobal("fetch", fetch);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">{children}</ClientProvider>
    );
    const { result, unmount } = renderHook(() => useSidebarState([], false), { wrapper });
    await act(async () => {});
    expect(fetch).toHaveBeenCalled();
    await act(async () => {
      await expect(result.current.rename("websocket:old", "New title"))
        .rejects.toThrow("Sidebar state is not loaded");
      await result.current.update((current) => ({ ...current, pinned_keys: ["websocket:new"] }));
    });
    expect(setSidebarState).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5_000 });
    expect(result.current.state).toEqual(expect.objectContaining(saved));
    await act(async () => {
      await result.current.update((current) => ({
        ...current, pinned_keys: [...current.pinned_keys, "websocket:new"],
      }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(setSidebarState).toHaveBeenCalledWith(expect.objectContaining({
      ...saved, pinned_keys: ["websocket:old", "websocket:new"],
    }));
    unmount();
  }, 10_000);

  it.each([
    { outcome: "fails", status: 503 },
    { outcome: "returns an older snapshot", status: 200 },
  ])("preserves pushed state when the initial fetch $outcome", async ({ status }) => {
    let resolveInitialFetch!: (response: Response) => void;
    const initialFetch = new Promise<Response>((resolve) => { resolveInitialFetch = resolve; });
    let receive: ((state: SidebarStatePayload) => void) | undefined;
    const setSidebarState = vi.fn(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open",
      onStatus: () => () => {},
      onSidebarStateUpdate: (handler: (state: SidebarStatePayload) => void) => {
        receive = handler;
        return () => { receive = undefined; };
      },
      setSidebarState,
    } as unknown as NanobotClient;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(initialFetch));
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">{children}</ClientProvider>
    );
    const { result } = renderHook(() => useSidebarState([], false), { wrapper });
    const pushed: SidebarStatePayload = {
      ...result.current.state,
      pinned_keys: ["websocket:saved"],
      archived_keys: ["websocket:archived"],
      session_order: ["websocket:saved", "websocket:archived"],
      title_overrides: { "websocket:saved": "Saved title" },
      tags_by_key: { "websocket:saved": ["saved-tag"] },
    };

    act(() => receive?.(pushed));
    expect(result.current.loading).toBe(false);
    await act(async () => { resolveInitialFetch(Response.json({}, { status })); });
    expect(result.current.state).toEqual(pushed);
    expect(setSidebarState).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.update((current) => ({
        ...current, pinned_keys: [...current.pinned_keys, "websocket:new"],
      }));
    });
    expect(setSidebarState).toHaveBeenCalledWith({
      ...pushed, pinned_keys: ["websocket:saved", "websocket:new"],
    });
  });

  it("stops a scheduled read retry once a server push supplies state", async () => {
    vi.useFakeTimers();
    let unmount: (() => void) | undefined;
    try {
      let receive: ((state: SidebarStatePayload) => void) | undefined;
      const client = {
        status: "open",
        onStatus: () => () => {},
        onSidebarStateUpdate: (handler: (state: SidebarStatePayload) => void) => {
          receive = handler;
          return () => { receive = undefined; };
        },
        setSidebarState: vi.fn(async (state: SidebarStatePayload) => state),
      } as unknown as NanobotClient;
      const fetch = vi.fn()
        .mockResolvedValueOnce(Response.json({}, { status: 503 }))
        .mockResolvedValue(Response.json({}));
      vi.stubGlobal("fetch", fetch);
      const wrapper = ({ children }: { children: ReactNode }) => (
        <ClientProvider client={client} token="token">{children}</ClientProvider>
      );
      const hook = renderHook(() => useSidebarState([], false), { wrapper });
      unmount = hook.unmount;
      await act(async () => {});
      expect(hook.result.current.loading).toBe(true);
      const pushed: SidebarStatePayload = {
        ...hook.result.current.state, pinned_keys: ["websocket:saved"],
      };
      act(() => receive?.(pushed));
      await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
      expect(hook.result.current.loading).toBe(false);
      expect(hook.result.current.state).toEqual(pushed);
      expect(fetch).toHaveBeenCalledTimes(1);
    } finally {
      unmount?.();
      vi.useRealTimers();
    }
  });

  it("keeps queued rename titles hidden until each acknowledgement", async () => {
    const { result, writes, setSidebarState, receive } = await renderLoadedSidebarState();
    let first!: Promise<void>;
    let second!: Promise<void>;
    const finished: string[] = [];
    act(() => {
      first = result.current.rename("websocket:a", "First requested").then(() => {
        finished.push("a");
      });
      second = result.current.rename("websocket:b", "Second requested").then(() => {
        finished.push("b");
      });
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(writes[0].state.title_overrides["websocket:a"]).toBe("First requested");
    act(() => receive(writes[0].state));
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "Saved title", "websocket:b": "Other title",
    });
    expect(finished).toEqual([]);

    await act(async () => {
      writes[0].resolve({
        ...writes[0].state,
        title_overrides: { "websocket:a": "First canonical", "websocket:b": "Other title" },
      });
      await first;
    });
    expect(finished).toEqual(["a"]);
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "First canonical", "websocket:b": "Other title",
    });
    expect(setSidebarState).toHaveBeenCalledTimes(2);
    expect(writes[1].state.title_overrides).toEqual({
      "websocket:a": "First canonical", "websocket:b": "Second requested",
    });
    await act(async () => { writes[1].resolve(); await second; });
    expect(finished).toEqual(["a", "b"]);
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "First canonical", "websocket:b": "Second requested",
    });
  });

  it("rejects a failed rename without retrying it until the user asks again", async () => {
    const { result, writes, setSidebarState, setStatus } = await renderLoadedSidebarState();
    let rename!: Promise<void>;
    act(() => { rename = result.current.rename("websocket:a", "Requested title"); });
    const rejected = expect(rename).rejects.toThrow("Rename failed");
    act(() => {
      void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:b"] }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    await act(async () => { writes[0].reject(new Error("Rename failed")); await rejected; });
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Saved title");
    expect(result.current.state.pinned_keys).toEqual(["websocket:b"]);
    expect(setSidebarState).toHaveBeenCalledTimes(2);
    expect(writes[1].state).toEqual(result.current.state);
    await act(async () => { writes[1].resolve(); });
    act(() => { setStatus("closed"); setStatus("open"); });
    expect(setSidebarState).toHaveBeenCalledTimes(2);

    act(() => { rename = result.current.rename("websocket:a", "Requested title"); });
    expect(setSidebarState).toHaveBeenCalledTimes(3);
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Saved title");
    expect(writes[2].state.pinned_keys).toEqual(["websocket:b"]);
    await act(async () => { writes[2].resolve(); await rename; });
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Requested title");
  });

  it("drains optimistic writes before renaming and preserves edits made during the rename", async () => {
    const { result, writes, setSidebarState } = await renderLoadedSidebarState();
    let rename!: Promise<void>;
    act(() => {
      void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:a"] }));
      rename = result.current.rename("websocket:a", "Requested title");
      void result.current.update((current) => ({ ...current, archived_keys: ["websocket:b"] }));
      void result.current.update((current) => ({
        ...current, view: { ...current.view, density: "compact" },
      }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    await act(async () => { writes[0].resolve(); });
    expect(setSidebarState).toHaveBeenCalledTimes(2);
    expect(writes[1].state).toEqual(expect.objectContaining({
      pinned_keys: ["websocket:a"],
      archived_keys: ["websocket:b"],
      view: expect.objectContaining({ density: "compact" }),
    }));
    expect(writes[1].state.title_overrides["websocket:a"]).toBe("Saved title");
    await act(async () => { writes[1].resolve(); });
    expect(setSidebarState).toHaveBeenCalledTimes(3);
    expect(writes[2].state).toEqual({
      ...writes[1].state,
      title_overrides: { "websocket:a": "Requested title", "websocket:b": "Other title" },
    });
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Saved title");

    act(() => {
      void result.current.update((current) => ({ ...current, pinned_keys: [] }));
      void result.current.update((current) => ({
        ...current, tags_by_key: { "websocket:b": ["important"] },
      }));
      void result.current.update((current) => ({
        ...current, view: { ...current.view, density: "comfortable" },
      }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(3);
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Saved title");
    await act(async () => {
      writes[2].resolve({
        ...writes[2].state,
        title_overrides: { "websocket:a": "Canonical title", "websocket:b": "Other title" },
      });
      await rename;
    });
    expect(result.current.state).toEqual(expect.objectContaining({
      pinned_keys: [],
      archived_keys: ["websocket:b"],
      tags_by_key: { "websocket:b": ["important"] },
      view: expect.objectContaining({ density: "comfortable" }),
      title_overrides: { "websocket:a": "Canonical title", "websocket:b": "Other title" },
    }));
    expect(setSidebarState).toHaveBeenCalledTimes(4);
    expect(writes[3].state).toEqual(result.current.state);
    await act(async () => { writes[3].resolve(); });
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Canonical title");
  });

  it("rejects waiting renames when an earlier optimistic write fails but retains its latest retry", async () => {
    const { result, writes, setSidebarState, setStatus } = await renderLoadedSidebarState();
    let first!: Promise<void>;
    let second!: Promise<void>;
    act(() => {
      void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:a"] }));
      first = result.current.rename("websocket:a", "First requested");
      second = result.current.rename("websocket:b", "Second requested");
      void result.current.update((current) => ({
        ...current, tags_by_key: { "websocket:b": ["important"] },
      }));
    });
    const firstRejected = expect(first).rejects.toThrow("Save failed");
    const secondRejected = expect(second).rejects.toThrow("Save failed");
    await act(async () => {
      writes[0].reject(new Error("Save failed"));
      await Promise.all([firstRejected, secondRejected]);
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "Saved title", "websocket:b": "Other title",
    });
    expect(result.current.state.tags_by_key).toEqual({ "websocket:b": ["important"] });
    act(() => { setStatus("closed"); setStatus("open"); });
    expect(setSidebarState).toHaveBeenCalledTimes(2);
    expect(writes[1].state).toEqual(result.current.state);
    expect(writes[1].state.pinned_keys).toEqual(["websocket:a"]);
    await act(async () => { writes[1].resolve(); });
    expect(setSidebarState).toHaveBeenCalledTimes(2);
  });

  it("rejects new and waiting renames on disconnect without replaying them on reconnect", async () => {
    const { result, writes, setSidebarState, setStatus } = await renderLoadedSidebarState();
    let rename!: Promise<void>;
    act(() => {
      void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:a"] }));
      rename = result.current.rename("websocket:a", "Requested title");
    });
    const rejected = expect(rename).rejects.toThrow("WebUI connection is not open");
    await act(async () => { setStatus("closed"); await rejected; });
    await act(async () => {
      await expect(result.current.rename("websocket:b", "Offline title"))
        .rejects.toThrow("WebUI connection is not open");
      await result.current.update((current) => ({ ...current, archived_keys: ["websocket:b"] }));
      writes[0].resolve();
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "Saved title", "websocket:b": "Other title",
    });
    expect(result.current.state.archived_keys).toEqual(["websocket:b"]);
    act(() => setStatus("open"));
    expect(setSidebarState).toHaveBeenCalledTimes(2);
    expect(writes[1].state).toEqual(result.current.state);
    await act(async () => { writes[1].resolve(); });
    expect(setSidebarState).toHaveBeenCalledTimes(2);
  });

  it("serializes full-state writes so an older request cannot overwrite a newer update", async () => {
    let resolveFirstWrite: (() => void) | null = null;
    let sidebarStateUpdateHandler: ((state: SidebarStatePayload) => void) | null = null;
    const setSidebarState = vi.fn()
      .mockImplementationOnce((state: SidebarStatePayload) => new Promise<SidebarStatePayload>(
        (resolve) => {
          resolveFirstWrite = () => resolve(state);
        },
      ))
      .mockImplementation(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open" as const,
      onStatus: () => () => {},
      onSidebarStateUpdate: (handler: (state: SidebarStatePayload) => void) => {
        sidebarStateUpdateHandler = handler;
        return () => {
          sidebarStateUpdateHandler = null;
        };
      },
      setSidebarState,
    } as unknown as NanobotClient;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({}),
    }));
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">
        {children}
      </ClientProvider>
    );
    const { result } = renderHook(() => useSidebarState([], false), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      void result.current.update((current) => ({
        ...current,
        title_overrides: { "websocket:a": "First" },
      }));
      void result.current.update((current) => ({
        ...current,
        title_overrides: { "websocket:a": "Second" },
      }));
    });

    expect(setSidebarState).toHaveBeenCalledTimes(1);
    act(() => {
      sidebarStateUpdateHandler?.(setSidebarState.mock.calls[0]?.[0]);
    });
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "Second",
    });
    act(() => resolveFirstWrite?.());
    await waitFor(() => expect(setSidebarState).toHaveBeenCalledTimes(2));
    expect(setSidebarState.mock.calls[1]?.[0]).toEqual(expect.objectContaining({
      title_overrides: { "websocket:a": "Second" },
    }));
  });
});
