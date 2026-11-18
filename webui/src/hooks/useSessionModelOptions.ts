import { useCallback, useEffect, useRef, useState } from "react";

import { useProviderModelCatalog } from "@/hooks/useProviderModelCatalog";
import { reasoningEffortValues } from "@/lib/provider-model-catalog";
import type { SessionModelOptions, SettingsPayload } from "@/lib/types";
import { useClient } from "@/providers/ClientProvider";

const NO_PROVIDER = {};
const PREFIX = "nanobot.model-options.v1.";
const INHERIT: SessionModelOptions = { reasoning_effort: null, codex_fast_mode: null };
type Preference = { preset: string; options: SessionModelOptions };
const preferenceKey = (host: string, session: string | null) => `${PREFIX}${JSON.stringify([host, session])}`;

function readPreference(key: string): Preference | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null");
    const options = value?.options;
    return typeof value?.preset === "string" && options
      && (options.reasoning_effort === null || typeof options.reasoning_effort === "string")
      && (options.codex_fast_mode === null || typeof options.codex_fast_mode === "boolean" || options.codex_fast_mode === "ultrafast")
      ? { preset: value.preset, options: { reasoning_effort: options.reasoning_effort, codex_fast_mode: options.codex_fast_mode } } : null;
  } catch { return null; }
}

function storePreference(key: string, value: Preference | null) {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value));
    else localStorage.removeItem(key);
  } catch { /* Browser preferences must not block sending. */ }
}

/** Browser-only choices; the ordinary send is the only gateway persistence boundary. */
export function useSessionModelOptions({ sessionKey, preset, settings, open, disabled, storedValue }: {
  sessionKey: string | null;
  preset: string;
  settings: SettingsPayload | null;
  open: boolean;
  disabled: boolean;
  storedValue?: SessionModelOptions;
}) {
  const { client, token, webuiCapabilities } = useClient();
  const enabled = !disabled && settings !== null && webuiCapabilities.includes("webui.model-options.v1");
  const host = client.preferenceScope;
  const key = preferenceKey(host, sessionKey);
  const entries = useRef(new Map<string, Preference | null>());
  const [, redraw] = useState(0);
  if (!entries.current.has(key)) entries.current.set(key, readPreference(key));
  const saved = entries.current.get(key);
  const localOptions = saved?.preset === preset ? saved.options : undefined;
  const value = localOptions ?? storedValue ?? INHERIT;
  const pending = useRef(new Map<string, Preference | null>());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flush = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    pending.current.forEach((entry, entryKey) => storePreference(entryKey, entry));
    pending.current.clear();
  }, []);
  const remember = useCallback((entryKey: string, entry: Preference | null) => {
    entries.current.set(entryKey, entry);
    pending.current.set(entryKey, entry);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(flush, 250);
    redraw((revision) => revision + 1);
  }, [flush]);
  useEffect(() => {
    if (enabled && saved && saved.preset !== preset) remember(key, null);
  }, [enabled, key, preset, remember, saved]);
  useEffect(() => {
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, [flush]);

  const configuration = settings?.model_presets.find((entry) => entry.name === preset);
  const capability = configuration?.model_options;
  const providerName = configuration?.resolved_provider ?? configuration?.provider;
  const provider = settings?.providers.find((entry) => entry.name === providerName);
  const model = configuration?.model ?? "";
  const canLoadCatalog = enabled && !!capability && !!model && !!provider?.configured && provider.model_catalog !== "unsupported";
  const { payload, loading, failed } = useProviderModelCatalog({
    revision: provider ?? NO_PROVIDER, token, provider: provider?.name ?? "",
    enabled: canLoadCatalog && open,
  });
  const efforts = reasoningEffortValues(payload, model, capability?.reasoning_effort.values);
  // The popover renders its contents before it starts the lazy catalog request.
  const effortsPending = canLoadCatalog && (loading || (!payload && !failed));
  const select = useCallback((options: SessionModelOptions) => {
    if (enabled) remember(key, { preset, options });
  }, [enabled, key, preset, remember]);
  const reset = useCallback((nextPreset: string) => {
    if (enabled) remember(key, { preset: nextPreset, options: INHERIT });
  }, [enabled, key, remember]);
  const moveToSession = useCallback((target: string, sentValue: SessionModelOptions | undefined) => {
    if (!enabled || sessionKey || !sentValue) return;
    const targetKey = preferenceKey(host, target);
    const targetChoice = entries.current.get(targetKey) ?? readPreference(targetKey);
    if (!targetChoice) remember(targetKey, { preset, options: sentValue });
    remember(key, null);
    // A completed draft must not be resurrected by a reload before the debounce fires.
    flush();
  }, [enabled, flush, host, key, preset, remember, sessionKey]);

  // The Gateway owns persisted options. Omission preserves them; null fields explicitly clear them.
  const sendValue = useCallback(() => enabled ? localOptions : undefined, [enabled, localOptions]);
  return {
    data: enabled && capability ? { value, capability, efforts, effortsPending } : null,
    select, reset, moveToSession, sendValue,
  };
}
