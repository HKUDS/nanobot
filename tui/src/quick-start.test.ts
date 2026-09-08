import { afterEach, expect, test } from "bun:test"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import { ConfigEditor, type ConfigEditorOptions } from "./config-editor"
import { configSnapshot } from "./config-editor-fixture"

const theme = { text: "#eeeeee", muted: "#aaaaaa", faint: "#888888", border: "#555555",
  accent: "#ff8800", success: "#00ff00", error: "#ff0000", selectedBackground: "#222222" }
let setup: TestRendererSetup
let editor: ConfigEditor

afterEach(() => { editor?.destroy(); setup?.renderer.destroy() })

async function mount(options: Partial<ConfigEditorOptions>, width = 88) {
  setup = await createTestRenderer({ width, height: 24, screenMode: "alternate-screen" })
  editor = new ConfigEditor(setup.renderer, theme, {
    load: async () => configSnapshot(), save: async () => configSnapshot(), ...options,
  })
  setup.renderer.root.add(editor.root)
  setup.renderer.keyInput.on("keypress", (key) => { if (editor.handleKey(key)) key.preventDefault() })
  editor.resize(width, 24)
  await editor.show(true)
  await settle()
}

async function settle() { await Bun.sleep(50); await setup.renderOnce() }

async function choose(label: string) {
  setup.mockInput.pressKey("\u001b[H")
  for (let i = 0; i < 80; i++) {
    await setup.renderOnce()
    if (setup.captureCharFrame().split("\n").some((line) => line.includes(`› ${label}`))) {
      setup.mockInput.pressEnter()
      await settle()
      return
    }
    setup.mockInput.pressKey("\u001b[B")
  }
  throw new Error(`Missing action: ${label}\n${setup.captureCharFrame()}`)
}

test("Quick start saves a masked API connection, then explicitly selects a default without deleting presets", async () => {
  let snapshot = configSnapshot()
  snapshot.config.modelPresets = { existing: { model: "old-model", provider: "anthropic" } }
  const saved: Record<string, unknown>[] = []
  await mount({
    load: async () => snapshot,
    read: async (path) => path.includes("provider-models")
      ? { models: [{ id: "claude-next", label: "Claude Next" }] }
      : { providers: [{ name: "anthropic", label: "Anthropic", auth_type: "api_key", api_key_required: true, default_api_base: "https://api.anthropic.com" }] },
    save: async (_revision, config) => {
      saved.push(structuredClone(config))
      snapshot = { ...snapshot, config: structuredClone(config), revision: `r${saved.length}` }
      return snapshot
    },
  })
  await choose("Use an API key")
  await choose("Anthropic")
  await choose("API key")
  await setup.mockInput.typeText("secret-for-setup")
  await setup.renderOnce()
  expect(setup.captureCharFrame()).not.toContain("secret-for-setup")
  setup.mockInput.pressEnter()
  await settle()
  await choose("Save connection and choose a model")
  expect(saved).toHaveLength(1)
  expect(saved[0]).toMatchObject({ agents: { defaults: { model: "anthropic/claude-test" } } })
  await choose("Claude Next")
  expect(setup.captureCharFrame()).toContain("4/4 Review and save")
  await choose("Save as default model")
  expect(saved).toHaveLength(2)
  expect(saved[1]).toMatchObject({
    agents: { defaults: { model: "claude-next", provider: "anthropic", modelPreset: null } },
    modelPresets: { existing: { model: "old-model" } },
    channels: { telegram: { token: null } },
  })
  expect(setup.captureCharFrame()).toContain("Start a new chat")
})

