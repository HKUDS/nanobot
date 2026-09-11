import { afterEach, expect, test } from "bun:test"
import { MarkdownRenderable, SyntaxStyle, TextRenderable } from "@opentui/core"
import { createTestRenderer, MockTreeSitterClient, type TestRendererSetup } from "@opentui/core/testing"

import { StreamingMarkdownRenderable } from "./streaming-markdown"

let setup: TestRendererSetup | undefined
let syntax: SyntaxStyle | undefined

afterEach(() => {
  setup?.renderer.destroy()
  syntax?.destroy()
  setup = undefined
  syntax = undefined
})

async function mount(content = "", streaming = true) {
  setup = await createTestRenderer({ width: 80, height: 24 })
  syntax = SyntaxStyle.fromStyles({ default: { fg: "#eeeeee" } })
  const options = {
    content, streaming, width: "100%" as const, syntaxStyle: syntax,
    fg: "#eeeeee", internalBlockMode: "top-level" as const,
    treeSitterClient: new MockTreeSitterClient({ autoResolveTimeout: 0 }),
  }
  const markdown = new StreamingMarkdownRenderable(setup.renderer, { ...options, id: "optimized" })
  setup.renderer.root.add(markdown)
  return { markdown, options }
}

test("retains the plain text node through streaming updates and rethemes it", async () => {
  const { markdown } = await mount("Hello 中文")
  const node = markdown.getChildren()[0]
  expect(node).toBeInstanceOf(TextRenderable)
  markdown.content += " more words".repeat(100)
  expect(markdown.getChildren()[0]).toBe(node)
  expect(markdown.content).toBe("Hello 中文" + " more words".repeat(100))
  markdown.fg = "#112233"
  expect((node as TextRenderable).fg.toInts()).toEqual([17, 34, 51, 255])
})

test("keeps unformatted text on the same node after completion", async () => {
  const { markdown } = await mount("first")
  const plain = markdown.getChildren()[0]
  markdown.content += " final words"
  markdown.streaming = false
  expect(markdown.content).toBe("first final words")
  expect(markdown.streaming).toBe(false)
  expect(plain?.isDestroyed).toBe(false)
  expect(markdown.getChildren()[0]).toBe(plain)
  expect(setup!.renderer.root.getChildren()[0]).toBe(markdown)
  await setup!.flush()
  expect(setup!.captureCharFrame()).toContain("first final words")
  markdown.content += " reconciled"
  expect(markdown.getChildren()[0]).toBe(plain)
  expect(markdown.content).toBe("first final words reconciled")
})

test.each([
  "plain words and 中文，内容。",
  "1. ordered item",
  "1) ordered item",
  "1.",
  "first\n2) ordered item",
  "first\n2.\nthird",
  "    indented code",
  "# heading",
  "first\n---",
  "first\nsecond",
  "first\n\nsecond",
  "first\n\n\nsecond",
  "first\n",
  "first\n\n",
  "first  \nsecond",
  "first\n===",
  "first\n- item",
  "first\n+ item",
  "first\n1. ordered item",
  "first\n    indented line",
  "The equation is x² + y² = z².\n\nThe equation is $x^2 + y^2",
  "Prices are $5 (USD) and $6.",
  "Hello **bold** and _emphasis_",
  "[link](https://example.com)",
  "https://example.com",
  "www.example.com",
  "user@example.com",
  "Hello &amp; world",
  "Hello 🚀",
  "Hello\tworld",
  "first\rsecond",
])("matches the Markdown renderer for %s", async (content) => {
  const { markdown, options } = await mount(content)
  await setup!.flush()
  const actual = setup!.captureCharFrame()
  const spans = setup!.captureSpans()
  setup!.renderer.root.remove(markdown)
  markdown.destroyRecursively()
  const reference = new MarkdownRenderable(setup!.renderer, { ...options, id: "reference" })
  setup!.renderer.root.add(reference)
  await setup!.flush()
  expect(setup!.captureCharFrame()).toBe(actual)
  expect(setup!.captureSpans()).toEqual(spans)
})

test("retains plain paragraphs and the exact source including trailing newlines", async () => {
  const { markdown } = await mount("first\n\nsecond\n\n")
  const node = markdown.getChildren()[0]
  expect(node).toBeInstanceOf(TextRenderable)
  expect(markdown.content).toBe("first\n\nsecond\n\n")
  markdown.content += "The equation is x² + y² = z²."
  expect(markdown.getChildren()[0]).toBe(node)
})

test("hands off to Markdown when formatting arrives and keeps subsequent parser state", async () => {
  const { markdown } = await mount("first")
  const plain = markdown.getChildren()[0]
  markdown.content += " **bold**"
  expect(plain?.isDestroyed).toBe(true)
  expect(markdown.content).toBe("first **bold**")
  const formatted = markdown.getChildren()[0]
  markdown.content += " tail"
  expect(markdown.getChildren()[0]).toBe(formatted)
  expect(markdown.content).toBe("first **bold** tail")
})

test("leaves completed history on the Markdown path", async () => {
  const { markdown } = await mount("plain history", false)
  expect(markdown.getChildren()[0]).not.toBeInstanceOf(TextRenderable)
  markdown.destroyRecursively()
  markdown.content = "late update"
  expect(markdown.content).toBe("plain history")
})
