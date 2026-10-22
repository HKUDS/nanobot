import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSettingsController } from "@/components/settings/useSettingsController";
import type { AutomationsPayload, SessionAutomationJob } from "@/lib/types";
import { jsonResponse, settingsPayload } from "@/tests/settings-test-utils";

const mocks = vi.hoisted(() => {
  const events = new Map<string, Set<() => void>>();
  const state = { capabilities: ["webui.state-events.v1"] };
  const mutate = vi.fn();
  const client = {
    status: "open",
    requestMutation: mutate,
    onStatus: (handler: (status: string) => void) => { handler("open"); return () => {}; },
    onStateChange: (resource: string, handler: () => void) => {
      const handlers = events.get(resource) || new Set();
      events.set(resource, handlers);
      handlers.add(handler);
      return () => { handlers.delete(handler); };
    },
  };
  return { client, state, events, mutate, read: vi.fn(), token: () => "synthetic-token" };
});
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({
  client: mocks.client, token: "synthetic-token", getToken: mocks.token, webuiCapabilities: mocks.state.capabilities,
}) }));

const job: SessionAutomationJob = {
  id: "daily-summary", name: "Daily summary", enabled: true,
  schedule: { kind: "every", every_ms: 86_400_000 }, payload: { message: "Summarize updates" },
  state: { next_run_at_ms: 1_800_000_000_000 }, origin: { channel: "websocket", session_key: "websocket:summary" },
};
const pending: AutomationsPayload = { jobs: [{ ...job, state: { ...job.state, pending: true } }] };
const completed: AutomationsPayload = { jobs: [{ ...job, state: {
  ...job.state, pending: false, last_status: "ok", last_run_at_ms: 1_799_999_000_000,
} }] };
const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");

function renderAutomations() {
  const initialSettings = settingsPayload();
  const onModelNameChange = vi.fn();
  return renderHook(() => useSettingsController({ initialSection: "automations", initialSettings, onModelNameChange }));
}

beforeEach(() => {
  vi.useFakeTimers();
  window.localStorage.clear(); window.sessionStorage.clear();
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  mocks.events.clear(); mocks.state.capabilities = ["webui.state-events.v1"];
  mocks.mutate.mockReset().mockResolvedValue(pending);
  mocks.read.mockReset().mockResolvedValue(jsonResponse({ jobs: [job] }));
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => String(input) === "/api/webui/automations"
    ? mocks.read() : Promise.resolve(jsonResponse(settingsPayload()))));
});
afterEach(() => {
  cleanup(); vi.useRealTimers(); vi.unstubAllGlobals();
  if (originalVisibility) Object.defineProperty(document, "visibilityState", originalVisibility);
  else Reflect.deleteProperty(document, "visibilityState");
});

describe("automation settings state refresh", () => {
  it("keeps run acknowledgements and event-delivered completion current without older delayed reads", async () => {
    const { result } = renderAutomations();
    await act(async () => {});
    expect(result.current.systemState.automations?.jobs).toEqual([job]);
    await act(async () => result.current.systemActions.handleAutomationAction("run", job));
    expect(mocks.mutate).toHaveBeenCalledWith("automation.run", { id: job.id }, 20_000);
    expect(result.current.systemState.automations).toEqual(pending);
    expect(result.current.systemState.automationAction).toBeNull();
    mocks.read.mockResolvedValue(jsonResponse(pending)).mockResolvedValueOnce(jsonResponse(completed));
    await act(async () => { for (const handler of mocks.events.get("automations") || []) handler(); });
    expect(result.current.systemState.automations).toEqual(completed);
    await act(async () => { await vi.advanceTimersByTimeAsync(4_999); });
    expect(result.current.systemState.automations).toEqual(completed);
    expect(mocks.read).toHaveBeenCalledTimes(2);
  });

  it("updates a legacy host's run status through its visible five-second refresh", async () => {
    mocks.state.capabilities = [];
    const { result } = renderAutomations();
    await act(async () => {});
    await act(async () => result.current.systemActions.handleAutomationAction("run", job));
    expect(result.current.systemState.automations).toEqual(pending);
    mocks.read.mockResolvedValue(jsonResponse(completed));
    await act(async () => { await vi.advanceTimersByTimeAsync(4_999); });
    expect(mocks.read).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(mocks.read).toHaveBeenCalledTimes(2);
    expect(result.current.systemState.automations).toEqual(completed);
  });

  it.each([true, false])("stops run-status reads after leaving automations (state events: %s)", async (events) => {
    mocks.state.capabilities = events ? ["webui.state-events.v1"] : [];
    const { result } = renderAutomations();
    await act(async () => {});
    await act(async () => result.current.systemActions.handleAutomationAction("run", job));
    act(() => result.current.selectSection("skills"));
    mocks.read.mockResolvedValue(jsonResponse(completed));
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(result.current.activeSection).toBe("skills");
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(result.current.systemState.automations).toEqual(pending);
  });
});