test.each(["callback_url", "authorization_code", "device_code"])("Quick start completes %s OAuth without entering an API key", async (input) => {
  const requests: Array<{ action: string; payload: Record<string, unknown> }> = []
  const provider = { name: "openai_codex", label: "Account provider", auth_type: "oauth", oauth_login_supported: true }
  await mount({
    read: async () => ({ providers: [provider] }),
    request: async (action, payload) => {
      requests.push({ action, payload })
      if (action.endsWith("oauth_login")) return { status: "authorization_required", flow_id: "flow-1",
        authorization_url: "https://example.test/authorize", completion_input: input, user_code: input === "device_code" ? "ABCD-EFGH" : "" }
      return { providers: [{ ...provider, configured: true }] }
    },
    openUrl: async (url) => { expect(url).toBe("https://example.test/authorize") },
  }, 64)
  await choose("Sign in with an account")
  await choose("Account provider")
  expect(setup.captureCharFrame()).not.toContain("› API key")
  await choose("Sign in to")
  if (input === "device_code") expect(setup.captureCharFrame()).toContain("ABCD-EFGH")
  await choose("Open sign-in page")
  if (input === "device_code") { await Bun.sleep(1600); await settle() }
  else {

    await choose(input === "callback_url" ? "Paste callback URL" : "Paste authorization code")
    await setup.mockInput.typeText("secret-authorization-response")
    await setup.renderOnce()
    expect(setup.captureCharFrame()).not.toContain("secret-authorization-response")
    setup.mockInput.pressEnter()
    await settle()
  }
  expect(requests[0]).toMatchObject({ action: "settings.provider.oauth_login", payload: { remote_browser: true, interactive_flow: true } })
  expect(requests[1]).toMatchObject({ action: "settings.provider.oauth_complete", payload: { flow_id: "flow-1" } })
  expect(setup.captureCharFrame()).toContain("3/4 Choose a model")
})

test("leaving OAuth setup cancels only its own pending flow", async () => {
  const requests: Record<string, unknown>[] = []
  await mount({
    read: async () => ({ providers: [{ name: "xai_grok", label: "Grok", auth_type: "oauth", oauth_login_supported: true }] }),
    request: async (_action, payload) => {
      requests.push(payload)
      return { status: "authorization_required", flow_id: "my-flow", authorization_url: "https://example.test/login", completion_input: "authorization_code" }
    },
  })
  await choose("Sign in with an account")
  await choose("Grok")
  await choose("Sign in to")
  setup.mockInput.pressKey("\u001b")
  await settle()
  expect(requests.at(-1)).toEqual({ provider: "xai_grok", flow_id: "my-flow", cancel: true })
})

test("model discovery failure retains manual entry and failed save stays reviewable", async () => {
  await mount({
    read: async (path) => {
      if (path.includes("provider-models")) throw new Error("Model service unavailable")
      return { providers: [{ name: "openai_codex", label: "Connected provider", configured: true, auth_type: "oauth" }] }
    },
    save: async () => { throw new Error("Configuration changed. Reload before saving.") },
  })
  await choose("Sign in with an account")
  await choose("Connected provider")
  expect(setup.captureCharFrame()).toContain("Model service unavailable")
  await choose("Enter a model ID")
  await setup.mockInput.typeText("my-model")
  setup.mockInput.pressEnter()
  await settle()
  await choose("Save as default model")
  expect(setup.captureCharFrame()).toContain("Reload before saving")
  expect(setup.captureCharFrame()).toContain("4/4 Review and save")
})


test("provider search filters while typing and keeps results bounded", async () => {
  await mount({ read: async () => ({ providers: Array.from({ length: 30 }, (_, i) => ({
    name: `provider-${i}`, label: `Service ${String(i).padStart(2, "0")}`, auth_type: "api_key",
  })) }) })
  await choose("Use an API key")
  expect(setup.captureCharFrame()).toContain("More results (8/30)")
  expect(setup.captureCharFrame()).not.toContain("Service 09")
  await setup.mockInput.typeText("29")
  await settle()
  expect(setup.captureCharFrame()).toContain("Service 29")
  expect(setup.captureCharFrame()).not.toContain("Service 00")
  setup.mockInput.pressEnter()
  await settle()
  expect(setup.captureCharFrame()).toContain("Service 29")
  expect(setup.captureCharFrame()).toContain("2/4 Connect")
})

test("a saved default skips setup and changing models reuses credentials", async () => {
  const snapshot = configSnapshot()
  const defaults = (snapshot.config.agents as { defaults: Record<string, unknown> }).defaults
  defaults.provider = "anthropic"
  await mount({ load: async () => snapshot, read: async (path) => path.includes("provider-models")
    ? { models: [{ id: "new-model", label: "New model" }] }
    : { providers: [{ name: "anthropic", label: "Anthropic", configured: true }] } })
  expect(setup.captureCharFrame()).toContain("Continue chatting")
  expect(setup.captureCharFrame()).not.toContain("settings ·")
  await choose("Change model")
  expect(setup.captureCharFrame()).toContain("New model")
  expect(setup.captureCharFrame()).not.toContain("API key (optional)")
})

