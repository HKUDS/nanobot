import { act, cleanup, renderHook } from "@testing-library/react";
import type { TFunction } from "i18next";
import { afterEach, expect, it, vi } from "vitest";
import { useCapabilitySettingsActions } from "@/components/settings/capabilities/useCapabilitySettingsActions";
import { useCapabilitySettingsState } from "@/components/settings/capabilities/useCapabilitySettingsState";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { SettingsPayload } from "@/lib/types";
import { settingsPayload } from "@/tests/settings-test-utils";

afterEach(cleanup);

it.each(["image", "voice", "safety", "web"] as const)("keeps a newer %s draft when an earlier save completes", async (section) => {
  const payload = settingsPayload();
  let finish!: (value: SettingsPayload) => void;
  const client = { requestMutation: vi.fn(() => new Promise<SettingsPayload>((resolve) => { finish = resolve; })) } as unknown as NanobotClient;
  const { result } = renderHook(() => {
    const state = useCapabilitySettingsState(payload);
    const actions = useCapabilitySettingsActions({
      state, settings: payload, client, t: ((key: string) => key) as TFunction,
      applyPayload: vi.fn(), maybeRestartHostEngine: async () => {},
      setPendingRestartSections: vi.fn(), installCapabilities: async () => true,
      imageGenerationDirty: true, transcriptionDirty: true, networkSafetyDirty: true,
    });
    return { state, actions };
  });
  let pending!: Promise<void>;
  act(() => {
    pending = section === "image" ? result.current.actions.saveImageGenerationSettings()
      : section === "voice" ? result.current.actions.saveTranscriptionSettings()
      : section === "safety" ? result.current.actions.saveNetworkSafetySettings()
      : result.current.actions.saveWebSearch();
  });
  act(() => {
    const state = result.current.state;
    if (section === "image") state.setImageGenerationForm((form) => ({ ...form, model: "new-model" }));
    if (section === "voice") state.setTranscriptionForm((form) => ({ ...form, model: "new-model" }));
    if (section === "safety") state.setNetworkSafetyForm((form) => ({ ...form, webuiAllowLocalServiceAccess: false }));
    if (section === "web") {
      state.setWebSearchForm((form) => ({ ...form, timeout: 45, apiKey: "new-key" }));
      state.setWebSearchKeyEditing(true);
      state.setWebSearchKeyVisible(true);
    }
  });
  await act(async () => { finish(payload); await pending; });
  const state = result.current.state;
  if (section === "image") expect(state.imageGenerationForm.model).toBe("new-model");
  if (section === "voice") expect(state.transcriptionForm.model).toBe("new-model");
  if (section === "safety") expect(state.networkSafetyForm.webuiAllowLocalServiceAccess).toBe(false);
  if (section === "web") {
    expect(state.webSearchForm).toMatchObject({ timeout: 45, apiKey: "new-key" });
    expect(state.webSearchKeyEditing).toBe(true);
    expect(state.webSearchKeyVisible).toBe(true);
  }
});
