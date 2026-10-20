import { fileURLToPath } from "node:url"
import { MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT, SOURCE_LIMIT, type DiagramImage, type DiagramInput } from "./types"

declare const NANOBOT_COMPILED: boolean

function launch(input: DiagramInput) {
  const args = typeof NANOBOT_COMPILED !== "undefined" && NANOBOT_COMPILED
    ? [process.execPath, "--render-mermaid"]
    : [process.execPath, fileURLToPath(new URL("../../index.ts", import.meta.url)), "--render-mermaid"]
  return Bun.spawn(args, { stdin: Buffer.from(JSON.stringify(input)), stdout: "pipe", stderr: "pipe", windowsHide: true })
}

type RasterProcess = ReturnType<typeof launch>
interface Job {
  input: DiagramInput
  signal: AbortSignal
  resolve: (image: DiagramImage) => void
  reject: (error: Error) => void
  cancel: () => void
}

async function readBounded(stream: ReadableStream<Uint8Array>, limit: number): Promise<string> {
  const reader = stream.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.length
      if (size > limit) throw new Error("Diagram worker output limit")
      chunks.push(value)
    }
    return Buffer.concat(chunks).toString("utf8")
  } finally { reader.releaseLock() }
}

/** A single native child per transcript; reaping the process also releases font/raster heaps. */
export class DiagramJobs {
  private queue: Job[] = []
  private active: { job: Job; child: RasterProcess; error?: Error } | null = null
  private disposed = false

  render(input: DiagramInput, signal: AbortSignal): Promise<DiagramImage> {
    if (this.disposed || signal.aborted) return Promise.reject(new Error("Diagram cancelled"))
    if (Buffer.byteLength(input.source) > SOURCE_LIMIT) return Promise.reject(new Error("Diagram source limit"))
    if (this.queue.length >= 8) return Promise.reject(new Error("Diagram render queue full"))
    return new Promise((resolve, reject) => {
      const job: Job = { input, signal, resolve, reject, cancel: () => {
        if (this.active?.job === job) this.stop(job, new Error("Diagram cancelled"))
        else {
          this.queue = this.queue.filter(queued => queued !== job)
          signal.removeEventListener("abort", job.cancel)
          reject(new Error("Diagram cancelled"))
        }
      } }
      signal.addEventListener("abort", job.cancel, { once: true })
      this.queue.push(job)
      this.start()
    })
  }

  dispose(): void {
    this.disposed = true
    for (const job of [...this.queue]) job.cancel()
    if (this.active) this.active.job.cancel()
  }

  private start(): void {
    if (this.disposed || this.active) return
    const job = this.queue.shift()
    if (!job) return
    let child: RasterProcess
    try { child = launch(job.input) }
    catch (error) {
      job.signal.removeEventListener("abort", job.cancel)
      job.reject(error instanceof Error ? error : new Error("Diagram worker unavailable"))
      this.start()
      return
    }
    const active = { job, child, error: undefined as Error | undefined }
    this.active = active
    const timer = setTimeout(() => this.stop(job, new Error("Diagram render timed out")), 10_000)
    const stdout = readBounded(child.stdout, Math.ceil(OUTPUT_LIMIT * 4 / 3) + 8192)
    const stderr = readBounded(child.stderr, 8192)
    void Promise.all([stdout, stderr, child.exited]).then(([stdout, , code]) => {
      if (active.error) throw active.error
      if (code !== 0) throw new Error("Diagram worker failed")
      const reply = JSON.parse(stdout)
      if (typeof reply.error === "string") throw new Error(reply.error)
      const image = reply.image
      if (!image || typeof image.png !== "string" || !Number.isSafeInteger(image.width) || !Number.isSafeInteger(image.height)) throw new Error("Invalid diagram worker result")
      if (image.width < 1 || image.height < 1 || image.width > MAX_DIMENSION || image.height > MAX_DIMENSION || image.width * image.height > MAX_PIXELS) throw new Error("Diagram pixel limit")
      const png = new Uint8Array(Buffer.from(image.png, "base64"))
      if (png.byteLength > OUTPUT_LIMIT) throw new Error("Diagram image limit")
      job.resolve({ png, width: image.width, height: image.height })
    }).catch(error => {
      const failure = active.error ?? (error instanceof Error ? error : new Error("Diagram rendering failed"))
      this.stop(job, failure)
      job.reject(failure)
    }).finally(async () => {
      clearTimeout(timer)
      job.signal.removeEventListener("abort", job.cancel)
      // No next native heap is admitted before the previous process has exited.
      await Promise.allSettled([stdout, stderr, child.exited])
      if (this.active === active) this.active = null
      this.start()
    })
  }

  private stop(job: Job, error: Error): void {
    const active = this.active
    if (active?.job !== job || active.error) return
    active.error = error
    active.child.kill()
  }
}
