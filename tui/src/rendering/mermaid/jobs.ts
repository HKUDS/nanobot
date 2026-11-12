import { fileURLToPath } from "node:url"
import { jsonLines, REPLY_LIMIT, REQUEST_LIMIT } from "./protocol"
import { MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT, SOURCE_LIMIT, type DiagramAsset, type DiagramFrame, type DiagramImage, type DiagramInput, type DiagramLayout, type DiagramWork } from "./types"

declare const NANOBOT_COMPILED: boolean

function launch() {
  const args = typeof NANOBOT_COMPILED !== "undefined" && NANOBOT_COMPILED
    ? [process.execPath, "--render-mermaid"]
    : [process.execPath, fileURLToPath(new URL("../../index.ts", import.meta.url)), "--render-mermaid"]
  return Bun.spawn(args, { stdin: "pipe", stdout: "pipe", stderr: "pipe", windowsHide: true })
}

type RasterProcess = ReturnType<typeof launch>
interface Job {
  work: DiagramWork
  signal: AbortSignal
  resolve: (image: DiagramImage | DiagramAsset) => void
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

/** One terminable child, retained only by visible diagrams or their viewer. */
export class DiagramJobs {
  private queue: Job[] = []
  private active: { job: Job; timer: ReturnType<typeof setTimeout> } | null = null
  private process: { child: RasterProcess; closing: boolean; error?: Error } | null = null
  private retainers = new Set<object>()
  private disposed = false

  get idle(): boolean { return !this.active && !this.queue.length }

  render(input: DiagramInput, signal: AbortSignal): Promise<DiagramAsset> {
    if (Buffer.byteLength(input.source) > SOURCE_LIMIT) return Promise.reject(new Error("Diagram source limit"))
    return this.enqueue<DiagramAsset>({ kind: "render", input }, signal)
  }

  raster(layout: DiagramLayout, frame: DiagramFrame, signal: AbortSignal): Promise<DiagramImage> {
    return this.enqueue<DiagramImage>({ kind: "raster", layout, frame }, signal)
  }

  reset(): void {
    for (const job of [...this.queue]) job.cancel()
    this.stop(new Error("Diagram cancelled"))
  }

  dispose(): void { this.disposed = true; this.reset() }

  retainWorker(): () => void {
    const owner = {}
    this.retainers.add(owner)
    return () => { this.retainers.delete(owner); this.start() }
  }

  private enqueue<T extends DiagramImage>(work: DiagramWork, signal: AbortSignal): Promise<T> {
    if (this.disposed || signal.aborted) return Promise.reject(new Error("Diagram cancelled"))
    if (this.queue.length >= 8) return Promise.reject(new Error("Diagram render queue full"))
    return new Promise((resolve, reject) => {
      const job: Job = { work, signal, resolve: image => resolve(image as T), reject, cancel: () => {
        if (this.active?.job === job) this.stop(new Error("Diagram cancelled"))
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

  private start(): void {
    if (this.disposed || this.active || this.process?.error || this.process?.closing) return
    const job = this.queue[0]
    if (!job) {
      if (this.process && !this.retainers.size) this.finishProcess()
      return
    }
    this.queue.shift()
    try {
      const input = JSON.stringify(job.work)
      if (Buffer.byteLength(input) > REQUEST_LIMIT) throw new Error("Diagram input limit")
      if (!this.process) {
        const process = { child: launch(), closing: false, error: undefined as Error | undefined }
        this.process = process
        void this.observe(process)
      }
      const process = this.process
      this.active = { job, timer: setTimeout(() => {
        if (this.active?.job === job) this.stop(new Error("Diagram render timed out"))
      }, 10_000) }
      process.child.stdin.write(input + "\n")
      void Promise.resolve(process.child.stdin.flush()).catch(() => {
        if (this.process === process) this.stop(new Error("Diagram worker pipe failed"))
      })
    } catch (error) {
      if (this.active?.job === job) this.stop(error instanceof Error ? error : new Error("Diagram worker unavailable"))
      else {
        job.signal.removeEventListener("abort", job.cancel)
        job.reject(error instanceof Error ? error : new Error("Diagram worker unavailable"))
        this.start()
      }
    }
  }

  private async observe(process: NonNullable<DiagramJobs["process"]>): Promise<void> {
    const { child } = process
    const stderr = readBounded(child.stderr, 8192)
    const stdout = (async () => {
      for await (const record of jsonLines(child.stdout, REPLY_LIMIT)) {
        if (process.error) break
        const active = this.active
        if (!active) throw new Error("Unexpected diagram worker reply")
        const reply = record as { error?: string; image?: { png: string; width: number; height: number; layout?: DiagramLayout } }
        let failure: Error | undefined, image: DiagramImage | DiagramAsset | undefined
        if (typeof reply.error === "string") failure = new Error(reply.error)
        else {
          const result = reply.image
          if (!result || typeof result.png !== "string" || !Number.isSafeInteger(result.width) || !Number.isSafeInteger(result.height)) throw new Error("Invalid diagram worker result")
          if (result.width < 1 || result.height < 1 || result.width > MAX_DIMENSION || result.height > MAX_DIMENSION || result.width * result.height > MAX_PIXELS) throw new Error("Diagram pixel limit")
          const png = new Uint8Array(Buffer.from(result.png, "base64"))
          if (png.byteLength > OUTPUT_LIMIT) throw new Error("Diagram image limit")
          if (active.job.work.kind === "render" && (!result.layout || Buffer.byteLength(result.layout.svg) > OUTPUT_LIMIT)) throw new Error("Invalid diagram layout")
          image = { ...result, png }
        }
        clearTimeout(active.timer)
        active.job.signal.removeEventListener("abort", active.job.cancel)
        this.active = null
        if (failure) active.job.reject(failure)
        else active.job.resolve(image!)
        this.start()
      }
    })()
    try { await Promise.all([stdout, stderr, child.exited]) }
    catch (error) { this.stop(error instanceof Error ? error : new Error("Diagram worker failed")) }
    finally {
      child.stdin.end()
      // Replacement admission includes exit plus both pipe collectors, even on failure.
      await Promise.allSettled([stdout, stderr, child.exited])
      if (this.process === process) {
        if (this.active) {
          clearTimeout(this.active.timer)
          this.active.job.signal.removeEventListener("abort", this.active.job.cancel)
          this.active.job.reject(process.error ?? new Error("Diagram worker exited"))
          this.active = null
        }
        this.process = null
        this.start()
      }
    }
  }

  private finishProcess(): void {
    const process = this.process!
    process.closing = true
    process.child.kill()
  }

  private stop(error: Error): void {
    const process = this.process
    if (!process || process.error) return
    process.error = error
    process.child.kill()
  }
}
