import type { ModelPresetOption } from "@/components/thread/ModelPresetBadge";
import { inferProviderFromModelName, providerDisplayLabel } from "@/lib/provider-brand";
import type { SettingsPayload } from "@/lib/types";

function compactModelName(modelName: string | null): string | null {
  if (!modelName) return null;
  const trimmed = modelName.trim();
  if (!trimmed) return null;
  const leaf = trimmed.split("/").pop() ?? trimmed;
  return leaf || trimmed;
}

export interface ModelBadgeInfo {
  label: string | null;
  model: string | null;
  provider: string | null;
  providerLabel: string | null;
  needsSetup: boolean;
}

function modelPresetForBadge(
  settings: SettingsPayload | null,
  scopedPreset: string | null,
): SettingsPayload["model_presets"][number] | null {
  if (!settings) return null;
  const presets = settings.model_presets ?? [];
  if (scopedPreset) {
    return presets.find((preset) => preset.name === scopedPreset) ?? null;
  }
  const configured = settings.agent.model_preset || "default";
  return (
    presets.find((preset) => preset.name === configured)
    ?? presets.find((preset) => preset.active)
    ?? null
  );
}

export function toModelBadgeInfo(
  modelName: string | null,
  settings: SettingsPayload | null,
  modelPreset: string | null = null,
): ModelBadgeInfo {
  const scopedPreset = modelPreset?.trim() || null;
  const preset = modelPresetForBadge(settings, scopedPreset);
  const model = scopedPreset
    ? preset?.model || null
    : settings?.agent.model || modelName || null;
  const label = preset
    ? preset.is_default
      ? preset.label?.trim() || "Default"
      : preset.name.trim()
    : scopedPreset || compactModelName(model);
  const rawProvider = preset?.provider
    || (!scopedPreset ? settings?.agent.provider : null)
    || null;
  const provider = rawProvider === "auto"
    ? preset?.resolved_provider
      || (!scopedPreset ? settings?.agent.resolved_provider : null)
      || null
    : rawProvider || inferProviderFromModelName(model);
  const providerRow = provider
    ? settings?.providers?.find((item) => item.name === provider)
    : null;
  const needsSetup = Boolean(
    settings && (!model || !provider || !providerRow || !providerRow.configured),
  );
  return {
    label,
    model: compactModelName(model),
    provider,
    providerLabel: provider ? providerDisplayLabel(settings?.providers ?? [], provider) : null,
    needsSetup,
  };
}

export function modelPresetOptionsFromSettings(
  settings: SettingsPayload | null,
): ModelPresetOption[] {
  if (!settings) return [];
  const order = new Map(
    (settings.model_call_order ?? []).map((name, index) => [name.trim(), index]),
  );
  return (settings.model_presets ?? [])
    .filter((preset) => !preset.is_default && preset.name.trim())
    .sort((a, b) => (
      (order.get(a.name.trim()) ?? Number.POSITIVE_INFINITY)
      - (order.get(b.name.trim()) ?? Number.POSITIVE_INFINITY)
    ))
    .map((preset) => {
      const name = preset.name.trim();
      return {
        name,
        model: preset.model,
        provider: preset.resolved_provider || preset.provider,
      };
    });
}
