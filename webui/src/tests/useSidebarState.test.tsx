import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useSidebarState } from "@/hooks/useSidebarState";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ConnectionStatus, SidebarStatePayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

describe("useSidebarState", () => {
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

  it.each([
    { outcome: "fails", status: 503 },
    { outcome: "returns an older snapshot", status: 200 },
  ])("preserves pushed state when the initial fetch $outcome", async ({ status }) => {
    let resolveInitialFetch!: (response: Response) => void;
    const initialFetch = new Promise<Response>((resolve) => {
      resolveInitialFetch = resolve;
    });
    let sidebarStateUpdateHandler: ((state: SidebarStatePayload) => void) | null = null;
    const setSidebarState = vi.fn().mockImplementation(async (state: SidebarStatePayload) => state);
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
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(initialFetch));
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">
        {children}
      </ClientProvider>
    );
    const { result } = renderHook(() => useSidebarState([], false), { wrapper });
    const pushed: SidebarStatePayload = {
      ...result.current.state,
      pinned_keys: ["websocket:saved"],
      archived_keys: ["websocket:archived"],
      title_overrides: { "websocket:saved": "Saved title" },
      tags_by_key: { "websocket:saved": ["saved-tag"] },
    };

    act(() => sidebarStateUpdateHandler?.(pushed));
    act(() => resolveInitialFetch(Response.json({}, { status })));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.state).toEqual(pushed);

    act(() => {
      void result.current.update((current) => ({
        ...current,
        pinned_keys: [...current.pinned_keys, "websocket:new"],
      }));
    });

    await waitFor(() => expect(setSidebarState).toHaveBeenCalledTimes(1));
    expect(setSidebarState).toHaveBeenCalledWith({
      ...pushed,
      pinned_keys: ["websocket:saved", "websocket:new"],
    });
  });

  it.each(["retry", "reconnect"] as const)("recovers a failed load on %s without accepting edits to unknown state", async (recovery) => {
    let statusHandler: ((status: ConnectionStatus) => void) | null = null;
    let resolveRecovery!: (response: Response) => void;
    const recoveryFetch = new Promise<Response>((resolve) => {
      resolveRecovery = resolve;
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({}, { status: 503 }))
      .mockReturnValueOnce(recoveryFetch);
    const setSidebarState = vi.fn().mockImplementation(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open" as const,
      onStatus: (handler: (status: ConnectionStatus) => void) => {
        statusHandler = handler;
        handler("open");
        return () => { statusHandler = null; };
      },
      onSidebarStateUpdate: () => () => {},
      setSidebarState,
    } as unknown as NanobotClient;
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">
        {children}
      </ClientProvider>
    );
    const { result } = renderHook(() => useSidebarState([], false), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadFailed).toBe(true);

    act(() => {
      void result.current.update((current) => ({
        ...current,
        pinned_keys: ["websocket:new"],
      }));
    });
    expect(result.current.state.pinned_keys).toEqual([]);
    expect(setSidebarState).not.toHaveBeenCalled();

    act(() => {
      if (recovery === "retry") result.current.retry();
      else {
        statusHandler?.("reconnecting");
        statusHandler?.("open");
      }
      result.current.retry();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.loading).toBe(true);
    const saved: SidebarStatePayload = {
      ...result.current.state,
      pinned_keys: ["websocket:saved"],
      archived_keys: ["websocket:archived"],
      title_overrides: { "websocket:saved": "Saved title" },
      tags_by_key: { "websocket:saved": ["saved-tag"] },
    };
    act(() => resolveRecovery(Response.json(saved)));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadFailed).toBe(false);
    expect(result.current.state).toEqual(saved);
    expect(setSidebarState).not.toHaveBeenCalled();

    act(() => {
      void result.current.update((current) => ({
        ...current,
        title_overrides: { ...current.title_overrides, "websocket:new": "New title" },
      }));
    });
    await waitFor(() => expect(setSidebarState).toHaveBeenCalledWith({
      ...saved,
      title_overrides: { ...saved.title_overrides, "websocket:new": "New title" },
    }));
  });

  it("does not accept local mutations when the initial sidebar-state fetch fails", async () => {
    const setSidebarState = vi.fn().mockImplementation(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open" as const,
      onStatus: () => () => {},
      onSidebarStateUpdate: () => () => {},
      setSidebarState,
    } as unknown as NanobotClient;
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
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
    });

    expect(result.current.loadFailed).toBe(true);
    expect(result.current.state.pinned_keys).toEqual([]);
    expect(setSidebarState).not.toHaveBeenCalled();
  });

  it("persists local mutations when the server returns an empty saved state", async () => {
    const setSidebarState = vi.fn().mockImplementation(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open" as const,
      onStatus: () => () => {},
      onSidebarStateUpdate: () => () => {},
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
    });

    await waitFor(() => expect(setSidebarState).toHaveBeenCalled());
  });
});
