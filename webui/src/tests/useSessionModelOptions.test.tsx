import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useSessionModelOptions } from "@/hooks/useSessionModelOptions";
import * as api from "@/lib/api";
import { NanobotClient } from "@/lib/nanobot-client";
import { reasoningEffortValues } from "@/lib/provider-model-catalog";
import type { ProviderModelsPayload, SessionModelOptions, SettingsPayload } from "@/lib/types";
import { ClientProvider } from "@/providers/ClientProvider";
import { settingsPayload } from "./settings-test-utils";

vi.mock("@/lib/api", () => ({ fetchProviderModels: vi.fn() }));
const inherit: SessionModelOptions = { reasoning_effort: null, codex_fast_mode: null };
const chosen: SessionModelOptions = { reasoning_effort: "max", codex_fast_mode: false };
const payload: ProviderModelsPayload = {
  provider: "custom", label: "Custom", status: "available", catalog_kind: "official", model_count: 1, source: "remote",
  models: [{ id: "openai/gpt-4o", reasoning_efforts: ["none", "low", "max"] }],
};
function props() {
  const settings = settingsPayload();
  settings.providers = [{ name: "custom", label: "Custom", configured: true }];
  settings.model_presets[0].resolved_provider = "custom";
  settings.model_presets[0].model_options = {
    reasoning_effort: { default: "low", values: ["low", "high"] }, codex_fast_mode: { default: true },
  };
  return { sessionKey: "websocket:a" as string | null, preset: "primary", settings, open: false, disabled: false,
    storedValue: undefined as SessionModelOptions | undefined };
}
function wrapper(connection = { client: new NanobotClient({ url: "ws://host-a/ws?token=old", reconnect: false }), token: "old" }, enabled = true) {
  return ({ children }: { children: ReactNode }) => <ClientProvider client={connection.client} token={connection.token}
    webuiCapabilities={enabled ? ["webui.model-options.v1"] : []}>{children}</ClientProvider>;
}
beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.fetchProviderModels).mockReset().mockResolvedValue(payload);
});
afterEach(() => vi.useRealTimers());

it("shares lazy settings recommendations and uses backend capability descriptions for custom providers", async () => {
  const initial = props();
  const view = renderHook(useSessionModelOptions, { wrapper: wrapper(), initialProps: initial });
  expect(api.fetchProviderModels).not.toHaveBeenCalled();
  expect(view.result.current.data?.efforts).toEqual(["low", "high"]);
  expect(view.result.current.data?.capability.codex_fast_mode?.default).toBe(true);
  view.rerender({ ...initial, open: true });
  await waitFor(() => expect(view.result.current.data?.efforts).toEqual(reasoningEffortValues(payload, initial.settings.agent.model)));
  expect(view.result.current.data?.value).toEqual(inherit);
  expect(view.result.current.sendValue()).toBeUndefined();
});

it("coalesces browser writes, immediately transmits false/null, and flushes pagehide without gateway mutations", () => {
  const view = renderHook(useSessionModelOptions, { wrapper: wrapper(), initialProps: props() });
  const mutation = vi.spyOn(NanobotClient.prototype, "requestMutation");
  const storage = vi.spyOn(localStorage, "setItem");
  vi.useFakeTimers();
  act(() => { view.result.current.select(chosen); view.result.current.select({ ...chosen, reasoning_effort: null }); });
  expect(view.result.current.sendValue()).toEqual({ reasoning_effort: null, codex_fast_mode: false });
  expect(storage).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(250));
  expect(storage).toHaveBeenCalledTimes(1);
  expect(JSON.parse(storage.mock.calls[0][1])).toEqual({ preset: "primary", options: { reasoning_effort: null, codex_fast_mode: false } });
  act(() => view.result.current.select(inherit));
  act(() => window.dispatchEvent(new Event("pagehide")));
  expect(storage).toHaveBeenCalledTimes(2);
  expect(mutation).not.toHaveBeenCalled();
  storage.mockRestore(); mutation.mockRestore();
});

it("reloads unsent preferences across token renewal and isolates hosts and sessions including rapid switches", () => {
  const connection = { client: new NanobotClient({ url: "ws://host-a/ws?token=old", reconnect: false }), token: "old" };
  const initial = props();
  const view = renderHook(useSessionModelOptions, { wrapper: wrapper(connection), initialProps: initial });
  act(() => view.result.current.select(chosen));
  connection.token = "renewed";
  connection.client.updateUrl("ws://host-a/ws?token=renewed");
  view.rerender({ ...initial });
  expect(view.result.current.sendValue()).toEqual(chosen);
  view.rerender({ ...initial, sessionKey: "websocket:b", storedValue: { reasoning_effort: "low", codex_fast_mode: true } });
  expect(view.result.current.data?.value).toEqual({ reasoning_effort: "low", codex_fast_mode: true });
  expect(view.result.current.sendValue()).toBeUndefined();
  act(() => view.result.current.select(inherit));
  view.rerender(initial);
  expect(view.result.current.sendValue()).toEqual(chosen);
  connection.client.updateUrl("ws://host-b/ws");
  view.rerender({ ...initial });
  expect(view.result.current.data?.value).toEqual(inherit);
  expect(view.result.current.sendValue()).toBeUndefined();
  connection.client.updateUrl("ws://host-a/ws?token=again");
  view.unmount();
  const reloaded = renderHook(useSessionModelOptions, { wrapper: wrapper(connection), initialProps: initial });
  expect(reloaded.result.current.sendValue()).toEqual(chosen);
  reloaded.rerender({ ...initial, sessionKey: "websocket:b" });
  expect(reloaded.result.current.sendValue()).toEqual(inherit);
});

