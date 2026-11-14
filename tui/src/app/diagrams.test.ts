import { afterEach, expect, spyOn, test } from "bun:test"
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
const nativeFontsAvailable = process.platform === "darwin" || existsSync("C:/Windows/Fonts/msyh.ttc")

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

test.skipIf(!nativeFontsAvailable)("viewer preserves preview footprint, transcript position and draft; session reset releases images", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  app.accept({ event: "delta", chat_id: "chat", text: content })
  app.accept({ event: "stream_end", chat_id: "chat", text: content })
  await setup.flush()
  await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
  await setup.flush()
  const preview = images(transcript.root)[0]!
  const render = spyOn(transcript.diagrams.jobs, "render")
  const raster = spyOn(transcript.diagrams.jobs, "raster")
  const height = transcript.root.scrollHeight
  const top = transcript.root.scrollTop
  const composer = setup.renderer.root.findDescendantById("nanobot-tui-composer") as TextareaRenderable
  composer.setText("keep draft 中文")
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  await setup.flush()
  expect(transcript.root.scrollHeight).toBe(height)
  expect(images(transcript.root)[0]).toBe(preview)
  expect(preview.visible).toBe(false)
  await waitUntil(() => images(transcript.diagrams.viewer.root).some(image => image.image !== null), 5000)
  await setup.flush()
  const dialogImage = images(transcript.diagrams.viewer.root)[0]
  const rasters = raster.mock.calls.length
  expect(raster).not.toHaveBeenCalled()
  setup.renderer.copyToClipboardOSC52 = () => true
  setup.mockInput.pressKey("c")
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("Source copied")
  setup.mockInput.pressKey("q")
  await setup.flush()
  expect(images(transcript.root)[0]).toBe(preview)
  expect(preview.visible).toBe(true)
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  expect(images(transcript.diagrams.viewer.root)[0]).toBe(dialogImage)
  expect(setup.captureCharFrame()).toContain("100% fit")
  expect(render).not.toHaveBeenCalled()
  expect(raster.mock.calls.length).toBe(rasters)
  setup.mockInput.pressKey("q")
  await setup.flush()
  render.mockRestore()
  raster.mockRestore()
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

test.skipIf(!nativeFontsAvailable)("inline image uses real terminal pixels without upscaling small diagrams", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  Object.defineProperty(setup.renderer, "resolution", { value: { width: 1300, height: 1008 } })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  app.accept({ event: "stream_end", chat_id: "chat", text: content })
  await setup.flush()
  await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
  await setup.flush()
  const image = images(transcript.root)[0]!
  expect(image.width).toBeLessThan(80)
  expect(image.image!.width).toBe(image.width * 13)
  expect(image.image!.height).toBe(image.height * 24)
  expect(image.height).toBeLessThanOrEqual(24)
}, 10_000)


test.skipIf(!nativeFontsAvailable)("source-only and cancelled viewer release the shared worker; image demand resumes explicitly", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  const spawn = spyOn(Bun, "spawn")
  try {
    app.accept({ event: "stream_end", chat_id: "chat", text: content })
    await setup.flush()
    await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
    const first = spawn.mock.results[0]!.value as Bun.Subprocess
    setup.mockInput.pressKey("\x07")
    await setup.flush()
    await waitUntil(() => images(transcript.diagrams.viewer.root).some(image => image.image !== null), 5000)
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(first.killed).toBe(false)
    setup.mockInput.pressKey("s")
    await setup.flush()
    await first.exited
    expect(first.killed).toBe(true)
    setup.mockInput.pressKey("+")
    await setup.flush()
    expect(spawn).toHaveBeenCalledTimes(1)
    setup.mockInput.pressKey("s")
    await setup.flush()
    setup.mockInput.pressKey("+")
    await setup.flush()
    await waitUntil(() => spawn.mock.calls.length === 2 && transcript.diagrams.jobs.idle, 5000)
    const second = spawn.mock.results[1]!.value as Bun.Subprocess
    expect(second.killed).toBe(false)
    setup.mockInput.pressKey("x")
    await setup.flush()
    await second.exited
    expect(second.killed).toBe(true)
    expect(setup.captureCharFrame()).toContain("Rendering cancelled")
    expect(setup.captureCharFrame()).toContain("A[中文长标签 English]")
    setup.mockInput.pressKey("s")
    await setup.flush()
    await waitUntil(() => images(transcript.diagrams.viewer.root).some(image => image.image !== null), 5000)
    await setup.flush()
    expect(setup.captureCharFrame()).toContain("150% fit")
    expect(spawn).toHaveBeenCalledTimes(3)
    transcript.reset({ workspace: "next session", version: "test" })
    expect(transcript.diagrams.layouts.retainedBytes).toBe(0)
  } finally { transcript.diagrams.jobs.dispose(); spawn.mockRestore() }
}, 20_000)


