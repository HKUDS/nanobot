import type { ConfigEditorSnapshot } from "./protocol"
import { cloneConfig, readConfigValue, writeConfigValue } from "./config-editor-model"

export interface SetupProvider {
  name: string
  label: string
  oauth: boolean
  configured: boolean
  loginSupported: boolean
  keyRequired: boolean
  baseRequired: boolean
  apiBase: string
  local: boolean
  advancedFields: string[]
}

export interface SetupModel { id: string; label: string; description: string }
export interface SetupPreset {
  provider: string
  model: string
  maxTokens: number
  contextWindowTokens: number
  temperature: number
  reasoningEffort: string | null
}
export interface SetupAuthorization {
  flowId: string
  url: string
  userCode: string
  input: "callback_url" | "authorization_code" | "device_code"
}

export function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

export function decodeSetupProviders(value: unknown): SetupProvider[] {
  if (!record(value) || !Array.isArray(value.providers)) throw new Error("Unable to load providers. Try again.")
  return value.providers.flatMap((row) => {
    if (!record(row) || typeof row.name !== "string" || typeof row.label !== "string"
      || row.model_selectable === false) return []
    return [{
      name: row.name, label: row.label, oauth: row.auth_type === "oauth",
      configured: row.configured === true, loginSupported: row.oauth_login_supported === true,
      keyRequired: row.api_key_required === true,
      baseRequired: row.api_base_required === true,
      local: row.is_local === true,
      advancedFields: Array.isArray(row.advanced_fields) ? row.advanced_fields.filter((field): field is string => typeof field === "string") : [],
      apiBase: typeof row.api_base === "string" && row.api_base ? row.api_base
        : typeof row.default_api_base === "string" ? row.default_api_base : "",
    }]
  }).sort((a, b) => Number(b.configured) - Number(a.configured)
    || Number(b.oauth) - Number(a.oauth) || a.label.localeCompare(b.label))
}

export function decodeSetupModels(value: unknown): { models: SetupModel[]; message: string } {
  if (!record(value) || !Array.isArray(value.models)) throw new Error("Unable to load models. Retry or enter a model ID.")
  return {
    models: value.models.flatMap((row) => record(row) && typeof row.id === "string" ? [{
      id: row.id, label: typeof row.label === "string" && row.label ? row.label : row.id,
      description: typeof row.description === "string" ? row.description : "",
    }] : []),
    message: typeof value.message === "string" ? value.message : "",
  }
}

export function decodeSetupAuthorization(value: unknown): SetupAuthorization | null {
  if (!record(value)) throw new Error("Unable to start sign-in. Try again.")
  if (value.status !== "authorization_required") {
    decodeSetupProviders(value)
    return null
  }
  if (typeof value.flow_id !== "string" || typeof value.authorization_url !== "string"
    || !["callback_url", "authorization_code", "device_code"].includes(String(value.completion_input))) {
    throw new Error("The gateway returned incomplete sign-in instructions. Try again.")
  }
  const url = new URL(value.authorization_url)
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("Invalid sign-in link.")
  return {
    flowId: value.flow_id, url: url.href,
    userCode: typeof value.user_code === "string" ? value.user_code : "",
    input: value.completion_input as SetupAuthorization["input"],
  }
}

export function newSetupPreset(snapshot: ConfigEditorSnapshot, provider: string): SetupPreset {
  const defaults = readConfigValue(snapshot.config, "/agents/defaults")
  const active = readConfigValue(snapshot.config, "/agents/defaults/modelPreset")
  const presets = snapshot.config.modelPresets
  const base = typeof active === "string" && record(presets) && record(presets[active])
    ? presets[active] : record(defaults) ? defaults : {}
  return {
    provider, model: "",
    maxTokens: typeof base.maxTokens === "number" ? base.maxTokens : 8192,
    contextWindowTokens: typeof base.contextWindowTokens === "number" ? base.contextWindowTokens : 200_000,
    temperature: typeof base.temperature === "number" ? base.temperature : 0.1,
    reasoningEffort: null,
  }
}

/** Stage one named preset and its optional default pointer in a single revision-bound save. */
export function setupDraft(snapshot: ConfigEditorSnapshot, name: string, preset: SetupPreset,
  makeDefault: boolean, existingName: string | null = null): Record<string, unknown> {
  name = name.trim()
  if (!name || Array.from(name).length > 48 || /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/u.test(name)) {
    throw new Error("Use a printable preset name of 1–48 characters.")
  }
  if (name.toLocaleLowerCase() === "default") throw new Error("The name default is reserved. Choose another preset name.")
  const presets = record(snapshot.config.modelPresets) ? snapshot.config.modelPresets : {}
  if (existingName !== null && (name !== existingName || !record(presets[existingName]))) {
    throw new Error("Reload the preset before saving. Rename existing presets in Advanced settings.")
  }
  if (Object.keys(presets).some((key) => key !== existingName && key.toLocaleLowerCase() === name.toLocaleLowerCase())) {
    throw new Error("A preset with this name already exists. Select it explicitly or choose a different name.")
  }
  if (!preset.model.trim()) throw new Error("Choose a model for this preset.")
  for (const [label, value] of [["Output token limit", preset.maxTokens], ["Context window", preset.contextWindowTokens]] as const) {
    if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} must be a positive integer.`)
  }
  if (!Number.isFinite(preset.temperature) || preset.temperature < 0 || preset.temperature > 2) {
    throw new Error("Temperature must be between 0 and 2.")
  }
  const draft = cloneConfig(snapshot.config)
  draft.modelPresets = {
    ...(record(draft.modelPresets) ? draft.modelPresets : {}),
    [name]: { ...(existingName && record(presets[existingName]) ? presets[existingName] : {}), ...preset },
  }
  if (makeDefault) writeConfigValue(draft, "/agents/defaults/modelPreset", name)
  return draft
}

export function activeSetupModel(snapshot: ConfigEditorSnapshot): string {
  const preset = readConfigValue(snapshot.config, "/agents/defaults/modelPreset")
  const presets = snapshot.config.modelPresets
  if (typeof preset === "string" && record(presets) && record(presets[preset])) {
    const model = presets[preset].model
    if (typeof model === "string") return model
  }
  return String(readConfigValue(snapshot.config, "/agents/defaults/model") || "No model selected")
}
