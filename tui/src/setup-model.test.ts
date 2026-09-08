import { expect, test } from "bun:test"
import { configSnapshot } from "./config-editor-fixture"
import { decodeSetupProviders, newSetupPreset, setupDraft, setupProviderStatus } from "./setup-model"

test("local OAuth storage never proves a live login, even before token expiry", () => {
  const [provider] = decodeSetupProviders({ providers: [{ name: "xai_grok", label: "Grok",
    auth_type: "oauth", configured: true, oauth_expires_at: Date.now() + 60_000 }] })
  expect(setupProviderStatus(provider!)).toBe("Saved · Not verified")
  expect(setupProviderStatus({ ...provider!, expiresAt: 1 })).toBe("Token expired")
  expect(setupProviderStatus({ ...provider!, expiresAt: null })).toBe("Saved · Not verified")
})

test("named preset saves preserve legacy defaults, secrets, and other presets", () => {
  const snapshot = configSnapshot()
  snapshot.config.modelPresets = { Existing: { model: "original", provider: "anthropic" } }
  const original = structuredClone(snapshot.config)
  const preset = { ...newSetupPreset(snapshot, "openai"), model: "new-model", temperature: 0.7 }
  const draft = setupDraft(snapshot, "Coding / fast", preset, false)
  expect(draft.agents).toEqual(original.agents)
  expect(draft.providers).toEqual(original.providers)
  expect(draft.modelPresets).toEqual({ ...original.modelPresets as object, "Coding / fast": preset })
  expect(snapshot.config).toEqual(original)
  const special = setupDraft(snapshot, "__proto__", preset, false)
  expect(JSON.parse(JSON.stringify(special)).modelPresets.__proto__).toEqual(preset)
  const active = setupDraft(snapshot, "Coding", preset, true)
  expect(active.agents).toMatchObject({ defaults: { model: "anthropic/claude-test", modelPreset: "Coding" } })
})

test("updating a preset requires explicit selection and keeps other generation settings", () => {
  const snapshot = configSnapshot()
  const preset = { ...newSetupPreset(snapshot, "anthropic"), model: "old", reasoningEffort: "high" }
  snapshot.config.modelPresets = { Coding: preset }
  expect(() => setupDraft(snapshot, "coding", preset, true)).toThrow("already exists")
  const result = setupDraft(snapshot, "Coding", { ...preset, model: "new" }, false, "Coding")
  expect(result.modelPresets).toEqual({ Coding: { ...preset, model: "new" } })
})

test("invalid preset names and generation limits cannot be saved", () => {
  const snapshot = configSnapshot()
  const preset = { ...newSetupPreset(snapshot, "anthropic"), model: "test" }
  for (const name of ["", "default", "Default", "line\nbreak", "x".repeat(49)]) {
    expect(() => setupDraft(snapshot, name, preset, true)).toThrow()
  }
  for (const invalid of [{ model: "" }, { maxTokens: 0 }, { contextWindowTokens: 1.5 }, { temperature: 3 }]) {
    expect(() => setupDraft(snapshot, "Coding", { ...preset, ...invalid }, true)).toThrow()
  }
})
