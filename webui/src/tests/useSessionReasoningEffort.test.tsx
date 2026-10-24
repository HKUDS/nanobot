import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { useSessionReasoningEffort } from "@/hooks/useSessionReasoningEffort";
import * as api from "@/lib/api";
import { NanobotClient } from "@/lib/nanobot-client";
import type { SessionReasoningEffort } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";

vi.mock("@/lib/api", () => ({ fetchSessionReasoningEffort: vi.fn(), setSessionReasoningEffort: vi.fn() }));
const initial = { sessionKey: "websocket:a" as string | null, preset: "default", settings: null, open: true, disabled: false };
const payload: SessionReasoningEffort = { preset: "default", scope: "scope", options: ["none", "low", "max"], value: null, preset_value: "low" };
function wrapper(enabled = true) {
  const client = new NanobotClient({ url: "ws://localhost:8765", reconnect: false });
  return ({ children }: { children: ReactNode }) => <ClientProvider client={client} token="test"
    webuiCapabilities={enabled ? ["webui.reasoning-effort.v1"] : []}>{children}</ClientProvider>;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.mocked(api.fetchSessionReasoningEffort).mockReset().mockResolvedValue(payload);
  vi.mocked(api.setSessionReasoningEffort).mockReset().mockImplementation(async (_client, _key, data, value) => ({ ...data, value }));
});

it("discovers only on menu open and leaves older hosts alone", async () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: { ...initial, open: false } });
  expect(api.fetchSessionReasoningEffort).not.toHaveBeenCalled();
  view.rerender(initial);
  await waitFor(() => expect(view.result.current.data).toEqual(payload));
  view.unmount();
  renderHook(useSessionReasoningEffort, { wrapper: wrapper(false), initialProps: initial });
  expect(api.fetchSessionReasoningEffort).toHaveBeenCalledTimes(1);
});

it("keeps draft choices local, preserves them on reopen, and applies before first input", async () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: { ...initial, sessionKey: null } });
  await waitFor(() => expect(view.result.current.data).toEqual(payload));
  await act(async () => view.result.current.select("none"));
  expect(api.setSessionReasoningEffort).not.toHaveBeenCalled();
  view.rerender({ ...initial, sessionKey: null, open: false });
  view.rerender({ ...initial, sessionKey: null });
  await waitFor(() => expect(api.fetchSessionReasoningEffort).toHaveBeenCalledTimes(2));
  expect(view.result.current.data?.value).toBe("none");
  await view.result.current.persistDraft("websocket:created");
  expect(api.setSessionReasoningEffort).toHaveBeenCalledWith(expect.anything(), "websocket:created", expect.objectContaining({ scope: "scope" }), "none");
  view.rerender({ ...initial, sessionKey: null, preset: "other" });
  expect(view.result.current.data).toBeNull();
  await act(async () => view.result.current.persistDraft("websocket:other"));
  expect(api.setSessionReasoningEffort).toHaveBeenCalledTimes(1);
});

it("waits for a pending write before send and exposes failures without changing the saved selection", async () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: initial });
  await waitFor(() => expect(view.result.current.data).toEqual(payload));
  const save = deferred<SessionReasoningEffort>();
  vi.mocked(api.setSessionReasoningEffort).mockReturnValueOnce(save.promise);
  let selected!: Promise<void>;
  act(() => { selected = view.result.current.select("max"); });
  const settled = vi.fn();
  const ready = Promise.resolve(view.result.current.settle()).then(settled);
  expect(view.result.current.pending).toBe(true);
  expect(settled).not.toHaveBeenCalled();
  await act(async () => { save.reject(new Error("stale scope")); await selected; await ready; });
  expect(settled).toHaveBeenCalledWith(false);
  expect(view.result.current.error).toBe(true);
  expect(view.result.current.data?.value).toBeNull();
  await act(async () => view.result.current.select("max"));
  expect(view.result.current.data?.value).toBe("max");
  await act(async () => view.result.current.select(null));
  expect(api.setSessionReasoningEffort).toHaveBeenLastCalledWith(expect.anything(), "websocket:a", expect.anything(), null);
});

it("isolates pending writes and discovery from another session", async () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: initial });
  await waitFor(() => expect(view.result.current.data).toEqual(payload));
  const save = deferred<SessionReasoningEffort>();
  vi.mocked(api.setSessionReasoningEffort).mockReturnValueOnce(save.promise);
  let selected!: Promise<void>;
  act(() => { selected = view.result.current.select("max"); });
  const ready = view.result.current.settle();
  view.rerender({ ...initial, sessionKey: "websocket:b" });
  await waitFor(() => expect(view.result.current.data).toEqual(payload));
  expect(view.result.current.pending).toBe(false);
  await act(async () => { save.resolve({ ...payload, value: "max" }); await selected; });
  expect(await ready).toBe(false);
  expect(view.result.current.data?.value).toBeNull();
  await act(async () => view.result.current.select("low"));
  expect(api.setSessionReasoningEffort).toHaveBeenLastCalledWith(expect.anything(), "websocket:b", payload, "low");
});

it("does not paint late discovery after changing hosts or presets", async () => {
  const read = deferred<SessionReasoningEffort>();
  vi.mocked(api.fetchSessionReasoningEffort).mockReturnValueOnce(read.promise)
    .mockResolvedValueOnce({ ...payload, preset: "other", scope: "other", options: [] });
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: initial });
  const signal = vi.mocked(api.fetchSessionReasoningEffort).mock.calls[0][3];
  view.rerender({ ...initial, preset: "other" });
  await waitFor(() => expect(view.result.current.data?.options).toEqual([]));
  await act(async () => read.resolve(payload));
  expect(signal?.aborted).toBe(true);
  expect(view.result.current.data?.preset).toBe("other");
});

it("does not let a reopening read rewind a choice saved before its response arrives", async () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: initial });
  await waitFor(() => expect(view.result.current.data).toEqual(payload));
  const read = deferred<SessionReasoningEffort>();
  vi.mocked(api.fetchSessionReasoningEffort).mockReturnValueOnce(read.promise);
  view.rerender({ ...initial, open: false });
  view.rerender(initial);
  const signal = vi.mocked(api.fetchSessionReasoningEffort).mock.lastCall?.[3];
  await act(async () => view.result.current.select("max"));
  await act(async () => read.resolve(payload));
  expect(signal?.aborted).toBe(true);
  expect(view.result.current.data?.value).toBe("max");
});
