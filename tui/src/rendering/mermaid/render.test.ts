import { describe, expect, test } from "bun:test"
import { NativeImage } from "@opentui/core"
import { existsSync } from "node:fs"
import { renderDiagram } from "./render"
import { resolveDiagramSvg } from "./svg"
import { DiagramJobs } from "./jobs"
import { SOURCE_LIMIT, type DiagramInput } from "./types"

const input: DiagramInput = {
  source: "graph TD\n A[中文：开始处理长标签] --> B{检查数据}\n B -->|通过| C[完成]",
  width: 800, scale: 2,
  fonts: {
    regular: { path: "C:/Windows/Fonts/msyh.ttc", postscriptName: "MicrosoftYaHei" },
    bold: { path: "C:/Windows/Fonts/msyhbd.ttc", postscriptName: "MicrosoftYaHei-Bold" },
    mono: { path: "C:/Windows/Fonts/consola.ttf", postscriptName: "Consolas" },
  },
  colors: { foreground: "#202020", muted: "#666666", surface: "#eeeeee", border: "#888888", accent: "#3366cc" },
}

const svg = (body: string) => `<svg xmlns="http://www.w3.org/2000/svg">${body}</svg>`

test("SVG image policy rejects external resources and executable elements", () => {
  for (const body of ['<image href="file:///secret.png"/>', '<script/>', '<foreignObject/>', '<path fill="url(https://example.org/image)"/>']) {
    expect(() => resolveDiagramSvg(svg(body), input, "sans-serif", "monospace")).toThrow()
  }
})

test("SVG variables resolve nested Pele aliases into concrete theme values", () => {
  const result = resolveDiagramSvg('<svg xmlns="http://www.w3.org/2000/svg" style="--_fg:var(--pele-fg,#111)"><text fill="var(--_fg)">Hello</text></svg>', input, "Microsoft YaHei", "Consolas")
  expect(result).toContain('fill="#202020"')
  expect(result).not.toContain("var(")
})

describe.skipIf(!existsSync(input.fonts!.regular.path))("Windows native raster integration", () => {
  test("Pele renders Chinese flowchart and sequence diagram to bounded PNGs", () => {
    for (const source of [input.source, "sequenceDiagram\n participant A as 用户\n participant B as 服务\n A->>B: 长标签消息\n B-->>A: 完成"]) {
      const image = renderDiagram({ ...input, source })
      expect(Array.from(image.png.subarray(0, 8))).toEqual([137, 80, 78, 71, 13, 10, 26, 10])
      expect(image.width).toBeGreaterThan(100)
      expect(image.width * image.height).toBeLessThanOrEqual(8_000_000)
      const native = NativeImage.decode(image.png)
      try {
        expect(native.info().hasAlpha).toBe(true)
        expect(native.raw().data[3]).toBe(0)
      } finally { native.dispose() }
    }
  })

  test("source limit and parser failures are explicit", () => {
    expect(() => renderDiagram({ ...input, source: "x".repeat(SOURCE_LIMIT + 1) })).toThrow("limit")
    expect(() => renderDiagram({ ...input, source: "graph TD\n A -->" })).toThrow()
  })

  test("worker cancellation is isolated and the next job completes", async () => {
    const jobs = new DiagramJobs()
    try {
      const cancel = new AbortController()
      const first = jobs.render(input, cancel.signal)
      const second = jobs.render(input, new AbortController().signal)
      cancel.abort()
      await expect(first).rejects.toThrow("cancelled")
      expect((await second).png.byteLength).toBeGreaterThan(100)
    } finally { jobs.dispose() }
  }, 20_000)
})
