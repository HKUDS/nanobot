import { afterEach, describe, expect, test } from "bun:test"
import { TextareaRenderable } from "@opentui/core"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"

import { ConfigEditor } from "./config-editor"
import { configSnapshot } from "./config-editor-fixture"

async function waitUntil(predicate: () => boolean, timeout = 1_000): Promise<void> {
  const deadline = Date.now() + timeout
  while (!predicate() && Date.now() < deadline) await Bun.sleep(5)
  if (!predicate()) throw new Error(`condition was not met within ${timeout}ms`)
}

const theme = {
  text: "#ECEDEE",
  muted: "#A1A1AA",
  faint: "#71717A",
  border: "#3F3F46",
  accent: "#EF8E30",
  success: "#5CC489",
  error: "#F87171",
  selectedBackground: "#2B2C2E",
}

describe("ConfigEditor", () => {
  let setup: TestRendererSetup | undefined
  let editor: ConfigEditor | undefined

  afterEach(() => {
    editor?.destroy()
    if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy()
    setup = undefined
    editor = undefined
  })

  test("keeps essentials on the first screen and finds folded advanced settings", async () => {
    setup = await createTestRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    editor = new ConfigEditor(setup.renderer, theme, {
      load: async () => configSnapshot(),
      save: async () => configSnapshot(),
    })
    setup.renderer.root.add(editor.root)
    setup.renderer.keyInput.on("keypress", (key) => {
      if (editor?.handleKey(key)) key.preventDefault()
    })

    await editor.show()
    await setup.renderOnce()
    const essentials = setup.captureCharFrame()
    expect(essentials).toContain("Configuration · Essentials")
    expect(essentials).toContain("Workspace")
    expect(essentials).toContain("API key")
    expect(essentials).toContain("Models and providers")
    expect(essentials).not.toContain("Max tokens")

    setup.mockInput.pressKey("/")
    await setup.mockInput.typeText("max tokens")
    setup.mockInput.pressEnter()
    await setup.renderOnce()
    const search = setup.captureCharFrame()
    expect(search).toContain("Configuration · Search · max tokens")
    expect(search).toContain("Max tokens")
  })

  test("stages edits, saves the full draft, and hides secret input", async () => {
    setup = await createTestRenderer({ width: 88, height: 24, screenMode: "alternate-screen" })
    const saved: Array<{ revision: string; config: Record<string, unknown> }> = []
    editor = new ConfigEditor(setup.renderer, theme, {
      load: async () => configSnapshot(),
      save: async (revision, config) => {
        saved.push({ revision, config })
        return {
          ...configSnapshot(),
          revision: "revision-2",
          config,
          requires_restart: true,
        }
      },
    })
    setup.renderer.root.add(editor.root)
    setup.renderer.keyInput.on("keypress", (key) => {
      if (editor?.handleKey(key)) key.preventDefault()
    })
    await editor.show()
    await setup.renderOnce()

    setup.mockInput.pressKey("/")
    await setup.mockInput.typeText("max tokens")
    setup.mockInput.pressEnter()
    await setup.renderOnce()
    setup.mockInput.pressKey("\u001B[B")
    await setup.renderOnce()
    setup.mockInput.pressEnter()
    await setup.renderOnce()
    const state = editor as unknown as {
      editorInput: TextareaRenderable
      editPurpose: string | null
      selected: number
      rows: Array<{ kind: string }>
    }
    expect(state.rows.map((row) => row.kind)).toEqual(["back", "field"])
    expect(state.selected).toBe(1)
    expect(state.editPurpose).toBe("field")
    const input = state.editorInput
    input.setText("4096")
    input.submit()
    await setup.flush()
    expect((editor as unknown as { dirty: Set<string> }).dirty.size).toBe(1)
    setup.mockInput.pressKey("s", { ctrl: true })
    await waitUntil(() => saved.length === 1)

    expect(saved[0]?.revision).toBe("revision-1")
    expect(saved[0]?.config).toMatchObject({
      agents: { defaults: { maxTokens: 4096, model: "anthropic/claude-test" } },
      channels: { telegram: { token: null } },
    })

    setup.mockInput.pressKey("/")
    input.setText("api key")
    input.submit()
    setup.mockInput.pressKey("\u001B[B")
    setup.mockInput.pressEnter()
    await setup.mockInput.typeText("never-render-this-secret")
    await setup.renderOnce()
    const secretFrame = setup.captureCharFrame()
    expect(secretFrame).toContain("New value: •••")
    expect(secretFrame).not.toContain("never-render-this-secret")
  })
})