test.skipIf(!nativeFontsAvailable)("offscreen return and cell-height changes reuse SVG; theme and session changes invalidate it", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  const resolution = { width: 1000, height: 840 }
  Object.defineProperty(setup.renderer, "resolution", { value: resolution })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  app.accept({ event: "stream_end", chat_id: "chat", text: content })
  await setup.flush()
  await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
  await setup.flush()
  const render = spyOn(transcript.diagrams.jobs, "render")
  const raster = spyOn(transcript.diagrams.jobs, "raster")
  try {
    const bytes = transcript.diagrams.layouts.retainedBytes
    app.accept({ event: "stream_end", chat_id: "chat", text: Array.from({ length: 60 }, (_, i) => `Paragraph ${i}\n`).join("\n") })
    await setup.flush()
    expect(images(transcript.root)).toHaveLength(0)
    expect(transcript.diagrams.layouts.retainedBytes).toBe(bytes)
    transcript.root.scrollTo(0)
    await setup.flush()
    await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
    await setup.flush()
    expect(render).not.toHaveBeenCalled()
    expect(raster).toHaveBeenCalledTimes(1)
    resolution.height = 1008
    setup.renderer.requestRender()
    await setup.flush()
    await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
    expect(render).not.toHaveBeenCalled()
    expect(raster).toHaveBeenCalledTimes(2)
    expect(transcript.diagrams.layouts.retainedBytes).toBe(bytes)
    transcript.diagrams.setTheme({ ...transcript.diagrams.colors(), accent: "#dd8800" })
    expect(transcript.diagrams.layouts.retainedBytes).toBe(0)
    await setup.flush()
    await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
    expect(render).toHaveBeenCalledTimes(1)
    transcript.reset({ workspace: "next session", version: "test" })
    expect(transcript.diagrams.layouts.retainedBytes).toBe(0)
  } finally { render.mockRestore(); raster.mockRestore() }
}, 20_000)


test.skipIf(!nativeFontsAvailable)("viewer navigation releases old layout pins under the real transcript budget", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  Object.defineProperty(setup.renderer, "resolution", { value: { width: 1000, height: 840 } })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  for (let index = 0; index < 8; index++) {
    const source = `flowchart TD\n${Array.from({ length: 40 }, (_, i) => `A${i}["数据库请求处理权限验证任务执行记录完成 ${index}-${i}"]`).join("\n")}\n${Array.from({ length: 39 }, (_, i) => `A${i} --> A${i + 1}`).join("\n")}`
    app.accept({ event: "stream_end", chat_id: "chat", text: `Graph ${index + 1}\n\n\`\`\`mermaid\n${source}\n\`\`\`\n\nEnd of graph ${index + 1}` })
  }
  await setup.flush()
  await waitUntil(() => images(transcript.root).some(image => image.image !== null), 5000)
  const preview = images(transcript.root)[0]!
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  const note = setup.renderer.root.findDescendantById("diagrams-note") as TextRenderable
  const ready = () => images(transcript.diagrams.viewer.root).some(image => image.image !== null)
    || note.content.chunks.some(chunk => chunk.text.includes("original source"))
  await waitUntil(ready, 5000)
  expect(images(transcript.diagrams.viewer.root)).toHaveLength(1)
  for (const direction of ["[", "]"]) {
    for (let index = 0; index < 7; index++) {
      setup.mockInput.pressKey(direction)
      await setup.flush()
      await waitUntil(ready, 5000)
      expect(images(transcript.diagrams.viewer.root)).toHaveLength(1)
      expect(transcript.diagrams.layouts.retainedBytes).toBeLessThanOrEqual(4_000_000)
    }
  }
  expect(preview.visible).toBe(false)
  setup.mockInput.pressKey("q")
  await setup.flush()
  expect(images(transcript.root)[0]).toBe(preview)
  expect(preview.visible).toBe(true)
}, 25_000)


test.skipIf(!nativeFontsAvailable)("source/image retry after a parser failure keeps the original source visible", async () => {
  setup = await createTestRenderer({ width: 100, height: 42 })
  Object.defineProperty(setup.renderer, "capabilities", { value: { kitty_graphics: true, multiplexer: "none", image_protocol: "auto" } })
  const app = mount(setup)
  const transcript = (app as unknown as { transcript: Transcript }).transcript
  app.accept({ event: "stream_end", chat_id: "chat", text: "```mermaid\ngraph TD\n A -->\n```" })
  await setup.flush()
  setup.mockInput.pressKey("\x07")
  await setup.flush()
  const sourceScroll = setup.renderer.root.findDescendantById("diagrams-source-scroll")!
  await waitUntil(() => sourceScroll.visible && transcript.diagrams.jobs.idle, 5000)
  setup.mockInput.pressKey("s")
  await setup.flush()
  await waitUntil(() => sourceScroll.visible && transcript.diagrams.jobs.idle, 5000)
  await setup.flush()
  expect(setup.captureCharFrame()).toContain("original source")
  expect(setup.captureCharFrame()).toContain("A -->")
}, 15_000)
