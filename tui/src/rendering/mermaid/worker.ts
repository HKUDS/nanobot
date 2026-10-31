import { jsonLines, REQUEST_LIMIT } from "./protocol"
import type { DiagramWork } from "./types"

/** Engine imports stay in the owning batch; the parent retains only vectors and images. */
export async function runDiagramWorker(): Promise<void> {
  for await (const record of jsonLines(Bun.stdin.stream(), REQUEST_LIMIT)) {
    let reply: object
    try {
      const work = record as DiagramWork
      const image = work.kind === "render"
        ? await (await import("./render")).renderDiagram(work.input)
        : (await import("./raster")).rasterDiagram(work.layout, work.frame)
      reply = { image: { ...image, png: Buffer.from(image.png).toString("base64") } }
    } catch (error) {
      reply = { error: error instanceof Error ? error.message.slice(0, 400) : "Diagram rendering failed" }
    }
    await Bun.write(Bun.stdout, JSON.stringify(reply) + "\n")
  }
}
