import DOMPurify from "dompurify";
import mermaid from "mermaid";

// Keep diagram input small before loading parsers/layout engines. Never accept
// model-provided configuration, active labels, links or external resources.
export function canRenderMermaid(source: string): boolean {
  return source.length <= 12_000
    && source.split("\n").length <= 200
    && !/%%\s*\{|^\s*---|<\s*[a-z!/?]|\b(?:https?|data|file|javascript):|\/\/|\\|@import|url\s*\(/im.test(source);
}

export function sanitizeDiagram(svg: string): string {
  return DOMPurify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true },
    FORBID_TAGS: ["foreignObject", "image", "use", "a", "script", "animate", "set"],
    FORBID_ATTR: ["href", "xlink:href"],
  });
}

// Mermaid configuration is global. Serialize initialization/rendering so that
// simultaneous blocks and theme changes cannot borrow another block's config.
let pending: Promise<unknown> = Promise.resolve();
let sequence = 0;
export function renderMermaid(source: string, dark: boolean, signal?: AbortSignal): Promise<string> {
  if (!canRenderMermaid(source)) return Promise.reject(new Error("Unsupported diagram"));
  const result = pending.then(async () => {
    signal?.throwIfAborted();
    const container = document.createElement("div");
    container.style.cssText = "position:absolute;left:-100000px;top:0;visibility:hidden";
    document.body.append(container);
    try {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        suppressErrorRendering: true,
        theme: dark ? "dark" : "default",
        fontFamily: "system-ui, sans-serif",
        maxTextSize: 12_000,
        maxEdges: 200,
        htmlLabels: false,
        flowchart: { htmlLabels: false },
      });
      const { svg } = await mermaid.render(`nanobot-diagram-${++sequence}`, source, container);
      if (svg.length > 1_000_000) throw new Error("Diagram too large");
      return sanitizeDiagram(svg);
    } finally {
      container.remove();
    }
  });
  pending = result.catch(() => {});
  return result;
}
