import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { detectType, load, render } from "pele/lazy";
import { canvasTextMeasurer } from "../components/markdown-diagrams/render";
import { diagramImageTemplate, DiagramImageError } from "../components/markdown-diagrams/svg-image";
import { OUTPUT_LIMIT, SOURCE_LIMIT, type DiagramInput, type DiagramReply } from "../components/markdown-diagrams/types";

const fonts: DiagramInput["fonts"] = {
  sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  mono: 'ui-monospace, "Cascadia Code", monospace', size: 14,
};
const source = 'flowchart LR\n A["`**粗体** _italic_ 中文 😀`"] --> B[Result]';
let base: string;

async function peleSvg(text: string): Promise<string> {
  await load(detectType(text));
  return render(text, {
    fontFamily: fonts.sans, fontFamilyMono: fonts.mono, fontSize: fonts.size,
    measurer: { width: (text) => text.length * 7 }, links: false, images: false,
    responsive: false, maxWidth: 600, maxEdges: 500,
  }).svg;
}
function documentSvg(body: string): string {
  return base.slice(0, base.indexOf(">") + 1) + body + "</svg>";
}
function reject(svg: string, reason = "policy"): void {
  expect(() => diagramImageTemplate(svg, fonts)).toThrowError(
    expect.objectContaining({ reason }),
  );
}
function canvasFixture() {
  const context = {
    font: "",
    measureText: vi.fn((text: string) => ({ width: text.length * 7 })),
  };
  vi.stubGlobal("OffscreenCanvas", class {
    getContext() { return context; }
  });
  return context;
}

