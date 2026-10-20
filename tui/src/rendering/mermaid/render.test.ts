import { describe, expect, spyOn, test } from "bun:test"
import { NativeImage } from "@opentui/core"
import { existsSync } from "node:fs"
import { renderDiagram } from "./render"
import { rasterDiagram } from "./raster"
import { diagramFrame } from "./geometry"
import { resolveDiagramSvg } from "./svg"
import { DiagramJobs } from "./jobs"
import { jsonLines } from "./protocol"
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

test("worker records preserve split UTF-8 and multiple replies across pipe reads", async () => {
  const bytes = Buffer.from('{"label":"中文"}\n{"width":9}\n')
  const stream = new ReadableStream<Uint8Array>({ start(controller) {
    controller.enqueue(bytes.subarray(0, 11))
    controller.enqueue(bytes.subarray(11, 20))
    controller.enqueue(bytes.subarray(20))
    controller.close()
  } })
  const records = []
  for await (const record of jsonLines(stream, 100)) records.push(record)
  expect(records).toEqual([{ label: "中文" }, { width: 9 }])
})

describe.skipIf(!existsSync(input.fonts!.regular.path))("Windows raster integration", () => {
  test("Pele renders Chinese flowchart and sequence diagram to bounded PNGs", async () => {
    for (const source of [input.source, "sequenceDiagram\n participant A as 用户\n participant B as 服务\n A->>B: 长标签消息\n B-->>A: 完成"]) {
      const image = await renderDiagram({ ...input, source })
      expect(Array.from(image.png.subarray(0, 8))).toEqual([137, 80, 78, 71, 13, 10, 26, 10])
      expect(image.width).toBeGreaterThan(100)
      expect(image.width * image.height).toBeLessThanOrEqual(8_000_000)
      expect(image.layout.svg).not.toContain("<text")
      const native = NativeImage.decode(image.png)
      const again = rasterDiagram(image.layout, { width: image.width, height: image.height, x: 0, y: 0, viewWidth: image.layout.width, viewHeight: image.layout.height })
      const raster = NativeImage.decode(again.png)
      try {
        expect(native.info().hasAlpha).toBe(true)
        expect(native.raw().data[3]).toBe(0)
        expect(new Bun.CryptoHasher("sha256").update(native.raw().data).digest("hex"))
          .toBe(new Bun.CryptoHasher("sha256").update(raster.raw().data).digest("hex"))
      } finally { native.dispose(); raster.dispose() }
    }
  })

  test("C4 technology labels and mixed Markdown italics render with the measured fonts", async () => {
    const sources = [
      'C4Container\n Person(user, "用户")\n Container(api, "API 服务", "TypeScript")\n Rel(user, api, "调用", "HTTPS")',
      'C4Component\n Component(api, "API 服务", "TypeScript")\n Component(db, "数据库", "SQL")\n Rel(api, db, "查询", "SQL")',
      'C4Deployment\n Deployment_Node(server, "服务器") {\n Container(api, "API 服务", "TypeScript")\n }\n Deployment_Node(data, "数据层") {\n ContainerDb(db, "数据库", "SQL")\n }\n Rel(api, db, "查询", "SQL")',
      'flowchart LR\n A["`**执行任务**\n调用 *模型与工具*`"] --> B["`***保存记录***`"]',
    ]
    for (const source of sources) {
      const image = await renderDiagram({ ...input, source, scale: 1 })
      expect(image.png.byteLength).toBeGreaterThan(100)
      const native = NativeImage.decode(image.png)
      try { expect(native.info().hasAlpha).toBe(true) } finally { native.dispose() }
    }
    const plain = await renderDiagram({ ...input, source: 'flowchart LR\n A["`模型与工具`"]', scale: 1 })
    const italic = await renderDiagram({ ...input, source: 'flowchart LR\n A["`*模型与工具*`"]', scale: 1 })
    expect([italic.width, italic.height]).toEqual([plain.width, plain.height])
    expect(new Bun.CryptoHasher("sha256").update(italic.png).digest("hex"))
      .not.toBe(new Bun.CryptoHasher("sha256").update(plain.png).digest("hex"))
  })

  test("inline raster preserves natural size and pads to terminal pixels instead of stretching", async () => {
    const natural = await renderDiagram({ ...input, width: 1400, scale: 1 })
    const cellWidth = 9, cellHeight = 18
    const preview = await renderDiagram({ ...input, width: 1404, scale: 1, viewport: { height: 432, cellWidth, cellHeight } })
    expect(preview.width).toBeLessThanOrEqual(natural.width + cellWidth)
    expect(preview.height).toBeLessThanOrEqual(natural.height + cellHeight)
    expect(preview.width % cellWidth).toBe(0)
    expect(preview.height % cellHeight).toBe(0)
    const narrow = await renderDiagram({ ...input, width: 360, scale: 1, viewport: { height: 216, cellWidth, cellHeight } })
    expect(narrow.width).toBeLessThanOrEqual(360)
    expect(narrow.height).toBeLessThanOrEqual(216)
  })

  test("zoom rasterizes the vector viewport at final pixels rather than enlarging a bitmap", async () => {
    const asset = await renderDiagram({ ...input, scale: 1 })
    const viewport = { width: 648, height: 432, cellWidth: 9, cellHeight: 18 }
    const fit = diagramFrame(asset.layout, viewport)
    const zoomed = diagramFrame(asset.layout, viewport, 4, 0.5, 1)
    expect(zoomed.viewWidth / zoomed.width).toBeCloseTo(fit.viewWidth / fit.width / 4)
    expect(zoomed.y).toBeGreaterThan(0)
    const image = await rasterDiagram(asset.layout, zoomed)
    expect(image.width).toBe(zoomed.width)
    expect(image.height).toBe(zoomed.height)
    expect(image.width % 9).toBe(0)
    expect(image.height % 18).toBe(0)
  })

  test("source limit and parser failures are explicit", async () => {
    await expect(renderDiagram({ ...input, source: "x".repeat(SOURCE_LIMIT + 1) })).rejects.toThrow("limit")
    await expect(renderDiagram({ ...input, source: "graph TD\n A -->" })).rejects.toThrow()
  })

  test("visible preview and viewer share one worker until both owners release it", async () => {
    const spawn = spyOn(Bun, "spawn")
    const jobs = new DiagramJobs()
    try {
      const releasePreview = jobs.retainWorker()
      const signal = new AbortController().signal
      const batch = [jobs.render(input, signal), jobs.render({ ...input, source: "sequenceDiagram\n A->>B: 中文消息" }, signal)]
      const [first] = await Promise.all(batch)
      const releaseViewer = jobs.retainWorker()
      releasePreview()
      const frame = diagramFrame(first!.layout, { width: 648, height: 432, cellWidth: 9, cellHeight: 18 }, 2)
      expect((await jobs.raster(first!.layout, frame, signal)).width).toBe(frame.width)
      expect((await jobs.raster(first!.layout, frame, signal)).width).toBe(frame.width)
      expect(spawn).toHaveBeenCalledTimes(1)
      const child = spawn.mock.results[0]!.value as Bun.Subprocess
      expect(child.killed).toBe(false)
      releaseViewer()
      expect(Number.isInteger(await child.exited)).toBe(true)
      expect(child.killed).toBe(true)
    } finally { jobs.dispose(); spawn.mockRestore() }
  }, 20_000)

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