test("local setup lists local servers without mixing in cloud credentials", async () => {
  await mount({ read: async () => ({ providers: [
    { name: "ollama", label: "Ollama", is_local: true },
    { name: "bedrock", label: "AWS Bedrock", api_key_required: false },
  ] }) })
  await choose("Connect a local model")
  expect(setup.captureCharFrame()).toContain("Ollama")
  expect(setup.captureCharFrame()).not.toContain("Bedrock")
})

test("a test message is explicit and failed checks preserve the saved model for recovery", async () => {
  let snapshot = configSnapshot()
  let calls = 0
  await mount({
    load: async () => snapshot,
    save: async (_revision, config) => { snapshot = { ...snapshot, config }; return snapshot },
    read: async (path) => path.includes("provider-models") ? { models: [{ id: "test-model" }] }
      : { providers: [{ name: "anthropic", label: "Anthropic", configured: true }] },
    request: async (action, payload) => {
      expect(action).toBe("settings.provider.test")
      expect(payload).toEqual({ provider: "anthropic", model: "test-model" })
      calls++
      return calls === 1 ? { status: "error", message: "Access denied. Change connection to sign in again." }
        : { status: "ok", message: "Hello!" }
    },
  })
  await choose("Use an API key")
  await choose("Anthropic")
  await choose("test-model")
  await choose("Save as default model")
  expect(calls).toBe(0)
  expect(setup.captureCharFrame()).toContain("not verified")
  await choose("Send a test message")
  expect(setup.captureCharFrame()).toContain("Access denied")
  expect(snapshot.config).toMatchObject({ agents: { defaults: { model: "test-model" } } })
  await choose("Send a test message")
  expect(setup.captureCharFrame()).toContain("Model replied successfully")
  expect(setup.captureCharFrame()).toContain("Hello!")
})

test("automatic callback sign-in opens the browser and advances without a manual check", async () => {
  let callback: ((url: string) => void) | undefined
  let opened = 0
  let stopped = 0
  await mount({
    read: async (path) => path.includes("provider-models") ? { models: [{ id: "hello-model" }] }
      : { providers: [{ name: "openai_codex", label: "Codex", auth_type: "oauth", oauth_login_supported: true }] },
    listenForCallback: (_url, complete) => { callback = complete; return () => { stopped++ } },
    openUrl: async () => { opened++ },
    request: async (action, payload) => action.endsWith("oauth_login")
      ? { status: "authorization_required", flow_id: "callback-flow", authorization_url: "https://example.test/login", completion_input: "callback_url" }
      : payload.authorization_response ? { providers: [{ name: "openai_codex", label: "Codex", configured: true }] }
      : { status: "pending" },
  })
  await choose("Sign in with an account")
  await choose("Codex")
  await choose("Sign in to")
  expect(opened).toBe(1)
  expect(setup.captureCharFrame()).not.toContain("Paste callback URL")
  callback!("http://localhost:1455/auth/callback?code=fake&state=test")
  await settle()
  expect(setup.captureCharFrame()).toContain("hello-model")
  expect(stopped).toBe(1)
})

test("leaving during an in-flight sign-in check ignores its late response", async () => {
  let finish: ((value: unknown) => void) | undefined
  const requests: Record<string, unknown>[] = []
  await mount({
    read: async () => ({ providers: [{ name: "github_copilot", label: "Copilot", auth_type: "oauth", oauth_login_supported: true }] }),
    openUrl: async () => {},
    request: async (action, payload) => {
      requests.push(payload)
      if (action.endsWith("oauth_login")) return { status: "authorization_required", flow_id: "pending-flow", authorization_url: "https://example.test/login", completion_input: "device_code" }
      if (payload.cancel) return { status: "cancelled" }
      return new Promise((resolve) => { finish = resolve })
    },
  })
  await choose("Sign in with an account")
  await choose("Copilot")
  await choose("Sign in to")
  await Bun.sleep(1600)
  expect(finish).toBeDefined()
  setup.mockInput.pressKey("\u001b")
  await settle()
  finish!({ providers: [{ name: "github_copilot", label: "Copilot", configured: true }] })
  await settle()
  expect(setup.captureCharFrame()).toContain("1/4 Choose a provider")
  expect(requests.at(-1)).toMatchObject({ cancel: true, flow_id: "pending-flow" })
})
