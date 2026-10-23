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

async function renderLoadedSidebarState(webuiCapabilities = ["webui.session-title-rename.v1"]) {
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
  let capabilities = webuiCapabilities;
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ClientProvider client={client} token="token" webuiCapabilities={capabilities}>{children}</ClientProvider>
  );
  const hook = renderHook(() => useSidebarState([], false), { wrapper });
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  return {
    ...hook,
    writes,
    setSidebarState,
    setStatus: (next: ConnectionStatus) => { status = next; onStatus?.(next); },
    receive: (state: SidebarStatePayload) => onState?.(state),
    setCapabilities: (next: string[]) => { capabilities = next; hook.rerender(); },
  };
}

describe("useSidebarState", () => {
  it("preserves legacy titles when editing layout on a compatible older host", async () => {
    const { result, writes } = await renderLoadedSidebarState([]);
    expect(result.current.state.title_overrides).toEqual({
      "websocket:a": "Saved title", "websocket:b": "Other title",
    });
    act(() => { void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:a"] })); });
    expect(writes[0].state.title_overrides).toEqual(result.current.state.title_overrides);
    await act(async () => { writes[0].resolve(); });
    expect(result.current.state.title_overrides["websocket:a"]).toBe("Saved title");
  });

  it("discards old-host title projections when the gateway gains rename support", async () => {
    const { result, writes, setCapabilities } = await renderLoadedSidebarState([]);
    act(() => { void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:a"] })); });
    expect(writes[0].state.title_overrides["websocket:a"]).toBe("Saved title");
    act(() => setCapabilities(["webui.session-title-rename.v1"]));
    expect(result.current.loading).toBe(false);
    expect(result.current.state.title_overrides).toEqual({});
    await act(async () => { writes[0].resolve(); });
    expect(result.current.state.title_overrides).toEqual({});
    act(() => { void result.current.update((current) => ({ ...current, archived_keys: ["websocket:b"] })); });
    expect(writes[1].state.title_overrides).toEqual({});
  });

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
      <ClientProvider client={client} token="token" webuiCapabilities={["webui.session-title-rename.v1"]}>{children}</ClientProvider>
    );
    const { result, unmount } = renderHook(() => useSidebarState([], false), { wrapper });
    await act(async () => {});
    expect(fetch).toHaveBeenCalled();
    await act(async () => {
      await result.current.update((current) => ({ ...current, pinned_keys: ["websocket:new"] }));
    });
    expect(setSidebarState).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false), { timeout: 5_000 });
    expect(result.current.state).toEqual(expect.objectContaining({
      ...saved, title_overrides: {},
    }));
    await act(async () => {
      await result.current.update((current) => ({
        ...current, pinned_keys: [...current.pinned_keys, "websocket:new"],
      }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(setSidebarState).toHaveBeenCalledWith(expect.objectContaining({
      ...saved, title_overrides: {}, pinned_keys: ["websocket:old", "websocket:new"],
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
      <ClientProvider client={client} token="token" webuiCapabilities={["webui.session-title-rename.v1"]}>{children}</ClientProvider>
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
    expect(result.current.state).toEqual({ ...pushed, title_overrides: {} });
    expect(setSidebarState).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.update((current) => ({
        ...current, pinned_keys: [...current.pinned_keys, "websocket:new"],
      }));
    });
    expect(setSidebarState).toHaveBeenCalledWith({
      ...pushed, title_overrides: {}, pinned_keys: ["websocket:saved", "websocket:new"],
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
        <ClientProvider client={client} token="token" webuiCapabilities={["webui.session-title-rename.v1"]}>{children}</ClientProvider>
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

  it("serializes layout edits and keeps the latest pending state after acknowledgement", async () => {
    const { result, writes, setSidebarState } = await renderLoadedSidebarState();
    act(() => {
      void result.current.update((current) => ({ ...current, pinned_keys: ["websocket:a"] }));
      void result.current.update((current) => ({ ...current, archived_keys: ["websocket:b"] }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(writes[0].state.pinned_keys).toEqual(["websocket:a"]);
    await act(async () => { writes[0].resolve(); });
    expect(setSidebarState).toHaveBeenCalledTimes(2);
    expect(writes[1].state.archived_keys).toEqual(["websocket:b"]);
    await act(async () => { writes[1].resolve(); });
    expect(result.current.state.archived_keys).toEqual(["websocket:b"]);
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
        pinned_keys: ["websocket:a"],
      }));
      void result.current.update((current) => ({
        ...current,
        pinned_keys: ["websocket:a", "websocket:b"],
      }));
    });

    expect(setSidebarState).toHaveBeenCalledTimes(1);
    act(() => {
      sidebarStateUpdateHandler?.(setSidebarState.mock.calls[0]?.[0]);
    });
    expect(result.current.state.pinned_keys).toEqual(["websocket:a", "websocket:b"]);
    act(() => resolveFirstWrite?.());
    await waitFor(() => expect(setSidebarState).toHaveBeenCalledTimes(2));
    expect(setSidebarState.mock.calls[1]?.[0]).toEqual(expect.objectContaining({
      pinned_keys: ["websocket:a", "websocket:b"],
    }));
  });
});
