import { detectType, load, render, PeleError } from "pele/lazy";
import { canvasTextMeasurer } from "./render";
import { diagramImageTemplate, DiagramImageError } from "./svg-image";
import {
  MAX_DIMENSION, OUTPUT_LIMIT, SOURCE_LIMIT,
  type DiagramInput, type DiagramReply,
} from "./types";

self.onmessage = async (event: MessageEvent<DiagramInput>) => {
  // One attempt per Worker. The parent owns watchdogs, termination, URLs and revisions.
  self.onmessage = null;
  const reply = (message: DiagramReply) => self.postMessage(message);
  let started = false;
  try {
    const input = event.data;
    if (input.source.length > SOURCE_LIMIT || !Number.isFinite(input.width)
      || input.width <= 0 || input.width > MAX_DIMENSION) throw new DiagramImageError("limit");
    // detectType preprocesses source config synchronously. The parent's loading
    // watchdog is already active here; it also covers all lazy module loading.
    const type = detectType(input.source);
    if (!await load(type)) throw new DiagramImageError("unsupported");
    const measurer = canvasTextMeasurer(input.fonts);
    reply({ kind: "started" });
    started = true;
    const result = render(input.source, {
      measurer, fontFamily: input.fonts.sans, fontFamilyMono: input.fonts.mono,
      fontSize: input.fonts.size, maxWidth: input.width, responsive: false,
      links: false, images: false, limit: SOURCE_LIMIT, outputLimit: OUTPUT_LIMIT,
      maxEdges: 500,
    });
    const template = diagramImageTemplate(result.svg, input.fonts);
    if (template.width !== result.width || template.height !== result.height) throw new DiagramImageError("policy");
    reply({ kind: "image", template });
  } catch (error) {
    if (error instanceof DiagramImageError) reply({ kind: "failed", reason: error.reason });
    else if (error instanceof PeleError) reply({
      kind: "failed", reason: error.code === "limit" ? "limit"
        : error.code === "unsupported-diagram" ? "unsupported" : "syntax",
    });
    else reply({ kind: "failed", reason: started ? "worker" : "load" });
  }
};
