// @vitest-environment jsdom
// DOMPurify's SVG namespace checks need a spec-compliant DOM, not happy-dom.
import { describe, expect, it, vi } from "vitest";
import { canRenderMermaid, renderMermaid, sanitizeDiagram } from "@/lib/mermaid-renderer";
import mermaid from "mermaid";

vi.mock("mermaid", () => ({ default: {
  initialize: vi.fn(),
  render: vi.fn().mockResolvedValue({ svg: '<svg xmlns="http://www.w3.org/2000/svg"><text>Example</text></svg>' }),
} }));

describe("untrusted Mermaid rendering", () => {
  it.each([
    "flowchart LR\n A[开始] --> B[完成]",
    "sequenceDiagram\n Alice->>Bob: Hello",
    "stateDiagram-v2\n [*] --> Active",
  ])("accepts bounded ordinary diagrams", (source) => {
    expect(canRenderMermaid(source)).toBe(true);
  });
  it.each([
    '%%{init: {"securityLevel":"loose"}}%%\nflowchart LR',
    "---\nconfig:\n securityLevel: loose\n---\nflowchart LR",
    'flowchart LR\n A["<img src=x onerror=alert(1)>"]',
    'flowchart LR\n click A "https://example.com"',
    'flowchart LR\n A@{ img: "data:image/svg+xml,example" }',
    'flowchart LR\n classDef a fill:url(//example.com)',
    "flowchart LR\n".repeat(201),
    "A".repeat(12_001),
  ])("keeps configuration, active resources and oversized input as source", (source) => {
    expect(canRenderMermaid(source)).toBe(false);
  });
  it("removes active SVG and external references", () => {
    const result = sanitizeDiagram('<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(1)</script><foreignObject><div>HTML</div></foreignObject><image href="https://example.com/x"/><a href="javascript:alert(1)"><text>Label</text></a><use href="#outside"/><text onclick="alert(1)">Safe</text></svg>');
    expect(result).not.toMatch(/script|foreignObject|<image|<use|<a\s|href=|onload|onclick/);
    expect(result).toContain("Safe");
  });
  it("fixes security configuration, returns sanitized SVG, and cleans temporary DOM", async () => {
    const before = document.body.childElementCount;
    const result = await renderMermaid("flowchart LR\n A-->B", true);
    expect(mermaid.initialize).toHaveBeenCalledWith(expect.objectContaining({
      securityLevel: "strict", htmlLabels: false, maxEdges: 200, theme: "dark",
    }));
    expect(result).toContain("<svg");
    expect(document.body.childElementCount).toBe(before);
  });
  it("does not render an abandoned queued diagram", async () => {
    vi.mocked(mermaid.render).mockClear();
    const controller = new AbortController();
    controller.abort();
    await expect(renderMermaid("flowchart LR\n A-->B", false, controller.signal)).rejects.toThrow();
    expect(mermaid.render).not.toHaveBeenCalled();
  });
  it("recovers after a render failure without leaking DOM", async () => {
    vi.mocked(mermaid.render).mockRejectedValueOnce(new Error("syntax"));
    const before = document.body.childElementCount;
    await expect(renderMermaid("invalid", false)).rejects.toThrow();
    expect(document.body.childElementCount).toBe(before);
    expect(await renderMermaid("flowchart LR\n A-->B", false)).toContain("<svg");
  });
});
