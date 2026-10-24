import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useSessionReasoningEffort } from "@/hooks/useSessionReasoningEffort";
import * as api from "@/lib/api";
import { NanobotClient } from "@/lib/nanobot-client";
import { reasoningEffortValues } from "@/lib/provider-model-catalog";
import type { ProviderModelsPayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";
import { settingsPayload } from "./settings-test-utils";

vi.mock("@/lib/api", () => ({ fetchProviderModels: vi.fn() }));
const payload: ProviderModelsPayload = { provider: "openai", label: "OpenAI", status: "available", catalog_kind: "official", model_count: 1, source: "remote", models: [
  { id: "openai/gpt-4o", reasoning_efforts: ["none", "low", "max"] },
] };
function props() {
  const settings = settingsPayload();
  settings.providers = [{ name: "openai", label: "OpenAI", configured: true }];
  settings.model_presets[0].reasoning_effort = "low";
  settings.model_presets[0].reasoning_effort_values = ["low", "high"];
  return { sessionKey: "websocket:a" as string | null, preset: "primary", settings, open: true, disabled: false, storedValue: null as string | null };
}
function wrapper(connection = { client: new NanobotClient({ url: "ws://host-a/ws?token=old", reconnect: false }), token: "old" }, enabled = true) {
  return ({ children }: { children: ReactNode }) => <ClientProvider client={connection.client} token={connection.token}
    webuiCapabilities={enabled ? ["webui.reasoning-effort.v1"] : []}>{children}</ClientProvider>;
}
beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.fetchProviderModels).mockReset().mockResolvedValue(payload);
});
afterEach(() => vi.useRealTimers());

it("uses the preset picker recommendations lazily, including saved recommendations when discovery is unavailable", async () => {
  const initial = props();
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: { ...initial, open: false } });
  expect(api.fetchProviderModels).not.toHaveBeenCalled();
  expect(view.result.current.data?.options).toEqual(["low", "high"]);
  view.rerender(initial);
  await waitFor(() => expect(view.result.current.data?.options).toEqual(reasoningEffortValues(payload, initial.settings.agent.model)));
  expect(view.result.current.data?.presetValue).toBe("low");
  expect(view.result.current.sendValue()).toBeNull();
});

it("coalesces browser writes while sending the latest click immediately without a backend mutation", async () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: props() });
  await waitFor(() => expect(view.result.current.data?.options).toContain("max"));
  const mutation = vi.spyOn(NanobotClient.prototype, "requestMutation");
  const storage = vi.spyOn(localStorage, "setItem");
  vi.useFakeTimers();
  act(() => { view.result.current.select("none"); view.result.current.select("max"); });
  expect(view.result.current.sendValue()).toBe("max");
  expect(storage).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(250));
  expect(storage).toHaveBeenCalledTimes(1);
  expect(JSON.parse(storage.mock.calls[0][1])).toEqual({ preset: "primary", value: "max" });
  expect(api.fetchProviderModels).toHaveBeenCalledTimes(1);
  expect(mutation).not.toHaveBeenCalled();
  storage.mockRestore(); mutation.mockRestore();
});

it("retains unsent choices after remount and token renewal, but isolates sessions and hosts", async () => {
  const connection = { client: new NanobotClient({ url: "ws://host-a/ws?token=old", reconnect: false }), token: "old" };
  const initial = props();
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(connection), initialProps: initial });
  await waitFor(() => expect(view.result.current.data?.options).toContain("max"));
  act(() => view.result.current.select("max"));
  connection.token = "renewed";
  connection.client.updateUrl("ws://host-a/ws?token=renewed");
  view.rerender({ ...initial, settings: { ...initial.settings } });
  expect(view.result.current.sendValue()).toBe("max");
  view.unmount();
  const next = renderHook(useSessionReasoningEffort, { wrapper: wrapper(connection), initialProps: initial });
  expect(next.result.current.sendValue()).toBe("max");
  next.rerender({ ...initial, sessionKey: "websocket:b", storedValue: "low" });
  expect(next.result.current.sendValue()).toBe("low");
  next.unmount();
  const other = renderHook(useSessionReasoningEffort, { wrapper: wrapper({ client: new NanobotClient({ url: "ws://host-b/ws", reconnect: false }), token: "test" }), initialProps: initial });
  expect(other.result.current.sendValue()).toBeNull();
  await act(async () => {});
});

it("transfers the landing choice to the real session locally and clears it when changing preset", async () => {
  const initial = { ...props(), sessionKey: null as string | null };
  const wrap = wrapper();
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrap, initialProps: initial });
  await waitFor(() => expect(view.result.current.data?.options).toContain("max"));
  act(() => view.result.current.select("max"));
  act(() => view.result.current.moveToSession("websocket:created", "max"));
  view.rerender({ ...initial, sessionKey: "websocket:created" });
  expect(view.result.current.sendValue()).toBe("max");
  act(() => view.result.current.reset("other"));
  view.rerender({ ...initial, sessionKey: "websocket:created", preset: "other" });
  expect(view.result.current.sendValue()).toBeNull();
  act(() => view.result.current.reset("primary"));
  view.rerender({ ...initial, sessionKey: "websocket:created" });
  expect(view.result.current.sendValue()).toBeNull();
  view.unmount();
  const landing = renderHook(useSessionReasoningEffort, { wrapper: wrap, initialProps: initial });
  expect(landing.result.current.sendValue()).toBeNull();
  await act(async () => {});
});

it("preserves a newer target choice if topic creation finishes after its composer becomes available", async () => {
  const initial = { ...props(), sessionKey: null as string | null };
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: initial });
  await waitFor(() => expect(view.result.current.data?.options).toContain("max"));
  act(() => view.result.current.select("max"));
  const transfer = view.result.current.moveToSession;
  view.rerender({ ...initial, sessionKey: "websocket:created-late" });
  act(() => view.result.current.select("low"));
  act(() => transfer("websocket:created-late", "max"));
  expect(view.result.current.sendValue()).toBe("low");
  view.unmount();
  const restored = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: { ...initial, sessionKey: "websocket:created-late" } });
  expect(restored.result.current.sendValue()).toBe("low");
  await act(async () => {});
});

it("does not clear an existing server selection while its session summary is still loading", () => {
  const view = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: { ...props(), open: false, storedValue: undefined } });
  expect(view.result.current.sendValue()).toBeUndefined();
});

it("leaves temporary chats and hosts without message support unchanged", () => {
  const disabled = renderHook(useSessionReasoningEffort, { wrapper: wrapper(), initialProps: { ...props(), disabled: true } });
  expect(disabled.result.current.data).toBeNull();
  expect(disabled.result.current.sendValue()).toBeUndefined();
  const oldHost = renderHook(useSessionReasoningEffort, { wrapper: wrapper(undefined, false), initialProps: props() });
  expect(oldHost.result.current.sendValue()).toBeUndefined();
  expect(api.fetchProviderModels).not.toHaveBeenCalled();
});
