import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useSidebarState } from "@/hooks/useSidebarState";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { SidebarStatePayload } from "@/lib/types";
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

  it("treats a missing saved state as a fresh install and allows persistence", async () => {
    const setSidebarState = vi.fn(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open" as const,
      onStatus: () => () => {},
      onSidebarStateUpdate: () => () => {},
      setSidebarState,
    } as unknown as NanobotClient;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => "sidebar state not found",
    }));
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">
        {children}
      </ClientProvider>
    );
    const { result } = renderHook(() => useSidebarState([], false), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBeNull();

    await act(async () => {
      await result.current.update((current) => ({
        ...current,
        title_overrides: { "websocket:a": "Fresh" },
      }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
  });

  it("blocks persistence while the saved state is unreadable and resumes after a successful reload", async () => {
    let statusHandler: ((status: string) => void) | null = null;
    const setSidebarState = vi.fn(async (state: SidebarStatePayload) => state);
    const client = {
      status: "open" as const,
      onStatus: (handler: (status: string) => void) => {
        statusHandler = handler;
        return () => {
          statusHandler = null;
        };
      },
      onSidebarStateUpdate: () => () => {},
      setSidebarState,
    } as unknown as NanobotClient;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        text: async () => "sidebar state file exists but could not be read (corrupt)",
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: { get: () => "application/json" },
        json: async () => ({ pinned_keys: ["websocket:a"] }),
      });
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ClientProvider client={client} token="token">
        {children}
      </ClientProvider>
    );

    const { result } = renderHook(() => useSidebarState([], false), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loadError).toBeTruthy();

    await act(async () => {
      await result.current.update((current) => ({
        ...current,
        title_overrides: { "websocket:a": "Blocked" },
      }));
    });
    expect(setSidebarState).not.toHaveBeenCalled();

    act(() => {
      statusHandler?.("open");
    });
    await waitFor(() => expect(result.current.loadError).toBeNull());
    expect(result.current.state.pinned_keys).toEqual(["websocket:a"]);

    await act(async () => {
      await result.current.update((current) => ({
        ...current,
        title_overrides: { "websocket:a": "Saved" },
      }));
    });
    expect(setSidebarState).toHaveBeenCalledTimes(1);
    expect(setSidebarState.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      title_overrides: { "websocket:a": "Saved" },
    }));
  });
});
