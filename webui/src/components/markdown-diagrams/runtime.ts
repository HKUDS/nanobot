import { MAX_DIMENSION, MAX_PIXELS, OUTPUT_LIMIT, SOURCE_LIMIT } from "./types";
import type { DiagramFailure, DiagramInput, DiagramTemplate } from "./types";

export interface DiagramImage {
  url: string;
  width: number;
  height: number;
  label: string;
}
export type DiagramState = { kind: "waiting" | "rendering" }
  | { kind: "ready"; image: DiagramImage }
  | { kind: "failed"; reason: DiagramFailure };
export type DiagramPalette = Readonly<Record<string, string>>;
export interface DiagramRequest {
  setDemand(demand: "none" | "visible" | "dialog"): void;
  setPalette(palette: DiagramPalette): void;
  retry(): void;
  dispose(): void;
}

const RUNNING_LIMIT = 2;
const QUEUE_LIMIT = 4;
const BYTE_LIMIT = 8 * OUTPUT_LIMIT;
const PIXEL_LIMIT = 32_000_000;
const PALETTE_LIMIT = 4096;
// Reserve one largest replacement inside the totals so retained images can always be recolored.
const ADMISSION_BYTE_LIMIT = BYTE_LIMIT - OUTPUT_LIMIT;
const ADMISSION_PIXEL_LIMIT = PIXEL_LIMIT - MAX_PIXELS;
const tasks = new Set<Task>();
const queue: Task[] = [];
let capacityWakePending = false;
let running = 0;
let retainedBytes = 0;
let retainedPixels = 0;

function pump() {
  queue.length = 0;
  // Prioritize before bounding admission, including a viewer opened behind a full queue.
  for (const demand of ["dialog", "visible"] as const) {
    for (const task of tasks) {
      if (queue.length >= QUEUE_LIMIT) break;
      if (task.eligible && task.demand === demand) queue.push(task);
    }
  }
  while (running < RUNNING_LIMIT && queue.length) {
    const task = queue.shift()!;
    if (task.eligible) task.run();
  }
}

function capacityChanged() {
  if (capacityWakePending) return;
  capacityWakePending = true;
  queueMicrotask(() => {
    capacityWakePending = false;
    for (const task of tasks) task.resumeCapacity();
    pump();
  });
}

function imageTemplate(value: unknown): value is DiagramTemplate {
  if (!value || typeof value !== "object") return false;
  const template = value as Partial<DiagramTemplate>;
  return typeof template.content === "string" && template.content.length <= OUTPUT_LIMIT
    && typeof template.style === "string" && template.style.length <= 4096
    && typeof template.label === "string" && template.label.length <= 4096
    && typeof template.width === "number" && Number.isFinite(template.width)
    && typeof template.height === "number" && Number.isFinite(template.height)
    && template.width > 0 && template.width <= MAX_DIMENSION
    && template.height > 0 && template.height <= MAX_DIMENSION
    && template.width * template.height <= MAX_PIXELS;
}
const failures = new Set<DiagramFailure>(["syntax", "unsupported", "policy", "limit", "load", "deadline", "worker", "image", "capability"]);
const escapeAttribute = (value: string) => value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

