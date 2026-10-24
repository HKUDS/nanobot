import { useCallback, useEffect, useRef, useState } from "react";

import { useProviderModelCatalog } from "@/hooks/useProviderModelCatalog";
import { reasoningEffortValues } from "@/lib/provider-model-catalog";
import type { SettingsPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

const NO_PROVIDER = {};
const PREFIX = "nanobot.reasoning-effort.v1.";
type Preference = { preset: string; value: string | null };
function readPreference(key: string): Preference | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null");
    return value && typeof value.preset === "string" && (value.value === null || typeof value.value === "string") ? value : null;
  } catch { return null; }
}
function storePreference(key: string, value: Preference | null) {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch { /* Browser preferences must not block sending. */ }
}

export function useSessionReasoningEffort({ sessionKey, preset, settings, open, disabled, storedValue }: {
  sessionKey: string | null;
  preset: string;
  settings: SettingsPayload | null;
  open: boolean;
  disabled: boolean;
  storedValue?: string | null;
}) {
  const { client, token, webuiCapabilities } = useClient();
  const enabled = !disabled && webuiCapabilities.includes("webui.reasoning-effort.v1");
  const key = `${PREFIX}${JSON.stringify([client.preferenceScope, sessionKey ?? "new"])}`;
  const scope = JSON.stringify([key, preset]);
  const saved = readPreference(key);
  const [choice, setChoice] = useState<{ scope: string; value: string | null } | null>(null);
  const value = choice?.scope === scope ? choice.value : saved?.preset === preset ? saved.value : storedValue;
  const latest = useRef(value);
  latest.current = value;
  const pending = useRef<{ key: string; value: Preference; timer: ReturnType<typeof setTimeout> } | null>(null);
  const flush = useCallback(() => {
    if (!pending.current) return;
    clearTimeout(pending.current.timer);
    storePreference(pending.current.key, pending.current.value);
    pending.current = null;
  }, []);
  useEffect(() => {
    if (!enabled) return;
    const previous = readPreference(key);
    if (previous && previous.preset !== preset) storePreference(key, null);
  }, [enabled, key, preset]);
  useEffect(() => {
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, [flush, scope]);

  const configuration = settings?.model_presets.find((entry) => entry.name === preset);
  const providerName = configuration?.resolved_provider ?? configuration?.provider ?? settings?.agent.resolved_provider ?? settings?.agent.provider;
  const provider = settings?.providers.find((entry) => entry.name === providerName);
  const model = configuration?.model ?? settings?.agent.model ?? "";
  const { payload } = useProviderModelCatalog({
    revision: provider ?? NO_PROVIDER, token, provider: provider?.name ?? "",
    enabled: enabled && open && !!model && !!provider?.configured && provider.model_catalog !== "unsupported",
  });
  const options = reasoningEffortValues(payload, model, configuration?.reasoning_effort_values);
  const presetValue = (configuration ? configuration.reasoning_effort : settings?.agent.reasoning_effort) ?? null;
  const select = useCallback((next: string) => {
    if (!enabled || !options.includes(next)) return;
    latest.current = next;
    setChoice({ scope, value: next });
    if (pending.current) clearTimeout(pending.current.timer);
    pending.current = { key, value: { preset, value: next }, timer: setTimeout(flush, 250) };
  }, [enabled, flush, key, options, preset, scope]);
  const reset = useCallback((nextPreset: string) => {
    flush();
    storePreference(key, { preset: nextPreset, value: null });
    setChoice({ scope: JSON.stringify([key, nextPreset]), value: null });
    latest.current = null;
  }, [flush, key]);
  const moveToSession = useCallback((target: string, sentValue: string | null | undefined) => {
    if (!enabled || sessionKey) return;
    if (pending.current?.key === key) {
      clearTimeout(pending.current.timer);
      pending.current = null;
    }
    const targetKey = `${PREFIX}${JSON.stringify([client.preferenceScope, target])}`;
    if (!readPreference(targetKey)) storePreference(targetKey, { preset, value: sentValue ?? null });
    storePreference(key, null);
    setChoice((current) => current?.scope === scope ? null : current);
  }, [client, enabled, key, preset, scope, sessionKey]);

  return {
    enabled,
    data: enabled ? { options, value: value ?? null, presetValue } : null,
    select, reset, moveToSession,
    sendValue: () => enabled ? latest.current : undefined,
  };
}