beforeAll(async () => { base = await peleSvg(source); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("Pele image-only output", () => {
  it.each([
    source,
    "sequenceDiagram\n Alice->>Bob: 中文 and emoji 😀\n Note over Alice,Bob: two lines<br/>second",
    "stateDiagram-v2\n [*] --> Active\n state Active {\n [*] --> Ready\n Ready --> [*]\n }",
  ])("accepts the published engine's measured geometries: %s", async (text) => {
    const svg = await peleSvg(text);
    const image = diagramImageTemplate(svg, fonts);
    expect(image.content).toContain("<text");
    expect(image.content).not.toMatch(/^<svg/);
    expect(image.style).toContain("--_bg:var(--pele-bg,#fff)");
    expect(image.style).toContain('font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif');
    expect(image.style).toContain('--_fm:ui-monospace,"Cascadia Code",monospace');
    expect(image.style).not.toContain("--pele-font,");
    expect(image.width).toBeGreaterThan(0);
    expect(image.height).toBeGreaterThan(0);
  });

  it("retains measured bold, italic and numeric size styling", async () => {
    const image = diagramImageTemplate(await peleSvg(`${source}\n classDef measured font-size:18px,font-weight:bold,font-style:italic\n class B measured`), fonts);
    expect(image.style).toContain("--_w:bold");
    expect(image.content).toContain("font-size:18px");
    expect(image.content).toContain("font-style:italic");
    expect(image.content).toContain('font-weight="var(--_w)"');
  });

  it.each([
    "font-family:fantasy", "letter-spacing:4px", "word-spacing:1em",
    "font-size:2em", "font-size:201px", "font-weight:600", "font-style:oblique",
  ])("rejects unmeasured author typography: %s", async (authorStyle) => {
    reject(await peleSvg(`flowchart LR\n A[Label] --> B\n style A ${authorStyle}`), "unsupported");
  });

  it("preserves and resolves local marker/clip references and monospace attributes", () => {
    const image = diagramImageTemplate(documentSvg('<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z"/></marker><clipPath id="clip"><rect width="40" height="20"/></clipPath></defs><path d="M0 0L40 20" marker-end="url(#arrow)" style="clip-path:url(#clip)"/><text font-family="var(--_fm)" font-size="12">code</text>'), fonts);
    expect(image.content).toContain('marker-end="url(#arrow)"');
    expect(image.content).toContain('style="clip-path:url(#clip)"');
    expect(image.content).toContain('font-family="var(--_fm)"');
    reject(documentSvg('<path d="M0 0L2 2" marker-end="url(#missing)"/>'));
    reject(documentSvg('<g id="wrong"/><path d="M0 0L2 2" marker-end="url(#wrong)"/>'));
  });

  it("serializes XML and extracts an inert plain accessible label", () => {
    const image = diagramImageTemplate(documentSvg('<title id="title">A &amp; B &lt;img&gt;</title><desc>中文\n description</desc><text><![CDATA[<script> & "quoted"]]></text>'), fonts);
    expect(image.label).toBe("A & B <img>. 中文 description");
    expect(image.content).toContain("&lt;script&gt; &amp; &quot;quoted&quot;");
    expect(image.content).not.toContain("<![CDATA[");
  });

  it.each([
    '<script>alert(1)</script>', '<foreignObject/>', '<animate attributeName="x"/>',
    '<image href="https://bad.test/image"/>', '<a href="https://bad.test/"><text>link</text></a>',
    '<use href="#shape"/>', '<path d="M0 0L1 1" onclick="alert(1)"/>',
    '<g xmlns="http://www.w3.org/1999/xhtml"/>', '<text>&unknown;</text>',
    '<path style="fill:url(https://bad.test/a)"/>', '<path style="fill:u\\72l(https://bad.test/a)"/>',
    '<path style="fill:var(--custom,red)"/>', '<path style="fill:var(--_fg,url(https://bad.test/a))"/>',
    '<path style="--custom:red;fill:var(--custom)"/>', '<path style="filter:blur(4px)"/>',
    '<path style="@import url(https://bad.test/a)"/>',
  ])("rejects active/resource/unsupported XML or CSS: %s", (body) => {
    reject(documentSvg(body));
  });

  it("rejects DTD/entity declarations and processing instructions", () => {
    reject('<!DOCTYPE svg [<!ENTITY value "expanded">]>' + documentSvg("<text>&value;</text>"));
    reject('<?xml-stylesheet href="https://bad.test/style"?>' + base);
  });

  it("bounds dimensions, finite geometry, element count and final UTF-8 bytes", () => {
    reject(base.replace(/width="\d+"/, 'width="8193"'), "limit");
    reject(base.replace(/viewBox="[^"]+"/, 'viewBox="0 0 1 1"'), "limit");
    reject(base.replace(/viewBox="[^"]+"/, 'viewBox="0 0 3000 3000"').replace(/width="\d+"/, 'width="3000"').replace(/height="\d+"/, 'height="3000"'), "limit");
    reject(documentSvg('<path d="M0 0L1e999 2"/>'), "limit");
    reject(documentSvg("<g/>".repeat(10_000)), "limit");
    const multibyte = documentSvg(`<text>${"中".repeat(360_000)}</text>`);
    expect(multibyte.length).toBeLessThan(OUTPUT_LIMIT);
    reject(multibyte, "limit");
    reject(documentSvg(`<text><![CDATA[${"<".repeat(270_000)}]]></text>`), "limit");
  });
});

describe("canvas-only typography", () => {
  it("uses the exact sans/mono size, bold and italic flags", () => {
    const context = canvasFixture();
    const measurer = canvasTextMeasurer(fonts);
    for (const [flags, expected] of [
      [0, `18px ${fonts.sans}`], [1, `bold 18px ${fonts.sans}`],
      [2, `italic 18px ${fonts.sans}`], [4, `18px ${fonts.mono}`],
      [7, `italic bold 18px ${fonts.mono}`],
    ] as const) {
      expect(measurer.width("中文 emoji 😀", 18, flags)).toBe(77);
      expect(context.font).toBe(expected);
    }
  });

  it("fails explicitly without OffscreenCanvas rather than using approximate metrics", () => {
    vi.stubGlobal("OffscreenCanvas", undefined);
    expect(() => canvasTextMeasurer(fonts)).toThrowError(new DiagramImageError("capability"));
  });
});

describe("single-input Worker protocol", () => {
  async function run(text: string): Promise<DiagramReply[]> {
    vi.resetModules();
    const replies: DiagramReply[] = [];
    const worker: {
      onmessage: ((event: MessageEvent<DiagramInput>) => Promise<void>) | null;
      postMessage(reply: DiagramReply): void;
    } = { onmessage: null, postMessage: (reply) => { replies.push(reply); } };
    vi.stubGlobal("self", worker);
    const canvas = canvasFixture();
    canvas.measureText.mockImplementation((text) => {
      expect(replies.at(-1)?.kind).toBe("started");
      return { width: text.length * 7 };
    });
    await import("../components/markdown-diagrams/pele.worker");
    if (!worker.onmessage) throw new Error("Worker handler missing");
    await worker.onmessage(new MessageEvent<DiagramInput>("message", {
      data: { source: text, width: 600, fonts },
    }));
    expect(worker.onmessage).toBeNull();
    return replies;
  }

  it("loads the actual engine, announces sync work, and returns only an image template", async () => {
    const replies = await run('---\ntitle: Supported frontmatter\nconfig:\n  links: true\n  images: true\n---\n%%{init: {"flowchart":{"wrappingWidth":120}}}%%\nflowchart LR\n A["<b>中文</b>"] --> B\n click A "https://bad.test/"\n');
    expect(replies.map((reply) => reply.kind)).toEqual(["started", "image"]);
    const image = replies[1];
    if (image.kind !== "image") throw new Error("Image missing");
    expect(image.template.content).toContain("Supported frontmatter");
    expect(image.template.content).not.toMatch(/<a\b|href=|<image\b/);
  });

  it("enforces host source/edge limits and reports unsupported or invalid syntax", async () => {
    expect(await run("x".repeat(SOURCE_LIMIT + 1))).toEqual([{ kind: "failed", reason: "limit" }]);
    expect(await run("unknownDiagram A")).toEqual([{ kind: "failed", reason: "unsupported" }]);
    expect((await run("flowchart LR\n A[unclosed")).at(-1)).toEqual({ kind: "failed", reason: "syntax" });
    const edges = Array.from({ length: 501 }, (_, i) => `A${i} --> A${i + 1}`).join("\n");
    expect((await run(`flowchart LR\n${edges}`)).at(-1)).toEqual({ kind: "failed", reason: "limit" });
  });
});