it("waits for settings before reconciling a reloaded browser preference with the active preset", () => {
  const initial = props();
  const key = 'nanobot.model-options.v1.["ws://host-a/ws","websocket:a"]';
  const saved = JSON.stringify({ preset: initial.preset, options: chosen });
  localStorage.setItem(key, saved);
  const view = renderHook(useSessionModelOptions, { wrapper: wrapper(), initialProps: {
    ...initial, preset: "default", settings: null as SettingsPayload | null,
  } });
  expect(view.result.current.sendValue()).toBeUndefined();
  act(() => window.dispatchEvent(new Event("pagehide")));
  expect(localStorage.getItem(key)).toBe(saved);
  view.rerender(initial);
  expect(view.result.current.sendValue()).toEqual(chosen);
  expect(view.result.current.data?.value).toEqual(chosen);
  view.unmount();
  expect(localStorage.getItem(key)).toBe(saved);
});

it("shows the Gateway's last-used options after a preset rename without sending a replacement", () => {
  const initial = props();
  const wrap = wrapper();
  const storedValue: SessionModelOptions = { reasoning_effort: "high", codex_fast_mode: "ultrafast" };
  const previous = renderHook(useSessionModelOptions, { wrapper: wrap, initialProps: initial });
  act(() => previous.result.current.select(storedValue));
  previous.unmount();

  initial.settings.model_presets[0].name = "renamed";
  const renamed = { ...initial, preset: "renamed", storedValue };
  const reopened = renderHook(useSessionModelOptions, { wrapper: wrap, initialProps: renamed });
  expect(reopened.result.current.data?.value).toEqual(storedValue);
  expect(reopened.result.current.sendValue()).toBeUndefined();
  reopened.unmount();

  const reloaded = renderHook(useSessionModelOptions, { wrapper: wrap, initialProps: renamed });
  expect(reloaded.result.current.data?.value).toEqual(storedValue);
  expect(reloaded.result.current.sendValue()).toBeUndefined();
});

it("migrates a draft snapshot to the first session, clears both choices on preset switch, and clears the draft", () => {
  const initial = { ...props(), sessionKey: null as string | null };
  const wrap = wrapper();
  const view = renderHook(useSessionModelOptions, { wrapper: wrap, initialProps: initial });
  act(() => view.result.current.select(chosen));
  act(() => view.result.current.moveToSession("websocket:created", chosen));
  view.rerender({ ...initial, sessionKey: "websocket:created" });
  expect(view.result.current.sendValue()).toEqual(chosen);
  // ThreadShell resets options and selects the preset in the same action.
  act(() => {
    view.result.current.reset("other");
    view.rerender({ ...initial, sessionKey: "websocket:created", preset: "other" });
  });
  expect(view.result.current.sendValue()).toEqual(inherit);
  act(() => {
    view.result.current.reset("primary");
    view.rerender({ ...initial, sessionKey: "websocket:created" });
  });
  expect(view.result.current.sendValue()).toEqual(inherit);
  view.unmount();
  const landing = renderHook(useSessionModelOptions, { wrapper: wrap, initialProps: initial });
  expect(landing.result.current.data?.value).toEqual(inherit);
  expect(landing.result.current.sendValue()).toBeUndefined();
});

it("preserves newer target choices made while draft creation was pending", () => {
  const initial = { ...props(), sessionKey: null as string | null };
  const view = renderHook(useSessionModelOptions, { wrapper: wrapper(), initialProps: initial });
  act(() => view.result.current.select(chosen));
  const transfer = view.result.current.moveToSession;
  view.rerender({ ...initial, sessionKey: "websocket:created" });
  const newer = { reasoning_effort: "low", codex_fast_mode: true };
  act(() => view.result.current.select(newer));
  act(() => transfer("websocket:created", chosen));
  expect(view.result.current.sendValue()).toEqual(newer);
});

it.each(["temporary", "unsupported"])("hides and omits options for %s chats", (mode) => {
  const view = renderHook(useSessionModelOptions, { wrapper: wrapper(undefined, mode !== "unsupported"),
    initialProps: { ...props(), disabled: mode === "temporary" } });
  act(() => view.result.current.select(chosen));
  expect(view.result.current.data).toBeNull();
  expect(view.result.current.sendValue()).toBeUndefined();
  expect(localStorage.length).toBe(0);
  expect(api.fetchProviderModels).not.toHaveBeenCalled();
});
