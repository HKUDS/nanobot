import { afterEach, expect, test } from "bun:test"
import { existsSync } from "node:fs"
import { ImageRenderable, TextareaRenderable, TextRenderable, type Renderable } from "@opentui/core"
import { createTestRenderer, type TestRendererSetup } from "@opentui/core/testing"
import type { Transcript } from "../rendering/transcript"
import { mount, waitUntil } from "./test-support"

let setup: TestRendererSetup | undefined

afterEach(() => { if (setup && !setup.renderer.isDestroyed) setup.renderer.destroy(); setup = undefined })

function images(root: Renderable): ImageRenderable[] {
  return root.getChildren().flatMap(child => [ ...(child instanceof ImageRenderable ? [child] : []), ...images(child) ])
}

const source = "graph TD\n A[中文长标签 English] --> B[完成]"
const content = `\`\`\`mermaid\n${source}\n\`\`\`\n\nTrailing paragraph`

test("streamed stable Mermaid fences stay source until reply completion, including the viewer", async () => {
  setup = await createTestRenderer({ width: 80, height: 35 })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  app.accept({ event: "delta", chat_id: "chat", text: content })
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("source while replying")
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("Replying · original source")
  expect(images(transcript.diagrams.viewer.root)).toHaveLength(0)
  setup.mockInput.pressKey("q")
  app.accept({ event: "stream_end", chat_id: "chat", text: content })
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("no image protocol")
  expect(setup.captureCharFrame()).toContain("A[中文长标签 English]")
  expect(images(transcript.root)).toHaveLength(0)
})

test.skipIf(!existsSync("C:/Windows/Fonts/msyh.ttc"))("viewer preserves preview footprint, transcript position and draft; session reset releases images", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  app.accept({ event: "delta", chat_id: "chat", text: content })
  app.accept({ event: "stream_end", chat_id: "chat", text: content })
  await setup.flush()
  await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
  await setup.flush()
  const height = transcript.root.scrollHeight
  const top = transcript.root.scrollTop
  const composer = setup.renderer.root.findDescendantById("nanobot-tui-composer") as TextareaRenderable
  composer.setText("keep draft 中文")
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  await setup.flush()
  expect(transcript.root.scrollHeight).toBe(height)
  expect(images(transcript.root)).toHaveLength(0)
  setup.mockInput.pressKey("q")
  await setup.flush()
  await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
  await setup.flush()
  expect(composer.plainText).toBe("keep draft 中文")
  expect(transcript.root.scrollTop).toBe(top)
  expect(transcript.root.scrollHeight).toBe(height)
  transcript.reset({ workspace: "next session", version: "test" })
  await setup.flush()
  expect(images(transcript.root)).toHaveLength(0)
  expect(transcript.diagrams.viewer.visible).toBe(false)
}, 15_000)

test("diagram source copy uses the original fence text and cancelled viewer work stays source", async () => {
  setup = await createTestRenderer({ width: 90, height: 30 })
  const app = mount(setup)
  let copied = ""
  setup.renderer.copyToClipboardOSC52 = text => { copied = text; return true }
  app.accept({ event: "delta", chat_id: "chat", text: content })
  app.accept({ event: "stream_end", chat_id: "chat", text: content })
  await setup.flush()
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  setup.mockInput.pressKey("c")
  await setup.flush()
  expect(copied).toBe(source)
  setup.mockInput.pressKey("x")
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("Rendering cancelled")
  expect(setup.captureCharFrame()).toContain("A[中文长标签 English]")
})

test("diagram command on ordinary Markdown shows an empty viewer and returns to the draft", async () => {
  setup = await createTestRenderer({ width: 80, height: 35 })
  const app = mount(setup)
  app.accept({ event: "stream_end", chat_id: "chat", text: "Ordinary **Markdown**" })
  const composer = setup.renderer.root.findDescendantById("nanobot-tui-composer") as TextareaRenderable
  composer.setText("draft")
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  const header = setup.renderer.root.findDescendantById("diagrams-header") as TextRenderable
  expect(header.content.chunks.map(chunk => chunk.text).join("")).toBe("Mermaid")
  expect(setup.captureCharFrame()).toContain("No Mermaid diagrams in this conversation.")
  expect(setup.captureCharFrame()).toContain("q/esc back")
  setup.mockInput.pressKey("q")
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("draft")
})
