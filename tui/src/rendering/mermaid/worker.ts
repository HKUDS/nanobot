import { renderDiagram } from "./render"
import { SOURCE_LIMIT, type DiagramInput } from "./types"

/** Internal pipe protocol, never terminal graphics output. The parent reaps this native heap. */
export async function runDiagramWorker(): Promise<void> {
  let reply: { image: { png: string; width: number; height: number } } | { error: string }
  try {
    const chunks: Uint8Array[] = []
    let size = 0
    for await (const chunk of Bun.stdin.stream()) {
      size += chunk.length
      if (size > SOURCE_LIMIT * 6 + 8192) throw new Error("Diagram input limit")
      chunks.push(chunk)
    }
    const input = JSON.parse(Buffer.concat(chunks).toString("utf8")) as DiagramInput
    const image = renderDiagram(input)
    reply = { image: { png: Buffer.from(image.png).toString("base64"), width: image.width, height: image.height } }
  } catch (error) {
    reply = { error: error instanceof Error ? error.message.slice(0, 400) : "Diagram rendering failed" }
  }
  await Bun.write(Bun.stdout, JSON.stringify(reply))
}
