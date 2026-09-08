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
}

export interface SetupModel { id: string; label: string; description: string }
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

/** Select the implicit default without modifying named presets used by other sessions. */
export function setupDraft(snapshot: ConfigEditorSnapshot, provider: string, model: string): Record<string, unknown> {
  const draft = cloneConfig(snapshot.config)
  writeConfigValue(draft, "/agents/defaults/provider", provider)
  writeConfigValue(draft, "/agents/defaults/model", model)
  writeConfigValue(draft, "/agents/defaults/modelPreset", null)
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
