import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { requestDiagram, type DiagramRequest, type DiagramState } from "@/components/markdown-diagrams/runtime";
import type { DiagramInput, DiagramReply } from "@/components/markdown-diagrams/types";

class RenderWorker {
  static instances: RenderWorker[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessageerror: (() => void) | null = null;
  terminate = vi.fn();
  postMessage = vi.fn();
  constructor() { RenderWorker.instances.push(this); }
  reply(data: DiagramReply) { this.onmessage?.({ data } as MessageEvent); }
}
class DecodedImage {
  static instances: DecodedImage[] = [];
  src = "";
  decoding = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  removeAttribute = vi.fn();
  decode = vi.fn(() => Promise.resolve());
  constructor() { DecodedImage.instances.push(this); }
}
const input: DiagramInput = { source: "flowchart LR\nA --> B", width: 500, fonts: { sans: "sans-serif", mono: "monospace", size: 16 } };
const result: DiagramReply = { kind: "image", template: { content: '<path d="M0 0L20 20"/>', style: "fill:black", width: 100, height: 50, label: "Example" } };
let requests: DiagramRequest[];
function start(source = input.source) {
  const controller = new AbortController();
  const states: DiagramState[] = [];
  const request = requestDiagram({ ...input, source }, controller.signal, (state) => states.push(state));
  requests.push(request);
  request.setDemand("visible");
  return { request, states, controller };
}

beforeEach(() => {
  requests = [];
  RenderWorker.instances = [];
  DecodedImage.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("Worker", RenderWorker);
  vi.stubGlobal("Image", DecodedImage);
  vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:diagram-${DecodedImage.instances.length}`);
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});
afterEach(() => {
  requests.forEach((request) => request.dispose());
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("diagram runtime", () => {
  it("bounds concurrent rendering, prioritizes an opened diagram and cancels only its task", () => {
    const jobs = Array.from({ length: 8 }, () => start());
    expect(RenderWorker.instances).toHaveLength(2);
    jobs[7].request.setDemand("dialog");
    jobs[0].controller.abort();
    expect(RenderWorker.instances[0].terminate).toHaveBeenCalledOnce();
    expect(RenderWorker.instances[1].terminate).not.toHaveBeenCalled();
    expect(RenderWorker.instances).toHaveLength(3);
    jobs[7].controller.abort();
    expect(RenderWorker.instances[2].terminate).toHaveBeenCalledOnce();
  });

  it("terminates timed-out synchronous work and ignores its late result", () => {
    const job = start();
    const worker = RenderWorker.instances[0];
    const lateReply = worker.onmessage!;
    worker.reply({ kind: "started" });
    vi.advanceTimersByTime(2000);
    expect(worker.terminate).toHaveBeenCalledOnce();
    expect(job.states.at(-1)).toEqual({ kind: "failed", reason: "deadline" });
    lateReply({ data: result } as MessageEvent);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("releases the worker when module loading fails and permits an explicit retry", () => {
    const job = start();
    vi.advanceTimersByTime(10_000);
    expect(job.states.at(-1)).toEqual({ kind: "failed", reason: "load" });
    expect(RenderWorker.instances[0].terminate).toHaveBeenCalledOnce();
    // Source view / scrolling offscreen must preserve the error and its retry action.
    job.request.setDemand("none");
    job.request.setDemand("visible");
    expect(job.states.at(-1)).toEqual({ kind: "failed", reason: "load" });
    expect(RenderWorker.instances).toHaveLength(1);
    job.request.retry();
    expect(RenderWorker.instances).toHaveLength(2);
  });

  it("decodes before publishing and rebinds the theme without executing Pele again", async () => {
    const job = start();
    RenderWorker.instances[0].reply(result);
    expect(job.states.at(-1)?.kind).toBe("rendering");
    expect(RenderWorker.instances[0].terminate).toHaveBeenCalledOnce();
    DecodedImage.instances[0].onload?.();
    await Promise.resolve();
    expect(job.states.at(-1)).toMatchObject({ kind: "ready", image: { width: 100, label: "Example" } });
    job.request.setPalette({ "--pele-fg": "#eeeeee" });
    expect(RenderWorker.instances).toHaveLength(1);
    DecodedImage.instances[1].onload?.();
    await Promise.resolve();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:diagram-0");
    job.controller.abort();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it("disposes a pending image on session change, suppressing its late decode", async () => {
    const job = start();
    RenderWorker.instances[0].reply(result);
    const image = DecodedImage.instances[0];
    let resolve!: () => void;
    image.decode.mockImplementation(() => new Promise<void>((done) => { resolve = done; }));
    image.onload?.();
    job.controller.abort();
    resolve();
    await Promise.resolve();
    expect(job.states.some((state) => state.kind === "ready")).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
  });

  it("releases offscreen assets and re-renders only on renewed demand", async () => {
    const job = start();
    RenderWorker.instances[0].reply(result);
    DecodedImage.instances[0].onload?.();
    await Promise.resolve();
    job.request.setDemand("none");
    expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    expect(job.states.at(-1)).toEqual({ kind: "waiting" });
    expect(RenderWorker.instances).toHaveLength(1);
    job.request.setDemand("visible");
    expect(RenderWorker.instances).toHaveLength(2);
  });

  it("waits for shared image capacity and resumes after another fence releases it", async () => {
    const jobs = Array.from({ length: 5 }, () => start());
    const large: DiagramReply = { kind: "image", template: { content: "<path/>", style: "fill:black", width: 4000, height: 2000, label: "Large graph" } };
    for (let index = 0; index < 4; index++) {
      RenderWorker.instances[index].reply(large);
      DecodedImage.instances[index].onload?.();
      await Promise.resolve();
      expect(jobs[index].states.at(-1)?.kind).toBe("ready");
    }
    RenderWorker.instances[4].reply(large);
    expect(jobs[4].states.at(-1)).toEqual({ kind: "waiting" });
    expect(DecodedImage.instances).toHaveLength(4);
    jobs[0].controller.abort();
    await Promise.resolve();
    expect(DecodedImage.instances).toHaveLength(5);
    DecodedImage.instances[4].onload?.();
    await Promise.resolve();
    expect(jobs[4].states.at(-1)?.kind).toBe("ready");
    expect(RenderWorker.instances).toHaveLength(5);
  });

  it("retains source-only failure when Worker is unavailable or source exceeds the budget", () => {
    const oversized = start("a".repeat(50_001));
    expect(oversized.states.at(-1)).toEqual({ kind: "failed", reason: "limit" });
    vi.stubGlobal("Worker", undefined);
    const unavailable = start();
    expect(unavailable.states.at(-1)).toEqual({ kind: "failed", reason: "capability" });
    expect(RenderWorker.instances).toHaveLength(0);
  });
});