function paletteStyle(palette: DiagramPalette): string {
  return Object.entries(palette).map(([key, value]) => {
    if (!/^--pele-(?:bg|fg|muted|line|surface|surface-alt|border|accent|critical|series-[1-8])$/.test(key)
      || !/^(?:#[\da-f]{3,8}|(?:rgb|hsl)a?\([\d\s%,./+-]+\))$/i.test(value)) {
      throw new Error("Invalid diagram palette");
    }
    return `${key}:${value}`;
  }).join(";");
}

class Task implements DiagramRequest {
  demand: "none" | "visible" | "dialog" = "none";
  private worker: Worker | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private disposed = false;
  private failed = false;
  private capacityBlocked = false;
  private template: DiagramTemplate | null = null;
  private templateBytes = 0;
  private asset: { image: DiagramImage; release: () => void } | null = null;
  private decoding: (() => void) | null = null;
  private attempt = 0;
  private palette: DiagramPalette = {};

  constructor(private input: DiagramInput, private signal: AbortSignal, private publish: (state: DiagramState) => void) {
    tasks.add(this);
    signal.addEventListener("abort", this.dispose, { once: true });
  }

  get eligible() {
    return !this.disposed && this.demand !== "none" && !this.failed && !this.capacityBlocked
      && !this.worker && !this.template && !this.decoding;
  }

  setDemand(demand: "none" | "visible" | "dialog") {
    if (this.disposed || demand === this.demand) return;
    this.demand = demand;
    if (demand === "none") {
      this.capacityBlocked = false;
      this.cancel();
      this.clearTemplate();
      this.asset?.release();
      this.asset = null;
      if (!this.failed) this.publish({ kind: "waiting" });
    }
    pump();
  }

  setPalette(palette: DiagramPalette) {
    if (this.disposed || JSON.stringify(palette) === JSON.stringify(this.palette)) return;
    this.palette = palette;
    if (this.template && !this.failed) this.decode();
  }

  retry() {
    if (this.disposed || !this.failed) return;
    this.failed = false;
    this.clearTemplate();
    this.publish({ kind: "waiting" });
    pump();
  }

  private stopWorker() {
    clearTimeout(this.timer);
    if (this.worker) {
      this.worker.onmessage = null;
      this.worker.onerror = null;
      this.worker.onmessageerror = null;
      this.worker.terminate();
      this.worker = null;
      running--;
    }
  }

  private cancel() {
    this.attempt++;
    const index = queue.indexOf(this);
    if (index !== -1) queue.splice(index, 1);
    this.stopWorker();
    this.decoding?.();
    this.decoding = null;
  }

  private clearTemplate() {
    if (this.templateBytes) {
      retainedBytes -= this.templateBytes;
      capacityChanged();
    }
    this.templateBytes = 0;
    this.template = null;
  }

  private waitForCapacity() {
    this.capacityBlocked = true;
    if (!this.asset) this.publish({ kind: "waiting" });
  }

  resumeCapacity() {
    if (!this.capacityBlocked || this.disposed) return;
    this.capacityBlocked = false;
    if (this.template && this.demand !== "none" && !this.failed) this.decode();
  }

  private fail(reason: DiagramFailure) {
    this.cancel();
    this.failed = true;
    this.clearTemplate();
    this.asset?.release();
    this.asset = null;
    this.publish({ kind: "failed", reason });
    queueMicrotask(pump);
  }

  run() {
    if (this.input.source.length > SOURCE_LIMIT) { this.fail("limit"); return; }
    if (typeof Worker === "undefined") { this.fail("capability"); return; }
    this.publish({ kind: "rendering" });
    try {
      const worker = new Worker(new URL("./pele.worker.ts", import.meta.url), { type: "module" });
      this.worker = worker;
      running++;
      const attempt = ++this.attempt;
      this.timer = setTimeout(() => this.fail("load"), 10_000);
      worker.onmessage = ({ data }: MessageEvent<unknown>) => {
        if (this.disposed || this.worker !== worker || attempt !== this.attempt) return;
        if (!data || typeof data !== "object" || !("kind" in data)) { this.fail("worker"); return; }
        if (data.kind === "started") {
          clearTimeout(this.timer);
          this.timer = setTimeout(() => this.fail("deadline"), 2000);
        } else if (data.kind === "image" && "template" in data && imageTemplate(data.template)) {
          this.stopWorker();
          const bytes = new Blob([data.template.content, data.template.style]).size;
          if (bytes > OUTPUT_LIMIT) { this.fail("limit"); return; }
          if (retainedBytes + bytes > ADMISSION_BYTE_LIMIT) { this.waitForCapacity(); pump(); return; }
          this.template = data.template;
          this.templateBytes = bytes;
          retainedBytes += bytes;
          this.decode();
          pump();
        } else if (data.kind === "failed" && "reason" in data && failures.has(data.reason as DiagramFailure)) {
          this.fail(data.reason as DiagramFailure);
        } else this.fail("worker");
      };
      worker.onerror = worker.onmessageerror = () => this.fail("worker");
      worker.postMessage(this.input);
    } catch { this.fail("worker"); }
  }

  private decode() {
    const template = this.template;
    if (!template || this.disposed || this.demand === "none") return;
    this.decoding?.();
    const attempt = ++this.attempt;
    let blob: Blob;
    let paletteBytes: number;
    try {
      const palette = paletteStyle(this.palette);
      paletteBytes = new Blob([palette]).size;
      if (paletteBytes > PALETTE_LIMIT) { this.fail("limit"); return; }
      const style = escapeAttribute(`${template.style};${palette}`);
      blob = new Blob([`<svg xmlns="http://www.w3.org/2000/svg" width="${template.width}" height="${template.height}" viewBox="0 0 ${template.width} ${template.height}" fill="var(--_fg)" style="${style}">${template.content}</svg>`], { type: "image/svg+xml" });
    } catch { this.fail("image"); return; }
    const pixels = template.width * template.height;
    // Only the bounded palette can vary for this template. Its envelope stays constant
    // across themes, preserving replacement headroom without charging small SVGs 1 MiB.
    const reservedBytes = Math.min(blob.size - paletteBytes + PALETTE_LIMIT, OUTPUT_LIMIT);
    const byteLimit = this.asset ? BYTE_LIMIT : ADMISSION_BYTE_LIMIT;
    const pixelLimit = this.asset ? PIXEL_LIMIT : ADMISSION_PIXEL_LIMIT;
    if (blob.size > OUTPUT_LIMIT) { this.fail("limit"); return; }
    if (retainedBytes + reservedBytes > byteLimit || retainedPixels + pixels > pixelLimit) {
      this.waitForCapacity(); return;
    }
    this.capacityBlocked = false;
    retainedBytes += reservedBytes;
    retainedPixels += pixels;
    let url: string;
    try { url = URL.createObjectURL(blob); }
    catch {
      retainedBytes -= reservedBytes;
      retainedPixels -= pixels;
      this.fail("image"); return;
    }
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      URL.revokeObjectURL(url);
      retainedBytes -= reservedBytes;
      retainedPixels -= pixels;
      capacityChanged();
    };
    const image = new Image();
    image.decoding = "async";
    const cleanup = () => {
      clearTimeout(timer);
      image.onload = image.onerror = null;
    };
    const finish = () => {
      if (this.disposed || attempt !== this.attempt || this.demand === "none") { cleanup(); release(); return; }
      cleanup();
      this.decoding = null;
      const previous = this.asset;
      this.asset = { image: { url, width: template.width, height: template.height, label: template.label }, release };
      this.publish({ kind: "ready", image: this.asset.image });
      previous?.release();
    };
    const timer = setTimeout(() => this.fail("image"), 5000);
    this.decoding = () => { cleanup(); image.removeAttribute("src"); release(); };
    image.onerror = () => this.fail("image");
    image.onload = () => {
      if (typeof image.decode === "function") void image.decode().then(finish, () => {
        if (attempt === this.attempt && !this.disposed) this.fail("image");
      });
      else finish();
    };
    image.src = url;
  }

  dispose = () => {
    if (this.disposed) return;
    this.disposed = true;
    this.signal.removeEventListener("abort", this.dispose);
    tasks.delete(this);
    this.cancel();
    this.asset?.release();
    this.asset = null;
    this.clearTemplate();
    pump();
  };
}

export function requestDiagram(input: DiagramInput, signal: AbortSignal, publish: (state: DiagramState) => void): DiagramRequest {
  const task = new Task(input, signal, publish);
  if (signal.aborted) task.dispose();
  return task;
}
